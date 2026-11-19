"""Bounded E1 diagnostics only; never change the 08P1 workload or mathematics."""
from __future__ import annotations

import argparse
import ast
from bisect import bisect_right
from contextlib import contextmanager, nullcontext
from dataclasses import fields, is_dataclass
import dis
import hashlib
from importlib.metadata import version, PackageNotFoundError
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import tracemalloc
from types import CodeType, FunctionType

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / '.ai/validation/rb_post3d_08p2e1'
BASE = '3508f7f'
BASE_COMMIT = '3508f7f30342775ad7534833f3d759d576341b72'
MODES = ('baseline', 'counts', 'trace')
HARNESS_VERSION = 'E1-R3-1'
CACHE_STATES = {'cold': ('cold_physics_cache',), 'warm': ('warm_physics_cache',),
                'both': ('cold_physics_cache', 'warm_physics_cache')}
CACHE_SEMANTICS = '08P1 initial clear; full cold dispatch/replays/daylight checks/package verification; no intervening clear'
OPERATIONS = ('producer', 'attribution', 'b2_numerical_acceptance', 'persistence', 'verification')
PROTECTED = {'smoke-r2.json', 'smoke-r2.json.sha256', 'smoke-r2-console.log'}
PHASES = ('setup', 'producer', 'attribution', 'persistence', 'verification', 'dispatch',
          'b2_numerical_acceptance', 'compatibility_controls')
OBJECTIVES = {
    '_solve_module_isc': '_module_state_at_current',
    '_solve_string_isc': '_string_state_at_current',
    'solve_parallel_branches_at_current': 'currents_at',
    '_branch_current_at_voltage_uncached': 'evaluate_series_branch_voltage',
    '_resolve_uniform_mpp_for_temperature_gate': 'point',
}
ROOTS = set(OBJECTIVES)
NAMES = ROOTS | set(OBJECTIVES.values()) | {
    '_evaluate_module', 'evaluate_protected_substring_at_current', '_branch_current_at_voltage',
    'current_at_voltage', 'voltage_at_current', '_bypass_clamp_voltage',
    '_branch_states_at_voltage', 'i_from_v', 'v_from_i', 'singlediode', 'calcparams_pvsyst',
    '_evaluate_interval', '_evaluate_attribution_interval', 'persist_run_package', 'verify_run_package',
    '_evaluate_numerical_candidate_physics', '_branch_open_with_reuse', '_branch_end_with_reuse',
}
SOURCE_FILES = tuple(sorted({str(p.relative_to(ROOT)) for p in
    (ROOT / 'shading/electrical').glob('*.py')} | {
    'engine/simulation/detailed_backend.py', 'engine/simulation/detailed_attribution.py',
    'engine/simulation/detailed_inputs.py', 'engine/simulation/canonical.py',
    'engine/simulation/artifacts.py', 'scripts/benchmarks/rb_post3d_08p1.py',
    'scripts/benchmarks/rb_post3d_08p2e1_root_work.py'}))
FIXTURE_FILES = (
    'tests/unit/test_rb_post3d_08b3d2_activation.py',
    'tests/unit/test_rb_post3d_08b2_region_physics.py',
    'tests/unit/test_phase69a_canonical_dispatch.py',
    'tests/integration/test_phase69a_detailed_backend.py',
    # runpy inputs do not necessarily appear in sys.modules.
    'tests/integration/test_phase68_real_parallel_mppt.py',
    'tests/integration/test_phase67_real_two_module_string.py',
    'tests/integration/test_phase66_module_iv_handoff.py',
    'tests/fixtures/panond/synthetic_module.pan',
    'tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND',
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    """Canonical JSON payload, exact binary64 including signed zero; no filtering."""
    def encode(item):
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ValueError('nonfinite numerical fingerprint')
            return {'binary64_hex': item.hex()}
        if isinstance(item, dict):
            return {k: encode(v) for k, v in sorted(item.items())}
        if isinstance(item, (list, tuple)):
            return [encode(v) for v in item]
        return item
    return digest(json.dumps(encode(value), sort_keys=True, separators=(',', ':'),
                             allow_nan=False).encode())


def input_identity(value):
    """Serialize workload inputs, including frozen store and weather data, without repr."""
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: input_identity(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict):
        return {k: input_identity(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [input_identity(v) for v in value]
    if isinstance(value, bytes):
        return {'bytes_sha256': digest(value)}
    # Imported only during fixture preparation; no observer installed here.
    import pandas as pd
    if isinstance(value, pd.DataFrame):
        return {'columns': list(value.columns), 'index': [v.isoformat() for v in value.index],
                'index_name': value.index.name, 'dtypes': [str(v) for v in value.dtypes],
                'values': value.values.tolist()}
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'unsupported fixture identity type: {type(value).__name__}')


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True).strip()


def hashes(paths):
    return {p: digest((ROOT / p).read_bytes()) for p in sorted(paths)}


def loaded_source_hashes():
    """Includes indirect imports; runpy dependencies are also explicitly pinned above."""
    paths = set()
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename:
            path = Path(filename).resolve()
            if path.is_relative_to(ROOT) and '.venv' not in path.parts and path.suffix == '.py':
                paths.add(str(path.relative_to(ROOT)))
    return hashes(paths)


def metadata():
    versions = {'python': sys.version, 'platform': sys.platform}
    for name in ('numpy', 'scipy', 'pvlib', 'pandas'):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    # Catalog inputs are read by the fixture; hashing all reference assets is conservative.
    fixtures = set(FIXTURE_FILES)
    for directory in ('components/reference', 'schemas', 'shading/electrical'):
        fixtures.update(str(p.relative_to(ROOT)) for p in (ROOT / directory).rglob('*.json'))
    return dict(commit=git('rev-parse', 'HEAD'), dirty_state=git('status', '--porcelain', '--untracked-files=all'),
                task_sha256=digest((ROOT / '.ai/TASK.md').read_bytes()),
                source_hashes=hashes(SOURCE_FILES), fixture_hashes=hashes(fixtures),
                environment=versions, harness_version=HARNESS_VERSION,
                harness_sha256=digest(Path(__file__).read_bytes()))


def not_observed(reason):
    return {'status': 'not_observed', 'reason': reason}


class _InstrumentationAbort(BaseException):
    """Private diagnostic abort that ordinary production handlers cannot consume."""


class ObservationOverflow(_InstrumentationAbort):
    pass


class ParentTerminated(BaseException):
    pass


def local_nodes(node):
    """Walk one function's syntax, excluding nested function/class bodies."""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield child
        yield from local_nodes(child)


def contains(node, line):
    return node.lineno <= line <= node.end_lineno


def plan_for(code):
    """Precompute source/bytecode probes; line callbacks never count iterations.

    A simple first statement's first executable opcode executes once per body
    entry, even when CPython emits repeated line events for multiline expressions.
    Unsupported/optimized-away bodies explicitly remain unobserved.
    """
    instructions = list(dis.get_instructions(code))
    plan = dict(offsets=[i.offset for i in instructions], instructions=instructions,
                entries={}, returns={i.offset for i in instructions
                                     if i.opname in ('RETURN_VALUE', 'RETURN_CONST')},
                calls={}, iteration_reason='source unavailable', refinement_entries=set())
    try:
        tree = ast.parse(Path(code.co_filename).read_text())
    except (OSError, SyntaxError, UnicodeError):
        return plan
    functions = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == code.co_name and min([n.lineno] + [d.lineno for d in n.decorator_list])
                 == code.co_firstlineno]
    if len(functions) != 1:
        return plan
    nodes = list(local_nodes(functions[0]))
    loops = [n for n in nodes if isinstance(n, (ast.For, ast.While))]
    objective = OBJECTIVES.get(code.co_name)
    objective_calls = [n for n in nodes if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                       and n.func.id == objective]
    refinement_loops = [loop for loop in loops if any(contains(loop, n.lineno) for n in objective_calls)]
    plan['iteration_reason'] = ('refinement loop has no unambiguous supported body-entry opcode'
                                if len(refinement_loops) == 1 else 'no uniquely identified refinement loop')
    for loop in loops:
        first = loop.body[0]
        if not isinstance(first, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Return, ast.Raise)):
            continue
        candidates = [i.offset for i in instructions if i.positions.lineno is not None
                      and contains(first, i.positions.lineno)
                      and i.opname not in ('NOP', 'RESUME', 'EXTENDED_ARG')]
        if candidates:
            offset = min(candidates)
            plan['entries'][offset] = loop.lineno
            if len(refinement_loops) == 1 and loop is refinement_loops[0]:
                plan['refinement_entries'].add(offset)
                plan['iteration_reason'] = None
    for call in objective_calls:
        if code.co_name == '_resolve_uniform_mpp_for_temperature_gate':
            category = ('golden_section_refinement' if any(contains(n, call.lineno) for n in refinement_loops)
                        else 'golden_section_initial')
            if refinement_loops and call.lineno > refinement_loops[-1].end_lineno:
                category = 'post_solve_reconstruction'
        elif any(contains(n, call.lineno) for n in refinement_loops):
            category = 'bisection_refinement'
        elif refinement_loops and call.lineno > refinement_loops[-1].end_lineno:
            category = 'post_solve_reconstruction'
        else:
            category = 'bracketing'
        for instruction in instructions:
            pos = instruction.positions
            if (instruction.opname.startswith('CALL') and pos.lineno == call.lineno
                    and pos.col_offset == call.col_offset and pos.end_lineno == call.end_lineno
                    and pos.end_col_offset == call.end_col_offset):
                plan['calls'][instruction.offset] = category
    return plan


