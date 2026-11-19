"""OND-specific semantic assembly beyond one-field-to-one-field mappings.

The mapping ledger handles scalar/list fields with explicit evidence. Some OND structures,
especially voltage-dependent inverter efficiency profiles, require cross-field assembly:
three voltage anchors, point counts, and Pin/Pout pairs must be combined into one canonical
efficiency model.

This module performs that deterministic assembly without inventing missing values.
"""

from __future__ import annotations

from copy import deepcopy
import math
from typing import Any


SINGLE_PROFILE_WARNING = (
    "The file gives one efficiency curve; efficiency is treated as independent of input "
    "voltage, as PVsyst does for such files."
)


SUPPORTED_PROFILE_MODE = frozenset({
    "POutf_PIn", "Efficiencyf_POut", "Efficf_POut", "Efficf_PIn", "Efficiencyf_PIn",
})


def assemble_inverter_semantics(
    data: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Assemble cross-field OND semantics into canonical inverter structures.

    Returns a deep-copied data object, explicit derivation records, and warnings.
    Unsupported or incomplete profile structures are preserved only as warnings; they are
    never silently coerced.
    """
    result = deepcopy(data)
    derivations: list[dict[str, Any]] = []
    warnings: list[str] = []

    source = result.pop("ond_efficiency_source", None)
    if source:
        profiles = source.get("profiles") or {}
        if profiles.get("single") and not any(key in profiles for key in ("v1", "v2", "v3")):
            model, derivation, profile_warnings = _assemble_single_profile(source, result.get("mppt_template") or {})
        else:
            model, derivation, profile_warnings = _assemble_efficiency_model(source)
        warnings.extend(profile_warnings)
        if model is not None:
            existing = result.get("efficiency_model") or {}
            reference_metrics = existing.get("reference_metrics")
            if reference_metrics:
                model["reference_metrics"] = reference_metrics
            result["efficiency_model"] = model
            derivations.append(derivation)

    derating = result.get("temperature_derating_model")
    if isinstance(derating, dict) and derating:
        derating.setdefault("temperature_basis", "unknown")
        derating.setdefault("source_model", "pvsyst_special_output_conditions")

    sizing = result.get("array_sizing_limits")
    if isinstance(sizing, dict) and sizing:
        sizing.setdefault(
            "notes",
            (
                "PVsyst/OND PV-array sizing fields are contractual/nameplate constraints; "
                "they are not used as physical inverter clipping or MPPT operating-current "
                "limits unless a separate canonical field establishes that behavior."
            ),
        )

    return result, derivations, warnings


def _assemble_efficiency_model(
    source: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    mode = source.get("profile_mode")
    voltages = source.get("voltages_v")
    profiles = source.get("profiles") or {}

    empty_derivation = {
        "target_path": "efficiency_model.curves",
        "method": "assemble_ond_voltage_dependent_pin_pout_profiles",
        "algorithm_version": "0.1",
        "inputs": deepcopy(source),
        "value": [],
        "unit": None,
        "estimated": False,
        "notes": "No canonical efficiency curves were assembled.",
    }

    if mode not in SUPPORTED_PROFILE_MODE:
        warnings.append(
            "OND voltage-dependent efficiency profiles were not assembled because "
            f"profile_mode={mode!r}; verified modes are {sorted(SUPPORTED_PROFILE_MODE)!r}."
        )
        return None, empty_derivation, warnings

    if not isinstance(voltages, list) or len(voltages) != 3:
        warnings.append(
            "OND voltage-dependent efficiency profiles require exactly three VNomEff "
            "voltage anchors."
        )
        return None, empty_derivation, warnings

    curves: list[dict[str, Any]] = []
    for index, voltage in enumerate(voltages, start=1):
        profile = profiles.get(f"v{index}") or {}
        count = profile.get("point_count")
        if not isinstance(count, int) or count < 2:
            warnings.append(
                f"OND efficiency profile v{index} has invalid/missing NPtsEff={count!r}."
            )
            return None, empty_derivation, warnings

        points: list[dict[str, float]] = []
        for point_index in range(1, count + 1):
            pair = profile.get(f"point_{point_index}")
            if not isinstance(pair, dict):
                warnings.append(
                    f"OND efficiency profile v{index} is missing Point_{point_index}."
                )
                return None, empty_derivation, warnings

            dc_power = float(pair["dc_power_w"])
            ac_power = float(pair["ac_power_w"])
            if not (math.isfinite(dc_power) and math.isfinite(ac_power)
                    and 0 <= ac_power <= dc_power):
                warnings.append(
                    f"OND efficiency profile v{index} ({voltage} V) Point_{point_index} "
                    "must satisfy finite PIn >= POut >= 0; the profile was not assembled."
                )
                return None, empty_derivation, warnings

            efficiency = ac_power / dc_power if dc_power > 0 else 0.0
            if not 0 <= efficiency <= 1:
                warnings.append(
                    f"OND efficiency profile v{index} ({voltage} V) Point_{point_index} "
                    "has efficiency outside [0, 1]; the profile was not assembled."
                )
                return None, empty_derivation, warnings
            points.append(
                {
                    "dc_power_w": dc_power,
                    "ac_power_w": ac_power,
                    "efficiency_fraction": efficiency,
                }
            )

        curves.append(
            {
                "dc_voltage_v": float(voltage),
                "points": points,
            }
        )

    model = {
        "model_type": "voltage_dependent_curves",
        "curve_power_basis": "dc_input_to_ac_output",
        "voltage_interpolation": "quadratic",
        "curves": curves,
    }
    derivation = {
        "target_path": "efficiency_model.curves",
        "method": "assemble_ond_voltage_dependent_pin_pout_profiles",
        "algorithm_version": "0.1",
        "inputs": deepcopy(source),
        "value": deepcopy(curves),
        "unit": None,
        "estimated": False,
        "notes": (
            "PVsyst ProfilPIOV1/V2/V3 Pin,Pout pairs converted to canonical "
            "voltage-dependent efficiency curves; efficiency=Pout/Pin."
        ),
    }
    return model, derivation, warnings


def _assemble_single_profile(source: dict[str, Any], template: dict[str, Any]):
    """DEC-85: voltage-independent transfer using the unchanged three-curve runtime."""
    low, high = template.get("min_operating_voltage_v"), template.get("max_operating_voltage_v")
    valid = lambda value: isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    if not (valid(low) and valid(high) and 0 <= low < high):
        return None, {}, ["OND single efficiency profile requires valid MPPT operating-window bounds."]
    nominal = template.get("nominal_voltage_v")
    use_nominal = valid(nominal) and low < nominal < high
    anchors = [low, nominal if use_nominal else (low + high) / 2, high]
    expanded = deepcopy(source)
    expanded["voltages_v"] = anchors
    expanded["profiles"] = {f"v{i}": deepcopy(source["profiles"]["single"]) for i in range(1, 4)}
    model, derivation, warnings = _assemble_efficiency_model(expanded)
    if model is None:
        return model, derivation, warnings
    derivation.update(method="single_profile_voltage_independent", inputs=deepcopy(source),
        anchors_v=anchors, middle_anchor_source="VmppNom" if use_nominal else "operating_window_midpoint",
        midpoint_reason=None if use_nominal else "VmppNom missing, non-finite or not strictly inside the operating window",
        notes="One ProfilPIO Pin/Pout curve copied to three anchors; voltage independence is explicit, not measured.")
    return model, derivation, [SINGLE_PROFILE_WARNING]
