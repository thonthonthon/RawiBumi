"""D2-A observer contracts using original numerical execution."""
import json
import math
from pathlib import Path
import subprocess
import sys

import pvlib
import pytest
from scripts.benchmarks import rb_post3d_08p2d2a_batchability as audit
from shading.electrical.parameterization import PVSystRegionElectricalState


def test_real_execution_and_restoration():
    model = audit.fixture((1000., 200., 600.)*2)
    current = model.current_domain_ceiling_a * .5
    reference = model.voltage_at_current(current)
    # Fresh model retains exactly the same B2 admission behavior.
    observed = audit.fixture((1000., 200., 600.)*2)
    original = PVSystRegionElectricalState.current_at_voltage
    public = pvlib.pvsystem.i_from_v
    observer = audit.Observation()
    with observer.installed():
        assert observed.voltage_at_current(current) == reference
        first = observer.numerical_calls
        assert observed.voltage_at_current(current) == reference
        # Existing B2 repeated-point reuse remains active with exact state types.
        assert observer.numerical_calls == first
    assert original is PVSystRegionElectricalState.current_at_voltage
    assert public is pvlib.pvsystem.i_from_v
    assert sys.getprofile() is None
    summary = observer.summary()
    assert summary['total_regional_numerical_calls'] > 0
    assert 1 <= summary['maximum_independent_group_size'] <= 2
    ids = [g['id'] for g in observer.groups]
    assert len(set(ids)) == len(ids)
    assert len(ids) > 2  # successive adaptive iterations stay separate
    for group in observer.groups:
        assert len({r['voltage_hex'] for r in group['requests']}) <= 1


def test_guard_dark_nonfinite_and_restoration_on_error():
    inputs = audit.cases()
    observer = audit.Observation()
    original = PVSystRegionElectricalState.current_at_voltage
    with observer.installed():
        for state, voltage, metadata in inputs:
            if metadata['boundary'] in ('below_reverse_domain', 'nonfinite'):
                with pytest.raises(ValueError):
                    state.current_at_voltage(voltage)
            elif metadata['boundary'] in ('reverse_domain', 'bypass_transition'):
                try:
                    state.current_at_voltage(voltage)
                except ValueError:
                    pass  # clamp may exceed the explicit current domain
            elif metadata['boundary'] == 'above_open_circuit':
                assert state.current_at_voltage(voltage) == 0
            elif metadata['category'] == 'dark' and voltage == 0:
                before = observer.numerical_calls
                assert state.current_at_voltage(voltage) == 0
                assert observer.numerical_calls == before
    assert observer.guards > 0 and observer.reverse_or_dark > 0
    assert PVSystRegionElectricalState.current_at_voltage is original
    with pytest.raises(RuntimeError):
        with observer.installed():
            raise RuntimeError('test')
    assert PVSystRegionElectricalState.current_at_voltage is original
    assert sys.getprofile() is None


def test_stateful_exclusion_and_no_suppressed_calls():
    class Stateful:
        def __init__(self):
            self.calls = []
        def current_at_voltage(self, voltage):
            self.calls.append(voltage)
            return len(self.calls)
    state = Stateful()
    assert not audit.trusted(state)
    with audit.Observation().installed():
        assert [state.current_at_voltage(v) for v in (1., 1., 2.)] == [1, 2, 3]
    assert state.calls == [1., 1., 2.]
    assert not audit.trusted(lambda: 0)


def test_exact_bits_and_exception_reporting():
    assert audit.compare([1.], [1.])['exact_equal']
    assert not audit.compare([0.], [-0.])['exact_equal']
    assert not audit.compare([math.nan], [math.nan])['exact_equal']
    errors = audit.failures(audit.cases())
    dark = [r for r in errors if r['metadata'][0]['category'] == 'dark']
    assert dark and all(not r['raw_applicable_to_production'] for r in dark)
    assert any(not r['exception_equal'] for r in dark)
    assert all(r['error_order_parity'] is None for r in dark)


def test_bounded_schema_and_no_retention():
    report = audit.run(currents=1, repeats=1, cap=2)
    assert report['status'] == 'completed'
    assert report['production_eligible'] is False
    assert set(report['versions']) == {'pvlib', 'numpy', 'scipy'}
    assert [r['points'] for r in report['small_batches']] == list(audit.SIZES)
    assert report['observation']['uncaptured_or_overflowed_observations'] > 0
    assert len(report['observation']['records']) <= 2
    assert len(report['observation']['groups']) <= 2
    assert audit.Observation().records == []
    json.dumps(report, allow_nan=False)
    for args in ((0, 1, 1), (1, 8, 1), (1, 1, 20001)):
        with pytest.raises(ValueError):
            audit.run(*args)


def test_cli_error_json(tmp_path):
    output = tmp_path / 'error.json'
    assert audit.main(['--output', str(output), '--currents', '5']) == 1
    assert json.loads(output.read_text())['status'] == 'error'


def test_only_authorized_changes():
    allowed = {'docs/validation/rb_post3d_08p2d1_kernel_audit.md',
               'scripts/benchmarks/rb_post3d_08p2d2a_batchability.py',
               'tests/unit/test_rb_post3d_08p2d2a_contract.py',
               'tests/unit/test_rb_post3d_08p2d1_kernel_contract.py',
               'docs/validation/rb_post3d_08p2d2a_batchability.md'}
    result = subprocess.run(['git', 'status', '--porcelain', '-uall'],
                            cwd=audit.ROOT, check=True, capture_output=True, text=True)
    assert {line[3:] for line in result.stdout.splitlines()} <= allowed
    source = Path(audit.__file__).read_text()
    assert 'pvlib.singlediode' not in source and 'scipy.' not in source
    assert 'lru_cache' not in source