class Observer:
    """Selected frame events only; bounded counters, no callable replacement."""
    MAX_CODES = 512
    MAX_COUNTER_KEYS = 32768
    MAX_KEY_LENGTH = 4096
    MAX_ACTIVE_FRAMES = 512

    def __init__(self, mode='counts', cap=None, targets=None):
        # Optional cap is for synthetic fault injection, never the production default.
        if mode not in ('counts', 'trace') or (cap is not None and
                (not isinstance(cap, int) or cap < 1)):
            raise ValueError('invalid observation mode/cap')
        self.mode, self.cap, self.targets = mode, cap, targets
        self.phase = 'setup'
        self.active = {}
        self.counters = {p: {} for p in PHASES}
        self.b2_context = None
        self.b2_context_counters = {p: {} for p in PHASES}
        self.counter_keys = 0
        self.events = self.overflow = 0
        self.overflow_reason = None
        self.hook_error = None
        self.plans = {}
        self.trace_state = {}

    def selected(self, code):
        if self.targets is not None:
            return code in self.targets
        path = code.co_filename.replace('\\', '/')
        return code.co_name in NAMES and ('/shading/electrical/' in path or
            '/engine/simulation/detailed_' in path or path.endswith('/engine/simulation/artifacts.py')
            or path.endswith('/pvlib/pvsystem.py'))

    def prepare(self):
        codes = set(self.targets or ())
        def visit(code):
            if self.selected(code):
                codes.add(code)
            for const in code.co_consts:
                if isinstance(const, CodeType):
                    visit(const)
        if self.targets is None:
            for module in tuple(sys.modules.values()):
                namespace = getattr(module, '__dict__', {})
                for obj in tuple(namespace.values()):
                    if isinstance(obj, FunctionType):
                        visit(obj.__code__)
                    elif isinstance(obj, type) and getattr(obj, '__module__', '') == namespace.get('__name__'):
                        for method in tuple(vars(obj).values()):
                            if isinstance(method, (staticmethod, classmethod)):
                                method = method.__func__
                            if isinstance(method, FunctionType):
                                visit(method.__code__)
        if len(codes) > self.MAX_CODES:
            self.abort_overflow('selected code registry exceeds 512 entries')
        self.plans = {code: plan_for(code) for code in codes}

    def key(self, code):
        return code.co_filename.replace(str(ROOT) + '/', '') + ':' + code.co_qualname

    def add(self, phase, key, amount=1, *, context=None):
        destinations = [self.counters[phase]]
        if phase == 'b2_numerical_acceptance':
            destinations.append(self.b2_context_counters[context or self.b2_context or 'setup'])
        for counters in destinations:
            if key not in counters:
                if len(key) > self.MAX_KEY_LENGTH:
                    self.abort_overflow('counter key exceeds retained length bound')
                if self.counter_keys >= self.MAX_COUNTER_KEYS:
                    self.abort_overflow('retained counter key limit exhausted; counters are partial')
                self.counter_keys += 1
            counters[key] = counters.get(key, 0) + amount

    def abort_overflow(self, reason):
        self.overflow = 1
        if self.overflow_reason is None:
            self.overflow_reason = reason
        raise ObservationOverflow(self.overflow_reason)

    def frame_budget(self, state, frame):
        if id(frame) not in state and len(state) >= self.MAX_ACTIVE_FRAMES:
            self.abort_overflow('selected live frame limit exhausted; counters are partial')

    def budget(self):
        if self.hook_error is not None:
            if isinstance(self.hook_error, _InstrumentationAbort):
                raise self.hook_error
            raise _InstrumentationAbort(str(self.hook_error)) from self.hook_error
        if self.cap is not None and self.events >= self.cap:
            self.abort_overflow(f'selected event cap {self.cap} exhausted; counters are partial')
        self.events += 1

    def classify(self, parent, code):
        if parent is None or OBJECTIVES.get(parent.f_code.co_name) != code.co_name:
            return
        plan = self.plans.get(parent.f_code)
        category = None
        if plan:
            index = bisect_right(plan['offsets'], parent.f_lasti) - 1
            if index >= 0:
                category = plan['calls'].get(plan['offsets'][index])
        family = parent.f_code.co_name
        if category is None:
            self.add(self.phase, family + ':unclassified_objective_calls')
            return
        self.add(self.phase, family + ':' + category)
        if family == '_resolve_uniform_mpp_for_temperature_gate':
            self.add(self.phase, family + ':golden_section_mpp_evaluations')
        if category != 'post_solve_reconstruction':
            self.add(self.phase, family + ':objective_evaluations')
        if category == 'bracketing':
            self.add(self.phase, family + ':bracket_evaluations')

    def profile(self, frame, event, arg):
        try:
            self._profile(frame, event, arg)
        except BaseException as exc:
            self.hook_error = self.hook_error or exc
            if isinstance(exc, _InstrumentationAbort):
                raise
            raise _InstrumentationAbort(str(exc)) from exc

    def _profile(self, frame, event, arg):
        if event not in ('call', 'return', 'c_call') or not self.selected(frame.f_code):
            return
        if frame.f_code not in self.plans:
            raise RuntimeError('selected code not prepared before observation')
        # Pop and restore BEFORE checking the budget, including overflow on return.
        record = self.active.pop(id(frame), None) if event == 'return' else None
        if record:
            self.phase = record[3]
            self.b2_context = record[4]
        self.budget()
        code, key = frame.f_code, self.key(frame.f_code)
        if event == 'c_call':
            self.add(self.phase, 'selected_frame_python_to_c_dispatch_events')
        elif event == 'call':
            self.classify(frame.f_back, code)
            previous = self.phase
            previous_context = self.b2_context
            # B2 physics and all descendants stay separate from their enclosing phase.
            if code.co_name == '_evaluate_numerical_candidate_physics':
                if self.phase != 'b2_numerical_acceptance':
                    self.b2_context = self.phase
                self.phase = 'b2_numerical_acceptance'
            elif self.phase not in ('compatibility_controls', 'b2_numerical_acceptance'):
                self.phase = {'_evaluate_interval': 'producer',
                    '_evaluate_attribution_interval': 'attribution',
                    'persist_run_package': 'persistence',
                    'verify_run_package': 'verification',
                    }.get(code.co_name, self.phase)
            self.frame_budget(self.active, frame)
            self.active[id(frame)] = (self.phase, key, time.perf_counter(), previous, previous_context)
            self.add(self.phase, key + ':calls')
            if self.mode == 'trace' and code.co_name in ROOTS and self.plans[code]['iteration_reason'] is None:
                self.add(self.phase, key + ':iterations', 0)
        elif record:
            phase, key, start, _, _ = record
            # Phase/context are already restored; return counters belong to the exited frame.
            context = record[4] if record[3] == phase else record[3]
            self.add(phase, key + ':returns_or_unwinds', context=context)
            self.add(phase, key + ':inclusive_seconds', time.perf_counter() - start, context=context)

    def trace(self, frame, event, arg):
        try:
            return self._trace(frame, event, arg)
        except BaseException as exc:
            self.hook_error = self.hook_error or exc
            if isinstance(exc, _InstrumentationAbort):
                raise
            raise _InstrumentationAbort(str(exc)) from exc

    def _trace(self, frame, event, arg):
        code = frame.f_code
        if not self.selected(code):
            return None
        plan = self.plans[code]
        key = self.key(code)
        if event == 'call':
            self.frame_budget(self.trace_state, frame)
            frame.f_trace_lines = False
            frame.f_trace_opcodes = True
            self.trace_state[id(frame)] = {'returned': False, 'exception': None}
        elif event == 'opcode':
            if frame.f_lasti in plan['entries'] or frame.f_lasti in plan['returns']:
                self.budget()
                if frame.f_lasti in plan['entries']:
                    self.add(self.phase, key + ':iteration_entry:' + str(plan['entries'][frame.f_lasti]))
                    if frame.f_lasti in plan['refinement_entries']:
                        self.add(self.phase, key + ':iterations')
                if frame.f_lasti in plan['returns']:
                    self.trace_state[id(frame)]['returned'] = True
                    self.add(self.phase, key + ':return_opcodes')
        elif event == 'exception':
            self.budget()
            name = arg[0].__name__
            if len(name) > self.MAX_KEY_LENGTH:
                self.abort_overflow('trace exception name exceeds retained length bound')
            self.trace_state[id(frame)]['exception'] = name
            self.add(self.phase, key + ':exception_events')
        elif event == 'return':
            state = self.trace_state.pop(id(frame), {})
            if state.get('exception') and not state.get('returned'):
                self.budget()
                self.add(self.phase, key + ':propagated_failure:' + state['exception'])
        return self.trace

    @contextmanager
    def installed(self):
        old_profile, old_trace = sys.getprofile(), sys.gettrace()
        if old_profile is not None or old_trace is not None or tracemalloc.is_tracing():
            raise RuntimeError('exclusive diagnostic hooks required')
        self.prepare()
        initial_phase = self.phase
        initial_context = self.b2_context
        allocation_owned = False
        exiting = False
        installation_frame = sys._getframe()
        old_opcode_flag = installation_frame.f_trace_opcodes
        try:
            if self.mode == 'trace':
                tracemalloc.start()
                allocation_owned = True
                # CPython 3.12 enables opcode monitoring at settrace time only
                # when an existing frame requests it. Prime our own frame,
                # then restore its flag on every exit.
                installation_frame.f_trace_opcodes = True
                sys.settrace(self.trace)
            sys.setprofile(self.profile)
            yield self
        except BaseException:
            exiting = True
            raise
        finally:
            sys.setprofile(old_profile)
            sys.settrace(old_trace)
            installation_frame.f_trace_opcodes = old_opcode_flag
            if allocation_owned:
                tracemalloc.stop()
            self.active.clear()
            self.trace_state.clear()
            self.phase = initial_phase
            self.b2_context = initial_context
            if self.hook_error is not None and not exiting:
                # A workload that caught a hook exception still cannot yield valid evidence.
                if isinstance(self.hook_error, _InstrumentationAbort):
                    raise self.hook_error
                raise _InstrumentationAbort(str(self.hook_error)) from self.hook_error

    def snapshot(self):
        return {p: dict(values) for p, values in self.counters.items()}

    def limitations(self):
        return {self.key(code): not_observed(plan['iteration_reason'] if self.mode == 'trace'
                else 'focused opcode observation disabled')
                for code, plan in self.plans.items() if code.co_name in ROOTS
                and (self.mode != 'trace' or plan['iteration_reason'] is not None)}

    def root_observations(self):
        observations = {}
        for phase, counters in self.counters.items():
            observations[phase] = {}
            for family in sorted(ROOTS):
                codes = [code for code in self.plans if code.co_name == family]
                calls = sum(counters.get(self.key(code) + ':calls', 0) for code in codes)
                if not calls:
                    observations[phase][family] = not_observed('root family not reached in this phase')
                    continue
                measured = lambda value: {'status': 'observed', 'value': value}
                record = {'solve_calls': measured(calls)}
                for field in ('objective_evaluations', 'bracket_evaluations', 'bisection_refinement',
                              'post_solve_reconstruction', 'golden_section_mpp_evaluations'):
                    if counters.get(family + ':unclassified_objective_calls') or any(not self.plans[c]['calls'] for c in codes):
                        record[field] = not_observed('objective call sites could not be classified completely')
                    elif field == 'bracket_evaluations' and family in (
                            '_branch_current_at_voltage_uncached', '_resolve_uniform_mpp_for_temperature_gate'):
                        record[field] = not_observed('nested cached endpoints or golden-section initial points; no direct root bracket probes')
                    else:
                        record[field] = measured(counters.get(family + ':' + field, 0))
                if self.mode != 'trace' or any(self.plans[c]['iteration_reason'] for c in codes):
                    record['iterations'] = not_observed('focused observation disabled or loop entry is ambiguous')
                else:
                    record['iterations'] = measured(sum(counters.get(self.key(c) + ':iterations', 0) for c in codes))
                record['termination_reasons'] = not_observed('return opcode does not establish scientific termination reason')
                observations[phase][family] = record
        return observations


