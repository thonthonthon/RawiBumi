"""Separable execution groups, unchanged DC kernels and one conversion per inverter."""

from __future__ import annotations

from geometry.shading.beam import _fallback_totals

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
import heapq
import json
from typing import TYPE_CHECKING, Any, Iterator, Mapping, Sequence
from types import ModuleType

import numpy as np
import pandas as pd

from electrical.mppt import aggregate_mppt_bank, validate_mppt_assignment
from engine.inverter import (
    simulate_voltage_dependent_inverter,
    InverterElectricalResult,
    INVERTER_VOLTAGE_DEPENDENT_BOUNDED,
    ADJACENT_ENVELOPE_POLICY,
)
from engine.losses.array import apply_pre_inverter_array_losses, ArrayLossResult
from engine.losses.chain import ElectricalLossChainResult
from engine.losses.ledger import (
    ElectricalLossLedgerResult,
    build_electrical_loss_ledger,
)
from engine.losses.energy import EnergyAggregationResult
from engine.losses import calculate_pv_kpis
from geometry.shading import (
    compile_shading_geometry,
    build_shading_acceleration_context,
)
from weather.core import CanonicalWeather
from weather.validation import run_solar_aware_weather_qc
from .artifacts import (
    canonical_object_sha256,
    build_standard_timeseries,
    build_summary_result,
    persist_parquet_result,
    ReceiverFactorParquetSink,
    _ReceiverFactorSpool,
)
from .execution_groups import (
    build_simulation_execution_plan,
    standard_execution_scope_findings,
    execution_units,
)
from .models import resolve_simulation_models
from .unshaded import (
    prepare_fixed_tilt_context,
    run_fixed_tilt_group_dc,
    run_fixed_tilt_class_dc,
    assemble_fixed_tilt_timeseries,
    aggregate_fixed_tilt_energy,
    _uniform_mppt_contract,
    FixedTiltExecutionContext,
    FixedTiltGroupDC,
    FixedTiltClassDC,
    UnshadedFixedTiltConfiguration,
    _loss_chain_options,
)

from .temporal import TemporalExecutionContext

if TYPE_CHECKING:
    from .canonical import CanonicalRevisionStore, CanonicalSimulationExecutionResult


INVERTER_POLICY = "power_weighted_voltage_efficiency_at_total_inverter_dc_power"


@dataclass
class GroupExecution:
    descriptor: dict[str, Any]
    config: UnshadedFixedTiltConfiguration
    dc: FixedTiltGroupDC | FixedTiltClassDC
    array_losses: ArrayLossResult | None
    timeseries: pd.DataFrame
    energy: EnergyAggregationResult
    nameplate_kwp: float


@dataclass
class PlantElectricalResult:
    ledger: ElectricalLossLedgerResult


@dataclass
class MultiGroupSimulationResult:
    temporal: TemporalExecutionContext
    timeseries: pd.DataFrame
    energy: EnergyAggregationResult
    kpis: dict[str, float]
    metadata: dict[str, Any]
    electrical: PlantElectricalResult
    groups: dict[str, GroupExecution]
    inverters: dict[str, ElectricalLossChainResult]
    context: FixedTiltExecutionContext
    shading_receiver_factors: None = None


def _sum_power_frames(frames: Sequence[pd.DataFrame]) -> pd.DataFrame:
    if len(frames) == 1:
        return frames[0].copy()
    index = frames[0].index
    if any(not f.index.equals(index) for f in frames):
        raise ValueError("execution intervals must align exactly")
    if any("orientation_mismatch_loss_w" in f for f in frames):
        frames = [f if "orientation_mismatch_loss_w" in f else f.assign(
            orientation_mismatch_loss_w=0.0, after_orientation_mismatch_w=f["raw_array_mpp_w"]) for f in frames]
    if any("orientation_mismatch_reconciliation_residual_w" in f for f in frames):
        frames = [f if "orientation_mismatch_reconciliation_residual_w" in f else f.assign(
            orientation_mismatch_reconciliation_residual_w=0.0) for f in frames]
    if any("mppt_current_limit_loss_w" in f for f in frames):
        # An inverter without a known MPPT current limit loses nothing to it.
        frames = [f if "mppt_current_limit_loss_w" in f else f.assign(
            mppt_current_limit_loss_w=0.0,
            after_mppt_current_limit_w=f["dc_mpp_available_w"]) for f in frames]
    columns = [c for c in frames[0] if c.endswith("_w")]
    if any(set(columns) - set(f) for f in frames):
        raise ValueError("electrical channel sets must agree")
    return pd.DataFrame(
        {
            c: np.sum(np.vstack([f[c].to_numpy(dtype=float) for f in frames]), axis=0)
            for c in columns
        },
        index=index.copy(),
    )


def _array_bank(results: Sequence[ArrayLossResult]) -> ArrayLossResult:
    if len(results) == 1:
        return results[0]
    bank = {}
    for result in results:
        if set(bank) & set(result.mppt_bank):
            raise ValueError("an MPPT cannot belong to more than one execution group")
        bank.update(result.mppt_bank)
    return ArrayLossResult(
        bank,
        _sum_power_frames([r.frame for r in results]),
        {
            "scope": "sum_of_group_DC_channels",
            "dc_array_resistance_ohm": 0.0,
            **(
                {
                    "circuits": {
                        key: value
                        for result in results
                        for key, value in result.metadata["circuits"].items()
                    }
                }
                if all("circuits" in result.metadata for result in results)
                else {}
            ),
        },
    )


