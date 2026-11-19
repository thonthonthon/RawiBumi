"""PAN-specific semantic assembly beyond one-field-to-one-field mappings.

The mapping ledger remains responsible for source-field interpretation and unit
conversion. This module assembles related PAN fields into executable canonical
module behavior without claiming exact PVsyst interpolation compatibility where
that has not been independently verified.
"""

from __future__ import annotations

from copy import deepcopy
from math import isfinite
from typing import Any


SUPPORTED_IAM_MODE = "UserProfile"
SUPPORTED_IAM_PROFILE_TYPE = "TCubicProfile"
OPEN_SIMPV_TABULATED_IAM_MODEL_ID = "iam.tabulated.pvlib_interp.v0.1"
MODULE_QUALITY_METHOD = "pvsyst_tolerance_quarter_range.v0.1"


def assemble_module_semantics(
    data: dict[str, Any],
    *,
    source_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """Assemble PAN cross-field semantics into canonical module structures."""
    result = deepcopy(data)
    derivations: list[dict[str, Any]] = []
    warnings: list[str] = []

    optical = result.get("optical")
    if isinstance(optical, dict) and optical.get("absorptance_fraction") is not None:
        if source_id:
            optical["absorptance_source_ids"] = [source_id]

    iam_source = result.pop("pan_iam_source", None)
    if iam_source:
        iam_model, derivation, iam_warnings = _assemble_iam_model(
            iam_source,
            source_id=source_id,
        )
        warnings.extend(iam_warnings)
        if iam_model is not None:
            optical = result.setdefault("optical", {})
            optical["iam"] = iam_model
            derivations.append(derivation)

    quality = result.get("quality")
    if isinstance(quality, dict):
        tolerance = quality.get("nameplate_power_tolerance")
        if isinstance(tolerance, dict):
            lower = tolerance.get("lower_fraction")
            upper = tolerance.get("upper_fraction")
            if lower is not None and upper is not None:
                lower = float(lower)
                upper = float(upper)
                if not (isfinite(lower) and isfinite(upper)):
                    warnings.append(
                        "PAN nameplate power tolerance was not assembled because "
                        "one or both bounds are non-finite."
                    )
                elif lower > upper:
                    warnings.append(
                        "PAN nameplate power tolerance was not assembled because "
                        f"lower_fraction={lower} exceeds upper_fraction={upper}."
                    )
                else:
                    # PVsyst initializes module quality from the lower tolerance plus
                    # one quarter of the full tolerance range, expressed as a signed
                    # performance offset. OpenSIMPV loss sign is the inverse:
                    # positive = loss, negative = gain.
                    performance_offset = lower + 0.25 * (upper - lower)
                    module_quality_loss = -performance_offset
                    quality["default_module_quality_loss_fraction"] = (
                        module_quality_loss
                    )
                    quality["default_module_quality_method"] = MODULE_QUALITY_METHOD
                    if source_id:
                        tolerance["source_ids"] = [source_id]
                        quality["source_ids"] = [source_id]
                    derivations.append(
                        {
                            "target_path": (
                                "quality.default_module_quality_loss_fraction"
                            ),
                            "method": MODULE_QUALITY_METHOD,
                            "algorithm_version": "0.1",
                            "inputs": {
                                "lower_tolerance_fraction": lower,
                                "upper_tolerance_fraction": upper,
                            },
                            "value": module_quality_loss,
                            "unit": "fraction",
                            "estimated": False,
                            "notes": (
                                "Derived from PAN PNomTolLow/PNomTolUp using the "
                                "documented PVsyst default module-quality convention. "
                                "OpenSIMPV loss sign is positive for loss and negative "
                                "for gain."
                            ),
                        }
                    )

    return result, derivations, warnings


def _assemble_iam_model(
    source: dict[str, Any],
    *,
    source_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any], list[str]]:
    warnings: list[str] = []

    mode = source.get("mode")
    profile_type = source.get("profile_type")
    point_count = source.get("point_count")
    source_mode_code = source.get("source_interpolation_mode_code")

    empty_derivation = {
        "target_path": "optical.iam",
        "method": "assemble_pan_user_iam_profile",
        "algorithm_version": "0.1",
        "inputs": deepcopy(source),
        "value": None,
        "unit": None,
        "estimated": False,
        "notes": "No canonical IAM profile was assembled.",
    }

    if mode != SUPPORTED_IAM_MODE:
        warnings.append(
            "PAN IAM profile was not assembled because "
            f"IAMMode={mode!r}; only {SUPPORTED_IAM_MODE!r} is verified."
        )
        return None, empty_derivation, warnings

    if profile_type != SUPPORTED_IAM_PROFILE_TYPE:
        warnings.append(
            "PAN IAM profile was not assembled because "
            f"profile_type={profile_type!r}; only "
            f"{SUPPORTED_IAM_PROFILE_TYPE!r} is verified."
        )
        return None, empty_derivation, warnings

    if not isinstance(point_count, int) or point_count < 2:
        warnings.append(
            "PAN IAM profile requires an integer NPtsEff >= 2; "
            f"received {point_count!r}."
        )
        return None, empty_derivation, warnings

    points: list[dict[str, float]] = []
    previous_angle: float | None = None
    for index in range(1, point_count + 1):
        pair = source.get(f"point_{index}")
        if not isinstance(pair, dict):
            warnings.append(
                f"PAN IAM profile is missing Point_{index}; profile was not assembled."
            )
            return None, empty_derivation, warnings

        angle = float(pair["angle_deg"])
        modifier = float(pair["modifier"])
        if not (isfinite(angle) and isfinite(modifier)):
            warnings.append(
                f"PAN IAM Point_{index} contains non-finite values."
            )
            return None, empty_derivation, warnings
        if not 0.0 <= angle <= 90.0:
            warnings.append(
                f"PAN IAM Point_{index} angle {angle} is outside 0..90 degrees."
            )
            return None, empty_derivation, warnings
        if modifier < 0.0:
            warnings.append(
                f"PAN IAM Point_{index} modifier {modifier} is negative."
            )
            return None, empty_derivation, warnings
        if previous_angle is not None and angle <= previous_angle:
            warnings.append(
                "PAN IAM profile angles must be strictly increasing."
            )
            return None, empty_derivation, warnings
        previous_angle = angle
        points.append({"angle_deg": angle, "modifier": modifier})

    implied_reference = None
    if points[0]["angle_deg"] > 0.0 and points[0]["modifier"] == 1.0:
        implied_reference = deepcopy(points[0])
        points.insert(0, {"angle_deg": 0.0, "modifier": 1.0})

    if points[0]["angle_deg"] != 0.0:
        warnings.append(
            "PAN IAM profile must include an explicit 0-degree reference."
        )
        return None, empty_derivation, warnings

    model: dict[str, Any] = {
        "model_type": "tabulated",
        "execution_model_id": OPEN_SIMPV_TABULATED_IAM_MODEL_ID,
        "interpolation_method": "cubic",
        "normalize": True,
        "points": points,
        "source_mode": mode,
        "source_profile_type": profile_type,
        "source_interpolation_mode_code": source_mode_code,
        "compatibility_note": (
            "The source profile is PVsyst TCubicProfile. OpenSIMPV executes the "
            "stored points with pvlib cubic interpolation; exact PVsyst cubic "
            "interpolation equivalence is not claimed."
        ),
    }
    if source_id:
        model["source_ids"] = [source_id]

    derivation = {
        "target_path": "optical.iam",
        "method": "assemble_pan_user_iam_profile",
        "algorithm_version": "0.1",
        "inputs": deepcopy(source),
        "value": deepcopy(model),
        "unit": None,
        "estimated": False,
        "notes": (
            "PAN PVObject_IAM user profile assembled into a canonical tabulated "
            "IAM model. Source profile type and mode code are preserved."
        ),
    }
    if implied_reference is not None:
        derivation["inputs"]["implied_normal_incidence_reference"] = True
        derivation["inputs"]["original_first_point"] = implied_reference
        derivation["notes"] += " Normal-incidence (0 degrees, 1.0) is implied by the source unit reference."

    return model, derivation, warnings