def delta(after, before):
    return {p: {k: v - before[p].get(k, 0) for k, v in after[p].items()} for p in PHASES}


def controls(args):
    if args.modules not in (10, 50) or args.intervals != 1 or args.workers != 1:
        raise ValueError('only 10/50 modules, one interval and one worker authorized')
    if not math.isfinite(args.wall_cap_seconds) or not 0 < args.wall_cap_seconds <= 900 or not 0 < args.memory_limit_mib <= 4096:
        raise ValueError('finite wall cap >0..900; sampled resident ceiling >0..4096 MiB required')
    if args.focused_trace and args.measurement_mode != 'both':
        raise ValueError('focused trace requires combined measurement mode')
    if args.child and (args.measurement_mode != 'both' or args.compare_baseline or args.compare_counts):
        raise ValueError('hidden child cannot select parent measurement/comparison modes')
    if bool(args.compare_baseline) != bool(args.compare_counts):
        raise ValueError('comparison requires both baseline and counts evidence paths')


def validate_output(output):
    output = output.absolute()
    if EVIDENCE.resolve() != EVIDENCE.absolute():
        raise ValueError('authorized evidence directory must not redirect through symlinks')
    for path in (output, output.with_suffix(output.suffix + '.sha256')):
        if path.name in PROTECTED:
            raise ValueError('archived R2 smoke evidence is protected')
        if not path.resolve().is_relative_to(EVIDENCE.resolve()) or path.resolve() == EVIDENCE.resolve():
            raise ValueError('diagnostic output must be inside .ai/validation/rb_post3d_08p2e1/')
        if path.exists():
            raise ValueError('diagnostic output already exists; choose a new evidence filename')
    return output


