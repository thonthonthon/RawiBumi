"""Narrow selected-state adapter; all downstream physics remains in the loss chain."""
from dataclasses import dataclass
import json
from pathlib import Path
from math import isclose, isfinite

import pandas as pd

from electrical.mppt import MPPTAggregationResult
from engine.losses.chain import simulate_electrical_loss_chain
from engine.losses.energy import aggregate_interval_quantities, calculate_pv_kpis
from .artifacts import canonical_object_sha256
from .detailed_backend import POWER_ABSOLUTE_TOLERANCE_W, POWER_RELATIVE_TOLERANCE
from .unshaded import resolve_module_runtime_inputs


class DetailedModuleQualityUnavailable(ValueError):
    """Physical MPPT execution is valid; quality calibration basis is unresolved."""


@dataclass(frozen=True)
class CompactDetailedMPPTResult:
    canonical_payload: bytes
    compact_result_sha256: str

    @classmethod
    def freeze(cls, payload, *, _decoded=False):
        result = cls(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
                     canonical_object_sha256(payload))
        if _decoded:
            result._validate_payload(payload)
        else:
            result.replay()
        return result

    def replay(self):
        return self._validate_payload(json.loads(self.canonical_payload))

    def _validate_payload(self, payload):
        """Validate caller-owned decoded data without creating another graph."""
        if canonical_object_sha256(payload) != self.compact_result_sha256:
            raise ValueError("compact detailed result hash mismatch")
        from jsonschema import Draft202012Validator, FormatChecker
        schema = json.loads((Path(__file__).resolve().parents[2] / "schemas/detailed-selected-mppt.schema.json").read_text())
        # Check scientific numeric semantics first for actionable boundary errors.
        if payload["schema_name"] != "CompactDetailedMPPTResult" or payload["schema_version"] != "0.1":
            raise ValueError("unsupported compact detailed result")
        previous, coverage = None, None
        for interval in payload["intervals"]:
            start, end, evaluation = (pd.Timestamp(interval[k]) for k in ("interval_start", "interval_end", "evaluation_time"))
            if start.tzinfo is None or evaluation.tzinfo is None or not start < end:
                raise ValueError("compact detailed interval/evaluation alignment mismatch")
            if previous is not None and previous != start:
                raise ValueError("compact detailed intervals are not contiguous")
            if (end - start).total_seconds() != interval["duration_seconds"]:
                raise ValueError("compact detailed interval duration mismatch")
            previous = end
            ids = [(m["mppt_instance_id"], m["mppt_index"], tuple(m["string_ids"])) for m in interval["mppts"]]
            if not ids or len({m[1] for m in ids}) != len(ids) or len({m[0] for m in ids}) != len(ids):
                raise ValueError("compact detailed MPPT coverage is invalid")
            if coverage is not None and coverage != ids:
                raise ValueError("compact detailed MPPT coverage changes across intervals")
            coverage = ids
            strings = [s for m in interval["mppts"] for s in m["string_ids"]]
            if len(strings) != len(set(strings)):
                raise ValueError("compact detailed string coverage is duplicated across MPPTs")
            modules = [m["module_instance_id"] for m in interval["modules"]]
            if len(modules) != len(set(modules)) or set(modules) != set(payload["temperature_metadata"]):
                raise ValueError("compact detailed module history coverage mismatch")
            for m in interval["mppts"]:
                if m["availability"] == "inactive_dark":
                    if (m["active"] is not False or m["power_w"] != 0 or any(m[k] is not None
                        for k in ("voltage_v", "current_a", "isc_a", "voc_v", "combined_curve_sha256"))):
                        raise ValueError("invalid inactive_dark selected state")
                    continue
                flags = m["constraint_flags"]
                known, above = flags["operating_current_limit_known"], flags["operating_current_above_limit"]
                if (known and not isinstance(above, bool)) or (not known and above is not None):
                    raise ValueError("compact detailed known/unknown current-limit state is inconsistent")
                for key in ("voltage_v", "current_a", "power_w", "isc_a", "voc_v"):
                    if not isinstance(m[key], (int, float)) or not isfinite(m[key]) or m[key] < 0:
                        raise ValueError("compact detailed state needs authoritative finite nonnegative " + key)
                if not isclose(m["power_w"], m["voltage_v"] * m["current_a"],
                               abs_tol=POWER_ABSOLUTE_TOLERANCE_W, rel_tol=POWER_RELATIVE_TOLERANCE):
                    raise ValueError("selected MPPT power does not equal voltage times current")
                if m["active"] != (m["power_w"] > 0):
                    raise ValueError("compact detailed active state disagrees with selected power")
        if not payload["intervals"]:
            raise ValueError("compact detailed result has no intervals")
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(payload)
        return payload

    def record(self):
        return {"payload": self.replay(), "compact_result_sha256": self.compact_result_sha256}


