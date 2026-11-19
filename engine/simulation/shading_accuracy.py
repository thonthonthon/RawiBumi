"""Versioned browser sampling policy; explicit engine configurations stay intact."""
from copy import deepcopy

DEFAULTS_ID = "shading_accuracy.v1"
LEVELS = {"standard": (48, 12), "high": (72, 18)}


def default_shading_accuracy():
    return {"schema_version": "0.1", "defaults_id": DEFAULTS_ID, "overrides": {}}


def resolve_shading_accuracy(settings):
    if not isinstance(settings, dict) or set(settings) != {"schema_version", "defaults_id", "overrides"}:
        raise ValueError("shading accuracy requires schema_version, defaults_id and overrides only")
    if settings["schema_version"] != "0.1" or settings["defaults_id"] != DEFAULTS_ID:
        raise ValueError("unsupported shading accuracy version or defaults")
    overrides = settings["overrides"]
    if not isinstance(overrides, dict) or set(overrides) - {"level"}:
        raise ValueError("shading accuracy overrides accept level only")
    level = overrides.get("level", "standard")
    if not isinstance(level, str) or level not in LEVELS:
        raise ValueError("shading accuracy level must be standard or high")
    azimuth, bands = LEVELS[level]
    return {
        "schema_version": "0.1", "defaults_id": DEFAULTS_ID, "level": level,
        "source": "project_override" if overrides else "recommended_defaults",
        "sky_dome_resolution": {
            "azimuth_sectors": azimuth, "elevation_bands": bands,
            "horizon_azimuth_sectors": azimuth, "horizon_elevation_bands": 1,
            "horizon_band_elevation_deg": 10.0,
        },
        "ground_dome_resolution": {"azimuth_sectors": azimuth, "depression_bands": bands},
        "ground_source": "preset_mapping",
    }


def patch_shading_accuracy(current, patch):
    resolve_shading_accuracy(current)
    if isinstance(patch, dict) and set(patch) == {"reset_to_recommended_defaults"} and patch["reset_to_recommended_defaults"] is True:
        return default_shading_accuracy()
    if not isinstance(patch, dict) or set(patch) != {"overrides"} or not isinstance(patch["overrides"], dict) or set(patch["overrides"]) - {"level"}:
        raise ValueError("provide shading accuracy overrides or reset_to_recommended_defaults only")
    result = deepcopy(current)
    for key, value in patch["overrides"].items():
        if value is None:
            result["overrides"].pop(key, None)
        else:
            result["overrides"][key] = value
    resolve_shading_accuracy(result)
    return result


def configure_browser_shading_accuracy(configuration, settings):
    resolved = resolve_shading_accuracy(settings)
    configuration["numerical_options"]["shading_accuracy"] = deepcopy(settings)
    for key in ("sky_dome_resolution", "ground_dome_resolution"):
        configuration["shading_configuration"][key] = deepcopy(resolved[key])


def run_shading_accuracy_snapshot(configuration):
    numerical = configuration.get("numerical_options") or {}
    if "shading_accuracy" not in numerical:
        return None
    resolved = resolve_shading_accuracy(numerical["shading_accuracy"])
    for key in ("sky_dome_resolution", "ground_dome_resolution"):
        if (configuration.get("shading_configuration") or {}).get(key) != resolved[key]:
            raise ValueError(f"shading accuracy snapshot disagrees with actual {key}")
    return resolved