def coverage():
    return {path: not_observed('08P1 daylight homogeneous fixture does not establish this coverage; '
                'compatibility negative controls are separate from representative performance evidence')
            for path in ('nonuniform_electrical_states', 'active_bypass', 'reverse_domain',
                         'dark_operation', 'stateful_arbitrary_callables')}


def prepare_workload(modules):
    from scripts.benchmarks import rb_post3d_08p1 as fixture
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation import artifacts
    inputs = fixture.build_fixture(modules)
    fixture.clear_physics_caches()
    identity = fingerprint(input_identity(inputs))
    provenance = {'loaded_repository_source_hashes': loaded_source_hashes(),
                  'fixture_and_input_files': hashes(FIXTURE_FILES),
                  'task_sha256': digest((ROOT / '.ai/TASK.md').read_bytes()),
                  'harness_sha256': digest(Path(__file__).read_bytes()),
                  'workload_input_sha256': identity,
                  'workload_input_basis': 'all project/config/store/scene/design/bundle fields, weather index/values/dtypes'}
    return fixture, _run, artifacts, inputs, identity, provenance


def execute_cache_run(fixture, run, artifacts, inputs, directory, temperature, observer=None):
    """Original sequence, shared verbatim by measured cold runs and warm priming."""
    project, config, store, scene, design, bundle = inputs
    if observer:
        observer.phase = 'dispatch'
    before = fixture.cache_stats()
    before_counts = observer.snapshot() if observer else None
    before_b2 = ({p: dict(v) for p, v in observer.b2_context_counters.items()}
                 if observer else None)
    start = time.perf_counter()
    result = run(Path(directory), project, config, store, name=temperature)
    elapsed = time.perf_counter() - start
    if any(v is None for v in (result.summary_result, result.detailed_backend_result,
                              result.detailed_attribution_result)):
        raise RuntimeError('production run incomplete')
    physical = result.detailed_backend_result.replay()
    attribution = result.detailed_attribution_result.replay()
    if len(physical['intervals']) != 1:
        raise RuntimeError('unexpected interval count')
    for module in physical['intervals'][0]['modules'].values():
        if sum(module['local_irradiance']['regions'][0]['unshaded_poa'].values()) <= 0:
            raise RuntimeError('expected established daylight fixture')
    after = fixture.cache_stats()
    if observer:
        observer.phase = 'verification'
    start = time.perf_counter()
    artifacts.verify_run_package(result.artifact_directory)
    return dict(cache_state=temperature, execution_wall_seconds=elapsed,
        verification_wall_seconds=time.perf_counter() - start,
        numerical_fingerprints={'physical': fingerprint(physical),
                                'attribution': fingerprint(attribution)},
        counters=delta(observer.snapshot(), before_counts) if observer else None,
        b2_context_counters=delta(observer.b2_context_counters, before_b2) if observer else None,
        cache_before=before, cache_after_execution=after,
        cache_after_verification=fixture.cache_stats(), status='completed',
        completed_operations=list(OPERATIONS))