# Quality fractions are strictly above -1, so the downstream current factor is strictly below 2.
CURRENT_LIMIT_BRANCH_FRACTION = 0.5


def _current_limit_branch(mppt, curve):
    """The combined curve from the selected point to open circuit, near a known current limit (USE1)."""
    limit = ((mppt.get("tracker_state") or {}).get("constraints") or {}).get("max_operating_current_a")
    point = mppt["selected_operating_point"]
    if limit is None or point["current_a"] <= CURRENT_LIMIT_BRANCH_FRACTION * float(limit):
        return {}
    branch = [(point["voltage_v"], point["current_a"])] + [
        (p["voltage_v"], p["current_a"]) for p in curve["points"] if p["voltage_v"] > point["voltage_v"]]
    if branch[-1][0] < curve["voc_v"]:
        branch.append((curve["voc_v"], 0.0))
    return {"current_limit_branch": {"voltage_v": [v for v, _ in branch], "current_a": [max(i, 0.0) for _, i in branch]}}


def compact_selected_states(numerical):
    """Projection only: no IV, irradiance, or tracker calculation is repeated."""
    source = numerical.replay_stream()
    intervals = []
    for interval in source["intervals"]:
        states = []
        for m in interval["mppts"]:
            if m.get("availability") == "inactive_dark":
                states.append({"mppt_instance_id": m["mppt_instance_id"], "mppt_index": m["mppt_index"],
                    "string_ids": m["combined_state"]["source_string_ids"], "voltage_v": None, "current_a": None,
                    "power_w": 0., "active": False, "isc_a": None, "voc_v": None,
                    "tracker_model_id": m["tracker_model_id"], "constraint_flags": m["constraint_flags"],
                    "availability": "inactive_dark", "combined_curve_sha256": None})
                continue
            curve = m["combined_curve"]
            states.append({"mppt_instance_id": m["mppt_instance_id"], "mppt_index": m["mppt_index"],
                "string_ids": m["combined_state"]["source_string_ids"], **m["selected_operating_point"],
                "active": m["selected_operating_point"]["power_w"] > 0,
                "isc_a": curve["isc_a"], "voc_v": curve["voc_v"],
                "tracker_model_id": m["tracker_model_id"], "constraint_flags": m["constraint_flags"],
                "availability": "selected_unconstrained_state", "combined_curve_sha256": canonical_object_sha256(curve),
                **_current_limit_branch(m, curve)})
        # Scalars required by KPI/reporting, area-weighted across module surfaces.
        modules = []
        for module_id, d in sorted(interval["modules"].items()):
            regions = d["local_irradiance"]["regions"]
            unshaded = sum(regions[0]["unshaded_poa"].values())
            modules.append({"module_instance_id": module_id,
                "incident_poa_w_m2": d["thermal_incident_poa_w_m2"],
                "effective_irradiance_w_m2": d["thermal_efficiency_effective_irradiance_w_m2"],
                "unshaded_poa_w_m2": unshaded,
                "cell_temperature_c": d["local_irradiance"]["module_temperature_c"],
                **({key: d[key] for key in ("post_iam_pre_soiling_w_m2", "soiling_loss_w_m2")} if "post_iam_pre_soiling_w_m2" in d else {})})
        intervals.append({**{k: interval[k] for k in ("interval_start", "interval_end", "evaluation_time", "duration_seconds")},
                          "mppts": states, "modules": modules})
    return CompactDetailedMPPTResult.freeze({"schema_name": "CompactDetailedMPPTResult", "schema_version": "0.1",
        "scientific_input_sha256": source["scientific_input_sha256"],
        "diagnostic_result_sha256": numerical.numerical_result_sha256,
        "temperature_metadata": source["temperature_metadata"], "intervals": intervals,
        **({"loss_circuit_references": source["loss_circuit_references"]} if "loss_circuit_references" in source else {})})