def _equivalent_frame(
    ledger: ElectricalLossLedgerResult,
    groups: Sequence[GroupExecution],
    context: FixedTiltExecutionContext,
) -> pd.DataFrame:
    """Common weather plus additive power and explicitly nameplate-equivalent POA."""
    frame = ledger.frame.copy()
    frame["duration_seconds"] = context.temporal.timeline.frame["duration_seconds"]
    for c in ("ghi_w_m2", "dni_w_m2", "dhi_w_m2"):
        frame[c] = context.irradiance.frame[c]
    for c in ("solar_zenith_deg", "solar_azimuth_deg"):
        if c in context.solar.frame:
            frame[c] = context.solar.frame[c]
    for c in ("ambient_temperature_c", "wind_speed_m_s"):
        if c in context.temporal.weather.series:
            frame[c] = context.temporal.weather.series[c]
    capacity = sum(g.nameplate_kwp for g in groups)
    channels = [
        c
        for c in groups[0].timeseries
        if c.startswith(("poa_", "near_shading_")) and c.endswith("_w_m2")
    ]
    channels.append("effective_irradiance_w_m2")
    for c in channels:
        frame[c] = sum((g.timeseries[c] * (g.nameplate_kwp / capacity) for g in groups))
    return frame


def _energy_and_kpis(
    frame: pd.DataFrame, ledger: ElectricalLossLedgerResult, capacity: float
) -> tuple[EnergyAggregationResult, dict[str, float]]:
    energy = aggregate_fixed_tilt_energy(
        frame, ledger.energy.metadata["power_columns_w"]
    )
    key = (
        "poa_global_unshaded_kwh_m2"
        if "poa_global_unshaded_kwh_m2" in energy.annual
        else "poa_global_kwh_m2"
    )
    kpis = calculate_pv_kpis(
        grid_energy_kwh=energy.annual["pcc_power_kwh"],
        installed_dc_kwp=capacity,
        incident_poa_kwh_m2=energy.annual[key],
    )
    return energy, kpis


def _spool_rows(path: Path) -> Iterator[dict[str, Any]]:
    import pyarrow.parquet as pq

    for batch in pq.ParquetFile(path).iter_batches(batch_size=8192):
        yield from batch.to_pylist()


def _merge_receiver_spools(
    paths: Sequence[Path], output_directory: Path, simulation_run_id: str
) -> dict[str, Any]:
    """Merge sorted group streams without retaining the receiver×time dataset."""
    sink = ReceiverFactorParquetSink(
        output_directory=output_directory, simulation_run_id=simulation_run_id
    )
    iterators = [iter(_spool_rows(p)) for p in paths]
    heap, buffer, columns = [], [], None
    for i, iterator in enumerate(iterators):
        row = next(iterator, None)
        if row is not None:
            columns = list(row)
            heapq.heappush(heap, (row["interval_start"], row["receiver_id"], i, row))
    try:
        while heap:
            _, _, i, row = heapq.heappop(heap)
            buffer.append(row)
            if len(buffer) == 8192:
                sink.write(pd.DataFrame(buffer, columns=columns))
                buffer.clear()
            row = next(iterators[i], None)
            if row is not None:
                heapq.heappush(
                    heap, (row["interval_start"], row["receiver_id"], i, row)
                )
        if buffer:
            sink.write(pd.DataFrame(buffer, columns=columns))
        return sink.finalize()
    except Exception:
        sink.abort()
        raise


