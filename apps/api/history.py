"""Bounded, process-local design history. No bundle/run persistence or numerics."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, replace
import hashlib
import json
import os
import re
import time
from uuid import uuid4

SCENE_ENVELOPE = frozenset(('revision_id', 'revision_number', 'supersedes_revision_id', 'created_at', 'created_by', 'status', 'change_summary'))
ELECTRICAL_ENVELOPE = frozenset(('electrical_revision_id', 'revision_number', 'supersedes_electrical_revision_id', 'supersedes_revision_id', 'project_revision_id', 'created_at', 'created_by', 'status', 'change_summary'))
OPTIONAL_KEYS = ('pinned_components', 'pinned_electrical_shading_assets', 'electrical_shading_selections', 'loss_settings', 'optics_thermal_settings', 'shading_accuracy', 'weather_selection', 'imagery', 'uncertainty_assumptions')


# Project labels with no effect on results; renaming never marks a run as an earlier design.
FINGERPRINT_EXCLUDED_PROJECT_KEYS = frozenset(('name', 'description'))
FINGERPRINT_EXCLUDED_SITE_KEYS = frozenset(('address', 'installation'))
# Context-only imagery (UX1) and the uncertainty ledger (UNC1, applied after a run) are undoable but never part of
# the design a run simulated.
FINGERPRINT_EXCLUDED_KEYS = frozenset(('imagery', 'uncertainty_assumptions'))


def _design_state(bundle):
    state = {key: bundle[key] for key in OPTIONAL_KEYS if key in bundle}
    state['project'] = {key: value for key, value in bundle['project'].items() if key != 'project_revision'}
    state['project']['site'] = {key: value for key, value in state['project']['site'].items() if key not in FINGERPRINT_EXCLUDED_SITE_KEYS}
    state['scene'] = {key: value for key, value in bundle['scene'].items() if key not in SCENE_ENVELOPE}
    state['electrical_design'] = {key: value for key, value in bundle['electrical_design'].items() if key not in ELECTRICAL_ENVELOPE}
    state['site_workspace_bootstrap'] = {key: value for key, value in bundle['site_workspace_bootstrap'].items() if key != 'workspace_context'}
    return state


def _canonical(state):
    return json.dumps(state, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def projection(bundle):
    return _canonical(_design_state(bundle))


def design_fingerprint(bundle):
    """The design a run used: the undo projection without project labels."""
    state = {key: value for key, value in _design_state(bundle).items() if key not in FINGERPRINT_EXCLUDED_KEYS}
    state['project'] = {key: value for key, value in state['project'].items() if key not in FINGERPRINT_EXCLUDED_PROJECT_KEYS}
    state['electrical_design'] = _fingerprint_electrical(state['electrical_design'])
    return 'sha256:' + hashlib.sha256(_canonical(state)).hexdigest()


def _fingerprint_electrical(design):
    """S14b: pairing and override reasons don't change results, so they're left out; the orientation tolerance does
    (it groups strings), so it stays when it differs from the default, and a design without a policy hashes as before."""
    from .orientation_policy import DEFAULT_TOLERANCE_DEG, tolerance_deg
    out = {key: value for key, value in design.items() if key != 'orientation_policy'}
    if 'inverter_instances' in out:
        out['inverter_instances'] = [{k: v for k, v in inverter.items() if k != 'paired_pv_field_ids'} for inverter in out['inverter_instances']]
    if tolerance_deg(design) != DEFAULT_TOLERANCE_DEG:
        out['orientation_policy'] = {'normal_angle_tolerance_deg': tolerance_deg(design)}
    return out


class HistoryConflictError(RuntimeError):
    def __init__(self, reason):
        super().__init__('Undo history is no longer available')
        self.reason = reason


@dataclass(frozen=True)
class HistorySettings:
    steps: int = 10
    project_bytes_max: int = 256 * 1024**2
    total_bytes_max: int = 1024**3
    idle_seconds: int = 1800

    @classmethod
    def from_env(cls):
        defaults = cls(steps=100 if os.environ.get('RAWIBUMI_DEPLOYMENT_EDITION') == 'commercial' else 10)
        values = {}
        for name, field in (('RAWIBUMI_UNDO_HISTORY_STEPS', 'steps'), ('RAWIBUMI_UNDO_PROJECT_BYTES_MAX', 'project_bytes_max'), ('RAWIBUMI_UNDO_TOTAL_BYTES_MAX', 'total_bytes_max'), ('RAWIBUMI_UNDO_IDLE_SECONDS', 'idle_seconds')):
            raw = os.environ.get(name)
            if raw is not None and not re.fullmatch(r'[0-9]+', raw):
                raise ValueError(f'{name} must be a positive integer')
            value = getattr(defaults, field) if raw is None else int(raw)
            if value < 1 or (field == 'steps' and value > 100):
                raise ValueError(f'{name} must be ' + ('between 1 and 100' if field == 'steps' else 'a positive integer'))
            values[field] = value
        return cls(**values)


@dataclass(frozen=True)
class Edge:
    entry_id: str
    label: str
    before: bytes
    after: bytes


@dataclass(frozen=True)
class Ring:
    past: tuple[Edge, ...] = ()
    future: tuple[Edge, ...] = ()
    edited: float = 0
    reason: str | None = None

    @property
    def payload_bytes(self):
        return sum(len(value) for value in {id(v): v for e in self.past + self.future for v in (e.before, e.after)}.values())


class DesignHistory:
    """All calls are serialized by the owning store lock, including save publication."""
    def __init__(self, settings=None, *, clock=time.monotonic):
        self.settings = settings or HistorySettings.from_env()
        self.clock = clock
        self.rings = OrderedDict()

    def _expire(self):
        now = self.clock()
        for key, ring in list(self.rings.items()):
            if (ring.past or ring.future) and now - ring.edited >= self.settings.idle_seconds:
                self.rings[key] = Ring(reason='expired')

    def clear(self, project_id, reason='barrier'):
        self.rings[project_id] = Ring(reason=reason)

    def prepare(self, project_id, before, after, label, *, mode='edit'):
        # No bookkeeping mutation before the atomic store save succeeds.
        if mode == 'neutral':
            return None
        if mode == 'barrier' or before is None:
            return Ring(reason='barrier')
        left, right = projection(before), projection(after)
        if left == right:
            return None
        old = self.rings.get(project_id, Ring())
        if self.clock() - old.edited >= self.settings.idle_seconds:
            old = Ring()
        # External writes not through this service must never splice two states.
        if old.past and old.past[-1].after != left:
            old = Ring()
        elif old.past:
            left = old.past[-1].after  # share the exact adjacent immutable bytes
        edge = Edge(uuid4().hex, label, left, right)
        ring = Ring(past=(*old.past, edge)[-self.settings.steps:], edited=self.clock())
        while ring.past and ring.payload_bytes > min(self.settings.project_bytes_max, self.settings.total_bytes_max):
            ring = replace(ring, past=ring.past[1:], reason='byte_limit')
        return ring

    def publish(self, project_id, ring):
        if ring is None:
            return
        self._expire()
        self.rings.pop(project_id, None)
        self.rings[project_id] = ring
        while sum(r.payload_bytes for r in self.rings.values()) > self.settings.total_bytes_max:
            victim = next(key for key, value in self.rings.items() if value.payload_bytes)
            self.clear(victim, 'server_byte_limit')

    def view(self, project_id):
        self._expire()
        ring = self.rings.get(project_id, Ring(reason='history_unavailable'))
        return {'limit': self.settings.steps,
                'past': [{'entry_id': e.entry_id, 'label': e.label} for e in ring.past],
                'future': [{'entry_id': e.entry_id, 'label': e.label} for e in ring.future],
                'reason': ring.reason}

    def target(self, project_id, bundle, *, redo, expected_project_revision_id, expected_entry_id):
        self._expire()
        ring = self.rings.get(project_id, Ring())
        edges = ring.future if redo else ring.past
        if not edges:
            self.clear(project_id, 'history_unavailable')
            raise HistoryConflictError('history_unavailable')
        edge = edges[0] if redo else edges[-1]
        if (edge.entry_id != expected_entry_id or bundle['project']['project_revision']['project_revision_id'] != expected_project_revision_id
                or projection(bundle) != (edge.before if redo else edge.after)):
            self.clear(project_id, 'revision_mismatch')
            raise HistoryConflictError('revision_mismatch')
        moved = (replace(ring, past=(*ring.past, edge), future=ring.future[1:], edited=self.clock()) if redo
                 else replace(ring, past=ring.past[:-1], future=(edge, *ring.future), edited=self.clock()))
        return json.loads(edge.after if redo else edge.before), edge.label, moved


def validate_restored_bundle(bundle):
    """Existing persistent contracts, without an execution/readiness geometry gate."""
    return _bundle_validator().validate(bundle)


from functools import lru_cache


@lru_cache(maxsize=1)
def _bundle_validator():
    from pathlib import Path
    from referencing import Registry, Resource
    from jsonschema import Draft202012Validator, FormatChecker
    root = Path(__file__).resolve().parents[2]
    registry = Registry()
    for directory in ('schemas', 'components/schema', 'weather/schema', 'geometry/scene', 'geometry/coordinates', 'geometry/scene3d', 'geometry/shading', 'electrical/schema', 'apps/web/schema', 'apps/api/schema'):
        for path in (root / directory).glob('*.schema.json'):
            schema = json.loads(path.read_text())
            if '$id' in schema:
                registry = registry.with_resource(schema['$id'], Resource.from_contents(schema))
    schema = json.loads((root / 'apps/api/schema/project-workspace-bundle.schema.json').read_text())
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())