def checkpoint(args, report, observer=None):
    """Retain completed cache runs before later work can be killed by a watchdog."""
    if observer:
        report.update(counters=observer.snapshot(), observation_events=observer.events,
                      b2_context_counters={p: dict(v) for p, v in observer.b2_context_counters.items()},
                      overflow=observer.overflow, overflow_reason=observer.overflow_reason,
                      hook_failure=None if observer.hook_error is None else {
                          'exception_type': type(observer.hook_error).__name__,
                          'exception_message': str(observer.hook_error)})
    if getattr(args, 'output', None):
        write_report(args.output, report)


def child(args):
    observer = None
    runs = []
    report = dict(measurement_mode=args.mode, status='in_progress', runs=runs,
                  cache_selection=args.cache_state, cache_semantics=CACHE_SEMANTICS,
                  priming=None, overflow=0, hook_failure=None, scientific_coverage=coverage(),
                  evidence=evidence_header())
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        # Imports, fixture building, identities and initial cache clearing precede hooks.
        fixture, run, artifacts, inputs, identity, provenance = prepare_workload(args.modules)
        report.update(fixture_identity=identity, provenance=provenance)
        with tempfile.TemporaryDirectory(prefix='workload-', dir=EVIDENCE) as directory:
            if args.cache_state == 'warm':
                # Use the ORIGINAL cold run ID, dispatch, replays, checks and verifier.
                # No observer exists yet. Verification can itself populate physics caches.
                if sys.getprofile() is not None or sys.gettrace() is not None or tracemalloc.is_tracing():
                    raise RuntimeError('uninstrumented warm priming requires exclusive diagnostic hooks')
                start = time.perf_counter()
                priming = execute_cache_run(fixture, run, artifacts, inputs, directory,
                                            'cold_physics_cache')
                priming['total_wall_seconds'] = time.perf_counter() - start
                priming['instrumented'] = False
                report['priming'] = priming
                checkpoint(args, report)
            observer = Observer(args.mode) if args.mode != 'baseline' else None
            with (observer.installed() if observer else nullcontext()):
                for temperature in CACHE_STATES[args.cache_state]:
                    runs.append(execute_cache_run(fixture, run, artifacts, inputs, directory,
                                                  temperature, observer))
                    checkpoint(args, report, observer)
                report['memory'] = {'python_traced_current_peak_bytes':
                                    tracemalloc.get_traced_memory() if args.mode == 'trace' else None}
        report['status'] = 'completed'
    except BaseException as exc:
        report.update(status='overflow' if isinstance(exc, ObservationOverflow) else 'failed',
                      exception_type=type(exc).__name__, exception_message=str(exc))
    finally:
        try:
            report.setdefault('provenance', {})['loaded_repository_sources_after_execution'] = loaded_source_hashes()
            report['provenance']['task_sha256_after_execution'] = digest((ROOT / '.ai/TASK.md').read_bytes())
        except Exception as exc:
            report.setdefault('provenance', {})['loaded_repository_sources_after_execution'] = not_observed(str(exc))
            if report['status'] == 'completed':
                report.update(status='failed', exception_type=type(exc).__name__, exception_message=str(exc))
        if observer:
            checkpoint(args, report, observer)
            report.update(iteration_limitations=observer.limitations(),
                          root_observations=observer.root_observations())
            # Independently invalidate intercepted or replaced hook aborts.
            report['original_child_status'] = report['status']
            if observer.overflow:
                report['status'] = 'overflow'
            elif observer.hook_error is not None and report['status'] == 'completed':
                report['status'] = 'failed'
        else:
            report['counters'] = not_observed('uninstrumented baseline or fixture preparation failed')
        report.update(timings={'wall_seconds': time.perf_counter() - wall,
            'cpu_seconds': time.process_time() - cpu,
            'inclusive_label': 'nested inclusive times overlap; never sum'},
            counter_absence=not_observed('missing keys are unobserved, never implicitly zero'),
            termination_reasons=not_observed('return opcodes identify exits, not scientific termination reasons'),
            nested_bracket_evaluations=not_observed('nested cached endpoint helpers are not direct objective evaluations'),
            coverage_gaps=['Selected frame dispatch only, not total interpreter dispatch.',
                'Only unambiguous simple loop-body opcode entries count iterations.',
                'Native kernel iterations and some native allocations are not observed.',
                'Trace exception events may be caught; only unwind events count propagated failures.',
                'B2 numerical acceptance has separate counters and parent-context breakdowns.',
                'B2 context counters duplicate B2 totals; inclusive enclosing timings overlap.',
                'Compatibility negative controls do not establish representative fixture coverage.',
                'Instrumented wall timings cannot establish individual performance speedups.'])
    return report


def resident_bytes(pid):
    """Linux current process RSS, never virtual address space."""
    try:
        return int(Path(f'/proc/{pid}/statm').read_text().split()[1]) * os.sysconf('SC_PAGE_SIZE')
    except (OSError, ValueError, IndexError):
        return None