def run_multi_group_physics(
    weather: CanonicalWeather,
    *,
    bindings: Mapping[str, dict[str, Any]],
    plan: Mapping[str, Any],
    compiled_geometry: Mapping[str, Any],
    shading_configuration: Mapping[str, Any],
    output_directory: Path | None = None,
    simulation_run_id: str | None = None,
    context: FixedTiltExecutionContext | None = None,
    geometry: bool = True,
) -> tuple[MultiGroupSimulationResult, dict[str, Any] | None]:
    """Execute group DC stages and physical inverter banks; no model approximation added."""
    from .geometry_aware import _geometry_poa_postprocessor, _sha256_json

    first_config = next(iter(bindings.values()))["config"]
    if any(entry["config"].inverter_model_id != first_config.inverter_model_id for entry in bindings.values()):
        raise ValueError("one simulation requires one resolved inverter model")
    context = context or prepare_fixed_tilt_context(weather, config=first_config)
    groups, runtimes, spool_paths = {}, {}, []
    mode = bindings[next(iter(bindings))]["shading_mode"]
    use_geometry = geometry and mode != "unshaded"
    all_receivers = sorted({r for g in execution_units(plan) for r in g["receiver_ids"]})
    acceleration = None
    if use_geometry:
        acceleration = build_shading_acceleration_context(
            compiled_geometry,
            shading_configuration=shading_configuration,
            receiver_ids=all_receivers,
            source_execution_plan_id=plan["execution_plan_id"],
            source_execution_plan_payload_sha256=plan["execution_plan_payload_sha256"],
        )
    receiver_reference = None
    with TemporaryDirectory(prefix="s16-receivers-") as temporary, ExitStack() as lifecycle:
        if acceleration is not None:
            lifecycle.callback(acceleration.close)
        for gid, binding in sorted(bindings.items()):
            group, config = binding["group"], binding["config"]
            callback = sink = None
            if use_geometry:
                sink = _ReceiverFactorSpool(
                    output_directory=Path(temporary), simulation_run_id=gid
                )
                callback = _geometry_poa_postprocessor(
                    compiled_geometry=compiled_geometry,
                    execution_group_plan=plan,
                    execution_group_id=gid,
                    shading_configuration=shading_configuration,
                    shared_acceleration_context=acceleration,
                    retain_receiver_factors=False,
                    receiver_factor_chunk_consumer=sink.write,
                )
            try:
                is_class = binding.get("is_class", False)
                dc = (run_fixed_tilt_class_dc if is_class else run_fixed_tilt_group_dc)(
                    context, config=config, poa_postprocessor=callback
                )
                if sink is not None:
                    spool_paths.append(sink.finalize())
                    runtimes[gid] = dc.poa_postprocess.metadata
            except Exception:
                if sink is not None:
                    sink.abort()
                raise
            if is_class:
                capacity_w = len(group["module_instance_ids"]) * dc.module_nominal_power_w
                optical_frame = pd.DataFrame({"raw_array_mpp_w":
                    dc.coupled_module.electrical.frame["pmp_w"] * len(group["module_instance_ids"])})
                if config.loss_settings is not None:
                    from engine.losses.soiling import optical_reference_channels
                    for key, values in optical_reference_channels(dc.optical,optical_frame["raw_array_mpp_w"],capacity_w).items():
                        optical_frame[key] = values
                frame = assemble_fixed_tilt_timeseries(context,dc,optical_frame)
                energy = aggregate_fixed_tilt_energy(frame,[c for c in optical_frame if c.endswith("_w")])
                groups[gid] = GroupExecution(group,config,dc,None,frame,energy,capacity_w/1000.)
                continue
            count, total, per_tracker, min_v, max_v, max_i = _uniform_mppt_contract(
                config.inverter_definition
            )
            mppts = aggregate_mppt_bank(
                dc.string_bank,
                config.mppt_assignments,
                mppt_count=count,
                total_input_count=total,
                input_count_per_mppt=per_tracker,
                min_operating_voltage_v=min_v,
                max_operating_voltage_v=max_v,
                max_operating_current_a=max_i,
            )
            if config.loss_settings is None:
                arrays = apply_pre_inverter_array_losses(
                    mppts,
                    module_quality_loss_fraction=dc.module_runtime.module_quality_loss_fraction,
                    module_mismatch_loss_fraction=config.module_mismatch_loss_fraction,
                    string_mismatch_loss_fraction=config.string_mismatch_loss_fraction,
                    dc_array_resistance_ohm=0.0,
                )
            if config.loss_settings is not None:
                from engine.losses.staged import apply_circuit_losses

                arrays = apply_circuit_losses(
                    mppts,
                    config.loss_settings,
                    _loss_chain_options(config)["circuit_references"],
                    quality=dc.module_runtime.module_quality_loss_fraction,
                )
                from engine.losses.soiling import optical_reference_channels

                capacity_w = (
                    len(config.string_ids)
                    * config.modules_in_series
                    * dc.module_nominal_power_w
                )
                for key, values in optical_reference_channels(
                    dc.optical, arrays.frame["raw_array_mpp_w"], capacity_w
                ).items():
                    arrays.frame[key] = values

            frame = assemble_fixed_tilt_timeseries(context, dc, arrays.frame)
            power_columns = [c for c in arrays.frame if c.endswith("_w")]
            energy = aggregate_fixed_tilt_energy(frame, power_columns)
            capacity = (
                len(config.string_ids)
                * config.modules_in_series
                * dc.module_nominal_power_w
                / 1000.0
            )
            groups[gid] = GroupExecution(
                group, config, dc, arrays, frame, energy, capacity
            )
        if use_geometry and output_directory is not None:
            receiver_reference = _merge_receiver_spools(
                spool_paths, output_directory, simulation_run_id
            )

    inverters = {}
    mixed_diagnostics = []
    for iid in sorted({g.descriptor["inverter_instance_id"] for g in groups.values()}):
        selected = [
            g for g in groups.values() if g.descriptor["inverter_instance_id"] == iid
        ]
        count, total, per_tracker, _, _, _ = _uniform_mppt_contract(
            selected[0].config.inverter_definition
        )
        assignments = {
            i: ids for g in selected for i, ids in g.config.mppt_assignments.items()
        }
        mixed_units = {gid:g for gid,g in groups.items() if g.array_losses is None and g.descriptor["inverter_instance_id"] == iid}
        physical = [m for m in plan.get("mixed_orientation",{}).get("mppts",[]) if m["inverter_instance_id"] == iid]
        for m in physical:
            assignments[m["mppt_index"]] = tuple(s["string_id"] for s in m["strings"])
        validate_mppt_assignment(
            assignments,
            string_ids=[sid for g in selected for sid in g.config.string_ids] + [s["string_id"] for m in physical for s in m["strings"]],
            mppt_count=count,
            total_input_count=total,
            input_count_per_mppt=per_tracker,
        )
        pieces = [g.array_losses for g in selected if g.array_losses is not None]
        if mixed_units:
            from .mixed_orientation import build_mixed_arrays
            mixed_arrays, diagnostics = build_mixed_arrays(mixed_units,physical,context)
            mixed_diagnostics.extend(diagnostics)
            if first_config.loss_settings is not None:
                for channel in ("optical_reference_w", "soiling_reference_loss_w", "after_soiling_reference_w", "module_operating_delta_w"):
                    total_values = sum(g.timeseries[channel] for g in mixed_units.values())
                    for number,array in enumerate(mixed_arrays):
                        array.frame[channel] = total_values if number == 0 else 0.
            pieces.extend(mixed_arrays)
        arrays = _array_bank(pieces)
        if len({g.config.inverter_model_id for g in selected}) != 1:
            raise ValueError("one inverter bank requires one resolved conversion model")
        inverter = simulate_voltage_dependent_inverter(
            arrays.mppt_bank, selected[0].config.inverter_definition,
            model_id=selected[0].config.inverter_model_id,
        )
        if first_config.loss_settings is None:
            ledger = build_electrical_loss_ledger(
                arrays,
                inverter,
                interval_seconds=context.temporal.timeline.frame["duration_seconds"],
            )
        else:
            from engine.losses.staged import build_staged_ledger, reconcile_loss_frame

            ledger = build_staged_ledger(
                arrays,
                inverter,
                settings=selected[0].config.loss_settings,
                nominal_w=float(
                    selected[0].config.inverter_definition["ac_limits"][
                        "nominal_ac_power_w"
                    ]
                ),
                interval_seconds=context.temporal.timeline.frame["duration_seconds"],
                apply_plant=False,
                circuit_loss_context=_loss_chain_options(selected[0].config).get("circuit_loss_context"),
            )
            ledger = reconcile_loss_frame(
                ledger.frame,
                interval_seconds=context.temporal.timeline.frame["duration_seconds"],
                optical=True,
                settings=ledger.metadata["resolved_loss_settings"],
            )

        inverters[iid] = ElectricalLossChainResult(
            arrays, inverter, ledger, {"multi_mppt_efficiency_policy": INVERTER_POLICY}
        )

    arrays = ArrayLossResult(
        {},
        _sum_power_frames([i.array_losses.frame for i in inverters.values()]),
        {"scope": "sum_of_physical_inverters"},
    )
    ac = InverterElectricalResult(
        _sum_power_frames([i.inverter.frame for i in inverters.values()]),
        {"scope": "sum_of_physical_inverters"},
    )
    if first_config.loss_settings is None:
        ledger = build_electrical_loss_ledger(
            arrays,
            ac,
            interval_seconds=context.temporal.timeline.frame["duration_seconds"],
        )
    else:
        from engine.losses.staged import apply_plant_losses, reconcile_loss_frame

        plant_frame = _sum_power_frames(
            [item.ledger.frame for item in inverters.values()]
        )
        nominal_w = sum(
            float(
                next(
                    g
                    for g in groups.values()
                    if g.descriptor["inverter_instance_id"] == iid
                ).config.inverter_definition["ac_limits"]["nominal_ac_power_w"]
            )
            for iid in inverters
        )
        for key, values in apply_plant_losses(
            plant_frame["after_ac_wiring_w"],
            first_config.loss_settings,
            nominal_w=nominal_w,
            plant_ac_segment=(first_config.circuit_loss_resolution or {}).get("plant_ac_wiring"),
        ).items():
            plant_frame[key] = values
        ledger = reconcile_loss_frame(
            plant_frame,
            interval_seconds=context.temporal.timeline.frame["duration_seconds"],
            optical=True,
            settings={
                **first_config.loss_settings,
                "circuits": {
                    f"{iid}:{key}": value
                    for iid, item in inverters.items()
                    for key, value in item.array_losses.metadata.get(
                        "circuits", {}
                    ).items()
                },
                "inverters": {
                    iid: {
                        "nominal_ac_power_w": item.ledger.metadata[
                            "resolved_loss_settings"
                        ]["inverter_reference_power_w"]
                    }
                    for iid, item in inverters.items()
                },
                "transformer_reference_power_w": first_config.loss_settings["values"][
                    "transformer"
                ]["reference_power_w"]
                or nominal_w,
                "measurement_boundary": "inverters_after_own_ac_wiring_plant_after_system_losses",
            },
        )

    frame = _equivalent_frame(ledger, list(groups.values()), context)
    capacity = sum(g.nameplate_kwp for g in groups.values())
    if first_config.loss_settings is not None:
        ledger.metadata["resolved_loss_settings"]["simulated_dc_nameplate_w"] = (
            capacity * 1000
        )
    energy, kpis = _energy_and_kpis(frame, ledger, capacity)
    metadata = {
        "scope": "mixed_orientation_coupled.v0.1" if mixed_diagnostics else "separable_multi_group_per_inverter.v0.1",
        "installed_dc_kwp": capacity,
        "model_manifest": {
            "multi_mppt_efficiency_policy": INVERTER_POLICY,
            "plant_poa_basis": "simulated_dc_nameplate_weighted",
        },
        "shading_runtime": None,
    }
    if use_geometry:
        runtime = dict(next(iter(runtimes.values())))
        for key in (
            "execution_group_id",
            "group_sky_visibility_factor",
            "group_horizon_visibility_factor",
            "group_ground_visibility_factor",
            "execution_telemetry",
        ):
            runtime.pop(key, None)
        runtime.update(
            receiver_set_sha256=_sha256_json(all_receivers),
            receiver_count=len(all_receivers),
            receiver_area_total_m2=sum(
                r["receiver_area_total_m2"] for r in runtimes.values()
            ),
            receiver_factor_rows=sum(
                r["receiver_factor_rows"] for r in runtimes.values()
            ),
            execution_groups={
                gid: {k: v for k, v in r.items() if k != "execution_telemetry"}
                for gid, r in runtimes.items()
            },
        )
        runtime.pop("shadow_union_precision_fallback", None)
        runtime.update(_fallback_totals([
            {**event, "execution_group_id": gid}
            for gid, group_runtime in runtimes.items()
            for event in group_runtime.get("shadow_union_precision_fallback", {}).get("events", [])
        ]))
        metadata["shading_runtime"] = runtime
    if mixed_diagnostics:
        from .mixed_orientation import run_record
        metadata["mixed_physical_breakdown"] = [d["breakdown"] for d in mixed_diagnostics]
        metadata["mixed_orientation"] = run_record(plan,{k:g for k,g in groups.items() if g.array_losses is None},mixed_diagnostics,context)
        metadata["model_manifest"]["mixed_orientation"] = metadata["mixed_orientation"]["model_id"]
    metadata["model_manifest"].update(
        solar_position=context.solar.metadata.get("model_id"),
        irradiance_decomposition=first_config.decomposition_model_id,
        poa_transposition=first_config.poa_model_id,
        thermal=first_config.thermal_model_id,
        group_runtime_models={
            gid: {
                "optical_model_id": group.dc.optical.metadata.get("model_id"),
                "thermal_model_id": group.dc.coupled_module.thermal.metadata.get(
                    "model_id"
                ),
                "module_model_id": group.dc.coupled_module.electrical.metadata.get(
                    "model_id"
                ),
                "module_runtime_resolution": group.dc.module_runtime.metadata,
            }
            for gid, group in groups.items()
        },
    )
    if first_config.inverter_model_id == INVERTER_VOLTAGE_DEPENDENT_BOUNDED:
        if any(i.inverter.metadata["model_id"] != INVERTER_VOLTAGE_DEPENDENT_BOUNDED for i in inverters.values()):
            raise ValueError("resolved inverter model did not reach every inverter bank")
        metadata["model_manifest"].update(inverter=INVERTER_VOLTAGE_DEPENDENT_BOUNDED,
                                          inverter_voltage_interpolation=ADJACENT_ENVELOPE_POLICY)
    return (
        MultiGroupSimulationResult(
            context.temporal,
            frame,
            energy,
            kpis,
            metadata,
            PlantElectricalResult(ledger),
            groups,
            inverters,
            context,
        ),
        receiver_reference,
    )


