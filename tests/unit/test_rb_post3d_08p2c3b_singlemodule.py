"""C3-B blocker regressions; no optimized solver or physical PASS substitute."""
from dataclasses import replace

import pytest

from shading.electrical import string_iv
from tests.unit.test_rb_post3d_08p2c3a_contract import real_model
from tests.unit.test_phase67_general_series_string_iv import _string


@pytest.mark.parametrize("shaded,temperature", [(False, 25.), (True, 45.)])
def test_real_single_module_retains_baseline_work_and_exact_results(
    monkeypatch, shaded, temperature,
):
    model = real_model(shaded=shaded, temperature=temperature)
    models = {model.module_instance_id: model}
    circuit = _string(models)
    control = string_iv.assemble_general_series_string_iv(circuit, models, sample_count=25)
    original = string_iv._string_state_at_current
    requests = []

    def observe(ordered, current, **kwargs):
        requests.append(float(current).hex())
        return original(ordered, current, **kwargs)

    monkeypatch.setattr(string_iv, "_string_state_at_current", observe)
    actual = string_iv.assemble_general_series_string_iv(circuit, models, sample_count=25)
    # Complete serialized curves/states include MPP candidates and all hashes.
    assert actual == control
    assert requests.count(0.0.hex()) == 3
    samples = actual.state["current_samples"]
    assert len(samples) == 25
    assert samples[0]["current_a"].hex() == 0.0.hex()
    assert samples[-1]["current_a"].hex() == actual.curve["isc_a"].hex()
    assert requests[-25:] == [s["current_a"].hex() for s in samples]


@pytest.mark.parametrize("failure_request", [2, 3])
def test_reusing_zero_state_would_suppress_supported_callable_failure(failure_request):
    # Wrap real physics: the assembler's public runtime contract permits this
    # callable and must propagate its later failure, even at a repeated current.
    model = real_model()
    original = model.voltage_at_current
    zero_requests = 0

    def evaluate(current):
        nonlocal zero_requests
        if current == 0.0:
            zero_requests += 1
            if zero_requests == failure_request:
                raise ValueError("later zero-current evaluation rejected")
        return original(current)

    wrapped = replace(model, voltage_at_current=evaluate)
    models = {wrapped.module_instance_id: wrapped}
    with pytest.raises(string_iv.GeneralSeriesStringIVError,
                       match="later zero-current evaluation rejected"):
        string_iv.assemble_general_series_string_iv(_string(models), models, sample_count=25)
    assert zero_requests == failure_request