def selected_states_to_mppt_bank(compact):
    """Use the generic carrier, never its identical-string aggregation function.

    vmp/imp/pmp carry the selected ideal-global-MPP tracker state; Isc/Voc are
    from the parallel IV kernel, not invented common string values. Flags remain
    diagnostics. Voltage eligibility belongs exclusively to the existing inverter.
    """
    payload = compact.replay()
    index = pd.DatetimeIndex([i["interval_start"] for i in payload["intervals"]], name="interval_start")
    bank = {}
    for position, first in enumerate(payload["intervals"][0]["mppts"]):
        rows = []
        for interval in payload["intervals"]:
            m = interval["mppts"][position]
            branch = m.get("current_limit_branch")
            if m["constraint_flags"]["operating_current_above_limit"] is True and not branch:
                raise ValueError("Known binding current constraint has no current-limit branch to constrain on")
            rows.append({"mppt_isc_a": m["isc_a"], "mppt_voc_v": m["voc_v"],
                # The selected point is the MPP the loss chain starts from; the branch lets the inverter move right of
                # it when the MPPT current limit binds (USE1).
                "source_mpp_vmp_v": m["voltage_v"], "source_mpp_imp_a": m["current_a"],
                "current_limit_branch": (tuple(branch["voltage_v"]), tuple(branch["current_a"])) if branch else None,
                "mppt_imp_a": m["current_a"], "mppt_vmp_v": m["voltage_v"], "mppt_pmp_w": m["power_w"],
                "active": m["active"], "string_count": len(m["string_ids"]),
                "evaluation_time": pd.Timestamp(interval["evaluation_time"]),
                "availability": m["availability"],
                "pmp_identity_relative_error": (None if m["availability"] == "inactive_dark" else
                    abs(m["power_w"] - m["voltage_v"] * m["current_a"]) / max(m["power_w"], 1e-12)),
                "operating_current_limit_known": m["constraint_flags"]["operating_current_limit_known"],
                "operating_current_above_limit": m["constraint_flags"]["operating_current_above_limit"]})
        bank[first["mppt_index"]] = MPPTAggregationResult(first["mppt_index"], tuple(first["string_ids"]),
            pd.DataFrame(rows, index=index), {"model_id": "mppt.detailed_selected_state_adapter.v0.1",
                "aggregation_scope": "authoritative_parallel_iv_selected_tracker_state",
                "scientific_input_sha256": payload["scientific_input_sha256"],
                "compact_result_sha256": compact.compact_result_sha256,
                "constraint_policy": "inverter_constrained_operating_point_from_branch"})
    return bank


@dataclass(frozen=True)
class DetailedDownstreamResult:
    timeseries: pd.DataFrame
    electrical: object
    energy: object
    kpis: dict
    metadata: dict


