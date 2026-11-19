"""Explanatory independent-module counterfactuals; never an execution producer.

Only existing region/branch/module and series-IV solvers evaluate physics. The
bypass-off adapter exposes a bounded unprotected module V(I), not a new reverse
or shading model. A complete positive-generation domain is required to claim N.
"""
from math import fsum

from .module_series_adapter import build_phase66_series_module_operating_model
from .parameterization import build_pvsyst_region_electrical_states
from .string_iv import SeriesModuleOperatingModel, assemble_general_series_string_iv
from .substring_reference import (solve_parallel_branches_at_current,
    evaluate_series_branch_voltage, _branch_current_ceiling, _branch_current_at_voltage,
    _BranchEndpointHolder, _branch_ceiling_with_reuse, _branch_end_with_reuse)
from engine.simulation.artifacts import canonical_object_sha256

MODEL_ID = "rawibumi.phase69b.detailed_dc_attribution.v0.1"
MODEL_VERSION = "0.1"
POWER_ABS_W = 1e-7
POWER_REL = 1e-9
VOLTAGE_TOL_V = 1e-9
CURRENT_TOL_A = 1e-9
MAX_ITERATIONS = 200


class BypassOffUnavailable(ValueError):
    def __init__(self, reason_code, detail):
        self.reason_code = reason_code
        super().__init__(detail)


def basis(power=None, *, status="available", reasons=()):
    return {"status": status, "power_w": power, "reason_codes": list(reasons)}


def uniform_effective_input(region_map, actual):
    """An explicitly named projection, never a forged actual irradiance state.

    Uniformize effective irradiance only, after geometry/IAM. Preserve actual
    module temperature. Neither geometry nor thermal physics is rerun.
    """
    areas = {r["region_id"]: r["area_m2"] for r in region_map["regions"]}
    mean = fsum(areas[r["region_id"]] * r["effective_irradiance_w_m2"]
                for r in actual["regions"]) / fsum(areas.values())
    return {"schema_name": "UniformRegionalEffectiveIrradianceCounterfactual",
        "source_electrical_region_map_id": actual["source_electrical_region_map_id"],
        "source_electrical_region_map_hash": actual["source_electrical_region_map_hash"],
        "source_actual_local_state_sha256": actual["state_payload_sha256"],
        "source_module_instance_id": actual["source_module_instance_id"],
        "module_temperature_c": actual["module_temperature_c"],
        "uniform_effective_irradiance_w_m2": mean,
        "regions": [{"region_id": r["region_id"], "effective_irradiance_w_m2": mean}
                    for r in actual["regions"]]}


