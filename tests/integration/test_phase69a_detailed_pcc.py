"""Controlled detailed PCC continuation; no annual execution claims."""
from copy import deepcopy
from dataclasses import replace
import json
from time import perf_counter
import resource

import pandas as pd
import pytest

from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
from tests.unit.test_phase69a_canonical_dispatch import _run
from engine.simulation.detailed_dispatch import _prepare_backend
from engine.simulation.detailed_downstream import (compact_selected_states, CompactDetailedMPPTResult,
    selected_states_to_mppt_bank, execute_detailed_downstream)
from engine.simulation.artifacts import verify_run_package
from engine.losses.chain import simulate_electrical_loss_chain
from engine.losses.array import apply_pre_inverter_array_losses


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    project, config, store, scene, electrical = _canonical_fixture()
    config["output_configuration"]["detailed_diagnostics"] = False
    config.setdefault("numerical_options", {}).setdefault("module_overrides", {})["module_quality_loss_fraction"] = 0.
    started = perf_counter()
    result = _run(tmp_path_factory.mktemp("phase69a-pcc"), project, config, store, name="pcc")
    assert result.simulation_run["status"] in {"completed", "completed_with_warnings"}, result.simulation_run
    args = _prepare_backend(config, store, scene, electrical, [], "parity", project["project_revision_id"], "2026-10-03T00:00:00Z")
    return project, config, store, result, args, perf_counter() - started


def test_selected_adapter_direct_chain_pcc_energy_and_compact_artifacts(completed):
    _, _, _, result, args, elapsed = completed
    compact = compact_selected_states(result.detailed_backend_result)
    bank = selected_states_to_mppt_bank(compact)
    payload = compact.replay()
    durations = [i["duration_seconds"] for i in payload["intervals"]]
    direct = simulate_electrical_loss_chain(bank, next(iter(args["module_configs"].values())).inverter_definition,
                                          interval_seconds=durations)
    pd.testing.assert_frame_equal(direct.ledger.frame, result.backend_result.electrical.ledger.frame)
    for interval in payload["intervals"]:
        for m in interval["mppts"]:
            assert m["power_w"] == pytest.approx(m["voltage_v"] * m["current_a"], rel=1e-9, abs=1e-7)
            assert m["constraint_flags"]["operating_current_above_limit"] is None
    assert result.summary_result["total_energy_wh"] == pytest.approx(sum(direct.ledger.frame.pcc_power_w * durations / 3600), abs=1e-9)
    assert result.summary_result["shading_energy_loss_wh"] is None
    assert result.summary_result["annual_energy_wh"] is None
    assert direct.ledger.frame.module_mismatch_loss_w.eq(0).all()
    assert direct.ledger.frame.string_mismatch_loss_w.eq(0).all()
    assert not (result.artifact_directory / "detailed-mppt-result.json").exists()
    verify_run_package(result.artifact_directory)
    compact_bytes = (result.artifact_directory / "detailed-selected-mppt.json").stat().st_size
    assert compact_bytes < len(result.detailed_backend_result.canonical_payload) / 10
    print({"elapsed_seconds": elapsed, "compact_bytes": compact_bytes,
           "full_diagnostic_bytes": len(result.detailed_backend_result.canonical_payload),
           "parquet_bytes": (result.artifact_directory / "timeseries.parquet").stat().st_size,
           "pcc_energy_wh": result.summary_result["total_energy_wh"],
           "process_peak_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
           "package_bytes": sum(p.stat().st_size for p in result.artifact_directory.iterdir() if p.is_file())})


def test_pvi_tamper_and_known_current_constraint_fail_closed(completed):
    compact = compact_selected_states(completed[3].detailed_backend_result)
    payload = compact.replay()
    payload["intervals"][0]["mppts"][0]["power_w"] += 1
    with pytest.raises(ValueError, match="voltage times current"):
        CompactDetailedMPPTResult.freeze(payload)
    payload = compact.replay()
    payload["intervals"][0]["mppts"][0]["constraint_flags"].update(operating_current_above_limit=True, operating_current_limit_known=True)
    with pytest.raises(ValueError, match="binding current"):
        selected_states_to_mppt_bank(CompactDetailedMPPTResult.freeze(payload))


def test_nonzero_quality_preserved_and_negative_legacy_loss_is_gain(completed):
    _, _, _, result, args, _ = completed
    compact = compact_selected_states(result.detailed_backend_result)
    configs = {m: replace(c, module_quality_loss_fraction=None) for m, c in args["module_configs"].items()}
    with pytest.raises(ValueError, match="calibration independence is unproven"):
        execute_detailed_downstream(compact, module_configs=configs, module_inputs=args["module_inputs"])
    gain = apply_pre_inverter_array_losses(selected_states_to_mppt_bank(compact), module_quality_loss_fraction=-.0075)
    assert (gain.frame.module_quality_loss_w < 0).all()
    assert gain.frame.after_module_quality_w.to_numpy() == pytest.approx(gain.frame.raw_array_mpp_w.to_numpy() * 1.0075)
    assert all(c.module_definition["quality"]["default_module_quality_loss_fraction"] == -.0075 for c in configs.values())