def execute_detailed_downstream(compact, *, module_configs, module_inputs):
    payload = compact.replay()
    bank = selected_states_to_mppt_bank(compact)
    runtimes = {m: resolve_module_runtime_inputs(c.module_definition, alpha_absorption=c.alpha_absorption,
        iam_model_id=c.iam_model_id, iam_profile=c.iam_profile, module_quality_loss_fraction=c.module_quality_loss_fraction) for m, c in module_configs.items()}
    from engine.losses.settings import resolve_detailed_circuit_quality, circuit_execution_context
    config = next(iter(module_configs.values()))
    resolved_quality = resolve_detailed_circuit_quality(config.circuit_loss_resolution, module_inputs)
    if resolved_quality is not None:
        declarations = {mid: q["quality_declarations"] for mid,q in resolved_quality.items()}
        quality_factor = 0.  # Every MPPT receives its explicit evidence-bound factor.
    else:
        quality_factors = set()
        declarations = {}
        for module_id, runtime in runtimes.items():
            evidence = module_inputs[module_id].replay()["evidence"]
            declaration = evidence.get("module_quality_declaration", {"relationship": "unknown"})
            relationship = declaration["relationship"]
            quality = runtime.module_quality_loss_fraction
            if quality != 0 and relationship == "unknown":
                raise DetailedModuleQualityUnavailable("Nonzero module quality cannot continue to PCC: calibration independence is unproven (unknown declaration)")
            if quality != 0 and declaration["module_quality_loss_fraction"] != quality:
                raise DetailedModuleQualityUnavailable("Module quality declaration does not bind the resolved signed quality value")
            quality_factors.add(quality if relationship == "separate_from_parameterization" else 0.)
            declarations[module_id] = {"evidence_id": evidence["evidence_id"], "declaration": declaration,
                "resolved_module_quality_loss_fraction": quality}
        if len(quality_factors) != 1:
            raise DetailedModuleQualityUnavailable("Detailed downstream requires one common effective module-quality factor; heterogeneous quality is unsupported")
        quality_factor = quality_factors.pop()
    configs = list(module_configs.values())
    if len({c.inverter_model_id for c in configs}) != 1:
        raise ValueError("Detailed downstream requires one resolved inverter model")
    if configs[0].loss_settings is None and any(c.module_mismatch_loss_fraction != 0 or c.string_mismatch_loss_fraction != 0 for c in configs):
        raise ValueError("Configured module/string mismatch would double-count detailed IV physics")
    if len({c.dc_array_resistance_ohm for c in configs}) != 1:
        raise ValueError("Detailed downstream requires one global DC wiring resistance")
    if any(c.inverter_definition != configs[0].inverter_definition for c in configs):
        raise ValueError("Detailed downstream requires one pinned inverter definition")
    index = next(iter(bank.values())).frame.index
    durations = pd.Series([i["duration_seconds"] for i in payload["intervals"]], index=index)
    chain = simulate_electrical_loss_chain(bank, configs[0].inverter_definition, interval_seconds=durations,
        module_quality_loss_fraction=quality_factor, module_mismatch_loss_fraction=0., string_mismatch_loss_fraction=0.,
        dc_array_resistance_ohm=configs[0].dc_array_resistance_ohm,
        inverter_model_id=configs[0].inverter_model_id,
        **({"loss_settings": configs[0].loss_settings,
            "circuit_references": {int(k): v for k, v in payload["loss_circuit_references"].items()},
            "circuit_loss_context": circuit_execution_context(configs[0].circuit_loss_resolution, configs[0].inverter_instance_id)}
           if configs[0].loss_settings is not None else {}))
    frame = chain.ledger.frame.copy()
    frame["duration_seconds"] = durations
    # Surface-area weighting supports different module footprints without choosing
    # an arbitrary module as the irradiance reference. This is a recorded KPI basis.
    areas = {m: p.replay()["module"]["mechanical"]["width_m"] * p.replay()["module"]["mechanical"]["height_m"]
             for m, p in module_inputs.items()}
    total_area = sum(areas.values())
    for column, source in (("poa_global_w_m2", "incident_poa_w_m2"),
                           ("poa_global_unshaded_w_m2", "unshaded_poa_w_m2"),
                           ("effective_irradiance_w_m2", "effective_irradiance_w_m2"),
                           ("cell_temperature_c", "cell_temperature_c")):
        frame[column] = [sum(areas[m["module_instance_id"]] * m[source] for m in i["modules"]) / total_area
                         for i in payload["intervals"]]
    if configs[0].loss_settings is not None:
        from dataclasses import replace
        from engine.losses.staged import reconcile_loss_frame
        for column in ("post_iam_pre_soiling_w_m2", "soiling_loss_w_m2"):
            frame[column] = [sum(module_inputs[m["module_instance_id"]].replay()["module"]["stc"]["nominal_power_w"] * m[column] / 1000
                for m in i["modules"]) for i in payload["intervals"]]
        frame["optical_reference_w"] = frame["post_iam_pre_soiling_w_m2"]
        frame["soiling_reference_loss_w"] = frame["soiling_loss_w_m2"]
        frame["after_soiling_reference_w"] = frame["optical_reference_w"] - frame["soiling_reference_loss_w"]
        frame["module_operating_delta_w"] = frame["after_soiling_reference_w"] - frame["raw_array_mpp_w"]
        # Retain irradiance diagnostics with physical W/m² units (area weighting).
        for column in ("post_iam_pre_soiling_w_m2", "soiling_loss_w_m2"):
            frame[column] = [sum(areas[m["module_instance_id"]] * m[column] for m in i["modules"]) / total_area for i in payload["intervals"]]
        chain = replace(chain, ledger=reconcile_loss_frame(frame.copy(), interval_seconds=durations,
            optical=True, settings={**configs[0].loss_settings, "circuits": payload["loss_circuit_references"],
                "method": "detailed_iv_plus_dispersion_scalar"}))
    energy = aggregate_interval_quantities(frame, interval_seconds=durations,
        power_columns_w=chain.ledger.energy.metadata["power_columns_w"],
        irradiance_columns_w_m2=["poa_global_w_m2", "poa_global_unshaded_w_m2", "effective_irradiance_w_m2"])
    installed = sum(p.replay()["module"]["stc"]["nominal_power_w"] for p in module_inputs.values()) / 1000
    if configs[0].loss_settings is not None:
        chain.ledger.metadata["resolved_loss_settings"]["simulated_dc_nameplate_w"] = installed * 1000
    kpis = calculate_pv_kpis(grid_energy_kwh=energy.annual["pcc_power_kwh"], installed_dc_kwp=installed,
                           incident_poa_kwh_m2=energy.annual["poa_global_unshaded_kwh_m2"])
    return DetailedDownstreamResult(frame, chain, energy, kpis,
        {"installed_dc_kwp": installed, "electrical_shading_loss_quantified": False,
         "kpi_irradiance_basis": "module_surface_area_weighted_unshaded_incident_poa",
         "scope": "controlled_detailed_pcc_no_annual_acceleration", "module_quality_policy": "evidence_bound_separate_or_embedded_unknown_zero_only",
         "module_quality_declarations": declarations})