def stop(process):
    """Kill the whole owned group even if its leader exited; always reap leader."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    finally:
        process.wait()


@contextmanager
def termination_guard():
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(signum, frame):
        raise ParentTerminated('parent received SIGTERM')
    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


@contextmanager
def child_backstop(seconds):
    """Independent OS real-time timer kills child even after parent disappears.

    Default SIGALRM is deliberately fatal (also while native code holds the GIL).
    Such abrupt termination cannot serialize partial counters; parent labels it.
    """
    previous = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer != (0.0, 0.0):
        raise RuntimeError('exclusive child runtime timer required')
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def tail(logs):
    logs.seek(0, os.SEEK_END)
    end = logs.tell()
    logs.seek(max(0, end - 8000))
    return logs.read().decode(errors='replace')[-8000:]


def collect_child(output, mode, exit_code, diagnostic, parent_status=None, parent_error=None):
    result = {'status': 'missing_child_output', 'measurement_mode': mode}
    if output.exists():
        try:
            # Bound parsing as well as retained counters; child reports are small.
            if output.stat().st_size > 32 * 1024**2:
                raise ValueError('child JSON exceeds 32 MiB report cap')
            result = json.loads(output.read_text())
            if not isinstance(result, dict) or not isinstance(result.get('status'), str):
                raise ValueError('child JSON lacks status object')
        except (OSError, ValueError) as exc:
            result = dict(status='invalid_child_output', measurement_mode=mode,
                          output_error=str(exc))
    result['child_status'] = result['status']
    result.setdefault('measurement_mode', mode)
    result['child_exit_code'] = exit_code
    result['diagnostic_log_tail'] = diagnostic
    if result.get('overflow'):
        # Defend against contradictory JSON as well as intercepted child aborts.
        result['status'] = 'overflow'
    elif result.get('hook_failure') and result['status'] == 'completed':
        result['status'] = 'failed'
    if parent_status:
        result['status'] = parent_status
    elif exit_code == -signal.SIGALRM:
        result['status'] = 'child_wall_capped'
    elif exit_code != 0 and result['status'] == 'completed':
        result['status'] = 'child_exit_failed'
    elif exit_code != 0 and result['status'] == 'missing_child_output':
        result['status'] = 'failed'
    if parent_error:
        result['parent_error'] = parent_error
    return result


def run_mode(args, mode, deadline):
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='child-', dir=EVIDENCE) as directory:
        output = Path(directory) / 'result.json'
        remaining = min(args.wall_cap_seconds, deadline - time.monotonic())
        if remaining <= 0:
            return dict(status='wall_capped', measurement_mode=mode)
        command = [sys.executable, str(Path(__file__).resolve()), '--child', '--mode', mode,
            '--cache-state', args.cache_state,
            '--output', str(output), '--modules', str(args.modules), '--intervals', '1', '--workers', '1',
            '--wall-cap-seconds', str(remaining), '--memory-limit-mib', str(args.memory_limit_mib)]
        process = None
        peak, available, status, parent_error = 0, True, None, None
        with tempfile.TemporaryFile(dir=EVIDENCE) as logs:
            with termination_guard():
                try:
                    process = subprocess.Popen(command, env=env, stdout=logs, stderr=logs, start_new_session=True)
                    while process.poll() is None:
                        rss = resident_bytes(process.pid)
                        if rss is None:
                            available = False
                        else:
                            peak = max(peak, rss)
                        if time.monotonic() >= deadline:
                            status = 'wall_capped'
                        elif rss is not None and rss > args.memory_limit_mib * 1024**2:
                            status = 'memory_capped'
                        if status:
                            break
                        time.sleep(0.02)
                except BaseException as exc:
                    status = ('interrupted' if isinstance(exc, KeyboardInterrupt) else
                              'parent_terminated' if isinstance(exc, ParentTerminated) else 'parent_failed')
                    parent_error = {'exception_type': type(exc).__name__, 'exception_message': str(exc)}
                finally:
                    if process is not None:
                        stop(process)
            diagnostic = tail(logs)
        result = collect_child(output, mode, process.returncode if process else None,
                               diagnostic, status, parent_error)
        result.setdefault('memory', {}).update(sampled_peak_resident_bytes=peak or None,
            enforcement='Linux RSS watchdog, 20ms sampling' if available and peak else 'unavailable or incomplete',
            limitation='Sampled enforcement, not a continuous hard memory limit; transient peaks and descendants excluded.')
        return result


def sha256_value(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run_identity(run, temperature):
    require(isinstance(run, dict) and run.get('cache_state') == temperature
            and run.get('status') == 'completed', 'missing/incomplete cache run')
    require(run.get('completed_operations') == list(OPERATIONS), 'missing required operations')
    fps = run.get('numerical_fingerprints')
    require(isinstance(fps, dict) and all(sha256_value(fps.get(k)) for k in
            ('physical', 'attribution')), 'missing numerical fingerprints')
    snapshots = tuple(run.get(k) for k in
                      ('cache_before', 'cache_after_execution', 'cache_after_verification'))
    require(all(isinstance(v, dict) and v for v in snapshots), 'missing cache snapshots')
    return (fps, snapshots, run['completed_operations'])


def measurement_identity(record):
    require(isinstance(record, dict) and record.get('status') == 'completed'
            and record.get('child_status') == 'completed' and type(record.get('child_exit_code')) is int
            and record['child_exit_code'] == 0,
            'child incomplete or unsuccessful exit')
    require(type(record.get('overflow')) is int and record['overflow'] == 0 and 'hook_failure' in record
            and record['hook_failure'] is None, 'missing/failed overflow or hook status')
    require(sha256_value(record.get('fixture_identity')), 'missing fixture identity')
    selection = record.get('cache_selection')
    require(isinstance(selection, str) and selection in CACHE_STATES
            and record.get('cache_semantics') == CACHE_SEMANTICS, 'missing/unknown cache semantics')
    runs = record.get('runs')
    require(isinstance(runs, list) and len(runs) == len(CACHE_STATES[selection]),
            'incomplete measurement coverage')
    identities = [run_identity(r, t) for r, t in zip(runs, CACHE_STATES[selection])]
    priming = record.get('priming')
    if selection == 'warm':
        priming_identity = run_identity(priming, 'cold_physics_cache')
        require(priming.get('instrumented') is False and priming.get('counters') is None
                and priming.get('b2_context_counters') is None,
                'warm priming must be uninstrumented')
        require(type(priming.get('total_wall_seconds')) in (float, int)
                and math.isfinite(priming['total_wall_seconds']) and priming['total_wall_seconds'] >= 0,
                'missing priming duration')
        require(priming['cache_after_verification'] == runs[0]['cache_before'],
                'warm preconditions differ from verified cold priming')
    else:
        require('priming' in record and priming is None, 'unexpected/missing priming declaration')
        priming_identity = None
        if selection == 'both':
            require(runs[0]['cache_after_verification'] == runs[1]['cache_before'],
                    'warm preconditions differ from verified cold run')
    if record.get('measurement_mode') in ('counts', 'trace'):
        require(isinstance(record.get('counters'), dict) and set(record['counters']) == set(PHASES)
                and isinstance(record.get('b2_context_counters'), dict)
                and set(record['b2_context_counters']) == set(PHASES), 'missing phase/B2 counters')
        require(type(record.get('observation_events')) is int and record['observation_events'] > 0,
                'missing observations')
        for run in runs:
            require(isinstance(run.get('counters'), dict) and set(run['counters']) == set(PHASES)
                    and isinstance(run.get('b2_context_counters'), dict)
                    and set(run['b2_context_counters']) == set(PHASES), 'missing cache-run counters')
    else:
        require(record.get('measurement_mode') == 'baseline', 'unknown measurement mode')
        require(all(r.get('counters') is None and r.get('b2_context_counters') is None for r in runs),
                'baseline run is instrumented')
    return (record['fixture_identity'], selection, record['cache_semantics'], identities, priming_identity)


def comparison(passes):
    if len(passes) < 2:
        return 'INCOMPLETE'
    try:
        identities = [measurement_identity(p) for p in passes]
    except ValueError:
        return 'INCOMPLETE'
    return 'MATCH' if all(v == identities[0] for v in identities[1:]) else 'MISMATCH'


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--modules', type=int, default=10)
    p.add_argument('--intervals', type=int, default=1)
    p.add_argument('--workers', type=int, default=1)
    p.add_argument('--wall-cap-seconds', type=float, default=900)
    p.add_argument('--memory-limit-mib', type=int, default=4096)
    p.add_argument('--measurement-mode', choices=('baseline', 'counts', 'both'), default='both')
    p.add_argument('--cache-state', choices=tuple(CACHE_STATES), default='both')
    p.add_argument('--compare-baseline', type=Path, help='read-only baseline artifact input')
    p.add_argument('--compare-counts', type=Path, help='read-only counts artifact input')
    p.add_argument('--focused-trace', action='store_true')
    p.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    p.add_argument('--mode', choices=MODES, default='baseline', help=argparse.SUPPRESS)
    return p


def evidence_header():
    return {'sha256': None,
            'basis': 'canonical sorted compact JSON with evidence.sha256=null; exact file digest in adjacent sidecar',
            'external_retention': 'operator must archive JSON and sidecar together outside ignored repository evidence'}


def parent(args, total_start):
    report = dict(schema_name='RawiBumiRootWorkAudit', schema_version=2,
        status='PENDING_MEASUREMENT', base=BASE, metadata=metadata(), evidence=evidence_header(),
        controls={k: getattr(args, k) for k in ('modules', 'intervals', 'workers',
                                               'wall_cap_seconds', 'memory_limit_mib')},
        measurement_mode=args.measurement_mode, cache_selection=args.cache_state,
        resource_limit_basis='each isolated mode receives its own wall and sampled RSS limits; priming included',
        passes=[])
    modes = (MODES if args.focused_trace else MODES[:2]) if args.measurement_mode == 'both' else (args.measurement_mode,)
    for mode in modes:
        # Each child starts with a fresh budget, including its imports and priming.
        report['passes'].append(run_mode(args, mode, time.monotonic() + args.wall_cap_seconds))
        report['diagnostic_status'] = 'in_progress'
        checkpoint(args, report)
        if report['passes'][-1]['status'] in ('interrupted', 'parent_terminated'):
            break
    report['fingerprint_comparison'] = (comparison(report['passes']) if len(modes) > 1
                                        else 'NOT_COMPARED_INDEPENDENT')
    try:
        for record, mode in zip(report['passes'], modes):
            measurement_identity(record)
            require(record.get('measurement_mode') == mode and record.get('cache_selection') == args.cache_state,
                    'child mode/coverage differs from requested measurement')
        complete = len(report['passes']) == len(modes)
    except ValueError:
        complete = False
    report['diagnostic_status'] = ('completed' if complete and
        (len(modes) == 1 or report['fingerprint_comparison'] == 'MATCH') else 'incomplete_or_mismatch')
    report['regression_gates'] = 'NOT_RUN'
    report['total_wall_seconds_before_serialization'] = time.monotonic() - total_start
    return report


def read_evidence(path):
    """Read only. Both canonical and adjacent raw-file digests are mandatory."""
    require(path.resolve().is_relative_to(EVIDENCE.resolve()), 'comparison input outside evidence directory')
    require(path.stat().st_size <= 32 * 1024**2, 'evidence exceeds 32 MiB report cap')
    raw = path.read_bytes()
    sidecar = path.with_suffix(path.suffix + '.sha256')
    require(sidecar.resolve().is_relative_to(EVIDENCE.resolve()), 'comparison sidecar outside evidence directory')
    require(sidecar.stat().st_size <= 256, 'oversized digest sidecar')
    require(sidecar.read_text().strip() == digest(raw), 'raw-file SHA-256 mismatch')
    report = json.loads(raw)
    require(isinstance(report, dict) and isinstance(report.get('evidence'), dict), 'missing canonical digest')
    expected = report['evidence'].get('sha256')
    require(sha256_value(expected), 'missing canonical digest')
    report['evidence']['sha256'] = None
    actual = digest(json.dumps(report, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())
    report['evidence']['sha256'] = expected
    require(actual == expected, 'canonical evidence SHA-256 mismatch')
    return report, digest(raw)


def hash_inventory(value, name):
    require(isinstance(value, dict) and value and all(isinstance(k, str) and k
            and sha256_value(v) for k, v in value.items()), 'missing/invalid ' + name)
    return value


def artifact_identity(report, mode):
    require(report.get('schema_name') == 'RawiBumiRootWorkAudit' and report.get('schema_version') == 2,
            'unsupported evidence schema')
    require(report.get('status') == 'PENDING_MEASUREMENT' and report.get('diagnostic_status') == 'completed',
            'evidence incomplete')
    require(report.get('base') == BASE, 'base commit mismatch')
    meta = report.get('metadata')
    require(isinstance(meta, dict), 'missing metadata')
    commit = meta.get('commit')
    require(commit == BASE_COMMIT, 'missing/incorrect base commit identity')
    for field in ('task_sha256', 'harness_sha256'):
        require(sha256_value(meta.get(field)), 'missing ' + field)
    require(meta.get('harness_version') == HARNESS_VERSION, 'missing/unsupported harness version')
    sources = hash_inventory(meta.get('source_hashes'), 'source hashes')
    require(set(SOURCE_FILES) <= set(sources), 'incomplete relevant source hashes')
    require(sources['scripts/benchmarks/rb_post3d_08p2e1_root_work.py'] == meta['harness_sha256'],
            'contradictory harness hash')
    fixtures = hash_inventory(meta.get('fixture_hashes'), 'fixture hashes')
    require(set(FIXTURE_FILES) <= set(fixtures), 'incomplete fixture hashes')
    environment = meta.get('environment')
    require(isinstance(environment, dict) and all(isinstance(environment.get(k), str) and environment[k]
            for k in ('python', 'platform', 'numpy', 'scipy', 'pvlib', 'pandas')), 'missing environment versions')
    controls = report.get('controls')
    require(isinstance(controls, dict) and all(type(controls.get(k)) is int
            for k in ('modules', 'intervals', 'workers')) and controls.get('modules') in (10, 50)
            and controls.get('intervals') == 1 and controls.get('workers') == 1, 'missing workload configuration')
    require(type(controls.get('wall_cap_seconds')) in (float, int)
            and math.isfinite(controls['wall_cap_seconds']) and 0 < controls['wall_cap_seconds'] <= 900
            and type(controls.get('memory_limit_mib')) is int and 0 < controls['memory_limit_mib'] <= 4096,
            'missing/invalid independent resource limits')
    selection = report.get('cache_selection')
    require(isinstance(selection, str) and selection in CACHE_STATES, 'missing measurement coverage')
    passes = report.get('passes')
    require(isinstance(passes, list) and passes, 'missing child measurements')
    for record in passes:
        measurement_identity(record)  # Any incomplete child invalidates the artifact.
        require(record['cache_selection'] == selection, 'contradictory measurement coverage')
    actual_modes = [p['measurement_mode'] for p in passes]
    requested = report.get('measurement_mode')
    require((requested in ('baseline', 'counts') and actual_modes == [requested]) or
            (requested == 'both' and actual_modes in ([*MODES[:2]], [*MODES])),
            'missing/contradictory requested mode coverage')
    require(report.get('fingerprint_comparison') ==
            ('MATCH' if requested == 'both' else 'NOT_COMPARED_INDEPENDENT'),
            'missing/contradictory artifact comparison status')
    if requested == 'both':
        require(comparison(passes) == 'MATCH', 'combined artifact numerical/coverage mismatch')
    records = [p for p in passes if p.get('measurement_mode') == mode]
    require(len(records) == 1, 'missing/ambiguous ' + mode + ' measurement')
    record = records[0]
    provenance = record.get('provenance')
    require(isinstance(provenance, dict), 'missing child provenance')
    for field in ('loaded_repository_source_hashes', 'loaded_repository_sources_after_execution', 'fixture_and_input_files'):
        hash_inventory(provenance.get(field), field)
    for field in ('loaded_repository_source_hashes', 'loaded_repository_sources_after_execution'):
        loaded = provenance[field]
        require('scripts/benchmarks/rb_post3d_08p2e1_root_work.py' in loaded, 'missing loaded harness identity')
        require(all(h == loaded[k] for k, h in (sources | fixtures).items() if k in loaded),
                'contradictory loaded source hashes')
    before, after = (provenance[k] for k in
                     ('loaded_repository_source_hashes', 'loaded_repository_sources_after_execution'))
    require(all(after.get(k) == h for k, h in before.items()), 'loaded sources changed during execution')
    require(provenance.get('task_sha256') == meta['task_sha256'] and
            provenance.get('task_sha256_after_execution') == meta['task_sha256'] and
            provenance.get('harness_sha256') == meta['harness_sha256'], 'contradictory task/harness identity')
    require(set(FIXTURE_FILES) <= set(provenance['fixture_and_input_files']), 'incomplete input-file identity')
    require(provenance.get('fixture_and_input_files') == {k: fixtures[k] for k in FIXTURE_FILES},
            'contradictory fixture/input hashes')
    require(sha256_value(provenance.get('workload_input_sha256')) and
            provenance['workload_input_sha256'] == record['fixture_identity'], 'missing/contradictory input identity')
    require(isinstance(provenance.get('workload_input_basis'), str) and provenance['workload_input_basis'],
            'missing input identity basis')
    return (report['base'], commit, sources, fixtures, meta['harness_version'], meta['harness_sha256'],
            meta['task_sha256'], environment, {k: controls[k] for k in ('modules', 'intervals', 'workers')},
            selection, provenance, measurement_identity(record))


def compare_evidence(baseline, counts):
    report = dict(schema_name='RawiBumiRootWorkAudit', schema_version=2, status='PENDING_MEASUREMENT',
                  evidence=evidence_header(), regression_gates='NOT_RUN', comparison_inputs=[],
                  diagnostic_status='incomplete_or_mismatch', fingerprint_comparison='INCOMPLETE')
    try:
        left, left_sha = read_evidence(baseline)
        right, right_sha = read_evidence(counts)
        report['comparison_inputs'] = [{'path': str(p), 'raw_sha256': h, 'canonical_sha256': r['evidence']['sha256']}
                                      for p, h, r in ((baseline, left_sha, left), (counts, right_sha, right))]
        first = artifact_identity(left, 'baseline')
        second = artifact_identity(right, 'counts')
        report['fingerprint_comparison'] = 'MATCH' if first == second else 'MISMATCH'
        if first == second:
            report['diagnostic_status'] = 'completed'
        else:
            report['comparison_error'] = 'identity, coverage, cache snapshots or numerical fingerprints mismatch'
    except (OSError, ValueError, TypeError, KeyError) as exc:
        report['comparison_error'] = str(exc)
    return report


def write_report(output, report):
    if output.name in PROTECTED or output.with_suffix(output.suffix + '.sha256').name in PROTECTED:
        raise ValueError('archived R2 smoke evidence is protected')
    if 'evidence' in report:
        report['evidence']['sha256'] = None
        report['evidence']['sha256'] = digest(json.dumps(report, sort_keys=True,
            separators=(',', ':'), allow_nan=False).encode())
    data = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    # Replace each file atomically so an interrupted checkpoint cannot truncate
    # the preceding completed records. A two-file interrupted update fails digest validation.
    for path, payload in ((output, data), (output.with_suffix(output.suffix + '.sha256'),
                                         (digest(data) + '\n').encode())):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def main():
    total_start = time.monotonic()
    args = parser().parse_args()
    controls(args)
    args.output = validate_output(args.output)  # Before metadata, imports, spawning or work.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.child:
        with child_backstop(args.wall_cap_seconds):
            report = child(args)
            write_report(args.output, report)
    else:
        report = (compare_evidence(args.compare_baseline, args.compare_counts)
                  if args.compare_baseline else parent(args, total_start))
        write_report(args.output, report)
    return 0 if report.get('status') in ('completed', 'PENDING_MEASUREMENT') and report.get('diagnostic_status', 'completed') == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