@pytest.mark.parametrize("field", ["module_mismatch_loss_fraction", "string_mismatch_loss_fraction"])
def test_legacy_mismatch_cannot_double_count(completed, field):
    _, _, _, result, args, _ = completed
    configs = {m: replace(c, **{field: .01}) for m, c in args["module_configs"].items()}
    with pytest.raises(ValueError, match="double-count"):
        execute_detailed_downstream(compact_selected_states(result.detailed_backend_result),
                                    module_configs=configs, module_inputs=args["module_inputs"])


def test_wiring_voltage_conversion_clipping_and_unsafe_voc_direct_parity(completed):
    _, _, _, result, args, _ = completed
    compact = compact_selected_states(result.detailed_backend_result)
    configs = {m: replace(c, dc_array_resistance_ohm=.02) for m, c in args["module_configs"].items()}
    wired = execute_detailed_downstream(compact, module_configs=configs, module_inputs=args["module_inputs"])
    bank = selected_states_to_mppt_bank(compact)
    direct = simulate_electrical_loss_chain(bank, next(iter(configs.values())).inverter_definition,
        interval_seconds=[i["duration_seconds"] for i in compact.replay()["intervals"]], dc_array_resistance_ohm=.02)
    pd.testing.assert_frame_equal(wired.electrical.ledger.frame, direct.ledger.frame)
    current = sum(b.frame.mppt_imp_a for b in bank.values())
    assert wired.timeseries.dc_wiring_loss_w.to_numpy() == pytest.approx((current**2 * .02).to_numpy(), abs=1e-9)
    # Eligibility belongs to the existing inverter, not tracker-flag clipping.
    inverter = deepcopy(next(iter(configs.values())).inverter_definition)
    inverter["mppt_template"]["min_operating_voltage_v"] = 900.
    configs_window = {m: replace(c, inverter_definition=inverter) for m, c in args["module_configs"].items()}
    rejected = execute_detailed_downstream(compact, module_configs=configs_window, module_inputs=args["module_inputs"])
    assert rejected.timeseries.dc_voltage_threshold_loss_w.to_numpy() == pytest.approx(rejected.timeseries.raw_array_mpp_w.to_numpy())
    assert rejected.timeseries.dc_to_converter_w.eq(0).all()
    unsafe = deepcopy(inverter)
    unsafe["dc_limits"]["max_dc_voltage_v"] = 1.
    with pytest.raises(ValueError, match="Voc|voltage|absolute"):
        execute_detailed_downstream(compact, module_configs={m: replace(c, inverter_definition=unsafe) for m,c in configs.items()},
                                    module_inputs=args["module_inputs"])


def test_explicit_durations_and_unknown_dark_voc_are_not_invented(completed):
    _, _, _, result, args, _ = completed
    payload = compact_selected_states(result.detailed_backend_result).replay()
    interval = payload["intervals"][0]
    interval["duration_seconds"] = 900
    interval["interval_end"] = (pd.Timestamp(interval["interval_start"]) + pd.Timedelta(seconds=900)).isoformat()
    interval["evaluation_time"] = (pd.Timestamp(interval["interval_start"]) + pd.Timedelta(seconds=450)).isoformat()
    payload["intervals"] = [interval]
    short = execute_detailed_downstream(CompactDetailedMPPTResult.freeze(payload),
                                       module_configs=args["module_configs"], module_inputs=args["module_inputs"])
    assert short.energy.annual["pcc_power_kwh"] * 1000 == pytest.approx(short.timeseries.pcc_power_w.iloc[0] * .25)
    interval["mppts"][0].update(power_w=0., current_a=0., active=False, voc_v=None)
    with pytest.raises(ValueError, match="authoritative"):
        CompactDetailedMPPTResult.freeze(payload)