def _breakdown(
    backend: MultiGroupSimulationResult,
    electrical: Mapping[str, Any],
    output_directory: Path,
    simulation_run_id: str,
) -> dict[str, Any]:
    inverters, groups = [], []
    inverter_frames, group_frames = [], []
    instances = {i["inverter_instance_id"]: i for i in electrical["inverter_instances"]}
    for gid, group in backend.groups.items():
        data = group.energy.annual
        unshaded = data.get("poa_global_unshaded_kwh_m2", data["poa_global_kwh_m2"])
        if group.array_losses is None:
            continue
        groups.append(
            {
                **group.descriptor,
                "simulated_dc_nameplate_w": group.nameplate_kwp * 1000,
                "poa_unshaded_wh_m2": unshaded * 1000,
                "poa_wh_m2": data["poa_global_kwh_m2"] * 1000,
                "effective_irradiation_wh_m2": data["effective_irradiance_kwh_m2"]
                * 1000,
                "raw_dc_energy_wh": data["raw_array_mpp_kwh"] * 1000,
                "post_array_loss_dc_energy_wh": data["array_virtual_mpp_kwh"] * 1000,
                "dc_loss_energy_wh": {
                    c: data[c] * 1000 for c in data if c.endswith("_loss_kwh")
                },
            }
        )
        frame = group.timeseries.copy()
        frame["timestamp"] = frame.index
        frame["execution_group_id"] = gid
        frame["inverter_instance_id"] = group.descriptor["inverter_instance_id"]
        group_frames.append(frame.reset_index(drop=True))
    for iid, chain in backend.inverters.items():
        selected = [
            g
            for g in backend.groups.values()
            if g.descriptor["inverter_instance_id"] == iid
        ]
        capacity = sum(g.nameplate_kwp for g in selected)
        frame = _equivalent_frame(chain.ledger, selected, backend.context)
        energy, kpis = _energy_and_kpis(frame, chain.ledger, capacity)
        # The existing summary builder is a projection of ledger/energy/KPIs only.
        view = MultiGroupSimulationResult(
            backend.temporal,
            frame,
            energy,
            kpis,
            {"installed_dc_kwp": capacity},
            PlantElectricalResult(chain.ledger),
            {},
            {},
            backend.context,
        )
        summary = build_summary_result(
            view, simulation_run_id=simulation_run_id, data_quality_summary={}
        )
        definition = selected[0].config.inverter_definition
        inverters.append(
            {
                "inverter_instance_id": iid,
                "name": instances[iid].get("name") or iid,
                "inverter_revision_id": definition["revision_id"],
                "simulated_dc_nameplate_w": capacity * 1000,
                "nominal_ac_power_w": definition["ac_limits"]["nominal_ac_power_w"],
                "total_energy_wh": summary["total_energy_wh"],
                "annual_energy_wh": summary["annual_energy_wh"],
                "specific_yield_wh_per_wp": summary["specific_yield_wh_per_wp"],
                "performance_ratio": summary["performance_ratio"],
                "monthly_energy": summary["monthly_energy"],
                "clipping_energy_wh": summary["clipping_energy_wh"],
                "voltage_threshold_energy_wh": energy.annual[
                    "dc_voltage_threshold_loss_kwh"
                ]
                * 1000,
                "startup_threshold_energy_wh": energy.annual[
                    "dc_power_threshold_loss_kwh"
                ]
                * 1000,
                "conversion_energy_wh": energy.annual["inverter_conversion_loss_kwh"]
                * 1000,
                "self_consumption_energy_wh": energy.annual[
                    "inverter_self_consumption_kwh"
                ]
                * 1000,
                "loss_summary": summary["loss_summary"],
            }
        )
        frame["timestamp"] = frame.index
        frame["inverter_instance_id"] = iid
        inverter_frames.append(frame.reset_index(drop=True))
    plant_fields = {}
    if "resolved_loss_settings" in backend.electrical.ledger.metadata:
        energy = backend.electrical.ledger.energy.annual
        plant_fields = {
            "measurement_boundary": "inverters_after_own_ac_wiring_plant_after_system_losses",
            "inverter_subtotal_energy_wh": sum(
                row["total_energy_wh"] for row in inverters
            ),
            "plant_adjustments": {
                key: float(backend.electrical.ledger.summary.set_index("channel").loc[key, "loss_energy_kwh"]) * 1000
                for key in (("plant_ac_wiring", "transformer_iron", "transformer_copper", "unavailability")
                    if "plant_ac_wiring_loss_w" in backend.electrical.ledger.frame else ("transformer_iron", "transformer_copper", "unavailability"))
            },
        }
    mixed_fields = {}
    classes = [g for g in backend.groups.values() if g.array_losses is None]
    if classes:
        mixed_fields = {"orientation_classes": [{**g.descriptor,
            "simulated_dc_nameplate_w":g.nameplate_kwp*1000,
            "poa_unshaded_wh_m2":g.energy.annual.get("poa_global_unshaded_kwh_m2",g.energy.annual["poa_global_kwh_m2"])*1000,
            "poa_wh_m2":g.energy.annual["poa_global_kwh_m2"]*1000,
            "raw_dc_energy_wh":g.energy.annual["raw_array_mpp_kwh"]*1000} for g in classes],
            "mixed_mppts":backend.metadata["mixed_physical_breakdown"]}
    return {
        **plant_fields,
        **mixed_fields,
        "schema_version": "0.1",
        "simulated_dc_nameplate_w": backend.metadata["installed_dc_kwp"] * 1000,
        "plant_poa_basis": "simulated_dc_nameplate_weighted",
        "inverters": inverters,
        "groups": groups,
        "group_timeseries_reference": persist_parquet_result(
            pd.concat(group_frames, ignore_index=True) if group_frames else pd.DataFrame({
                "timestamp":pd.Series([],dtype="datetime64[ns, UTC]"), "execution_group_id":pd.Series([],dtype=str),
                "inverter_instance_id":pd.Series([],dtype=str)}),
            output_directory=output_directory,
            simulation_run_id=simulation_run_id,
            filename="group-timeseries.parquet",
        ),
        "inverter_timeseries_reference": persist_parquet_result(
            pd.concat(inverter_frames, ignore_index=True),
            output_directory=output_directory,
            simulation_run_id=simulation_run_id,
            filename="inverter-timeseries.parquet",
        ),
    }