def build_bypass_off_module_model(pinned, region_map, local, *, region_solver="lambertw", authorization_witness=None, lifecycle_sink=None):
    if lifecycle_sink is not None:
        from .branch_memo_lifecycle import validate_lifecycle_sink
        validate_lifecycle_sink(lifecycle_sink)

    states = build_pvsyst_region_electrical_states(pinned["topology"], region_map,
        local, pinned["parameterization"], pinned["evidence"], solver=region_solver, authorization_witness=authorization_witness)
    substrings = sorted(pinned["topology"]["electrical_substrings"], key=lambda s: s["series_order"])
    branch_reuse = _BranchEndpointHolder(
        [branch for substring in substrings for branch in substring["parallel_branches"]], states)
    if lifecycle_sink is not None:
        lifecycle_token = lifecycle_sink.holder_created(
            factory_role="bypass_off", slot_count=len(branch_reuse._slots),
        )

    def branch_endpoint(branch):
        slot = branch_reuse.bind(branch, states)
        ceiling = _branch_ceiling_with_reuse(branch, states, slot, evaluator=_branch_current_ceiling)
        return _branch_end_with_reuse(branch, states, ceiling, slot, evaluator=evaluate_series_branch_voltage)

    supported = []
    for substring in substrings:
        branches = substring["parallel_branches"]
        # Same common-voltage intersection used by the validated Phase 6.5
        # branch solver. The weakest common endpoint bounds the whole group.
        low_v = max(branch_endpoint(b) for b in branches)
        supported.append(fsum(_branch_current_at_voltage(b, states, voltage_v=low_v,
            voltage_tolerance_v=VOLTAGE_TOL_V, current_tolerance_a=CURRENT_TOL_A,
            max_iterations=MAX_ITERATIONS, _reuse=branch_reuse) for b in branches))
    ceiling = min(supported)

    def voltage_at_current(current):
        if current < 0 or current > ceiling + CURRENT_TOL_A:
            raise BypassOffUnavailable("bypass_off_domain_unsupported", "current outside supported common branch domain")
        resolved = []
        for substring in substrings:
            solved = solve_parallel_branches_at_current(substring["parallel_branches"], states,
                total_current_a=current, voltage_tolerance_v=VOLTAGE_TOL_V,
                current_tolerance_a=CURRENT_TOL_A, max_iterations=MAX_ITERATIONS, _reuse=branch_reuse)
            resolved.append({"substring_id": substring["substring_id"],
                "terminal_voltage_v": solved["common_voltage_v"],
                "bypass_active": False, "bypass_current_a": 0.})
        return {"terminal_voltage_v": fsum(s["terminal_voltage_v"] for s in resolved),
                "protected_substrings": resolved}

    if ceiling <= 0 or voltage_at_current(ceiling)["terminal_voltage_v"] > VOLTAGE_TOL_V:
        raise BypassOffUnavailable("bypass_off_positive_power_domain_not_covered",
            "validated unprotected branch domains do not reach module V=0; no global MPP claim is possible")
    identity = canonical_object_sha256({"model_id": MODEL_ID, "basis": "N",
        "parameterization": pinned["parameterization"], "topology": pinned["topology"],
        "actual_local_state": local, "region_solver": region_solver,
        "common_current_ceiling_a": ceiling})
    model = SeriesModuleOperatingModel(region_map["source_module_instance_id"], ceiling,
        identity, MODEL_ID + ".bypass_off", MODEL_VERSION, voltage_at_current)
    if lifecycle_sink is not None:
        lifecycle_sink.owner_returned(*lifecycle_token)
    return model


def optimize_independent_module(model, *, sample_count):
    # Solver-only circuit: never a physical design string or a production IV.
    circuit = {"string_id": "counterfactual-independent:" + model.module_instance_id,
        "project_revision_id": "counterfactual-independent-module-optimization",
        "module_instance_ids": [model.module_instance_id], "polarity": "normal", "enabled": True}
    return assemble_general_series_string_iv(circuit, {model.module_instance_id: model},
        sample_count=sample_count, voltage_tolerance_v=VOLTAGE_TOL_V,
        current_tolerance_a=CURRENT_TOL_A, max_iterations=MAX_ITERATIONS).curve


def evaluate_independent_module_bases(pinned, diagnostic, *, sample_count, region_solver="lambertw", authorization_witness=None):
    from engine.simulation.detailed_inputs import SnapshotWitnessError, validate_regional_transport
    from shading.electrical.contract import NumericalAssumptionInputError
    validate_regional_transport(authorization_witness, pinned["topology"], pinned["parameterization"], pinned["evidence"])
    local, region_map = diagnostic["local_irradiance"], diagnostic["region_map"]
    if all(r["effective_irradiance_w_m2"] == 0 for r in local["regions"]):
        return {k: basis(status="not_applicable", reasons=["inactive_dark_no_photovoltaic_operating_point"])
                for k in "UNB"}, {}
    results, curves = {}, {}
    for name in "UNB":
        try:
            if name == "N":
                model = build_bypass_off_module_model(pinned, region_map, local, region_solver=region_solver, authorization_witness=authorization_witness)
            else:
                state = uniform_effective_input(region_map, local) if name == "U" else local
                model = build_phase66_series_module_operating_model(pinned["topology"], region_map,
                    state, pinned["parameterization"], pinned["evidence"], region_solver=region_solver, authorization_witness=authorization_witness)
            curve = optimize_independent_module(model, sample_count=sample_count)
            results[name] = basis(curve["global_mpp"]["power_w"])
            curves[name] = curve
        except BypassOffUnavailable as exc:
            results[name] = basis(status="unavailable", reasons=[exc.reason_code])
        except (NumericalAssumptionInputError, SnapshotWitnessError):
            raise
        except ValueError:
            # A bounded solver rejection does not turn into a partial-domain MPP
            # or zero. Actual physics has already completed independently.
            results[name] = basis(status="unavailable", reasons=[
                "bypass_off_domain_unsupported" if name == "N" else "independent_module_iv_unavailable"])
    return results, curves
