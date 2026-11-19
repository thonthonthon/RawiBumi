"""Versioned optics/thermal inputs. Absent engine blocks preserve legacy execution."""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

import numpy as np
import pandas as pd
from engine.irradiance import (
    POA_ISOTROPIC,
    POA_HAYDAVIES,
    POA_PEREZ,
    POA_PEREZ_DRIESSE,
    POA_PVSYST81_PEREZ,
)

DEFAULTS_ID = "recommended_optics_thermal.v1"
TRANSPOSITION = {
    "isotropic": POA_ISOTROPIC,
    "hay_davies": POA_HAYDAVIES,
    "perez_1990": POA_PEREZ,
    "perez_driesse": POA_PEREZ_DRIESSE,
    "perez_hourly": POA_PVSYST81_PEREZ,
}
PRESETS = {
    "semi_integrated": 20.0,
    "open_rack": 29.0,
    "insulated_back": 15.0,
    "dome": 27.0,
}
DEFAULTS = {
    "transposition": "perez_hourly",
    "iam": {"selection": "module_auto", "fallback": "physical_glass"},
    "thermal": {
        "model": "steady_state",
        "mounting_preset": "semi_integrated",
        "u_c_w_m2k": 20.0,
        "u_v_w_m2k_per_ms": 0.0,
        "irradiance_basis": "effective",
    },
    "albedo": {"monthly_values": [0.2] * 12},
}
FALLBACK_PARAMETERS = {"n": 1.526, "K": 4.0, "L": 0.002, "n_ar": None}


def default_optics_thermal_settings() -> dict[str, Any]:
    return {"schema_version": "0.1", "defaults_id": DEFAULTS_ID, "overrides": {}}


