"""Phase-5.10 analytical and external shading-validation helpers.

This module does not implement or tune shading physics.  It defines the
comparison contract used to decompose analytical, controlled synthetic, and
PVsyst VC0-VC5 evidence without treating PVsyst as OpenSIMPV's equation
definition.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Mapping

import yaml


VALIDATION_HIERARCHY = {
    "A": "analytical_geometry_truth",
    "B": "controlled_synthetic_opensimpv",
    "C": "independent_open_implementation",
    "D": "external_cross_software",
    "E": "regression_only",
}

PVSYST_REQUIRED_CHANNELS = (
    "beam_shading_loss_kwh_m2",
    "circumsolar_shading_loss_kwh_m2",
    "diffuse_shading_loss_kwh_m2",
    "albedo_shading_loss_kwh_m2",
)

EXTERNAL_COMPARISON_REQUIRED_MATCHES = (
    "weather",
    "scene_geometry",
    "simulation_timestep",
    "solar_time_semantics",
    "pre_shading_irradiance",
    "channel_semantics",
)


class Phase510ValidationError(ValueError):
    """Raised when a Phase-5.10 comparison would be scientifically ambiguous."""


@dataclass(frozen=True)
class ExternalComparisonContext:
    """Declare whether an external comparison is on a compatible basis."""

    weather: bool
    scene_geometry: bool
    simulation_timestep: bool
    solar_time_semantics: bool
    pre_shading_irradiance: bool
    channel_semantics: bool

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ExternalComparisonContext":
        missing = [
            field for field in EXTERNAL_COMPARISON_REQUIRED_MATCHES if field not in value
        ]
        if missing:
            raise Phase510ValidationError(
                "external comparison context is missing: " + ", ".join(missing)
            )
        return cls(
            **{
                field: bool(value[field])
                for field in EXTERNAL_COMPARISON_REQUIRED_MATCHES
            }
        )

    @property
    def fully_matched(self) -> bool:
        return all(getattr(self, field) for field in EXTERNAL_COMPARISON_REQUIRED_MATCHES)

    def mismatches(self) -> list[str]:
        return [
            field
            for field in EXTERNAL_COMPARISON_REQUIRED_MATCHES
            if not getattr(self, field)
        ]


def load_pvsyst_vc_oracle(path: str | Path) -> dict[str, Any]:
    """Load and minimally validate the frozen Phase-4.9B VC0-VC5 oracle."""
    value = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if value.get("oracle_id") != "P49B-SHADED-PVSYST816-20260924":
        raise Phase510ValidationError("unexpected external shaded oracle identity")
    cases = value.get("cases")
    if not isinstance(cases, Mapping) or set(cases) != {
        "VC0", "VC1", "VC2", "VC3", "VC4", "VC5"
    }:
        raise Phase510ValidationError("external oracle must contain VC0 through VC5")
    return value


def _finite(value: Any, *, field: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise Phase510ValidationError(f"{field} must be finite")
    return number


def reconcile_pvsyst_case(
    case_id: str,
    case: Mapping[str, Any],
    *,
    tolerance_kwh_m2: float = 1e-3,
) -> dict[str, Any]:
    """Reconcile the frozen PVsyst channel decomposition to total shading loss."""
    annual = case.get("annual") or {}
    components = {
        field: _finite(annual.get(field), field=f"{case_id}.{field}")
        for field in PVSYST_REQUIRED_CHANNELS
    }
    total = _finite(
        annual.get("shading_loss_kwh_m2"),
        field=f"{case_id}.shading_loss_kwh_m2",
    )
    component_sum = sum(components.values())
    residual = component_sum - total
    return {
        "case_id": case_id,
        "label": str(case.get("label") or ""),
        "authority_class": "D",
        "component_sum_kwh_m2": component_sum,
        "reported_total_kwh_m2": total,
        "component_reconciliation_residual_kwh_m2": residual,
        "component_reconciliation_pass": abs(residual) <= tolerance_kwh_m2,
        "channels": components,
        "e_grid_kwh": _finite(
            annual.get("e_grid_kwh"),
            field=f"{case_id}.e_grid_kwh",
        ),
    }


def build_external_oracle_evidence(oracle: Mapping[str, Any]) -> dict[str, Any]:
    """Build deterministic source-side evidence without claiming OpenSIMPV parity."""
    cases = {
        case_id: reconcile_pvsyst_case(case_id, case)
        for case_id, case in sorted(oracle["cases"].items())
    }

    vc2 = oracle["cases"]["VC2"]["directional_signature"]
    vc3 = oracle["cases"]["VC3"]["directional_signature"]
    east_morning = float(vc2["beam_plus_circ_morning_kwh_m2"])
    east_afternoon = float(vc2["beam_plus_circ_afternoon_kwh_m2"])
    west_morning = float(vc3["beam_plus_circ_morning_kwh_m2"])
    west_afternoon = float(vc3["beam_plus_circ_afternoon_kwh_m2"])

    vc4 = float(oracle["cases"]["VC4"]["annual"]["shading_loss_kwh_m2"])
    vc2_total = float(oracle["cases"]["VC2"]["annual"]["shading_loss_kwh_m2"])
    vc3_total = float(oracle["cases"]["VC3"]["annual"]["shading_loss_kwh_m2"])
    vc5 = float(oracle["cases"]["VC5"]["annual"]["shading_loss_kwh_m2"])
    vc0_total = float(oracle["cases"]["VC0"]["annual"]["shading_loss_kwh_m2"])
    vc1_total = float(oracle["cases"]["VC1"]["annual"]["shading_loss_kwh_m2"])

    return {
        "schema_name": "Phase510ExternalOracleEvidence",
        "schema_version": "0.1",
        "oracle_id": oracle["oracle_id"],
        "authority_class": "D",
        "cases": cases,
        "directional_signatures": {
            "VC2_east_morning_dominant": east_morning > east_afternoon,
            "VC3_west_afternoon_dominant": west_afternoon > west_morning,
            "VC2_morning_kwh_m2": east_morning,
            "VC2_afternoon_kwh_m2": east_afternoon,
            "VC3_morning_kwh_m2": west_morning,
            "VC3_afternoon_kwh_m2": west_afternoon,
        },
        "combined_case_nonadditivity": {
            "VC4_east_west_reported_kwh_m2": vc4,
            "VC2_plus_VC3_kwh_m2": vc2_total + vc3_total,
            "VC4_is_not_simple_sum": not math.isclose(
                vc4, vc2_total + vc3_total, rel_tol=0.0, abs_tol=1e-9
            ),
            "VC5_north_south_reported_kwh_m2": vc5,
            "VC0_plus_VC1_kwh_m2": vc0_total + vc1_total,
            "VC5_is_not_simple_sum": not math.isclose(
                vc5, vc0_total + vc1_total, rel_tol=0.0, abs_tol=1e-9
            ),
        },
        "source_reconciliation_pass": all(
            item["component_reconciliation_pass"] for item in cases.values()
        ),
        "interpretation": (
            "This validates the frozen external oracle's internal decomposition "
            "and directional evidence only. It is not an OpenSIMPV-vs-PVsyst "
            "numerical agreement claim."
        ),
    }


def compare_external_case(
    *,
    case_id: str,
    opensimpv: Mapping[str, Any],
    pvsyst_case: Mapping[str, Any],
    context: ExternalComparisonContext | Mapping[str, Any],
) -> dict[str, Any]:
    """Compare one OpenSIMPV result with one external case on an explicit basis.

    A quantitative residual is emitted only for fields with aligned semantics
    and only when all comparison-basis declarations are true.
    """
    if not isinstance(context, ExternalComparisonContext):
        context = ExternalComparisonContext.from_mapping(context)

    if not context.fully_matched:
        return {
            "case_id": case_id,
            "status": "not_quantitatively_comparable",
            "authority_class": "D",
            "basis_mismatches": context.mismatches(),
            "residuals": {},
            "interpretation": (
                "No quantitative agreement verdict is permitted because the "
                "comparison basis is not fully matched."
            ),
        }

    annual = pvsyst_case["annual"]
    mapping = {
        "beam_shading_loss_kwh_m2": "beam_shading_loss_kwh_m2",
        "circumsolar_shading_loss_kwh_m2": "circumsolar_shading_loss_kwh_m2",
        "diffuse_shading_loss_kwh_m2": "diffuse_shading_loss_kwh_m2",
        "albedo_shading_loss_kwh_m2": "albedo_shading_loss_kwh_m2",
        "shading_loss_kwh_m2": "shading_loss_kwh_m2",
    }
    residuals: dict[str, dict[str, float]] = {}
    for open_field, external_field in mapping.items():
        if open_field not in opensimpv:
            continue
        open_value = _finite(opensimpv[open_field], field=open_field)
        external_value = _finite(annual[external_field], field=external_field)
        residuals[open_field] = {
            "opensimpv": open_value,
            "external": external_value,
            "signed_residual": open_value - external_value,
            "relative_residual_fraction": (
                (open_value - external_value) / external_value
                if external_value != 0.0
                else 0.0
            ),
        }

    if not residuals:
        raise Phase510ValidationError(
            "matched external comparison supplied no aligned numerical fields"
        )

    return {
        "case_id": case_id,
        "status": "quantitative_residuals_reported_no_fit_or_winner",
        "authority_class": "D",
        "basis_mismatches": [],
        "residuals": residuals,
        "interpretation": (
            "Residuals are decomposition evidence. Phase 5.10 does not tune "
            "validated OpenSIMPV subsystems merely to reduce cross-software residuals."
        ),
    }


def phase510_validation_hierarchy_manifest() -> dict[str, Any]:
    """Return the frozen Phase-5.10 evidence hierarchy and decision rule."""
    return {
        "schema_name": "Phase510ValidationHierarchy",
        "schema_version": "0.1",
        "hierarchy": deepcopy(VALIDATION_HIERARCHY),
        "decision_rule": (
            "Analytical truth has priority for geometry correctness. Controlled "
            "OpenSIMPV cases validate integration. External PVsyst evidence is "
            "decomposed by geometry, solar position, transposition, diffuse, "
            "ground, electrical approximation, and source convention; PVsyst is "
            "not the internal equation definition."
        ),
        "prohibited_shortcut": (
            "Do not alter independently validated solar-position or shading "
            "equations solely to improve final annual-energy agreement."
        ),
    }