def run_multi_group_canonical(
    *,
    project_revision: dict[str, Any],
    simulation_configuration: dict[str, Any],
    revision_store: CanonicalRevisionStore,
    output_path: Path,
    simulation_run_id: str,
    engine_version: str,
    now: str,
    scene: dict[str, Any],
    electrical: dict[str, Any],
    weather: CanonicalWeather,
    findings: list[dict[str, Any]],
    design_validation_evidence: dict[str, Any] | None,
) -> CanonicalSimulationExecutionResult:
    from . import canonical as c
    from .annual_shading import build_annual_shading_result

    project_revision_id = project_revision["project_revision_id"]
    assumptions, bindings, resolutions = [], {}, []

    def add(
        rule_id: str,
        message: str,
        entity_id: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        c._add(
            findings,
            run_id=simulation_run_id,
            project_revision_id=project_revision_id,
            entity_id=entity_id or str(electrical["electrical_revision_id"]),
            rule_id=rule_id,
            severity="blocking_error",
            category="execution_scope",
            message=message,
            generated_at=now,
            context=context or {},
        )

    compiled = compile_shading_geometry(scene)
    plan = build_simulation_execution_plan(
        scene,
        electrical,
        numerical_options=simulation_configuration.get("numerical_options"),
        compiled_shading_geometry=compiled,
    )
    mode = c._resolve_shading_mode(
        simulation_configuration,
        run_id=simulation_run_id,
        project_revision_id=project_revision_id,
        generated_at=now,
        findings=findings,
    )
    for item in plan["findings"]:
        if (
            item["severity"] == "error"
            and item["code"] != "execution_group_mppt_heterogeneous"
        ):
            add(
                "SIMULATION_EXECUTION_GROUP_PLAN_INVALID",
                item["message"],
                item.get("entity_id"),
                item.get("context"),
            )
    for item in standard_execution_scope_findings(
        scene,
        electrical,
        plan,
        numerical_options=simulation_configuration.get("numerical_options"),
    ):
        add(item["rule_id"], item["message"], item["entity_id"], item["context"])
    for s in electrical["strings"]:
        if s.get("enabled") and s.get("polarity") != "normal":
            add(
                "SIMULATION_UNSUPPORTED_STRING_POLARITY",
                "Only normal string polarity is supported.",
                s["string_id"],
            )
    mppts = {
        m["mppt_instance_id"]: m
        for m in electrical["mppt_instances"]
        if m.get("enabled")
    }
    strings = {s["string_id"]: s for s in electrical["strings"] if s.get("enabled")}
    components = revision_store.component_revisions
    from engine.losses.settings import resolve_circuit_loss_settings
    circuit_resolution = None
    try:
        stored_losses = simulation_configuration.get("numerical_options", {}).get("loss_settings")
        if stored_losses is not None:
            circuit_resolution = resolve_circuit_loss_settings(stored_losses, scene, electrical, components,
                module_quality_override=simulation_configuration.get("numerical_options", {}).get("module_overrides", {}).get("module_quality_loss_fraction"))
    except (ValueError, KeyError, TypeError) as exc:
        add("LOSS_SETTINGS_INVALID", str(exc))
    for m in plan.get("mixed_orientation",{}).get("mppts",[]):
        expected = {s["string_id"] for s in m["strings"]}
        if expected != set(mppts[m["mppt_instance_id"]].get("connected_string_ids") or []):
            add("SIMULATION_STRING_MPPT_ASSIGNMENT_INCONSISTENT", "String and MPPT assignments do not reconcile.",m["mppt_instance_id"])
    modules, inverter_definitions = {}, {}
    for group in execution_units(plan):
        is_class = group not in plan["groups"]
        gid = group["execution_group_id"]
        mrid = group["module_revision_id"]
        irid = group["inverter_definition_revision_id"]
        if mrid not in components or irid not in components:
            add(
                "SIMULATION_COMPONENT_REVISION_NOT_FOUND",
                "A pinned group component revision is unavailable.",
                gid,
            )
            continue
        module, inverter = components[mrid], components[irid]
        modules[mrid] = module
        inverter_definitions[irid] = inverter
        for definition, filename in [
            (module, "module-definition.schema.json"),
            (inverter, "inverter-definition.schema.json"),
        ]:
            findings.extend(
                c._schema_findings(
                    definition,
                    filename="components/schema/" + filename,
                    entity_id=definition["revision_id"],
                    project_revision_id=project_revision_id,
                    generated_at=now,
                    finding_prefix=simulation_run_id
                    + ":"
                    + gid
                    + ":"
                    + definition["revision_id"],
                )
            )
        try:
            _uniform_mppt_contract(inverter)
        except ValueError as exc:
            add("SIMULATION_UNSUPPORTED_MPPT_DEFINITION", str(exc), irid)
        assignments = {}
        for mid in group.get("mppt_instance_ids",[]):
            m = mppts[mid]
            ids = tuple(m.get("connected_string_ids") or [])
            if set(ids) - set(group["string_ids"]) or any(
                sid not in strings or strings[sid].get("target_mppt_instance_id") != mid
                for sid in ids
            ):
                add(
                    "SIMULATION_STRING_MPPT_ASSIGNMENT_INCONSISTENT",
                    "String and MPPT assignments do not reconcile.",
                    mid,
                )
            assignments[int(m["index"])] = ids
        if mode != "unshaded" and group["missing_receiver_module_ids"]:
            add(
                "SIMULATION_SCOPE_BEAM_RECEIVERS_UNRESOLVED",
                "Geometry-aware execution requires every group receiver.",
                gid,
            )
        physical_reference = next((m for m in plan.get("mixed_orientation",{}).get("mppts",[])
            if any(gid in row["composition"] for row in m["strings"])),None)
        descriptor = {
            **group,
            **({"modules_in_series":physical_reference["modules_in_series"],"string_ids":()} if is_class else {}),
            "circuit_loss_resolution": circuit_resolution,
            "module": module,
            "inverter": inverter,
            "inverter_revision_id": irid,
            "albedo_source": (
                group["albedo_sources"][0]
                if len(group["albedo_sources"]) == 1
                else "execution_group.mixed_provenance_equal_value"
            ),
            "mppt_assignments": assignments,
        }
        resolution = resolve_simulation_models(
            module,
            inverter,
            resolution_id="model-resolution:"
            + canonical_object_sha256(
                {
                    "group": gid,
                    "selections": simulation_configuration["model_selections"],
                }
            )[:16],
            requested_module_model_id=simulation_configuration["model_selections"].get(
                "module_electrical"
            ),
            requested_inverter_model_id=simulation_configuration[
                "model_selections"
            ].get("inverter"),
        )
        resolutions.append(
            {
                "execution_group_id": gid,
                "inverter_instance_id": group["inverter_instance_id"],
                "resolution": resolution,
            }
        )
        assumptions.extend(resolution["assumptions"])
        if resolution["status"] == "blocked":
            add(
                "SIMULATION_MODEL_RESOLUTION_BLOCKED",
                "Pinned group component models are not executable.",
                gid,
            )
        config = c._build_runtime_config(
            simulation_configuration,
            descriptor,
            resolution,
            run_id=simulation_run_id + ":" + gid,
            project_revision_id=project_revision_id,
            generated_at=now,
            findings=findings,
            assumptions=assumptions,
        )
        bindings[gid] = {"group": group, "config": config, "shading_mode": mode, "is_class": is_class}
    manifest = {
        "module_revision_ids": sorted(modules),
        "inverter_revision_ids": sorted(inverter_definitions),
        "execution_group_bindings": [
            {
                k: g[k]
                for k in (
                    "execution_group_id",
                    "inverter_instance_id",
                    "module_revision_id",
                    "inverter_definition_revision_id",
                )
            }
            for g in execution_units(plan)
        ],
    }
    if plan.get("mixed_orientation"):
        from .mixed_orientation import bypass_basis
        mixed_revisions = {c["module_revision_id"] for c in plan["mixed_orientation"]["classes"]}
        for revision in sorted(mixed_revisions):
            basis = bypass_basis(modules[revision])
            if "assumed" in (basis["count_basis"],basis["forward_voltage_basis"]):
                assumptions.append(c._runtime_assumption("mixed-bypass:"+revision,kind="fallback",scope=revision,
                    statement="Missing bypass data uses 3 diodes and/or 0.7 V forward voltage; zero diodes means no bypass protection.",
                    basis="USE5 documented bypass fallback; supplied values preserved",source_paths=tuple(basis["source_paths"]),affects=("mixed_orientation",)))
    selected = c._select_weather_period(weather, simulation_configuration)
    hashes = c._input_hashes(
        engine_version=engine_version,
        project_revision=project_revision,
        simulation_configuration=simulation_configuration,
        scene=scene,
        electrical=electrical,
        weather=selected,
        component_manifest=manifest,
        module=modules,
        inverter=inverter_definitions,
    )
    if not bindings or c._has_blocker(findings):
        return _failed(
            c,
            project_revision,
            simulation_configuration,
            simulation_run_id,
            engine_version,
            now,
            findings,
            assumptions,
            manifest,
            hashes,
            output_path,
            design_validation_evidence,
        )
    context = prepare_fixed_tilt_context(
        selected, config=next(iter(bindings.values()))["config"]
    )
    qc = run_solar_aware_weather_qc(context.temporal.weather, context.solar)
    findings.extend(
        c._weather_findings(
            qc,
            run_id=simulation_run_id,
            project_revision_id=project_revision_id,
            weather_revision_id=selected.dataset["revision_id"],
            generated_at=now,
            existing_count=len(findings),
        )
    )
    if c._has_blocker(findings):
        return _failed(
            c,
            project_revision,
            simulation_configuration,
            simulation_run_id,
            engine_version,
            now,
            findings,
            assumptions,
            manifest,
            hashes,
            output_path,
            design_validation_evidence,
        )
    shading = simulation_configuration.get("shading_configuration") or {}
    backend, receiver_ref = run_multi_group_physics(
        selected,
        bindings=bindings,
        plan=plan,
        compiled_geometry=compiled,
        shading_configuration=shading,
        output_directory=output_path,
        simulation_run_id=simulation_run_id,
        context=context,
    )
    backend.metadata["execution_model_resolutions"] = resolutions
    backend.metadata["model_manifest"]["execution_model_resolutions"] = resolutions
    backend.metadata["execution_model_resolution_id"] = (
        "model-resolutions:" + canonical_object_sha256(resolutions)[:16]
    )
    duration = float(backend.timeseries["duration_seconds"].sum()) / 3600
    if mode != "unshaded" and (
        abs(duration - 8760) < 1e-9 or abs(duration - 8784) < 1e-9
    ):
        clear, _ = run_multi_group_physics(
            selected,
            bindings=bindings,
            plan=plan,
            compiled_geometry=compiled,
            shading_configuration=shading,
            context=context,
            geometry=False,
        )
        actual = float(backend.energy.annual["pcc_power_kwh"]) * 1000
        unshaded = float(clear.energy.annual["pcc_power_kwh"]) * 1000
        backend.metadata["shading_energy_counterfactual"] = {
            "method_id": "s16.same_run_inputs_geometric_visibility_forced_clear.v0.1",
            "scope": "geometric_near_shading_only",
            "actual_pcc_energy_wh": actual,
            "counterfactual_pcc_energy_wh": unshaded,
            "shading_energy_loss_wh": unshaded - actual,
            "electrical_mismatch_included": False,
            "same_weather": True,
            "same_design": True,
            "same_optical_iam_models": True,
            "same_thermal_model": True,
            "same_electrical_model": True,
            "same_non_shading_losses": True,
        }
    if plan.get("mixed_orientation") and "shading_energy_counterfactual" in backend.metadata:
        backend.metadata["shading_energy_counterfactual"].update(
            electrical_mismatch_included=True,
            electrical_mismatch_basis="orientation_class_coupling_only",
            module_level_shading_mismatch_included=False,
        )
    standard = build_standard_timeseries(backend)
    reference = persist_parquet_result(
        standard, output_directory=output_path, simulation_run_id=simulation_run_id
    )
    summary = build_summary_result(
        backend,
        simulation_run_id=simulation_run_id,
        data_quality_summary={
            "status": qc["status"],
            "finding_counts": qc["finding_counts"],
            "solar_aware": True,
        },
    )
    summary["execution_breakdown"] = _breakdown(
        backend, electrical, output_path, simulation_run_id
    )
    _assert_breakdown_totals(summary)
    annual = None
    if receiver_ref is not None:
        annual = build_annual_shading_result(
            compiled_geometry=compiled,
            execution_group_plan=plan,
            shading_configuration=shading,
            shading_runtime=backend.metadata["shading_runtime"],
            dataset_reference=receiver_ref,
        )
        c._assert_output_schema(annual, "geometry/shading/shading-result.schema.json")
        c._assert_output_schema(receiver_ref, "result-dataset-reference.schema.json")
    c._assert_output_schema(summary, "summary-result.schema.json")
    c._assert_output_schema(reference, "result-dataset-reference.schema.json")
    if simulation_configuration.get("numerical_options", {}).get("optics_thermal_settings") is not None:
        from .optics_thermal import run_optics_snapshot
        backend.metadata["resolved_optics_thermal_settings"] = run_optics_snapshot(simulation_configuration, scene, electrical, revision_store.component_revisions)
    return c._persist_completed_execution(
        project_revision=project_revision,
        simulation_configuration=simulation_configuration,
        project_revision_id=project_revision_id,
        simulation_run_id=simulation_run_id,
        engine_version=engine_version,
        now=now,
        backend=backend,
        topology={"execution_group_plan": plan,
        "circuit_loss_resolution": circuit_resolution, "shading_execution_mode": mode},
        model_resolution=None,
        component_manifest=manifest,
        selected_weather=selected,
        weather_qc=qc,
        findings=findings,
        assumptions=assumptions,
        input_hashes=hashes,
        result_reference=reference,
        shading_receiver_factor_reference=receiver_ref,
        annual_shading_result=annual,
        resolved_numerical_options={
            **(simulation_configuration.get("numerical_options") or {}),
            "execution_groups": {
                gid: {
                    "albedo": v["config"].albedo,
                    "module_runtime_resolution": backend.groups[
                        gid
                    ].dc.module_runtime.metadata,
                }
                for gid, v in bindings.items()
            },
        },
        summary=summary,
        standard_timeseries=standard,
        output_path=output_path,
        design_validation_evidence=design_validation_evidence,
    )


def _assert_breakdown_totals(summary: Mapping[str, Any]) -> None:
    breakdown = summary["execution_breakdown"]
    rows = breakdown["inverters"]
    if "plant_adjustments" in breakdown:
        adjustments = breakdown["plant_adjustments"]
        total = sum(row["total_energy_wh"] for row in rows) - sum(adjustments.values())
        if not np.isclose(total, summary["total_energy_wh"], rtol=1e-9, atol=1e-6):
            raise RuntimeError(
                "inverter subtotal minus plant adjustments does not reconcile"
            )
        for loss in summary["loss_summary"]:
            kind = loss["loss_type"]
            expected = (
                adjustments[kind]
                if kind in adjustments
                else sum(
                    next((x["lost_energy_wh"] for x in row["loss_summary"] if x["loss_type"] == kind),
                         0. if kind == "orientation_mismatch" else float("nan"))
                    for row in rows
                )
            )
            if not np.isclose(expected, loss["lost_energy_wh"], rtol=1e-9, atol=1e-6):
                raise RuntimeError("per-inverter and plant loss types do not reconcile")
        return
    for key in ("total_energy_wh", "clipping_energy_wh"):
        if not np.isclose(
            sum(r[key] for r in rows), summary[key], rtol=1e-9, atol=1e-6
        ):
            raise RuntimeError(
                f"per-inverter {key} does not reconcile with plant total"
            )
    for loss in summary["loss_summary"]:
        total = sum(
            next((x["lost_energy_wh"] for x in row["loss_summary"] if x["loss_type"] == loss["loss_type"]),
                 0. if loss["loss_type"] == "orientation_mismatch" else float("nan"))
            for row in rows
        )
        if not np.isclose(total, loss["lost_energy_wh"], rtol=1e-9, atol=1e-6):
            raise RuntimeError("per-inverter loss waterfall does not reconcile")


def _failed(
    c: ModuleType,
    project: dict[str, Any],
    config: dict[str, Any],
    run_id: str,
    version: str,
    now: str,
    findings: list[dict[str, Any]],
    assumptions: list[dict[str, Any]],
    manifest: dict[str, Any],
    hashes: dict[str, str],
    path: Path,
    evidence: dict[str, Any] | None,
) -> CanonicalSimulationExecutionResult:
    from .artifacts import persist_run_package

    run = c._failed_run(
        simulation_run_id=run_id,
        project_revision=project,
        simulation_configuration=config,
        engine_version=version,
        timestamp=now,
        findings=findings,
        assumptions=assumptions,
        model_resolution=None,
        component_manifest=manifest,
        input_hash=hashes["combined_input_sha256"],
        design_validation_evidence=evidence,
    )
    c._assert_output_schema(run, "simulation-run.schema.json")
    folder = persist_run_package(
        output_directory=path,
        simulation_run_id=run_id,
        simulation_run=run,
        summary_result=None,
        reproducibility_manifest=None,
        validation_findings=findings,
        model_resolution=None,
    )
    return c.CanonicalSimulationExecutionResult(run, None, None, None, folder)