def _number(value, key, *, positive=False, fraction=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ValueError(f"{key} must be a finite number")
    if value < 0 or positive and value == 0 or fraction and value > 1:
        raise ValueError(
            f"{key} must be "
            + (
                "greater than zero"
                if positive
                else "within [0, 1]" if fraction else "non-negative"
            )
        )
    return float(value)


def validate_optics_thermal_settings(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict) or set(settings) != {
        "schema_version",
        "defaults_id",
        "overrides",
    }:
        raise ValueError(
            "optics/thermal settings require schema_version, defaults_id and overrides only"
        )
    if settings["schema_version"] != "0.1" or settings["defaults_id"] != DEFAULTS_ID:
        raise ValueError("unsupported optics/thermal settings version or defaults")
    overrides = settings["overrides"]
    if not isinstance(overrides, dict) or set(overrides) - set(DEFAULTS):
        raise ValueError("optics/thermal overrides contain unknown fields")
    values = deepcopy(DEFAULTS)
    for key, value in overrides.items():
        if isinstance(DEFAULTS[key], dict):
            allowed = set(DEFAULTS[key]) | (
                {"annual_value"} if key == "albedo" else set()
            )
            if (
                not isinstance(value, dict)
                or set(value) - allowed
                or any(v is None for v in value.values())
            ):
                raise ValueError(
                    f"{key} contains unknown fields or null leaves; PATCH null removes an override"
                )
            values[key].update(deepcopy(value))
        else:
            values[key] = value
    if (
        not isinstance(values["transposition"], str)
        or values["transposition"] not in TRANSPOSITION
    ):
        raise ValueError("unsupported transposition choice")
    iam = values["iam"]
    if (
        iam["selection"]
        not in ("module_auto", "module_table", "physical_glass", "none")
        or iam["fallback"] != "physical_glass"
    ):
        raise ValueError("unsupported IAM choice or fallback")
    thermal = values["thermal"]
    custom = overrides.get("thermal", {})
    if thermal["model"] != "steady_state" or thermal["irradiance_basis"] not in (
        "effective",
        "incident_pre_iam",
    ):
        raise ValueError("unsupported thermal model or irradiance basis")
    preset = thermal["mounting_preset"]
    if preset not in (*PRESETS, "custom"):
        raise ValueError("unsupported mounting preset")
    if (
        any(k in custom for k in ("u_c_w_m2k", "u_v_w_m2k_per_ms"))
        and "mounting_preset" not in custom
    ):
        thermal["mounting_preset"] = "custom"
    elif preset in PRESETS:
        pair = {"u_c_w_m2k": PRESETS[preset], "u_v_w_m2k_per_ms": 0.0}
        if any(k in custom and custom[k] != v for k, v in pair.items()):
            raise ValueError(
                "mounting preset conflicts with custom U-values; select custom"
            )
        thermal.update(pair)
    for k in ("u_c_w_m2k", "u_v_w_m2k_per_ms"):
        thermal[k] = _number(thermal[k], k, positive=k == "u_c_w_m2k")
    albedo = values["albedo"]
    given = overrides.get("albedo", {})
    if "annual_value" in given:
        if "monthly_values" in given:
            raise ValueError("choose annual or monthly albedo, not both")
        albedo["monthly_values"] = [
            _number(albedo.pop("annual_value"), "annual albedo", fraction=True)
        ] * 12
    months = albedo["monthly_values"]
    if not isinstance(months, list) or len(months) != 12:
        raise ValueError("monthly albedo requires exactly 12 values")
    albedo["monthly_values"] = [
        _number(v, "monthly albedo", fraction=True) for v in months
    ]
    return values


def patch_optics_thermal_settings(current, patch) -> dict[str, Any]:
    result = deepcopy(
        current if current is not None else default_optics_thermal_settings()
    )
    validate_optics_thermal_settings(result)
    if (
        isinstance(patch, dict)
        and set(patch) == {"reset_to_recommended_defaults"}
        and patch["reset_to_recommended_defaults"] is True
    ):
        return default_optics_thermal_settings()
    if (
        not isinstance(patch, dict)
        or set(patch) != {"overrides"}
        or not isinstance(patch["overrides"], dict)
    ):
        raise ValueError(
            "provide optics/thermal overrides or reset_to_recommended_defaults only"
        )

    def merge(target, source, path=""):
        for key, value in source.items():
            allowed = (
                set(DEFAULTS)
                if not path
                else set(DEFAULTS[path])
                | ({"annual_value"} if path == "albedo" else set())
            )
            if key not in allowed:
                raise ValueError(f"unknown optics/thermal override {path}.{key}")
            if value is None:
                target.pop(key, None)
            elif isinstance(value, dict):
                if path or key not in ("iam", "thermal", "albedo"):
                    raise ValueError(
                        f"{path}.{key} must be a scalar or array, not an object"
                    )
                if key not in target:
                    target[key] = {}
                if not isinstance(target[key], dict):
                    raise ValueError(f"{key} must be an object")
                if key == "albedo":
                    if value.get("annual_value") is not None:
                        target[key].pop("monthly_values", None)
                    if value.get("monthly_values") is not None:
                        target[key].pop("annual_value", None)
                if key == "thermal":
                    if (
                        isinstance(value.get("mounting_preset"), str)
                        and value.get("mounting_preset") in PRESETS
                    ):
                        target[key].pop("u_c_w_m2k", None)
                        target[key].pop("u_v_w_m2k_per_ms", None)
                    elif (
                        any(
                            value.get(k) is not None
                            for k in ("u_c_w_m2k", "u_v_w_m2k_per_ms")
                        )
                        and "mounting_preset" not in value
                    ):
                        target[key]["mounting_preset"] = "custom"
                merge(target[key], value, key)
                if not target[key]:
                    target.pop(key)
            else:
                target[key] = deepcopy(value)

    merge(result["overrides"], patch["overrides"])
    validate_optics_thermal_settings(result)
    return result


def resolve_optics_thermal_settings(settings) -> dict[str, Any]:
    values = validate_optics_thermal_settings(settings)
    sources = {}
    for key, value in values.items():
        leaves = value.items() if isinstance(value, dict) else [("", value)]
        for leaf, _ in leaves:
            path = f"{key}.{leaf}" if leaf else key
            supplied = settings["overrides"].get(key, {})
            sources[path] = (
                "user"
                if (
                    leaf in supplied
                    if isinstance(supplied, dict)
                    else key in settings["overrides"]
                )
                else "recommended_defaults"
            )
    if "annual_value" in settings["overrides"].get("albedo", {}):
        sources["albedo.monthly_values"] = "user"
    if settings["overrides"].get("thermal", {}).get("mounting_preset") in PRESETS:
        sources["thermal.u_c_w_m2k"] = sources["thermal.u_v_w_m2k_per_ms"] = "user"
    payload = {
        "values": values,
        "defaults_id": DEFAULTS_ID,
        "fallback_parameters": FALLBACK_PARAMETERS,
    }
    digest = sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    return {
        **deepcopy(settings),
        "values": values,
        "sources": sources,
        "settings_sha256": digest,
        "fallback_parameters": deepcopy(FALLBACK_PARAMETERS),
        "status": "edited" if settings["overrides"] else "recommended_defaults",
    }


def configure_optics_thermal(configuration, settings) -> None:
    """Browser adapter: write one consistent resolved choice into existing selections."""
    resolved = resolve_optics_thermal_settings(settings)
    values = resolved["values"]
    numerical = configuration["numerical_options"]
    numerical["optics_thermal_settings"] = deepcopy(settings)
    numerical["thermal"] = {
        k: values["thermal"][k] for k in ("u_c_w_m2k", "u_v_w_m2k_per_ms")
    }
    numerical["albedo"] = values["albedo"]["monthly_values"][0]
    selections = configuration["model_selections"]
    selections["transposition"] = TRANSPOSITION[values["transposition"]]
    from engine.thermal import THERMAL_PVSYST

    selections["temperature"] = THERMAL_PVSYST
    from engine.optical import IAM_NONE, IAM_TABULATED

    selections["iam"] = {
        "none": IAM_NONE,
        "module_auto": "component_default",
        "module_table": IAM_TABULATED,
        "physical_glass": "iam.physical_glass.v0.1",
    }[values["iam"]["selection"]]


def albedo_for_index(settings: Mapping[str, Any], index: pd.DatetimeIndex):
    if index.tz is None:
        raise ValueError("monthly albedo requires timezone-aware local interval starts")
    months = settings["values"]["albedo"]["monthly_values"]
    if all(v == months[0] for v in months):
        return float(months[0])
    return np.asarray(months)[index.month.to_numpy() - 1]


def resolve_iam(settings, definition):
    from engine.optical import IAM_NONE, IAM_TABULATED, TabulatedIAMProfile

    choice = settings["values"]["iam"]["selection"]
    optical = definition.get("optical") or {}
    if not isinstance(optical, dict):
        raise ValueError(
            f"Module {definition.get('revision_id')} optical inputs must be an object"
        )
    table = optical.get("iam")
    if choice == "none":
        return IAM_NONE, None, "explicit_none"
    if choice == "physical_glass":
        return "iam.physical_glass.v0.1", None, "physical_glass"
    if table is None:
        if choice == "module_table":
            raise ValueError(f"Module {definition.get('revision_id')} has no IAM table")
        return "iam.physical_glass.v0.1", None, "fallback_physical_glass"
    if (
        not isinstance(table, dict)
        or table.get("model_type") != "tabulated"
        or table.get("execution_model_id") != IAM_TABULATED
    ):
        raise ValueError(
            f"Module {definition.get('revision_id')} has an unusable IAM table"
        )
    try:
        profile = TabulatedIAMProfile.from_points(
            [
                (p["angle_deg"], p["modifier"]) if isinstance(p, dict) else p
                for p in (table.get("points") or [])
            ],
            interpolation_method=table.get("interpolation_method", "linear"),
            normalize=table.get("normalize", True),
        )
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError(
            f"Module {definition.get('revision_id')} has an unusable IAM table: {exc}"
        ) from exc
    return IAM_TABULATED, profile, "module_table"


def run_optics_snapshot(configuration, scene, electrical, components):
    stored = configuration.get("numerical_options", {}).get("optics_thermal_settings")
    if stored is None:
        return None
    resolved = resolve_optics_thermal_settings(stored)
    enabled_inv = {
        i["inverter_instance_id"]
        for i in electrical["inverter_instances"]
        if i["enabled"]
    }
    trackers = {
        m["mppt_instance_id"]
        for m in electrical["mppt_instances"]
        if m["enabled"] and m["inverter_instance_id"] in enabled_inv
    }
    string_ids = {
        sid
        for mppt in electrical["mppt_instances"]
        if mppt["mppt_instance_id"] in trackers
        for sid in mppt["connected_string_ids"]
    }
    ids = {
        m
        for s in electrical["strings"]
        if s["enabled"] and s["string_id"] in string_ids
        for m in s["module_instance_ids"]
    }
    modules = {}
    for item in sorted(
        scene["module_instances"], key=lambda m: m["module_instance_id"]
    ):
        if item["enabled"] and item["module_instance_id"] in ids:
            revision = item["module_definition_revision_id"]
            definition = components[revision]
            _, profile, source = resolve_iam(resolved, definition)
            from .unshaded import resolve_module_runtime_inputs

            alpha = resolve_module_runtime_inputs(
                definition, iam_model_id="iam.none.v0.1"
            ).alpha_absorption
            modules[item["module_instance_id"]] = {
                "module_revision_id": revision,
                "iam_source": source,
                "alpha_absorption": alpha,
                "iam_profile_sha256": (
                    sha256(repr(profile).encode()).hexdigest() if profile else None
                ),
            }
    return {**resolved, "modules": modules}


def zero_horizontal_irradiance_limit(poa, irradiance):
    """Exact zero-input limit, only for opted-in optics execution.

    Perez clearness is undefined for a zero/zero input. Do not repair or infer
    any nonzero irradiance interval, weather value, or solar-position value.
    """
    from engine.irradiance import PlaneOfArrayResult
    source = irradiance.frame
    zero = (source[["ghi_w_m2", "dni_w_m2", "dhi_w_m2"]] == 0.0).all(axis=1)
    if not zero.any():
        return poa
    frame = poa.frame.copy()
    columns = ["poa_beam_w_m2", "poa_sky_diffuse_w_m2", "poa_ground_diffuse_w_m2",
               "poa_diffuse_w_m2", "poa_global_w_m2", "poa_isotropic_w_m2",
               "poa_circumsolar_w_m2", "poa_horizon_w_m2"]
    frame.loc[zero, columns] = 0.0
    return PlaneOfArrayResult(frame, {**poa.metadata,
        "zero_input_policy": "exact_zero_horizontal_components",
        "zero_input_interval_count": int(zero.sum())})


def uses_legacy_optics_values(settings):
    """Recognize the explicit legacy numerical policy, independently of source labels."""
    values = settings["values"]
    thermal = values["thermal"]
    return (values["transposition"] == "isotropic"
            and values["iam"]["selection"] == "none"
            and thermal["model"] == "steady_state"
            and thermal["irradiance_basis"] == "incident_pre_iam"
            and thermal["u_c_w_m2k"] == 20.0
            and thermal["u_v_w_m2k_per_ms"] == 0.0
            and values["albedo"]["monthly_values"] == [0.20] * 12)
