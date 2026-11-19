"""End-to-end unshaded fixed-tilt Phase-3 execution at an explicit cadence."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Callable, Mapping

import pandas as pd

from electrical.mppt import MPPTAggregationResult, aggregate_mppt_bank
from engine.inverter import INVERTER_VOLTAGE_DEPENDENT
from electrical.string import StringElectricalResult, build_identical_string_bank
from engine.irradiance import (
    IrradianceCompletionResult,
    PerezCoefficientSet,
    PlaneOfArrayResult,
    calculate_poa,
    complete_irradiance,
)
from engine.losses import (
    ElectricalLossChainResult,
    EnergyAggregationResult,
    aggregate_interval_quantities,
    calculate_pv_kpis,
    simulate_electrical_loss_chain,
)
from engine.module import (
    CoupledModuleThermalResult,
    extract_validated_pvsyst_parameter_set,
    solve_pvsyst_module_thermal_coupling,
)
from engine.optical import (
    IAM_NONE,
    IAM_TABULATED,
    OpticalResult,
    TabulatedIAMProfile,
    apply_iam,
)
from engine.solar import SolarPositionResult, solar_position_from_weather
from engine.thermal import THERMAL_PVSYST
from weather.core import CanonicalWeather

from .temporal import TemporalExecutionContext, prepare_temporal_execution


@dataclass(frozen=True, kw_only=True)
class UnshadedFixedTiltConfiguration:
    """Explicit runtime inputs for the current Phase-3 reference scope."""

    simulation_timestep_seconds: int
    surface_tilt_deg: float
    surface_azimuth_deg: float
    poa_model_id: str
    module_definition: dict[str, Any]
    inverter_definition: dict[str, Any]
    modules_in_series: int
    string_ids: tuple[str, ...]
    mppt_assignments: Mapping[int, tuple[str, ...] | list[str]]
    u_c_w_m2k: float
    u_v_w_m2k_per_ms: float
    alpha_absorption: float | None = None
    thermal_model_id: str = THERMAL_PVSYST

    albedo: float = 0.20
    decomposition_model_id: str | None = None
    perez_model: str = "allsitescomposite1990"
    pvsyst81_perez_coefficient_set: PerezCoefficientSet | None = None
    allow_unverified_pvsyst81_perez_coefficients: bool = False
    iam_model_id: str | None = None
    iam_profile: TabulatedIAMProfile | None = None

    module_quality_loss_fraction: float | None = None
    module_mismatch_loss_fraction: float = 0.0
    string_mismatch_loss_fraction: float = 0.0
    dc_array_resistance_ohm: float = 0.0
    loss_settings: dict[str, Any] | None = None
    circuit_loss_resolution: dict[str, Any] | None = None
    inverter_instance_id: str | None = None
    inverter_model_id: str = INVERTER_VOLTAGE_DEPENDENT
    optics_thermal_settings: dict[str, Any] | None = None

    solar_delta_t_seconds: float | None = None
    initial_module_efficiency_fraction: float = 0.0
    temperature_tolerance_c: float = 1e-4
    efficiency_tolerance_fraction: float = 1e-8
    max_coupling_iterations: int = 25
    coupling_relaxation_factor: float = 1.0
    module_solver: str = "lambertw"


@dataclass(frozen=True)
class ResolvedModuleRuntimeInputs:
    """Component-derived runtime defaults after explicit override resolution."""

    alpha_absorption: float
    iam_model_id: str
    iam_profile: TabulatedIAMProfile | None
    module_quality_loss_fraction: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class FixedTiltPOAPostprocessResult:
    """Optional POA transformation inserted after transposition and before IAM."""

    poa: PlaneOfArrayResult
    metadata: dict[str, Any]
    receiver_factors: pd.DataFrame | None = None


@dataclass(frozen=True)
class UnshadedFixedTiltSimulationResult:
    temporal: TemporalExecutionContext
    solar: SolarPositionResult
    irradiance: IrradianceCompletionResult
    poa: PlaneOfArrayResult
    optical: OpticalResult
    coupled_module: CoupledModuleThermalResult
    string_bank: dict[str, StringElectricalResult]
    mppt_bank: dict[int, MPPTAggregationResult]
    electrical: ElectricalLossChainResult
    timeseries: pd.DataFrame
    energy: EnergyAggregationResult
    kpis: dict[str, float]
    metadata: dict[str, Any]
    shading_receiver_factors: pd.DataFrame | None = None


def resolve_module_runtime_inputs(
    module_definition: dict[str, Any],
    *,
    alpha_absorption: float | None = None,
    iam_model_id: str | None = None,
    iam_profile: TabulatedIAMProfile | None = None,
    module_quality_loss_fraction: float | None = None,
) -> ResolvedModuleRuntimeInputs:
    """Resolve module optical/quality behavior with explicit overrides first.

    Resolution order is explicit runtime override, then canonical ModuleDefinition
    behavior, then a documented generic fallback where the selected model permits it.

    A supplied IAM profile without an explicit IAM model ID is rejected because it
    would be ambiguous whether the caller intended to override component IAM behavior.
    """
    optical = module_definition.get("optical") or {}
    quality = module_definition.get("quality") or {}

    if alpha_absorption is not None:
        resolved_alpha = float(alpha_absorption)
        alpha_source = "configuration_override"
    elif optical.get("absorptance_fraction") is not None:
        resolved_alpha = float(optical["absorptance_fraction"])
        alpha_source = "module_definition.optical.absorptance_fraction"
    else:
        resolved_alpha = 0.90
        alpha_source = "documented_generic_default_0.90"

    if not isfinite(resolved_alpha) or not 0.0 < resolved_alpha <= 1.0:
        raise ValueError("resolved module absorptance must be finite and within (0, 1]")

    if iam_profile is not None and iam_model_id is None:
        raise ValueError(
            "iam_profile requires an explicit iam_model_id when overriding "
            "component IAM behavior"
        )

    if iam_model_id is not None:
        resolved_iam_model_id = iam_model_id
        resolved_iam_profile = iam_profile
        iam_source = "configuration_override"
    else:
        component_iam = optical.get("iam")
        if component_iam is None:
            resolved_iam_model_id = IAM_NONE
            resolved_iam_profile = None
            iam_source = "no_component_iam"
        elif not isinstance(component_iam, dict):
            raise ValueError("module optical.iam must be an object when present")
        else:
            execution_model_id = component_iam.get("execution_model_id")
            model_type = component_iam.get("model_type")
            if model_type != "tabulated" or execution_model_id != IAM_TABULATED:
                raise ValueError(
                    "module optical IAM is present but is not executable by the "
                    "Phase-3 tabulated IAM runtime"
                )
            points = component_iam.get("points") or []
            resolved_iam_profile = TabulatedIAMProfile.from_points(
                [(point["angle_deg"], point["modifier"]) for point in points],
                interpolation_method=component_iam.get(
                    "interpolation_method", "linear"
                ),
                normalize=bool(component_iam.get("normalize", True)),
            )
            resolved_iam_model_id = IAM_TABULATED
            iam_source = "module_definition.optical.iam"

    if module_quality_loss_fraction is not None:
        resolved_quality = float(module_quality_loss_fraction)
        quality_source = "configuration_override"
    elif quality.get("default_module_quality_loss_fraction") is not None:
        resolved_quality = float(
            quality["default_module_quality_loss_fraction"]
        )
        quality_source = (
            "module_definition.quality.default_module_quality_loss_fraction"
        )
    else:
        resolved_quality = 0.0
        quality_source = "generic_default_zero"

    if not isfinite(resolved_quality):
        raise ValueError("resolved module-quality loss fraction must be finite")

    metadata = {
        "alpha_absorption": {
            "value": resolved_alpha,
            "source": alpha_source,
        },
        "iam": {
            "model_id": resolved_iam_model_id,
            "source": iam_source,
            "profile_point_count": (
                len(resolved_iam_profile.theta_ref_deg)
                if resolved_iam_profile is not None
                else 0
            ),
            "interpolation_method": (
                resolved_iam_profile.interpolation_method
                if resolved_iam_profile is not None
                else None
            ),
        },
        "module_quality_loss_fraction": {
            "value": resolved_quality,
            "source": quality_source,
            "method": (
                quality.get("default_module_quality_method")
                if quality_source.startswith("module_definition.")
                else None
            ),
        },
    }

    return ResolvedModuleRuntimeInputs(
        alpha_absorption=resolved_alpha,
        iam_model_id=resolved_iam_model_id,
        iam_profile=resolved_iam_profile,
        module_quality_loss_fraction=resolved_quality,
        metadata=metadata,
    )


def _module_runtime_properties(
    module_definition: dict[str, Any],
) -> tuple[dict[str, Any], float, float, float | None]:
    params = extract_validated_pvsyst_parameter_set(module_definition)

    mechanical = module_definition.get("mechanical") or {}
    width = mechanical.get("width_m")
    height = mechanical.get("height_m")
    if width is None or height is None:
        raise ValueError("module definition requires width_m and height_m")
    area = float(width) * float(height)
    if not isfinite(area) or area <= 0:
        raise ValueError("module mechanical area must be finite and positive")

    mass = mechanical.get("mass_kg")
    if mass is None:
        unit_mass = None
    else:
        mass_value = float(mass)
        if not isfinite(mass_value) or mass_value <= 0:
            raise ValueError("module mechanical mass_kg must be finite and positive")
        unit_mass = mass_value / area

    stc = module_definition.get("stc") or {}
    nominal = stc.get("nominal_power_w")
    if nominal is None:
        nominal = stc.get("pmp_w")
    if nominal is None or not isfinite(float(nominal)) or float(nominal) <= 0:
        raise ValueError("module definition requires positive STC nominal power")

    return params, area, float(nominal), unit_mass


def _uniform_mppt_contract(
    inverter_definition: dict[str, Any],
) -> tuple[int, int | None, int | None, float | None, float | None, float | None]:
    """Return the current uniform-template MPPT contract.

    The Phase-3 unshaded runner intentionally uses the canonical uniform
    mppt_template path. Heterogeneous per-tracker definitions require a future
    topology-specific runtime rather than flattening them into one template.
    """
    if inverter_definition.get("mppts"):
        raise ValueError(
            "Phase-3 unshaded runner does not flatten explicit heterogeneous "
            "MPPT definitions; use a topology-specific runtime"
        )

    template = inverter_definition.get("mppt_template")
    if not isinstance(template, dict):
        raise ValueError("inverter definition requires mppt_template")

    count = int(template.get("count") or 0)
    if count < 1:
        raise ValueError("inverter mppt_template requires count >= 1")

    total_inputs = template.get("total_input_count")
    total_inputs = int(total_inputs) if total_inputs is not None else None

    per_mppt = template.get("input_count_per_mppt")
    per_mppt = int(per_mppt) if per_mppt is not None else None

    min_v = template.get("min_operating_voltage_v")
    max_v = template.get("max_operating_voltage_v")
    max_i = template.get("max_operating_current_a")

    return (
        count,
        total_inputs,
        per_mppt,
        float(min_v) if min_v is not None else None,
        float(max_v) if max_v is not None else None,
        float(max_i) if max_i is not None else None,
    )


def _assemble_timeseries(
    result_frames: list[pd.DataFrame],
    *,
    base_index: pd.DatetimeIndex,
) -> pd.DataFrame:
    """Merge stage outputs once while refusing conflicting duplicate values."""
    selected: dict[str, pd.Series] = {}

    for frame in result_frames:
        if not frame.index.equals(base_index):
            raise ValueError("simulation stage intervals do not align exactly")
        for column in frame.columns:
            values = frame[column]
            previous = selected.get(str(column))
            if previous is not None:
                if not previous.equals(values):
                    raise ValueError(
                        f"stage output column {column!r} conflicts with an earlier stage"
                    )
                continue
            selected[str(column)] = values

    output = pd.DataFrame(
        {
            column: values.to_numpy()
            for column, values in selected.items()
        },
        index=base_index.copy(),
    )
    output.index.name = "interval_start"
    return output


@dataclass(frozen=True)
class FixedTiltExecutionContext:
    temporal: TemporalExecutionContext
    solar: SolarPositionResult
    irradiance: IrradianceCompletionResult


@dataclass(frozen=True)
class FixedTiltClassDC:
    poa: PlaneOfArrayResult
    optical: OpticalResult
    coupled_module: CoupledModuleThermalResult
    module_runtime: ResolvedModuleRuntimeInputs
    module_area_m2: float
    module_nominal_power_w: float
    module_unit_mass_kg_m2: float | None
    poa_postprocess: FixedTiltPOAPostprocessResult | None


@dataclass(frozen=True)
class FixedTiltGroupDC:
    poa: PlaneOfArrayResult
    optical: OpticalResult
    coupled_module: CoupledModuleThermalResult
    string_bank: dict[str, StringElectricalResult]
    module_runtime: ResolvedModuleRuntimeInputs
    module_area_m2: float
    module_nominal_power_w: float
    module_unit_mass_kg_m2: float | None
    poa_postprocess: FixedTiltPOAPostprocessResult | None


def prepare_fixed_tilt_context(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
) -> FixedTiltExecutionContext:
    """Prepare common temporal, solar and irradiance inputs without a group solve."""
    temporal = prepare_temporal_execution(
        weather,
        simulation_timestep_seconds=config.simulation_timestep_seconds,
    )
    working_weather = temporal.weather
    timeline = temporal.timeline

    solar = solar_position_from_weather(
        working_weather,
        timeline=timeline,
        delta_t_seconds=config.solar_delta_t_seconds,
    )
    irradiance = complete_irradiance(
        working_weather,
        solar,
        decomposition_model_id=config.decomposition_model_id,
    )
    return FixedTiltExecutionContext(temporal, solar, irradiance)


def run_fixed_tilt_class_dc(
    context: FixedTiltExecutionContext,
    *,
    config: UnshadedFixedTiltConfiguration,
    poa_postprocessor: Callable[
        [PlaneOfArrayResult, SolarPositionResult, TemporalExecutionContext],
        FixedTiltPOAPostprocessResult,
    ] | None = None,
) -> FixedTiltClassDC:
    """Run the unchanged POA-to-module stages for one optical class."""
    temporal, solar, irradiance = context.temporal, context.solar, context.irradiance
    working_weather, timeline = temporal.weather, temporal.timeline
    from .optics_thermal import albedo_for_index
    poa = calculate_poa(
        irradiance,
        solar,
        surface_tilt_deg=float(config.surface_tilt_deg),
        surface_azimuth_deg=float(config.surface_azimuth_deg),
        albedo=albedo_for_index(config.optics_thermal_settings, working_weather.series.index) if config.optics_thermal_settings is not None else float(config.albedo),
        model_id=config.poa_model_id,
        model_perez=config.perez_model,
        simulation_timestep_seconds=int(config.simulation_timestep_seconds),
        pvsyst81_perez_coefficient_set=config.pvsyst81_perez_coefficient_set,
        allow_unverified_pvsyst81_coefficients=(
            config.allow_unverified_pvsyst81_perez_coefficients
        ),
    )
    if config.optics_thermal_settings is not None:
        from .optics_thermal import zero_horizontal_irradiance_limit
        poa = zero_horizontal_irradiance_limit(poa, irradiance)
    poa_postprocess = None
    if poa_postprocessor is not None:
        poa_postprocess = poa_postprocessor(poa, solar, temporal)
        if not isinstance(poa_postprocess, FixedTiltPOAPostprocessResult):
            raise TypeError(
                "poa_postprocessor must return FixedTiltPOAPostprocessResult"
            )
        if not poa_postprocess.poa.frame.index.equals(poa.frame.index):
            raise ValueError("POA postprocessor changed interval alignment")
        poa = poa_postprocess.poa

    module_runtime = resolve_module_runtime_inputs(
        config.module_definition,
        alpha_absorption=config.alpha_absorption,
        iam_model_id=config.iam_model_id,
        iam_profile=config.iam_profile,
        module_quality_loss_fraction=config.module_quality_loss_fraction,
    )
    optical = apply_iam(
        poa,
        model_id=module_runtime.iam_model_id,
        surface_tilt_deg=float(config.surface_tilt_deg),
        profile=module_runtime.iam_profile,
    )

    if config.loss_settings is not None:
        from engine.losses.soiling import apply_soiling
        optical = apply_soiling(optical, config.loss_settings)

    (
        parameter_set,
        module_area_m2,
        module_nominal_power_w,
        module_unit_mass_kg_m2,
    ) = _module_runtime_properties(config.module_definition)
    coupled = solve_pvsyst_module_thermal_coupling(
        poa,
        optical,
        working_weather,
        parameter_set=parameter_set,
        module_area_m2=module_area_m2,
        u_c_w_m2k=float(config.u_c_w_m2k),
        u_v_w_m2k_per_ms=float(config.u_v_w_m2k_per_ms),
        alpha_absorption=module_runtime.alpha_absorption,
        thermal_model_id=config.thermal_model_id,
        module_unit_mass_kg_m2=module_unit_mass_kg_m2,
        initial_module_efficiency_fraction=float(
            config.initial_module_efficiency_fraction
        ),
        temperature_tolerance_c=float(config.temperature_tolerance_c),
        efficiency_tolerance_fraction=float(
            config.efficiency_tolerance_fraction
        ),
        max_iterations=int(config.max_coupling_iterations),
        relaxation_factor=float(config.coupling_relaxation_factor),
        solver=config.module_solver,
        **({"thermal_irradiance_basis": config.optics_thermal_settings["values"]["thermal"]["irradiance_basis"]} if config.optics_thermal_settings is not None else {}),
    )

    return FixedTiltClassDC(
        poa, optical, coupled, module_runtime,
        module_area_m2, module_nominal_power_w, module_unit_mass_kg_m2,
        poa_postprocess,
    )


def run_fixed_tilt_group_dc(context, *, config, poa_postprocessor=None) -> FixedTiltGroupDC:
    dc = run_fixed_tilt_class_dc(context, config=config, poa_postprocessor=poa_postprocessor)
    if not config.string_ids:
        raise ValueError("string_ids must not be empty")
    strings = build_identical_string_bank(
        dc.coupled_module.electrical,
        string_ids=config.string_ids,
        modules_in_series=int(config.modules_in_series),
    )
    return FixedTiltGroupDC(dc.poa, dc.optical, dc.coupled_module, strings, dc.module_runtime,
                           dc.module_area_m2, dc.module_nominal_power_w, dc.module_unit_mass_kg_m2,
                           dc.poa_postprocess)


def assemble_fixed_tilt_timeseries(
    context: FixedTiltExecutionContext,
    group_dc: FixedTiltGroupDC,
    electrical_frame: pd.DataFrame,
) -> pd.DataFrame:
    """Assemble the existing group physics columns with explicit electrical channels."""
    temporal, solar, irradiance = context.temporal, context.solar, context.irradiance
    working_weather, timeline = temporal.weather, temporal.timeline
    poa, optical, coupled = group_dc.poa, group_dc.optical, group_dc.coupled_module
    weather_frame = working_weather.series.copy()
    # Completed components are authoritative simulation irradiance inputs, so do not
    # duplicate source DNI/DHI columns in the merged result.
    for column in ("dni_w_m2", "dhi_w_m2"):
        if column in weather_frame:
            weather_frame = weather_frame.drop(columns=[column])

    timeline_frame = timeline.frame[[
        "interval_end",
        "interval_midpoint",
        "evaluation_time",
        "duration_seconds",
    ]]
    solar_frame = solar.frame.drop(columns=["evaluation_time"])
    irradiance_frame = irradiance.frame[
        ["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]
    ].drop(columns=["ghi_w_m2"])
    poa_frame = poa.frame.drop(
        columns=[
            column
            for column in ("evaluation_time", "solar_elevation_deg")
            if column in poa.frame
        ]
    )
    optical_frame = optical.frame.drop(
        columns=[
            column
            for column in (
                "evaluation_time",
                "aoi_deg",
            )
            if column in optical.frame
        ]
    )
    thermal_columns = [
        "heat_input_w_m2",
        "heat_loss_coefficient_w_m2k",
        "temperature_rise_c",
        "cell_temperature_c",
        "module_temperature_c",
    ]
    thermal_columns.extend(
        column
        for column in (
            "steady_state_cell_temperature_c",
            "steady_state_module_temperature_c",
            "prilliman_interval_start_temperature_c",
            "prilliman_interval_end_temperature_c",
            "thermal_relaxation_rate_s_inv",
            "thermal_relaxation_time_s",
        )
        if column in coupled.thermal.frame
    )
    thermal_frame = coupled.thermal.frame[thermal_columns]
    module_frame = coupled.electrical.frame[
        [
            "isc_a",
            "voc_v",
            "imp_a",
            "vmp_v",
            "pmp_w",
            "module_efficiency_fraction",
            "active",
        ]
    ].rename(
        columns={
            "isc_a": "module_isc_a",
            "voc_v": "module_voc_v",
            "imp_a": "module_imp_a",
            "vmp_v": "module_vmp_v",
            "pmp_w": "module_pmp_w",
            "active": "module_active",
        }
    )
    electrical_frame = electrical_frame.drop(
        columns=[
            column
            for column in ("evaluation_time",)
            if column in electrical_frame
        ]
    )

    timeseries = _assemble_timeseries(
        [
            timeline_frame,
            weather_frame,
            solar_frame,
            irradiance_frame,
            poa_frame,
            optical_frame,
            thermal_frame,
            module_frame,
            electrical_frame,
            temporal.provenance,
        ],
        base_index=working_weather.series.index,
    )

    return timeseries


def aggregate_fixed_tilt_energy(
    timeseries: pd.DataFrame,
    power_columns_w: list[str] | tuple[str, ...],
    *,
    interval_seconds: float | pd.Series | None = None,
) -> EnergyAggregationResult:
    """Integrate existing power and irradiation channels with explicit durations."""
    electrical_power_columns = list(power_columns_w)
    irradiation_columns = [
        "ghi_w_m2",
        "poa_global_w_m2",
        "effective_irradiance_w_m2",
    ]
    for column in (
        "poa_global_unshaded_w_m2",
        "poa_beam_unshaded_w_m2",
        "poa_beam_shaded_w_m2",
        "near_shading_beam_loss_w_m2",
        "poa_sky_diffuse_unshaded_w_m2",
        "poa_sky_diffuse_shaded_w_m2",
        "near_shading_sky_diffuse_loss_w_m2",
        "poa_isotropic_unshaded_w_m2",
        "poa_isotropic_shaded_w_m2",
        "near_shading_isotropic_loss_w_m2",
        "poa_circumsolar_unshaded_w_m2",
        "poa_circumsolar_shaded_w_m2",
        "near_shading_circumsolar_loss_w_m2",
        "poa_horizon_unshaded_w_m2",
        "poa_horizon_shaded_w_m2",
        "near_shading_horizon_delta_w_m2",
        "poa_ground_diffuse_unshaded_w_m2",
        "poa_ground_diffuse_shaded_w_m2",
        "near_shading_ground_diffuse_loss_w_m2",
    ):
        if column in timeseries.columns:
            irradiation_columns.append(column)
    energy = aggregate_interval_quantities(
        timeseries,
        interval_seconds=(timeseries["duration_seconds"] if interval_seconds is None else interval_seconds),
        power_columns_w=electrical_power_columns,
        irradiance_columns_w_m2=irradiation_columns,
    )

    return energy


def _loss_chain_options(config: UnshadedFixedTiltConfiguration) -> dict[str, Any]:
    inverter_options = (
        {"inverter_model_id": config.inverter_model_id}
        if config.inverter_model_id != INVERTER_VOLTAGE_DEPENDENT else {}
    )
    if config.loss_settings is None:
        return inverter_options
    from engine.losses.settings import circuit_reference
    from engine.losses.settings import assert_compatible_wiring_modes
    assert_compatible_wiring_modes(per_circuit=True, global_resistance_ohm=config.dc_array_resistance_ohm)
    references = {key: circuit_reference(config.loss_settings, config.module_definition,
        modules_in_series=config.modules_in_series, parallel_strings=len(ids), mppt_index=key)
        for key, ids in config.mppt_assignments.items() if ids}
    from engine.losses.settings import circuit_execution_context
    context = circuit_execution_context(config.circuit_loss_resolution, config.inverter_instance_id)
    if context is not None:
        from copy import deepcopy
        for key, reference in references.items():
            resolved = context["circuits"][key]
            local = deepcopy(config.loss_settings)
            local["values"]["dc_wiring_stc_fraction"] = resolved["dc_wiring_stc_fraction"]
            reference.update(circuit_reference(local, config.module_definition,
                modules_in_series=config.modules_in_series,
                parallel_strings=len(config.mppt_assignments[key]), mppt_index=key))
            quality = set(resolved["module_quality_by_module"].values())
            if len(quality) != 1:
                raise ValueError(f"MPPT {resolved['mppt_instance_id']}: different module quality values require separate circuits")
            reference.update(mppt_instance_id=resolved["mppt_instance_id"],
                inverter_instance_id=resolved["inverter_instance_id"],
                dc_wiring_source=resolved["dc_wiring_source"],
                module_quality_fraction=quality.pop())
        return {"loss_settings": config.loss_settings, "circuit_references": references,
                "circuit_loss_context": context, **inverter_options}
    return {"loss_settings": config.loss_settings, "circuit_references": references, **inverter_options}


def _run_fixed_tilt(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
    poa_postprocessor: Callable[
        [PlaneOfArrayResult, SolarPositionResult, TemporalExecutionContext],
        FixedTiltPOAPostprocessResult,
    ] | None = None,
    execution_scope: str = "fixed_tilt_unshaded_identical_string_phase3",
) -> UnshadedFixedTiltSimulationResult:
    """Run the common fixed-tilt chain with an optional explicit POA transform.

    Resolution conversion occurs exactly once at the temporal-execution boundary.
    Every downstream stage consumes the resulting working interval index and the
    final energy integration uses the timeline's explicit duration_seconds.
    """
    context = prepare_fixed_tilt_context(weather, config=config)
    temporal, solar, irradiance = context.temporal, context.solar, context.irradiance
    working_weather, timeline = temporal.weather, temporal.timeline
    group_dc = run_fixed_tilt_group_dc(
        context, config=config, poa_postprocessor=poa_postprocessor,
    )
    poa, optical = group_dc.poa, group_dc.optical
    coupled, strings = group_dc.coupled_module, group_dc.string_bank
    module_runtime = group_dc.module_runtime
    module_area_m2 = group_dc.module_area_m2
    module_nominal_power_w = group_dc.module_nominal_power_w
    module_unit_mass_kg_m2 = group_dc.module_unit_mass_kg_m2
    poa_postprocess = group_dc.poa_postprocess

    (
        mppt_count,
        total_input_count,
        input_count_per_mppt,
        min_operating_voltage_v,
        max_operating_voltage_v,
        max_operating_current_a,
    ) = _uniform_mppt_contract(config.inverter_definition)

    mppts = aggregate_mppt_bank(
        strings,
        config.mppt_assignments,
        mppt_count=mppt_count,
        total_input_count=total_input_count,
        input_count_per_mppt=input_count_per_mppt,
        min_operating_voltage_v=min_operating_voltage_v,
        max_operating_voltage_v=max_operating_voltage_v,
        max_operating_current_a=max_operating_current_a,
    )

    electrical = simulate_electrical_loss_chain(
        mppts,
        config.inverter_definition,
        interval_seconds=timeline.frame["duration_seconds"],
        module_quality_loss_fraction=module_runtime.module_quality_loss_fraction,
        module_mismatch_loss_fraction=float(
            config.module_mismatch_loss_fraction
        ),
        string_mismatch_loss_fraction=float(
            config.string_mismatch_loss_fraction
        ),
        dc_array_resistance_ohm=float(config.dc_array_resistance_ohm),
        **_loss_chain_options(config),
    )
    if config.loss_settings is not None:
        from engine.losses.soiling import optical_reference_channels
        from engine.losses.staged import reconcile_loss_frame
        ledger_frame = electrical.ledger.frame.copy()
        capacity_w = module_nominal_power_w * config.modules_in_series * len(config.string_ids)
        for key, data in optical_reference_channels(optical, ledger_frame["raw_array_mpp_w"], capacity_w).items():
            ledger_frame[key] = data
        from dataclasses import replace
        electrical = replace(electrical, ledger=reconcile_loss_frame(
            ledger_frame, interval_seconds=timeline.frame["duration_seconds"],
            optical=True, settings=electrical.ledger.metadata["resolved_loss_settings"]))

    timeseries = assemble_fixed_tilt_timeseries(context, group_dc, electrical.ledger.frame)

    energy = aggregate_fixed_tilt_energy(
        timeseries, electrical.ledger.energy.metadata["power_columns_w"],
        interval_seconds=timeline.frame["duration_seconds"],
    )

    installed_dc_kwp = (
        module_nominal_power_w
        * int(config.modules_in_series)
        * len(config.string_ids)
        / 1000.0
    )
    if config.loss_settings is not None:
        electrical.ledger.metadata["resolved_loss_settings"]["simulated_dc_nameplate_w"] = installed_dc_kwp * 1000.0
    incident_poa_key = (
        "poa_global_unshaded_kwh_m2"
        if "poa_global_unshaded_kwh_m2" in energy.annual
        else "poa_global_kwh_m2"
    )
    kpis = calculate_pv_kpis(
        grid_energy_kwh=energy.annual["pcc_power_kwh"],
        installed_dc_kwp=installed_dc_kwp,
        incident_poa_kwh_m2=energy.annual[incident_poa_key],
    )

    model_manifest = {
        "solar_position": solar.metadata.get("model_id"),
        "irradiance_decomposition": config.decomposition_model_id,
        "poa_transposition": poa.metadata.get("model_id"),
        "iam": optical.metadata.get("model_id"),
        "thermal": coupled.thermal.metadata.get("model_id"),
        "module": coupled.electrical.metadata.get("model_id"),
        "string": next(iter(strings.values())).metadata.get("model_id"),
        "mppt": next(iter(mppts.values())).metadata.get("model_id"),
        "array_losses": electrical.array_losses.metadata.get("model_id"),
        "inverter": electrical.inverter.metadata.get("model_id"),
        "loss_ledger": electrical.ledger.metadata.get("model_id"),
        "energy_integration": energy.metadata.get("integration_method"),
        "near_shading": (
            poa_postprocess.metadata.get("model_id")
            if poa_postprocess is not None
            else "none"
        ),
    }

    metadata = {
        "schema_name": "UnshadedFixedTiltSimulationResult",
        "schema_version": "0.1",
        "scope": execution_scope,
        "simulation_timestep_seconds": config.simulation_timestep_seconds,
        "native_weather_resolution_seconds": temporal.metadata[
            "native_resolution_seconds"
        ],
        "weather_temporal_fidelity": temporal.metadata["temporal_fidelity"],
        "weather_false_precision_warning": temporal.metadata[
            "false_precision_warning"
        ],
        "module_definition_id": config.module_definition.get(
            "module_definition_id"
        ),
        "module_revision_id": config.module_definition.get("revision_id"),
        "module_unit_mass_kg_m2": module_unit_mass_kg_m2,
        "thermal_runtime": coupled.thermal.metadata,
        "inverter_definition_id": config.inverter_definition.get(
            "inverter_definition_id"
        ),
        "inverter_revision_id": config.inverter_definition.get("revision_id"),
        "installed_dc_kwp": installed_dc_kwp,
        "string_count": len(config.string_ids),
        "modules_in_series": int(config.modules_in_series),
        "module_count": len(config.string_ids) * int(config.modules_in_series),
        "model_manifest": model_manifest,
        "poa_runtime": poa.metadata,
        "module_runtime_resolution": module_runtime.metadata,
        "deterministic": True,
        "resolution_conversion_stage": "before_timeline_and_all_physics",
        "energy_duration_source": "timeline.duration_seconds",
        "pcc_boundary": electrical.ledger.metadata["pcc_boundary"],
        "shading_runtime": (
            {
                key: value
                for key, value in poa_postprocess.metadata.items()
                if key != "execution_telemetry"
            }
            if poa_postprocess is not None
            else None
        ),
        "execution_telemetry": (
            dict(poa_postprocess.metadata.get("execution_telemetry") or {})
            if poa_postprocess is not None
            else {}
        ),
        "electrical_shading_loss_quantified": False if poa_postprocess is not None else True,
    }

    return UnshadedFixedTiltSimulationResult(
        temporal=temporal,
        solar=solar,
        irradiance=irradiance,
        poa=poa,
        optical=optical,
        coupled_module=coupled,
        string_bank=strings,
        mppt_bank=mppts,
        electrical=electrical,
        timeseries=timeseries,
        energy=energy,
        kpis=kpis,
        metadata=metadata,
        shading_receiver_factors=(
            poa_postprocess.receiver_factors
            if poa_postprocess is not None
            else None
        ),
    )


def run_unshaded_fixed_tilt(
    weather: CanonicalWeather,
    *,
    config: UnshadedFixedTiltConfiguration,
) -> UnshadedFixedTiltSimulationResult:
    """Run the unchanged unshaded fixed-tilt reference chain."""
    return _run_fixed_tilt(
        weather,
        config=config,
        poa_postprocessor=None,
        execution_scope="fixed_tilt_unshaded_identical_string_phase3",
    )