def complete_detailed_run(*, run, context, compact, downstream, numerical, configuration,
                          project, weather, store, numerical_arguments, output_directory, attribution=None):
    """Assemble normal artifacts with the existing projections and persistence."""
    from .artifacts import build_standard_timeseries, build_summary_result, persist_parquet_result, persist_run_package
    from .canonical import CanonicalSimulationExecutionResult, _assert_output_schema
    from .temporal import prepare_temporal_execution
    temporal = prepare_temporal_execution(weather, simulation_timestep_seconds=configuration["simulation_timestep_seconds"])
    if not temporal.weather.series.index.equals(downstream.timeseries.index):
        raise ValueError("Detailed downstream working weather intervals do not align")
    standard = build_standard_timeseries(downstream)
    # Detailed runs preserve all normal downstream ledger power channels, plus
    # selected tracker scalar series. Legacy standard projections stay unchanged.
    for column in downstream.electrical.ledger.energy.metadata["power_columns_w"]:
        if column not in standard:
            standard[column] = downstream.timeseries[column].to_numpy()
    for index, state in selected_states_to_mppt_bank(compact).items():
        for column in ("mppt_vmp_v", "mppt_imp_a", "mppt_pmp_w", "mppt_isc_a", "mppt_voc_v", "active",
                       "operating_current_limit_known", "operating_current_above_limit", "availability"):
            standard[f"mppt_{index}_{column}"] = state.frame[column].to_numpy()
    summary = build_summary_result(downstream, simulation_run_id=run["simulation_run_id"],
                                   data_quality_summary={"weather_qc": numerical.replay_stream()["weather_qc"]})
    reference = persist_parquet_result(standard, output_directory=output_directory, simulation_run_id=run["simulation_run_id"])
    manifest = {key: value["revision_id"] for key, value in store.component_revisions.items()}
    models = {**run["model_manifest"], "execution_scope": context["identity"]["execution_scope"],
              "detailed_adapter": "mppt.detailed_selected_state_adapter.v0.1",
              "kpi_irradiance_basis": downstream.metadata["kpi_irradiance_basis"],
              "per_module_resolution": numerical_arguments["model_resolution_metadata"],
              "temperature_metadata": compact.replay()["temperature_metadata"],
              **({"resolved_loss_settings": downstream.electrical.ledger.metadata["resolved_loss_settings"]}
                 if "resolved_loss_settings" in downstream.electrical.ledger.metadata else {})}
    resolution = next(iter(numerical_arguments["module_configs"].values())).circuit_loss_resolution
    if resolution is not None:
        from engine.losses.settings import completed_circuit_loss_audit
        run["circuit_loss_resolution"] = completed_circuit_loss_audit(resolution, downstream)
    if configuration.get("numerical_options", {}).get("optics_thermal_settings") is not None:
        from .optics_thermal import run_optics_snapshot
        snapshot = run_optics_snapshot(configuration, store.scene_revisions[project["scene_revision_id"]],
            store.electrical_revisions[project["electrical_revision_id"]], store.component_revisions)
        models["resolved_optics_thermal_settings"] = snapshot
        run["resolved_optics_thermal_settings"] = snapshot
    hashes = {**context["input_hashes"], "combined_input_sha256": run["input_hash"],
        "project_revision_sha256": context["input_hashes"]["project_revision"],
        "simulation_configuration_sha256": context["input_hashes"]["simulation_configuration"],
        "scene_revision_sha256": context["input_hashes"]["scene"],
        "electrical_revision_sha256": context["input_hashes"]["electrical_design"],
        "weather_dataset_sha256": canonical_object_sha256(weather.dataset),
        "weather_series_logical_sha256": context["inputs"]["weather_series_logical_sha256"],
        "component_manifest_sha256": canonical_object_sha256(manifest),
        "engine_version_sha256": context["input_hashes"]["engine_version"]}
    reproduction = {"schema_name": "ReproducibilityManifest", "schema_version": "0.1",
        "project_revision_id": project["project_revision_id"], "scene_revision_id": run["scene_revision_id"],
        "electrical_revision_id": run["electrical_revision_id"], "weather_revision_id": run["weather_revision_id"],
        "component_revision_manifest": manifest, "engine_version": run["engine_version"], "model_manifest": models,
        "simulation_timestep_seconds": configuration["simulation_timestep_seconds"],
        "timezone": str(temporal.weather.series.index.tz),
        "native_weather_resolution_seconds": temporal.metadata["native_resolution_seconds"],
        "working_weather_resolution_seconds": temporal.metadata["simulation_timestep_seconds"],
        "source_timestamp_convention": weather.dataset["source_timestamp_convention"],
        "representative_time_policy": temporal.timeline.metadata["representative_time_policy"],
        "solar_evaluation_offset_minutes": temporal.timeline.metadata["solar_evaluation_offset_minutes"],
        "weather_transformations": list(temporal.weather.dataset.get("transformations") or []),
        "loss_models": list(configuration.get("loss_model_ids") or []),
        "shading_configuration": configuration["shading_configuration"],
        "numerical_options": {**(configuration.get("numerical_options") or {}),
            "detailed_numerical_policy": context["inputs"]["detailed_numerical_policy"],
            "module_quality_policy": downstream.metadata["module_quality_policy"],
            "module_quality_declarations": downstream.metadata["module_quality_declarations"], "legacy_mismatch_policy":
                "detailed_iv_plus_dispersion_scalar" if "loss_settings" in configuration.get("numerical_options", {}) else "rejected_nonzero"},
        "output_configuration": configuration.get("output_configuration") or {},
        "result_logical_content_sha256": reference["logical_content_sha256"], "result_file_sha256": reference["sha256"],
        "input_hashes": hashes}
    for key in ("design_validation_report_id", "design_validation_report_sha256", "design_validation_rule_set_id"):
        if key in run:
            reproduction[key] = run[key]
    run.update(status="completed_with_warnings" if any(f["severity"] in {"warning", "recommendation"} for f in run["validation_findings"]) else "completed",
        result_reference=reference, summary_result=summary, reproducibility_manifest=reproduction,
        component_revision_manifest=manifest, model_manifest=models,
        job_stage_history=["queued", "validating", "preprocessing", "simulating", "aggregating", "reconciling", "completed"])
    _assert_output_schema(summary, "summary-result.schema.json")
    _assert_output_schema(reproduction, "reproducibility-manifest.schema.json")
    _assert_output_schema(run, "simulation-run.schema.json")
    directory = persist_run_package(output_directory=output_directory, simulation_run_id=run["simulation_run_id"],
        simulation_run=run, summary_result=summary, reproducibility_manifest=reproduction,
        validation_findings=run["validation_findings"], model_resolution=None, detailed_context=context,
        detailed_backend_result=numerical, detailed_compact_result=compact, detailed_attribution_result=attribution,
        detailed_diagnostics=configuration.get("output_configuration", {}).get("detailed_diagnostics", False))
    return CanonicalSimulationExecutionResult(run, summary, standard, downstream, directory, numerical, attribution)
