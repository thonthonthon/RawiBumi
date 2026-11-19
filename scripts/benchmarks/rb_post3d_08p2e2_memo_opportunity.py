"""E2 exact memo observation; workload execution requires separate authorization.

The observer never makes a cache decision, binds a holder, evaluates a quantity,
or repeats a scientific callback. Observer faults are latched, not propagated
through the solver. A completed workload with partial telemetry is INCOMPLETE.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import contextmanager
from dataclasses import dataclass, field
import functools
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.benchmarks import rb_post3d_08p2e1_root_work as e1

BASE = '8ad1cfcd6165d8cdbb3104fc236c76f694dee955'
BRANCH = 'ai/rb-post3d-08p2-e2-r2a-memo-observe'
EVIDENCE = ROOT / '.ai/validation/rb_post3d_08p2e2'
CAPACITIES = (256, 512, 1024, 2048, 4096)
SCENARIOS = tuple(map(str, CAPACITIES)) + ('bounded_unlimited', 'last_key', '256_plus_last_key')
MAX_KEYS = 3145728  # diagnostic retention only; production memo stays at 256
MAX_EVENTS = 150000000
MAX_WALL_SECONDS = 2400
PHASES = e1.PHASES
ENTRY_ESTIMATE = 1024  # conservative planning allowance, not measured allocation
SLOT_ESTIMATE = 8192


def not_observed(reason):
    return {'status': 'NOT_OBSERVED', 'reason': reason}


def encode_key(key):
    """Lossless journal representation; replay uses Python's tuple equality.

    Tolerance signed zero / int / bool equivalence is intentionally Python's
    existing equality, whereas voltage signed zero is distinct via target.hex().
    Never hash, compare, stringify or convert an unknown option object.
    """
    if type(key) is not tuple or len(key) != 4 or type(key[0]) is not str or len(key[0]) > 32:
        raise ValueError('unobserved exact key shape')
    result = [key[0]]
    for value in key[1:]:
        if type(value) is float and math.isfinite(value):
            result.append(['float', value.hex()])
        elif type(value) in (int, bool) and (type(value) is bool or value.bit_length() <= 64):
            result.append([type(value).__name__, value])
        else:
            raise ValueError('unsupported solver-option type/value')
    return result


def decode_key(encoded):
    key = (encoded[0], *(float.fromhex(v) if t == 'float' else v for t, v in encoded[1:]))
    if encode_key(key) != encoded:
        raise ValueError('noncanonical journal key')
    return key


@dataclass
class SlotReplay:
    """First-N ranks plus the exact last successful key, owned by this slot.

    The hybrid retains all first-256 keys and additionally the last key.
    Successful hits update the last key too; failures leave both states intact.
    """
    ranks: dict = field(default_factory=dict)
    last: tuple | None = None

    def predict(self, key):
        rank = self.ranks.get(key)
        last_hit = key == self.last
        return {**{str(n): rank is not None and rank <= n for n in CAPACITIES},
                'bounded_unlimited': rank is not None, 'last_key': last_hit,
                '256_plus_last_key': (rank is not None and rank <= 256) or last_hit}

    def admit(self, key, success):
        if success:
            if key not in self.ranks:
                self.ranks[key] = len(self.ranks) + 1
            self.last = key


class Journal:
    """Streaming exact events, bounded on disk; no event-list retention."""
    def __init__(self, stream, byte_cap):
        self.stream, self.byte_cap = stream, byte_cap
        self.bytes = self.events = 0
        self.sha = hashlib.sha256()

    def append(self, event):
        raw = (json.dumps(event, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
        if len(raw) > 4096 or self.bytes + len(raw) > self.byte_cap:
            raise OverflowError('journal byte/row cap exhausted')
        if self.stream.write(raw) != len(raw):
            raise OSError('short journal write')
        self.sha.update(raw)
        self.bytes += len(raw)
        self.events += 1

    def identity(self):
        return dict(events=self.events, bytes=self.bytes, sha256=self.sha.hexdigest())


class Replay:
    """Derived counts; 256 reconciliation must hold for every eligible event."""
    def __init__(self, max_slots=4096, max_keys=MAX_KEYS):
        if not 0 < max_keys <= MAX_KEYS:
            raise ValueError('max_keys exceeds bounded implementation limits')
        self.max_slots, self.max_keys = max_slots, max_keys
        self.slots = {}
        self.keys = 0
        self.derived = {p: {n: dict(hits=0, misses=0, successful_admissions=0,
            potential_avoided_uncached_evaluations=0, potential_avoided_observed_i_from_v=0)
            for n in SCENARIOS} for p in PHASES}
        for scenarios in self.derived.values():
            for counts in scenarios.values():
                counts.update(potential_additional_uncached_evaluations=0,
                              counterfactual_minus_actual_uncached_evaluations=0)

    def register(self, serial):
        if serial in self.slots or len(self.slots) >= self.max_slots:
            raise OverflowError('slot registration cap/duplicate')
        self.slots[serial] = SlotReplay()

    def event(self, event):
        if event['slot'] is None:
            return
        slot = self.slots[event['slot']]
        key = decode_key(event['key'])
        predictions = slot.predict(key)
        hit, success = event['actual'] == 'hit', event['success']
        if predictions['256'] != hit:
            raise ValueError('256 hit/miss reconciliation failed')
        if event['uncached_calls'] != int(not hit):
            raise ValueError('256 uncached-call reconciliation failed')
        expected_admission = success and not hit and len(slot.ranks) < 256
        if event['admitted'] != expected_admission:
            raise ValueError('256 admission reconciliation failed')
        if not success and any(predictions.values()):
            raise ValueError('successful-key replay later failed; pure outcome assumption invalid')
        new = success and key not in slot.ranks
        if new and self.keys >= self.max_keys:
            raise OverflowError('exact successful key cap exhausted')
        for name, predicted_hit in predictions.items():
            counts = self.derived[event['phase']][name]
            counts['hits' if predicted_hit else 'misses'] += 1
            admitted = success and not predicted_hit and (
                name in ('bounded_unlimited', 'last_key', '256_plus_last_key') or
                len(slot.ranks) < int(name))
            counts['successful_admissions'] += int(admitted)
            avoided = success and not hit and predicted_hit
            additional = success and hit and not predicted_hit
            counts['potential_avoided_uncached_evaluations'] += int(avoided)
            counts['potential_additional_uncached_evaluations'] += int(additional)
            counts['counterfactual_minus_actual_uncached_evaluations'] += int(additional) - int(avoided)
            counts['potential_avoided_observed_i_from_v'] += event['i_from_v_calls'] if avoided else 0
        slot.admit(key, success)
        self.keys += int(new)

    def memory(self):
        extra = {str(n): sum(max(0, min(len(s.ranks), n) - min(len(s.ranks), 256))
                            for s in self.slots.values()) * ENTRY_ESTIMATE for n in CAPACITIES}
        extra['bounded_unlimited'] = sum(max(0, len(s.ranks) - 256) for s in self.slots.values()) * ENTRY_ESTIMATE
        # An additional last-key allowance per slot; no original entry is evicted.
        extra['256_plus_last_key'] = len(self.slots) * ENTRY_ESTIMATE
        retained = self.max_keys * ENTRY_ESTIMATE + self.max_slots * SLOT_ESTIMATE
        return dict(basis='ESTIMATE: cumulative all-slot upper bound on peak, no lifetime overlap assumption',
            entry_allowance_bytes=ENTRY_ESTIMATE, modeled_incremental_bytes=extra,
            chronological_peak_incremental_production_bytes=not_observed('no chronological slot-lifetime observation'),
            last_key_retained_bytes=len(self.slots) * ENTRY_ESTIMATE,
            diagnostic_key_retention_allowance_bytes=self.max_keys * ENTRY_ESTIMATE,
            diagnostic_slot_retention_allowance_bytes=self.max_slots * SLOT_ESTIMATE,
            diagnostic_retention_allowance_bytes=retained,
            online_replay_allowance_bytes=retained,
            offline_replay_allowance_bytes=retained,
            sequential_verification_peak_allowance_bytes=retained + 32 * 1024**2,
            verification_memory_basis='online ranks released before offline replay; allocator RSS may remain resident',
            target_bytes=256 * 1024**2, observed_rss=not_observed('supplied only by external watchdog'))


def line_plan(function):
    """Fail closed if the source no longer has the inspected memo control flow."""
    source, start = inspect.getsourcelines(function)
    node = ast.parse(''.join(source)).body[0]
    body = node.body
    key_assignments = [s for s in body if isinstance(s, ast.Assign) and
                       any(isinstance(t, ast.Name) and t.id == 'key' for t in s.targets)]
    if len(key_assignments) != 1:
        raise ValueError('memo key assignment coverage changed')
    index = body.index(key_assignments[0])
    hit_if, call, admit_if, ret = body[index + 1:]
    if not (isinstance(hit_if, ast.If) and len(hit_if.body) == 1 and
            isinstance(hit_if.body[0], ast.Return) and isinstance(call, ast.Assign) and
            isinstance(call.value, ast.Call) and isinstance(call.value.func, ast.Name) and
            call.value.func.id == '_branch_current_at_voltage_uncached' and
            isinstance(admit_if, ast.If) and len(admit_if.body) == 1 and
            isinstance(admit_if.body[0], ast.Assign) and isinstance(ret, ast.Return)):
        raise ValueError('memo hit/miss/admission coverage changed')
    return dict(key_ready=start + hit_if.lineno - 1,
                hit=start + hit_if.body[0].lineno - 1,
                admission=start + admit_if.body[0].lineno - 1)


class Observer:
    """Single-thread scoped observer; no cache, binding or physical mutation."""
    def __init__(self, journal, *, max_events=MAX_EVENTS, max_slots=4096,
                 max_keys=MAX_KEYS, max_frames=256):
        if not 0 < max_events <= MAX_EVENTS:
            raise ValueError('max_events exceeds bounded implementation limits')
        from shading.electrical import substring_reference as kernel
        from shading.electrical import parameterization, dc_attribution, module_series_adapter
        from engine.simulation import detailed_backend, detailed_attribution, artifacts
        import pvlib
        self.kernel = kernel
        self.original = kernel._branch_current_at_voltage
        if dc_attribution._branch_current_at_voltage is not self.original:
            raise ValueError('attribution memo binding changed')
        if (module_series_adapter._BranchEndpointHolder is not kernel._BranchEndpointHolder or
                dc_attribution._BranchEndpointHolder is not kernel._BranchEndpointHolder or
                kernel._BRANCH_CURRENT_MEMO_LIMIT != 256):
            raise ValueError('holder binding/capacity changed')
        self.plan = line_plan(self.original)
        self.memo_code = self.original.__code__
        self.uncached_code = kernel._branch_current_at_voltage_uncached.__code__
        self.holder_code = kernel._BranchEndpointHolder.__init__.__code__
        self.i_code = pvlib.pvsystem.i_from_v.__code__
        self.phase_codes = {detailed_backend._evaluate_interval.__code__: 'producer',
            detailed_attribution._evaluate_attribution_interval.__code__: 'attribution',
            parameterization._evaluate_numerical_candidate_physics.__code__: 'b2_numerical_acceptance',
            artifacts.persist_run_package.__code__: 'persistence',
            artifacts.verify_run_package.__code__: 'verification'}
        self.bound_functions = [(owner, name, getattr(owner, name), getattr(owner, name).__code__)
            for owner, name in ((kernel, '_branch_current_at_voltage_uncached'),
                (kernel._BranchEndpointHolder, '__init__'),
                (kernel._BranchEndpointHolder, 'bind'), (pvlib.pvsystem, 'i_from_v'),
                (detailed_backend, '_evaluate_interval'),
                (detailed_attribution, '_evaluate_attribution_interval'),
                (parameterization, '_evaluate_numerical_candidate_physics'),
                (artifacts, 'persist_run_package'), (artifacts, 'verify_run_package'))]
        self.journal = journal
        self.replay = Replay(max_slots, max_keys)
        self.max_events, self.max_frames = max_events, max_frames
        self.events = self.calls = 0
        self.fault = None
        self.overflow = False
        self.phase = 'dispatch'
        self.context = None
        self.pending = []
        self.active_memos = {}
        self.active_phases = {}
        self.active_uncached = set()
        self.slot_ids = {}
        self.ownership = {}
        self.next_holder = 0
        self.next_slot = 0
        self.direct = {p: dict(memo_calls=0, original_memo_calls=0, hits=0, misses=0,
            bypasses=0, bypass_uncached_calls=0, failures=0, admissions=0, saturation_rejections=0,
            original_uncached_calls=0, standalone_uncached_calls=0, i_from_v_calls=0)
            for p in PHASES}
        self.b2_contexts = {p: dict(memo_calls=0, i_from_v_calls=0) for p in PHASES}
        self.patches = []
        self.owner_thread = None
        self.profile_hook, self.trace_hook = self.profile, self.trace
        self.used = False

    def invalidate(self, exc):
        # Bound error retention; never stringify arbitrary user exceptions.
        if self.fault is None:
            args = BaseException.args.__get__(exc)
            kind = type.__getattribute__(type(exc), '__name__')
            self.fault = kind + ':' + (args[0][:200] if args and type(args[0]) is str else 'observer error')
        self.overflow |= isinstance(exc, OverflowError)

    def safe(self, callback, *args):
        if self.fault is not None:
            return None
        try:
            if threading.get_ident() != self.owner_thread:
                raise ValueError('foreign-thread observation')
            return callback(*args)
        except BaseException as exc:
            self.invalidate(exc)
            return None

    def budget(self):
        if self.events >= self.max_events:
            raise OverflowError('selected event cap exhausted')
        self.events += 1

    def profile(self, frame, event, arg):
        self.safe(self._profile, frame, event)

    def _profile(self, frame, event):
        code, fid = frame.f_code, id(frame)
        if event not in ('call', 'return'):
            return
        if event == 'return':
            if fid in self.active_phases:
                self.phase, self.context = self.active_phases.pop(fid)
            self.active_uncached.discard(fid)
            self.active_memos.pop(fid, None)
            return
        if code in self.phase_codes:
            self.check_bindings()
            self.budget()
            if len(self.active_phases) >= self.max_frames:
                raise OverflowError('phase frame cap exhausted')
            self.active_phases[fid] = (self.phase, self.context)
            requested = self.phase_codes[code]
            if requested == 'b2_numerical_acceptance':
                if self.phase != requested:
                    self.context = self.phase
                self.phase = requested
            elif self.phase != 'b2_numerical_acceptance':
                self.phase = requested
        elif code == self.memo_code:
            self.budget()
            self.direct[self.phase]['original_memo_calls'] += 1
            if not self.pending or self.pending[-1]['frame'] is not None:
                raise ValueError('original memo call bypassed observational wrapper')
            record = self.pending[-1]
            record['frame'] = fid
            self.active_memos[fid] = record
        elif code == self.uncached_code:
            self.budget()
            self.direct[self.phase]['original_uncached_calls'] += 1
            record = self.active_memos.get(id(frame.f_back))
            if record is None:
                self.direct[self.phase]['standalone_uncached_calls'] += 1
            else:
                record['uncached_calls'] += 1
            if len(self.active_uncached) >= self.max_frames:
                raise OverflowError('uncached frame cap exhausted')
            self.active_uncached.add(fid)
        elif code == self.i_code:
            self.budget()
            self.direct[self.phase]['i_from_v_calls'] += 1
            if self.phase == 'b2_numerical_acceptance':
                self.b2_contexts[self.context]['i_from_v_calls'] += 1
            # Nearest original memo owns descendants; count only inside its uncached invocation.
            parent = frame.f_back
            depth, inside_uncached = 0, False
            while parent is not None and depth < self.max_frames:
                inside_uncached |= id(parent) in self.active_uncached
                record = self.active_memos.get(id(parent))
                if record is not None:
                    if inside_uncached:
                        record['i_from_v_calls'] += 1
                    break
                parent, depth = parent.f_back, depth + 1
            if parent is not None and depth == self.max_frames:
                raise OverflowError('kernel ancestry cap exhausted')

    def trace(self, frame, event, arg):
        if frame.f_code not in (self.memo_code, self.holder_code):
            return None
        self.safe(self._trace, frame, event)
        return self.trace_hook

    def _trace(self, frame, event):
        self.budget()
        if frame.f_code == self.holder_code:
            if event == 'return':
                holder = frame.f_locals['self']
                if type(holder) is not self.kernel._BranchEndpointHolder:
                    raise ValueError('unknown holder type')
                self.next_holder += 1
                creator = frame.f_back.f_code if frame.f_back is not None else None
                origin = (creator.co_filename.replace(str(ROOT) + '/', '') + ':' + creator.co_qualname
                          if creator is not None else 'NOT_OBSERVED')
                if len(origin) > 1024:
                    raise OverflowError('holder origin length cap exhausted')
                for branch_order, slot in enumerate(holder._slots.values()):
                    if slot.currents:
                        raise ValueError('new holder contains preexisting memo entries')
                    self.next_slot += 1
                    self.replay.register(self.next_slot)
                    self.ownership[self.next_slot] = dict(holder_serial=self.next_holder,
                        branch_order=branch_order, creation_phase=self.phase,
                        b2_parent_context=self.context, creator=origin)
                    # IDs are overwritten on each constructor: no strong references,
                    # no extension of model lifetime, no sharing across ID reuse.
                    self.slot_ids[id(slot)] = self.next_slot
                if len(self.slot_ids) > self.replay.max_slots:
                    raise OverflowError('slot identity cap exhausted')
            return
        if event == 'call':
            # CPython delivers the global trace call before the profile call.
            # Ownership is established by profile before the first line event.
            return
        record = self.active_memos.get(id(frame))
        if record is None:
            raise ValueError('memo frame has no wrapper owner')
        if event == 'line' and frame.f_lineno == self.plan['key_ready']:
            slot, key = frame.f_locals['slot'], frame.f_locals['key']
            record['key_ready'] = True
            if slot is not None:
                if type(slot.currents) is not dict:
                    raise ValueError('unknown production memo storage')
                serial = self.slot_ids.get(id(slot))
                if serial is None:
                    raise ValueError('preexisting/unobserved holder lifetime')
                record.update(slot=serial, key=encode_key(key), storage=slot.currents,
                              size_before=len(slot.currents))
        elif event == 'line' and frame.f_lineno == self.plan['hit']:
            record['hit'] = True
        elif event == 'line' and frame.f_lineno == self.plan['admission']:
            record['admission_path'] = True

    def begin(self):
        self.check_bindings()
        self.budget()
        if len(self.pending) >= self.max_frames:
            raise OverflowError('wrapper frame cap exhausted')
        if self.pending:
            raise ValueError('reentrant memo access stream not covered')
        record = dict(frame=None, phase=self.phase, context=self.context, slot=None,
            key=None, key_ready=False, hit=False, admission_path=False,
            uncached_calls=0, i_from_v_calls=0, storage=None, size_before=0)
        self.pending.append(record)
        return record

    def finish(self, record, success):
        self.check_bindings()
        counts = self.direct[record['phase']]
        counts['memo_calls'] += 1
        counts['failures'] += int(not success)
        if record['phase'] == 'b2_numerical_acceptance':
            self.b2_contexts[record['context']]['memo_calls'] += 1
        if record['slot'] is not None:
            actual = 'hit' if record['hit'] else 'miss'
            counts['hits' if record['hit'] else 'misses'] += 1
            admitted = success and record['admission_path']
            if len(record['storage']) != record['size_before'] + int(admitted):
                raise ValueError('production admission size changed unexpectedly')
            counts['admissions'] += int(admitted)
            counts['saturation_rejections'] += int(success and not record['hit'] and not admitted)
        else:
            actual, admitted = 'bypass', False
            counts['bypasses'] += 1
            counts['bypass_uncached_calls'] += record['uncached_calls']
            if success and not record['key_ready']:
                raise ValueError('successful call lacked key-path coverage')
        event = dict(sequence=self.calls + 1, phase=record['phase'], b2_context=record['context'],
            slot=record['slot'], key=record['key'], actual=actual, success=success,
            admitted=admitted, uncached_calls=record['uncached_calls'],
            i_from_v_calls=record['i_from_v_calls'])
        self.journal.append(event)
        self.replay.event(event)
        self.calls += 1

    def wrapper(self, *args, **kwargs):
        record = self.safe(self.begin)
        try:
            result = self.original(*args, **kwargs)  # exactly once, unchanged arguments
        except BaseException:
            if record is not None:
                self.safe(self.finish, record, False)
            raise  # same exception object; no observer failure replaces it
        else:
            if record is not None:
                self.safe(self.finish, record, True)
            return result  # unchanged result object
        finally:
            if record is not None:
                if self.pending and self.pending[-1] is record:
                    self.pending.pop()
                else:
                    self.invalidate(ValueError('wrapper stack mismatch'))

    def aliases(self):
        bindings = []
        for module in tuple(sys.modules.values()):
            if type(module) is not ModuleType:
                continue
            namespace = vars(module)
            if len(namespace) > 16384:
                raise OverflowError('module namespace scan cap exhausted')
            for name, value in tuple(namespace.items()):
                if value is self.original:
                    bindings.append((module, name, value))
                    if len(bindings) > 256:
                        raise OverflowError('memo alias registry cap exhausted')
        return bindings

    def check_bindings(self):
        for module, name, original in self.patches:
            if vars(module).get(name) is not self.wrapped:
                raise ValueError('memo binding replaced during observation')
        for owner, name, function, code in self.bound_functions:
            if getattr(owner, name, None) is not function or function.__code__ is not code:
                raise ValueError('observed call binding replaced')
        if self.original.__code__ is not self.memo_code:
            raise ValueError('memo code replaced')
        if self.kernel._BRANCH_CURRENT_MEMO_LIMIT != 256:
            raise ValueError('production memo limit changed')

    @contextmanager
    def installed(self):
        if self.used or sys.getprofile() is not None or sys.gettrace() is not None:
            raise RuntimeError('fresh observer and exclusive profile/trace hooks required')
        self.used = True
        self.owner_thread = threading.get_ident()
        # A real closure permits wraps without mutating the original or bound method.
        def delegated(*args, **kwargs):
            return self.wrapper(*args, **kwargs)
        self.wrapped = functools.wraps(self.original)(delegated)
        self.patches = self.aliases()
        if not any(m is self.kernel and n == '_branch_current_at_voltage' for m, n, _ in self.patches):
            raise ValueError('canonical memo binding missing')
        try:
            for module, name, _ in self.patches:
                vars(module)[name] = self.wrapped
            sys.setprofile(self.profile_hook)
            sys.settrace(self.trace_hook)
            yield self
        finally:
            if sys.getprofile() is not self.profile_hook or sys.gettrace() is not self.trace_hook:
                self.invalidate(ValueError('observation hooks replaced'))
            if sys.gettrace() is self.trace_hook:
                sys.settrace(None)
            if sys.getprofile() is self.profile_hook:
                sys.setprofile(None)
            self.safe(self.check_bindings)
            for module, name, original in reversed(self.patches):
                if vars(module).get(name) is self.wrapped:
                    vars(module)[name] = original
            # A module imported while the hook was installed may import the wrapper.
            # Restore those aliases too, even after a latched telemetry fault.
            try:
                for module in tuple(sys.modules.values()):
                    if type(module) is not ModuleType:
                        continue
                    namespace = vars(module)
                    for name, value in tuple(namespace.items()):
                        if value is self.wrapped:
                            namespace[name] = self.original
            except BaseException as exc:
                self.invalidate(exc)
            if self.pending or self.active_memos or self.active_uncached or self.active_phases:
                self.invalidate(ValueError('live observation frames at cleanup'))
            self.pending.clear()
            self.active_memos.clear()
            self.active_phases.clear()
            self.active_uncached.clear()

    def report(self, required_phases=('producer', 'attribution', 'b2_numerical_acceptance')):
        if self.replay is None:
            raise RuntimeError('observation already frozen; replay released')
        reasons = []
        if self.fault:
            reasons.append(self.fault)
        for phase, counts in self.direct.items():
            if counts['memo_calls'] != counts['original_memo_calls']:
                reasons.append(phase + ': wrapper/original memo mismatch')
            expected = counts['misses'] + counts['bypass_uncached_calls']
            observed = counts['original_uncached_calls'] - counts['standalone_uncached_calls']
            if observed != expected:
                reasons.append(phase + ': independent uncached count mismatch')
            if self.replay.derived[phase]['256']['misses'] != counts['misses']:
                reasons.append(phase + ': aggregate 256 miss mismatch')
        for phase in required_phases:
            if self.direct[phase]['memo_calls'] == 0:
                reasons.append(phase + ': missing memo coverage')
        if not self.calls:
            reasons.append('no completed memo observations')
        complete = not reasons
        memory = self.replay.memory()
        memory['observation_complete'] = complete
        if not complete:
            memory['modeled_incremental_bytes'] = not_observed('whole observation incomplete')
            memory['last_key_retained_bytes'] = not_observed('whole observation incomplete')
        return dict(status='COMPLETED' if complete else ('OVERFLOW' if self.overflow else 'INCOMPLETE'),
            reasons=reasons, selected_events=self.events, overflow=self.overflow,
            direct_observations=self.direct,
            direct_observation_completeness='COMPLETE' if complete else 'PARTIAL_OR_NOT_OBSERVED',
            b2_parent_contexts=self.b2_contexts,
            exact_stream=self.journal.identity(), slot_lifetimes_observed=len(self.replay.slots),
            holder_lifetimes_observed=self.next_holder, slot_ownership=self.ownership,
            hook_bindings=[dict(owner=getattr(owner, '__name__', type(owner).__name__),
                                binding=name, file=code.co_filename, line=code.co_firstlineno,
                                qualname=code.co_qualname) for owner, name, _, code in self.bound_functions],
            wrapped_memo_aliases=[m.__name__ + ':' + n for m, n, _ in self.patches],
            successful_keys_retained=self.replay.keys,
            reconciliation_256='MATCH' if complete else 'NOT_ESTABLISHED',
            counterfactuals=self.replay.derived if complete else not_observed('incomplete observation; partial counts inadmissible'),
            memory=memory,
            hypotheses='Same eligible exact access stream and pure successful outcomes; no causal speedup or kernel-call savings claim.',
            additional_i_from_v_cost=not_observed('actual hits do not evaluate kernels; standalone last_key extra misses have no observed cost'),
            phase_coverage={p: 'OBSERVED' if any(c.values()) else not_observed('phase not reached')
                            for p, c in self.direct.items()},
            coverage_gaps={p: not_observed(v['reason']) for p, v in e1.coverage().items()})

    def snapshot_and_release(self):
        """One detached immutable snapshot; never report from released rank state."""
        if self.replay is None:
            raise RuntimeError('observation already frozen; replay released')
        try:
            return observation_bytes(self.report())
        finally:
            self.replay.slots.clear()
            self.replay = None


def observation_bytes(observation):
    # Normalize JSON object keys (slot serials) before canonical sorting so the
    # snapshot digest is reproducible from the serialized child/parent report.
    detached = json.loads(json.dumps(observation, allow_nan=False))
    return json.dumps(detached, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read_journal_sidecar(path):
    path = Path(path)
    sidecar = Path(str(path) + '.sha256')
    if path.is_symlink() or sidecar.is_symlink():
        raise ValueError('journal/sidecar must not redirect through symlinks')
    if sidecar.stat().st_size != 65:
        raise ValueError('invalid journal SHA-256 sidecar size')
    with sidecar.open('rb') as stream:
        raw = stream.read(66)
    if len(raw) != 65 or raw[-1:] != b'\n':
        raise ValueError('invalid journal SHA-256 sidecar')
    digest = raw[:-1].decode('ascii')
    if not e1.sha256_value(digest):
        raise ValueError('invalid journal SHA-256 digest')
    return digest


def write_journal_sidecar(path, identity):
    """Publish the writer's final digest only after a complete, closed stream."""
    path = Path(path)
    if (not e1.sha256_value(identity['sha256']) or identity['events'] <= 0
            or path.stat().st_size != identity['bytes']):
        raise ValueError('incomplete journal identity')
    with Path(str(path) + '.sha256').open('x') as stream:
        stream.write(identity['sha256'] + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def verify_journal_bytes(path, max_bytes):
    """Parent independently checks final raw bytes without another rank table."""
    expected = read_journal_sidecar(path)
    sha, size, events, last = hashlib.sha256(), 0, 0, b''
    with Path(path).open('rb') as stream:
        while True:
            raw = stream.read(min(1024**2, max_bytes - size + 1))
            if not raw:
                break
            size += len(raw)
            if size > max_bytes:
                raise OverflowError('journal byte cap exhausted during parent verification')
            sha.update(raw)
            events += raw.count(b'\n')
            last = raw[-1:]
    if not events or last != b'\n' or sha.hexdigest() != expected or read_journal_sidecar(path) != expected:
        raise ValueError('journal raw-byte/sidecar mismatch')
    return dict(events=events, bytes=size, sha256=sha.hexdigest())


def verify_journal(path, max_events=MAX_EVENTS, max_bytes=2 * 1024**3,
                   max_slots=4096, max_keys=MAX_KEYS):
    """Independent offline replay of an exact journal, bounded while parsing."""
    replay, sha, count, size = Replay(max_slots, max_keys), hashlib.sha256(), 0, 0
    if not 0 < max_events <= MAX_EVENTS:
        raise ValueError('max_events exceeds bounded implementation limits')
    expected = read_journal_sidecar(path)
    with Path(path).open('rb') as stream:
        while True:
            raw = stream.readline(4097)
            if not raw:
                break
            count, size = count + 1, size + len(raw)
            if len(raw) > 4096 or not raw.endswith(b'\n') or count > max_events or size > max_bytes:
                raise OverflowError('journal verification bound exceeded')
            event = json.loads(raw)
            if event['sequence'] != count or event['phase'] not in PHASES:
                raise ValueError('journal sequence/phase mismatch')
            if event['slot'] is not None and event['slot'] not in replay.slots:
                replay.register(event['slot'])
            replay.event(event)
            sha.update(raw)
    if not count or sha.hexdigest() != expected or read_journal_sidecar(path) != expected:
        raise ValueError('journal raw-byte/sidecar mismatch')
    return dict(events=count, bytes=size, sha256=sha.hexdigest(), counterfactuals=replay.derived)


def controls(args):
    if args.modules not in (10, 50) or args.intervals != 1 or args.workers != 1:
        raise ValueError('only 10/50 modules, one interval, one worker')
    if not math.isfinite(args.wall_cap_seconds) or not 0 < args.wall_cap_seconds <= MAX_WALL_SECONDS:
        raise ValueError('wall cap must be finite in (0,2400]')
    if not 0 < args.memory_limit_mib <= 4096:
        raise ValueError('RSS cap must be in (0,4096] MiB')
    for name, ceiling in (('max_events', MAX_EVENTS), ('max_slots', 4096),
                          ('max_keys', MAX_KEYS), ('journal_limit_mib', 2048)):
        if not 0 < getattr(args, name) <= ceiling:
            raise ValueError(name + ' exceeds bounded implementation limits')


def validate_output(path):
    path = path.absolute()
    if EVIDENCE.resolve() != EVIDENCE.absolute():
        raise ValueError('E2 evidence root must not redirect through symlinks')
    for suffix in ('', '.sha256', '.events.jsonl', '.events.jsonl.sha256', '.child.json', '.child.json.sha256'):
        candidate = Path(str(path) + suffix)
        if not candidate.resolve().is_relative_to(EVIDENCE) or candidate.resolve() == EVIDENCE:
            raise ValueError('output must be inside separate E2 evidence directory')
        if candidate.exists() or candidate.is_symlink():
            raise ValueError('output already exists')
    return path


def reference(args):
    report, digest = e1.read_evidence(args.reference_e1)
    identity = e1.artifact_identity(report, 'baseline')
    counts, counts_digest = e1.read_evidence(args.reference_e1_counts)
    if e1.artifact_identity(counts, 'counts') != identity:
        raise ValueError('independent E1 baseline/counts identities differ')
    if report['controls']['modules'] != args.modules:
        raise ValueError('E1 reference module count differs')
    if e1.CACHE_STATES[args.cache_state][0] not in e1.CACHE_STATES[report['cache_selection']]:
        raise ValueError('E1 reference lacks selected cache coverage')
    sources = e1.hashes(e1.SOURCE_FILES)
    if sources != report['metadata']['source_hashes']:
        raise ValueError('E1 source fingerprints changed')
    if e1.hashes(report['metadata']['fixture_hashes']) != report['metadata']['fixture_hashes']:
        raise ValueError('E1 fixture fingerprints changed')
    if e1.metadata()['environment'] != report['metadata']['environment']:
        raise ValueError('E1 numerical environment differs')
    return report, digest, counts, counts_digest


def compare_direct_counts(observation, counts_reference, cache_state):
    record = next(p for p in counts_reference['passes'] if p['measurement_mode'] == 'counts')
    counters = next(r['counters'] for r in record['runs']
                    if r['cache_state'] == e1.CACHE_STATES[cache_state][0])
    for phase in PHASES:
        for field, function in (('original_memo_calls', '_branch_current_at_voltage'),
                                ('original_uncached_calls', '_branch_current_at_voltage_uncached'),
                                ('i_from_v_calls', 'i_from_v')):
            values = [v for k, v in counters[phase].items() if k.endswith(':' + function + ':calls')]
            if len(values) > 1 or observation['direct_observations'][phase][field] != sum(values):
                raise ValueError('immutable E1 actual call-count mismatch: ' + phase + ':' + field)
    return 'MATCH'


def child(args):
    report = dict(status='FAILED', overflow=False, hook_failure=None, runs=[],
                  cache_semantics=e1.CACHE_SEMANTICS, priming=None,
                  numerical_comparison=not_observed('workload not completed'),
                  independent_journal_verification=not_observed('observation not completed'),
                  journal_sidecar_verification=not_observed('observation not completed'),
                  independent_e1_call_counts=not_observed('observation not completed'))
    observer = None
    snapshot = None
    metadata_before = e1.metadata()
    task_before = metadata_before['task_sha256']
    harness_before = e1.digest(Path(__file__).read_bytes())
    try:
        ref, ref_digest, counts_ref, counts_digest = reference(args)
        fixture, run, artifacts, inputs, identity, provenance = e1.prepare_workload(args.modules)
        report.update(fixture_identity=identity, provenance=provenance,
            reference_e1=dict(path=str(args.reference_e1), sha256=ref_digest),
            reference_e1_counts=dict(path=str(args.reference_e1_counts), sha256=counts_digest),
            source_hashes=e1.hashes(e1.SOURCE_FILES), harness_sha256=harness_before,
            metadata=metadata_before,
            metadata_basis='E1 helper metadata harness fields identify E1; top-level harness fields identify E2',
            cache_selection=args.cache_state, modules=args.modules)
        with tempfile.TemporaryDirectory(prefix='e2-workload-', dir=EVIDENCE) as directory:
            if args.cache_state == 'warm':
                report['priming'] = e1.execute_cache_run(fixture, run, artifacts, inputs, directory, 'cold_physics_cache')
            with Path(str(args.output) + '.events.jsonl').open('xb') as stream:
                observer = Observer(Journal(stream, args.journal_limit_mib * 1024**2),
                    max_events=args.max_events, max_slots=args.max_slots, max_keys=args.max_keys)
                with observer.installed():
                    for temperature in e1.CACHE_STATES[args.cache_state]:
                        # E1 run sequence verbatim. E2 phase dispatch is established by original frames.
                        report['runs'].append(e1.execute_cache_run(fixture, run, artifacts, inputs, directory, temperature))
                stream.flush()
                os.fsync(stream.fileno())
        snapshot = observer.snapshot_and_release()
        observation = json.loads(snapshot)
        report['observation'] = observation
        report['sequential_verification'] = dict(online_replay_released=True,
            observation_snapshot_sha256=e1.digest(snapshot))
        if observation['status'] != 'COMPLETED':
            raise ValueError('incomplete observation cannot publish complete journal evidence')
        write_journal_sidecar(Path(str(args.output) + '.events.jsonl'), observation['exact_stream'])
        verified = verify_journal(Path(str(args.output) + '.events.jsonl'), args.max_events,
            args.journal_limit_mib * 1024**2, args.max_slots, args.max_keys)
        if verified != (observation['exact_stream'] | {'counterfactuals': observation['counterfactuals']}):
            raise ValueError('independent exact-stream replay mismatch')
        report['independent_journal_verification'] = 'MATCH'
        report['journal_sidecar_verification'] = 'MATCH'
        report['independent_e1_call_counts'] = compare_direct_counts(observation, counts_ref, args.cache_state)
        baseline = next(p for p in ref['passes'] if p['measurement_mode'] == 'baseline')
        if identity != baseline['fixture_identity']:
            raise ValueError('E1 workload identity mismatch')
        for measured in report['runs']:
            original = next(r for r in baseline['runs'] if r['cache_state'] == measured['cache_state'])
            if e1.run_identity(measured, measured['cache_state']) != e1.run_identity(original, original['cache_state']):
                raise ValueError('E1 numerical/cache/operation parity mismatch')
        report['numerical_comparison'] = 'MATCH'
        report['status'] = observation['status']
    except BaseException as exc:
        report.update(status='OVERFLOW' if isinstance(exc, OverflowError) else 'FAILED',
                      error_type=type(exc).__name__, error=str(exc)[:500])
    finally:
        if observer is not None:
            if observer.replay is not None:
                snapshot = observer.snapshot_and_release()
                report['observation'] = json.loads(snapshot)
                report['sequential_verification'] = dict(online_replay_released=True,
                    observation_snapshot_sha256=e1.digest(snapshot))
            report.update(overflow=observer.overflow, hook_failure=observer.fault)
            if observer.fault:
                report['status'] = 'OVERFLOW' if observer.overflow else 'INCOMPLETE'
        report['source_hashes_after'] = e1.hashes(e1.SOURCE_FILES)
        if report.get('source_hashes') != report['source_hashes_after']:
            report['status'] = 'FAILED'
        report['provenance_after'] = e1.loaded_source_hashes()
        report['task_sha256_after'] = e1.digest((ROOT / '.ai/TASK.md').read_bytes())
        report['harness_sha256_after'] = e1.digest(Path(__file__).read_bytes())
        if report['task_sha256_after'] != task_before or report['harness_sha256_after'] != harness_before:
            report['status'] = 'FAILED'
        before = report.get('provenance', {}).get('loaded_repository_source_hashes', {})
        if any(report['provenance_after'].get(k) != v for k, v in before.items()):
            report['status'] = 'FAILED'
    return report


def completed_child(report, args):
    """Fail closed on missing coverage, contradictory states or incomplete gates."""
    if report.get('status') != 'COMPLETED':
        return False
    obs = report.get('observation', {})
    if (obs.get('status') != 'COMPLETED' or obs.get('reconciliation_256') != 'MATCH'
            or obs.get('overflow') is not False or obs.get('reasons') != []
            or report.get('overflow') is not False or report.get('hook_failure') is not None
            or report.get('numerical_comparison') != 'MATCH'
            or report.get('independent_journal_verification') != 'MATCH'
            or report.get('journal_sidecar_verification') != 'MATCH'
            or report.get('independent_e1_call_counts') != 'MATCH'
            or report.get('cache_selection') != args.cache_state or report.get('modules') != args.modules):
        return False
    sequential = report.get('sequential_verification', {})
    if (sequential.get('online_replay_released') is not True
            or sequential.get('observation_snapshot_sha256') != e1.digest(observation_bytes(obs))):
        return False
    direct = obs.get('direct_observations', {})
    derived = obs.get('counterfactuals', {})
    if set(direct) != set(PHASES) or set(derived) != set(PHASES):
        return False
    for phase in ('producer', 'attribution', 'b2_numerical_acceptance'):
        if direct[phase].get('memo_calls', 0) <= 0:
            return False
    for phase in PHASES:
        d = direct[phase]
        if (set(derived[phase]) != set(SCENARIOS)
                or d.get('memo_calls') != d.get('original_memo_calls')
                or d.get('original_uncached_calls') != d.get('standalone_uncached_calls', 0) +
                    d.get('misses', 0) + d.get('bypass_uncached_calls', 0)
                or derived[phase].get('256', {}).get('misses') != d.get('misses')
                or derived[phase].get('256', {}).get('hits') != d.get('hits')
                or derived[phase].get('256', {}).get('successful_admissions') != d.get('admissions')
                or d.get('memo_calls') != d.get('hits', 0) + d.get('misses', 0) + d.get('bypasses', 0)):
            return False
        for counts in derived[phase].values():
            fields = ('hits', 'misses', 'successful_admissions',
                      'potential_avoided_uncached_evaluations', 'potential_avoided_observed_i_from_v',
                      'potential_additional_uncached_evaluations')
            if any(type(counts.get(k)) is not int or counts[k] < 0 for k in fields):
                return False
            if (counts['hits'] + counts['misses'] != d['hits'] + d['misses']
                    or counts.get('counterfactual_minus_actual_uncached_evaluations') !=
                        counts['potential_additional_uncached_evaluations'] -
                        counts['potential_avoided_uncached_evaluations']):
                return False
    memory = obs.get('memory', {})
    modeled = memory.get('modeled_incremental_bytes', {})
    if (memory.get('observation_complete') is not True
            or set(modeled) != set(map(str, CAPACITIES)) | {'bounded_unlimited', '256_plus_last_key'}
            or any(type(v) is not int or v < 0 for v in modeled.values())):
        return False
    retained = args.max_keys * ENTRY_ESTIMATE + args.max_slots * SLOT_ESTIMATE
    allowances = dict(diagnostic_key_retention_allowance_bytes=args.max_keys * ENTRY_ESTIMATE,
        diagnostic_slot_retention_allowance_bytes=args.max_slots * SLOT_ESTIMATE,
        diagnostic_retention_allowance_bytes=retained, online_replay_allowance_bytes=retained,
        offline_replay_allowance_bytes=retained,
        sequential_verification_peak_allowance_bytes=retained + 32 * 1024**2)
    if (any(type(memory.get(k)) is not int or memory[k] != v for k, v in allowances.items())
            or memory.get('chronological_peak_incremental_production_bytes', {}).get('status') != 'NOT_OBSERVED'):
        return False
    stream = obs.get('exact_stream', {})
    if not (type(stream.get('events')) is int and 0 < stream['events'] <= args.max_events
            and type(stream.get('bytes')) is int and 0 < stream['bytes'] <= args.journal_limit_mib * 1024**2
            and e1.sha256_value(stream.get('sha256'))):
        return False
    if stream['events'] != sum(d['memo_calls'] for d in direct.values()):
        return False
    if report.get('source_hashes') != report.get('source_hashes_after') or not report.get('source_hashes'):
        return False
    if report.get('harness_sha256') != report.get('harness_sha256_after'):
        return False
    return True


def write_report(path, report):
    raw = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    with path.open('xb') as stream:
        stream.write(raw)
    with Path(str(path) + '.sha256').open('x') as stream:
        stream.write(e1.digest(raw) + '\n')


def screening(report, args):
    result = dict(basis='preregistered 50-module warm original whole-run i_from_v count',
        original_i_from_v=2349889, fraction=.05, required_potential_avoided_calls=117495,
        modeled_incremental_memory_target_bytes=256 * 1024**2,
        memory_screen=not_observed('requires complete 50-module warm observation'),
        decision=not_observed('requires complete 50-module warm observation; not a production speedup gate'))
    if report['status'] != 'COMPLETED' or args.modules != 50 or args.cache_state != 'warm':
        return result
    obs = report['child']['observation']
    actual = sum(v['i_from_v_calls'] for v in obs['direct_observations'].values())
    if actual != result['original_i_from_v']:
        result['decision'] = not_observed('observed whole-run denominator differs from preregistration')
        return result
    potential = sum(v['1024']['potential_avoided_observed_i_from_v'] for v in obs['counterfactuals'].values())
    extra = obs['memory']['modeled_incremental_bytes']['1024']
    memory_screen = 'MEMORY_SCREEN_MET' if extra <= 256 * 1024**2 else 'MEMORY_SCREEN_INCONCLUSIVE'
    result.update(observed_whole_run_i_from_v=actual, hypothetical_avoided_observed_i_from_v=potential,
        hypothetical_fraction_of_original=potential / actual, estimated_extra_memory_upper_bound_bytes=extra,
        memory_basis='cumulative across all slots; conservative modeled peak upper bound, not chronological peak',
        chronological_peak_incremental_production_bytes=not_observed('no chronological slot-lifetime observation'),
        memory_screen=memory_screen,
        call_screen_met=potential >= 117495, estimated_memory_target_established=extra <= 256 * 1024**2,
        decision=('SCREEN_MET' if extra <= 256 * 1024**2 else 'MEMORY_SCREEN_INCONCLUSIVE')
                 if potential >= 117495 else 'CALL_SCREEN_NOT_MET')
    return result


def parent(args):
    """Owned child process group, wall backstop, sampled RSS, separate E2 outputs."""
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + args.wall_cap_seconds
    command = [sys.executable, '-B', str(Path(__file__).resolve()), '--child',
               '--output', str(args.output), '--reference-e1', str(args.reference_e1),
               '--reference-e1-counts', str(args.reference_e1_counts)]
    for name in ('modules', 'intervals', 'workers', 'wall_cap_seconds', 'memory_limit_mib',
                 'max_events', 'max_slots', 'max_keys', 'journal_limit_mib', 'cache_state'):
        command.extend(['--' + name.replace('_', '-'), str(getattr(args, name))])
    process, peak, reason, rss_available = None, 0, None, True
    with tempfile.TemporaryFile(dir=EVIDENCE) as logs:
        with e1.termination_guard():
            try:
                process = subprocess.Popen(command, stdout=logs, stderr=logs, start_new_session=True,
                    env=dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                             PYTHONDONTWRITEBYTECODE='1'))
                while process.poll() is None:
                    rss = e1.resident_bytes(process.pid)
                    if rss is None:
                        rss_available = False
                    else:
                        peak = max(peak, rss)
                    if time.monotonic() >= deadline:
                        reason = 'WALL_CAPPED'
                    elif rss is not None and rss > args.memory_limit_mib * 1024**2:
                        reason = 'MEMORY_CAPPED'
                    if reason:
                        break
                    time.sleep(.02)
            except BaseException as exc:
                reason = 'INTERRUPTED:' + type(exc).__name__
            finally:
                if process is not None:
                    e1.stop(process)
        report = dict(schema_name='RawiBumiMemoOpportunity', schema_version=2,
            status=reason or 'FAILED', baseline_commit=BASE, reference_e1=str(args.reference_e1),
            reference_e1_counts=str(args.reference_e1_counts),
            journal_integrity=not_observed('child completion not established'),
            controls={k: v for k, v in vars(args).items() if k not in ('output', 'reference_e1', 'reference_e1_counts')},
            sampled_peak_resident_bytes=peak or not_observed('RSS unavailable'),
            rss_sampling_complete=rss_available, rss_limit_basis='20ms Linux leader RSS; transient/native peaks may escape sampling',
            child_exit_code=process.returncode if process else None, log_tail=e1.tail(logs))
        child_path = Path(str(args.output) + '.child.json')
        if child_path.exists() and child_path.stat().st_size <= 32 * 1024**2:
            try:
                raw = child_path.read_bytes()
                report['child_sha256'] = e1.digest(raw)
                sidecar = Path(str(child_path) + '.sha256')
                if sidecar.stat().st_size > 256 or sidecar.read_text().strip() != report['child_sha256']:
                    raise ValueError('child digest mismatch')
                report['child'] = json.loads(raw)
                if not reason and process and process.returncode == 0:
                    candidate = report['child'].get('status', 'INCOMPLETE')
                    if completed_child(report['child'], args):
                        journal_identity = verify_journal_bytes(Path(str(args.output) + '.events.jsonl'),
                            args.journal_limit_mib * 1024**2)
                        if journal_identity != report['child']['observation']['exact_stream']:
                            raise ValueError('parent journal identity mismatch')
                        report['journal_integrity'] = 'MATCH'
                        report['status'] = 'COMPLETED'
                    else:
                        report['status'] = 'INCOMPLETE' if candidate == 'COMPLETED' else candidate
            except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:
                report['child_error'] = str(exc)[:500]
                report['status'] = reason or 'FAILED'
        if (not rss_available or not peak) and report['status'] == 'COMPLETED':
            report['status'] = 'INCOMPLETE'
        report['screening'] = screening(report, args)
        write_report(args.output, report)
    return report


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--reference-e1', type=Path, required=True)
    p.add_argument('--reference-e1-counts', type=Path, required=True)
    p.add_argument('--modules', type=int, choices=(10, 50), default=10)
    p.add_argument('--intervals', type=int, default=1)
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--cache-state', choices=('cold', 'warm'), default='warm')
    p.add_argument('--wall-cap-seconds', type=float, default=900)
    p.add_argument('--memory-limit-mib', type=int, default=4096)
    p.add_argument('--max-events', type=int, default=MAX_EVENTS)
    p.add_argument('--max-slots', type=int, default=4096)
    p.add_argument('--max-keys', type=int, default=MAX_KEYS)
    p.add_argument('--journal-limit-mib', type=int, default=2048)
    p.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    return p


def main():
    args = parser().parse_args()
    controls(args)
    args.output = validate_output(args.output)
    if e1.git('rev-parse', 'HEAD') != BASE or e1.git('branch', '--show-current') != BRANCH:
        raise ValueError('expected E2 baseline HEAD/branch required')
    reference(args)  # read-only validation before starting a workload or writing evidence
    if args.child:
        with e1.child_backstop(args.wall_cap_seconds):
            report = child(args)
            write_report(Path(str(args.output) + '.child.json'), report)
    else:
        report = parent(args)
    return 0 if report['status'] == 'COMPLETED' else 1


if __name__ == '__main__':
    raise SystemExit(main())