def test_canonical_one_interval_replay_and_optional_diagnostics(tmp_path, completed):
    project, config, store, _, _, _ = completed
    config = deepcopy(config)
    weather = next(iter(store.weather_revisions.values()))
    config["end_time"] = (weather.series.index[0] + pd.Timedelta(seconds=3600)).isoformat()
    started = perf_counter()
    first = _run(tmp_path, project, config, store, name="one")
    print({"one_interval_seconds": perf_counter() - started, "one_interval_compact_bytes": (first.artifact_directory / "detailed-selected-mppt.json").stat().st_size, "one_interval_parquet_bytes": (first.artifact_directory / "timeseries.parquet").stat().st_size})
    assert first.summary_result is not None, first.simulation_run
    config["output_configuration"]["detailed_diagnostics"] = True
    second = _run(tmp_path, project, config, store, name="reference", executed_at="2026-10-05T00:00:00Z")
    assert first.simulation_run["input_hash"] == second.simulation_run["input_hash"]
    assert first.detailed_backend_result == second.detailed_backend_result
    pd.testing.assert_frame_equal(first.standard_timeseries, second.standard_timeseries)
    assert (second.artifact_directory / "detailed-mppt-result.json").is_file()
    verify_run_package(second.artifact_directory)
    path = first.artifact_directory / "detailed-selected-mppt.json"
    record = json.loads(path.read_text())
    record["payload"]["intervals"][0]["mppts"][0]["power_w"] += 1
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="hash|SHA|size|checksum"):
        verify_run_package(first.artifact_directory)


def test_conversion_clipping_and_standby_applied_once(completed):
    _, _, _, result, args, _ = completed
    compact = compact_selected_states(result.detailed_backend_result)
    inverter = deepcopy(next(iter(args["module_configs"].values())).inverter_definition)
    inverter["ac_limits"]["max_ac_power_w"] = 100.
    configs = {m: replace(c, inverter_definition=inverter) for m, c in args["module_configs"].items()}
    clipped = execute_detailed_downstream(compact, module_configs=configs, module_inputs=args["module_inputs"])
    f = clipped.timeseries
    assert f.inverter_clipping_loss_w.gt(0).all()
    assert f.ac_available_w.to_numpy() == pytest.approx([100.] * len(f))
    assert f.inverter_conversion_loss_w.to_numpy() == pytest.approx((f.dc_to_converter_w - f.ac_unclipped_w).to_numpy())
    assert f.inverter_clipping_loss_w.to_numpy() == pytest.approx((f.ac_unclipped_w - f.ac_available_w).to_numpy())
    assert f.pcc_power_w.to_numpy() == pytest.approx((f.ac_available_w - f.inverter_self_consumption_w).to_numpy())
    standby = deepcopy(inverter)
    standby.setdefault("operating_thresholds", {})["startup_power_w"] = 1e9
    standby["operating_thresholds"]["standby_loss_w"] = 3.
    configs = {m: replace(c, inverter_definition=standby) for m, c in configs.items()}
    waiting = execute_detailed_downstream(compact, module_configs=configs, module_inputs=args["module_inputs"])
    assert waiting.timeseries.dc_to_converter_w.eq(0).all()
    assert waiting.timeseries.standby_consumption_w.eq(3.).all()
    assert waiting.timeseries.pcc_power_w.eq(-3.).all()


def test_existing_inactive_consumer_night_contract_without_claiming_dark_iv_support():
    # The legacy consumer has a valid zero-state contract. The frozen detailed
    # producer cannot supply it, so this does not fabricate a detailed IV state.
    from tests.unit.test_engine_inverter import _mppt, _huawei_inverter
    bank = {1: _mppt(pmp=0., vmp=0., imp=0., voc=0., isc=0., active=False)}
    chain = simulate_electrical_loss_chain(bank, _huawei_inverter(), interval_seconds=900.)
    assert chain.ledger.frame.night_consumption_w.iloc[0] == 2.
    assert chain.ledger.frame.pcc_power_w.iloc[0] == -2.
    assert chain.ledger.energy.annual["pcc_power_kwh"] == pytest.approx(-.0005)


def test_adapter_preserves_canonical_evaluation_offset_without_forcing_midpoint(completed):
    payload = compact_selected_states(completed[3].detailed_backend_result).replay()
    # Existing canonical solar semantics permit source-defined offsets; transport
    # must preserve them rather than constrain the evaluation to the interval.
    payload["intervals"][0]["evaluation_time"] = (pd.Timestamp(payload["intervals"][0]["interval_start"]) - pd.Timedelta(minutes=15)).isoformat()
    compact = CompactDetailedMPPTResult.freeze(payload)
    bank = selected_states_to_mppt_bank(compact)
    assert bank[1].frame.evaluation_time.iloc[0] == pd.Timestamp(payload["intervals"][0]["evaluation_time"])


def test_diagnostic_request_requires_explicit_boolean(tmp_path, monkeypatch):
    from tests.unit.test_phase69a_canonical_dispatch import _context
    project, config, store, _ = _context()
    config.setdefault("output_configuration", {})["detailed_diagnostics"] = "true"
    def forbidden(*a, **kw):
        raise AssertionError("invalid output option entered physics")
    monkeypatch.setattr("engine.simulation.detailed_backend.execute_detailed_mppt_backend", forbidden)
    result = _run(tmp_path, project, config, store)
    assert result.simulation_run["status"] == "failed"
    assert any("explicit boolean" in r for r in result.simulation_run["detailed_execution_identity"]["failure_reasons"])
