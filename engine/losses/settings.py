"""Versioned loss inputs and reproducible, topology-bound derived references.

Fractions are dimensionless; power W, resistance ohm. Only browser adapters
supply defaults: an absent engine block retains the historical numerical path.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
from math import isfinite
from typing import Any, Mapping

DEFAULTS_ID = "recommended_defaults.v2"
EXTENSION_KEYS = {"circuit_overrides", "plant_ac_wiring"}
DEFAULTS = {
    "soiling": {"monthly_fractions": [0.03] * 12},
    "lid_fraction": None,
    "module_mismatch_fraction": None,
    "string_mismatch_fraction": None,
    "dc_wiring_stc_fraction": 0.015,
    "ac_wiring_nominal_fraction": 0.0,
    "annual_degradation_fraction": 0.004,
    "operating_year": 1,
    "transformer": {
        "enabled": False,
        "reference_power_w": None,
        "iron_fraction": 0.001,
        "copper_fraction": None,
    },
    "unavailability_fraction": 0.0,
}


def default_loss_settings() -> dict[str, Any]:
    return {
        "schema_name": "LossSettings",
        "schema_version": "0.1",
        "defaults_id": DEFAULTS_ID,
        "overrides": {},
    }


def _number(value: Any, key: str, *, inclusive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise ValueError(f"{key} must be a finite number")
    if not isfinite(value) or value < 0 or (value > 1 if inclusive else value >= 1):
        end = "1 inclusive" if inclusive else "1 exclusive"
        raise ValueError(f"{key} must be between 0 and {end}")
    return float(value)


def validate_loss_settings(settings: Any) -> dict[str, Any]:
    if not isinstance(settings, dict) or set(settings) != {
        "schema_name",
        "schema_version",
        "defaults_id",
        "overrides",
    }:
        raise ValueError(
            "loss settings require schema_name, schema_version, defaults_id and overrides only"
        )
    if (
        settings["schema_name"] != "LossSettings"
        or settings["schema_version"] != "0.1"
        or settings["defaults_id"] not in ("recommended_defaults.v1", DEFAULTS_ID)
    ):
        raise ValueError("unsupported loss settings version or defaults")
    overrides = settings["overrides"]
    if not isinstance(overrides, dict) or set(overrides) - (
        set(DEFAULTS) | EXTENSION_KEYS
    ):
        raise ValueError("loss overrides contain unknown fields")
    resolved = deepcopy(DEFAULTS)
    if settings["defaults_id"] == "recommended_defaults.v1":
        resolved["lid_fraction"] = 0.0
    for key, value in overrides.items():
        if key in EXTENSION_KEYS:
            resolved[key] = (
                validate_circuit_overrides(value)
                if key == "circuit_overrides"
                else validate_ac_segment(value)
            )
            continue
        if key in ("soiling", "transformer"):
            allowed = (
                {"annual_fraction", "monthly_fractions"}
                if key == "soiling"
                else set(DEFAULTS[key])
            )
            if not isinstance(value, dict) or set(value) - allowed:
                raise ValueError(f"{key} contains unknown fields")
            if any(item is None for item in value.values()):
                raise ValueError(
                    f"{key}: omit a leaf to inherit; PATCH null removes an override"
                )
            resolved[key].update(deepcopy(value))
        else:
            resolved[key] = value
    soil = resolved["soiling"]
    if "annual_fraction" in soil:
        if "monthly_fractions" in overrides.get("soiling", {}):
            raise ValueError("choose annual or monthly soiling, not both")
        soil["monthly_fractions"] = [
            _number(
                soil.pop("annual_fraction"), "soiling.annual_fraction", inclusive=True
            )
        ] * 12
    months = soil["monthly_fractions"]
    if not isinstance(months, list) or len(months) != 12:
        raise ValueError("soiling.monthly_fractions must contain exactly 12 values")
    soil["monthly_fractions"] = [
        _number(v, "soiling.monthly_fractions", inclusive=True) for v in months
    ]
    for key in DEFAULTS:
        if key in ("soiling", "transformer", "operating_year"):
            continue
        if (
            key in ("lid_fraction", "module_mismatch_fraction", "string_mismatch_fraction")
            and resolved[key] is None
        ):
            if key in overrides:
                raise ValueError(f"{key}: omit the override to use the automatic rule")
            continue
        resolved[key] = _number(
            resolved[key], key, inclusive=key == "unavailability_fraction"
        )
    year = resolved["operating_year"]
    if type(year) is not int or not 1 <= year <= 100:
        raise ValueError("operating_year must be an integer between 1 and 100")
    resolved["degradation_fraction"] = resolved["annual_degradation_fraction"] * (
        year - 0.5
    )
    if resolved["degradation_fraction"] >= 1:
        raise ValueError(
            "annual degradation and operating year would exhaust module power"
        )
    transformer = resolved["transformer"]
    if type(transformer["enabled"]) is not bool:
        raise ValueError("transformer.enabled must be a boolean")
    for key in ("iron_fraction", "copper_fraction"):
        if (
            key == "copper_fraction"
            and transformer[key] is None
            and not transformer["enabled"]
        ):
            continue
        transformer[key] = _number(transformer[key], f"transformer.{key}")
    power = transformer["reference_power_w"]
    if power is not None and (
        isinstance(power, bool)
        or not isinstance(power, (int, float))
        or not isfinite(power)
        or power <= 0
    ):
        raise ValueError(
            "transformer.reference_power_w must be a positive finite power in W"
        )
    return resolved


def patch_loss_settings(current: Any, patch: Any) -> dict[str, Any]:
    result = deepcopy(current if current is not None else default_loss_settings())
    if not isinstance(patch, dict):
        raise ValueError("loss settings patch must be an object")
    if patch == {"reset_to_recommended_defaults": True}:
        return default_loss_settings()
    if set(patch) not in ({"overrides"}, {"defaults_id", "overrides"}) or not isinstance(
        patch["overrides"], dict
    ):
        raise ValueError(
            "provide overrides, optionally defaults_id, or reset_to_recommended_defaults only"
        )
    if "defaults_id" in patch:
        result["defaults_id"] = patch["defaults_id"]

    def merge(target, source):
        for key, value in source.items():
            if value is None:
                target.pop(key, None)
            elif isinstance(value, dict):
                if key in {"ac_wiring", "plant_ac_wiring"} and "mode" in value:
                    target[key] = deepcopy(value)
                    continue
                if key not in target:
                    target[key] = {}
                if not isinstance(target[key], dict):
                    raise ValueError(f"{key} must be an object")
                if key == "soiling":
                    if (
                        "annual_fraction" in value
                        and value["annual_fraction"] is not None
                    ):
                        target[key].pop("monthly_fractions", None)
                    if (
                        "monthly_fractions" in value
                        and value["monthly_fractions"] is not None
                    ):
                        target[key].pop("annual_fraction", None)
                merge(target[key], value)
                if not target[key]:
                    target.pop(key)
            else:
                target[key] = deepcopy(value)

    merge(result["overrides"], patch["overrides"])
    circuit = result["overrides"].get("circuit_overrides")
    if (
        isinstance(circuit, dict)
        and not circuit.get("inverters")
        and not circuit.get("mppts")
    ):
        validate_circuit_overrides(circuit, allow_empty=True)
        result["overrides"].pop("circuit_overrides")
    validate_loss_settings(result)
    return result


def resolve_loss_settings(settings: Any) -> dict[str, Any]:
    values = validate_loss_settings(settings)
    sources = {}

    def walk(node, path=""):
        for key, value in node.items():
            leaf = f"{path}.{key}" if path else key
            if isinstance(value, dict):
                walk(value, leaf)
            else:
                obj = settings["overrides"]
                for part in leaf.split("."):
                    obj = obj.get(part, {}) if isinstance(obj, dict) else {}
                sources[leaf] = "user" if obj != {} else "recommended_defaults"

    walk(values)
    sources["degradation_fraction"] = "derived"
    if "annual_fraction" in settings["overrides"].get("soiling", {}):
        sources["soiling.monthly_fractions"] = "user"
    payload = json.dumps(
        settings, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    resolved = {
        **deepcopy(settings),
        "values": values,
        "sources": sources,
        "settings_sha256": sha256(payload.encode()).hexdigest(),
        "stage_methods": {
            "soiling": "monthly_post_iam",
            "lid": "permanent_mpp_scalar",
            "manufacturing_dispersion": "post_mpp_scalar",
            "degradation": "midpoint_linear",
            "dc_wiring": "independent_circuit_stc_i2r",
            "ac_wiring": "per_inverter_nominal_power_quadratic",
            "transformer": "continuously_energized_iron_and_quadratic_copper",
            "unavailability": "deterministic_positive_net_export_fraction",
            "optical_energy_reference": "post_iam_stc_with_signed_module_operating_bridge",
        },
        "status": "edited" if settings["overrides"] else "recommended_defaults",
    }

    extensions = settings["overrides"].get("circuit_overrides", {})
    if any("ac_wiring" in row for row in extensions.get("inverters", {}).values()):
        resolved["stage_methods"][
            "ac_wiring"
        ] = "per_inverter_declared_segment_quadratic"
    if "plant_ac_wiring" in settings["overrides"]:
        resolved["stage_methods"][
            "plant_ac_wiring"
        ] = "plant_declared_segment_quadratic"
    return resolved


def assert_compatible_wiring_modes(
    *, per_circuit: bool, global_resistance_ohm: float
) -> None:
    """Readiness and execution must refuse the same ambiguous double input."""
    if per_circuit and float(global_resistance_ohm) != 0:
        raise ValueError(
            "Per-circuit DC wiring cannot be combined with nonzero global DC-array resistance; set global resistance to 0 ohm."
        )


def resolve_lid(
    settings: Mapping[str, Any], module: Mapping[str, Any]
) -> dict[str, Any]:
    """A common user scalar, pinned v1 zero, or the v2 module/technology default."""
    if "lid_fraction" in settings["overrides"]:
        return {"lid_fraction": settings["values"]["lid_fraction"], "lid_source": "user"}
    if settings["defaults_id"] == "recommended_defaults.v1":
        return {"lid_fraction": 0.0, "lid_source": "recommended_defaults"}
    value = (module.get("quality") or {}).get("lid_loss_fraction")
    if (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and isfinite(value)
        and 0 <= value < 1
    ):
        return {"lid_fraction": float(value), "lid_source": "module_file"}
    technology = str(module.get("technology") or "").strip().lower()
    if any(name in technology for name in ("topcon", "hjt", "heterojunction", "ibc")):
        fraction = 0.005
    elif technology in {
        "cdte", "cadmium_telluride", "cigs", "cis", "a_si",
        "amorphous_silicon", "thin_film", "thinfilm",
    }:
        fraction = 0.0
    else:
        fraction = 0.015
    return {"lid_fraction": fraction, "lid_source": "generic_default"}


def resolve_module_dispersion(
    settings: Mapping[str, Any], module: Mapping[str, Any], *, modules_in_series: int
) -> float:
    """Pinned v1 table or an explicit scalar, without requiring a wiring reference."""
    values = settings["values"]
    technology = str(module.get("technology") or "").strip().lower()
    # Material/category identifiers only: doping (n_type/p_type) is not proof
    # that a missing module technology belongs to crystalline silicon.
    thinfilm = {
        "cdte",
        "cadmium_telluride",
        "cigs",
        "cis",
        "a_si",
        "amorphous_silicon",
        "thin_film",
        "thinfilm",
    }
    silicon = {
        "crystalline_silicon_mono",
        "crystalline_silicon_poly",
        "crystalline_silicon_multi",
        "crystalline_silicon",
        "monocrystalline_silicon",
        "polycrystalline_silicon",
        "mono_si",
        "multi_si",
        "c_si",
        "topcon",
        "perc",
        "hjt",
    }
    module_fraction = values["module_mismatch_fraction"]
    if module_fraction is None:
        if technology not in thinfilm | silicon:
            raise ValueError(
                "module technology is unknown; set an explicit module mismatch fraction"
            )
        module_fraction = {1: 0.0, 2: 0.005, 3: 0.01}.get(modules_in_series, 0.02)
        if technology in thinfilm:
            module_fraction /= 2
    return module_fraction


def resolve_string_dispersion(
    settings: Mapping[str, Any], *, parallel_strings: int
) -> float:
    values = settings["values"]
    string_fraction = values["string_mismatch_fraction"]
    if string_fraction is None:
        string_fraction = (
            0.0
            if parallel_strings == 1
            else (
                0.0005
                if parallel_strings == 2
                else (0.001 if parallel_strings <= 10 else 0.0015)
            )
        )
    return string_fraction


def resolve_detailed_losses(
    settings: Mapping[str, Any],
    *,
    strings: list[Mapping[str, Any]],
    modules: Mapping[str, Mapping[str, Any]],
    inverter_name: str,
    mppt_name: str,
) -> dict[str, float]:
    """Resolve dispersion and refuse ambiguous LID in readiness and execution."""
    dispersion = resolve_detailed_dispersion(
        settings, strings=strings, modules=modules,
        inverter_name=inverter_name, mppt_name=mppt_name,
    )
    lid_fractions = {
        resolve_lid(settings, modules[mid])["lid_fraction"]
        for string in strings
        for mid in string["module_instance_ids"]
    }
    if len(lid_fractions) != 1:
        text = ", ".join(f"{fraction * 100:g}%" for fraction in sorted(lid_fractions))
        raise ValueError(
            f"Inverter {inverter_name}, MPPT {mppt_name}: automatic LID fractions differ ({text}). "
            "Set an explicit LID override; 0% is allowed."
        )
    return dispersion


def resolve_detailed_dispersion(
    settings: Mapping[str, Any],
    *,
    strings: list[Mapping[str, Any]],
    modules: Mapping[str, Mapping[str, Any]],
    inverter_name: str,
    mppt_name: str,
) -> dict[str, float]:
    """One readiness/execution policy for the aggregate selected MPPT carrier."""
    if not strings:
        raise ValueError(
            f"Inverter {inverter_name}, MPPT {mppt_name}: assign strings before resolving dispersion"
        )
    fractions = {
        resolve_module_dispersion(
            settings, modules[mid], modules_in_series=len(string["module_instance_ids"])
        )
        for string in strings
        for mid in string["module_instance_ids"]
    }
    if len(fractions) != 1:
        text = ", ".join(f"{fraction * 100:g}%" for fraction in sorted(fractions))
        raise ValueError(
            f"Inverter {inverter_name}, MPPT {mppt_name}: automatic module-dispersion fractions differ ({text}). "
            "Set an explicit module-mismatch override; 0% is allowed."
        )
    return {
        "module_mismatch_fraction": fractions.pop(),
        "string_mismatch_fraction": resolve_string_dispersion(
            settings, parallel_strings=len(strings)
        ),
    }


def circuit_reference(
    settings: Mapping[str, Any],
    module: Mapping[str, Any],
    *,
    modules_in_series: int,
    parallel_strings: int,
    mppt_index: int,
) -> dict[str, Any]:
    """Resolve the fixed nominal reference, never using reduced operating current."""
    values = settings["values"]
    stc = module.get("stc") or {}
    voltage = stc.get("vmp_v")
    current = stc.get("imp_a")
    if not all(
        isinstance(v, (int, float)) and isfinite(v) and v > 0
        for v in (voltage, current)
    ):
        raise ValueError(
            f"MPPT {mppt_index}: positive pinned STC Vmp and Imp are required for circuit wiring"
        )
    if modules_in_series < 1 or parallel_strings < 1:
        raise ValueError(
            "circuit STC reference requires positive series and parallel counts"
        )
    technology = str(module.get("technology") or "").strip().lower()
    module_fraction = resolve_module_dispersion(
        settings, module, modules_in_series=modules_in_series
    )
    string_fraction = resolve_string_dispersion(
        settings, parallel_strings=parallel_strings
    )
    v0 = voltage * modules_in_series
    i0 = current * parallel_strings
    return {
        # Keep v1 audit bytes unchanged; its LID remains in the project values.
        **(
            resolve_lid(settings, module)
            if settings["defaults_id"] != "recommended_defaults.v1" else {}
        ),
        "mppt_index": mppt_index,
        "method": "pinned_nominal_stc_series_parallel",
        "module_revision_id": module.get(
            "module_revision_id", module.get("revision_id")
        ),
        "modules_in_series": modules_in_series,
        "parallel_strings": parallel_strings,
        "technology": technology,
        "reference_voltage_v": v0,
        "reference_current_a": i0,
        "dc_wiring_stc_fraction": values["dc_wiring_stc_fraction"],
        "resistance_ohm": values["dc_wiring_stc_fraction"] * v0 / i0,
        "module_mismatch_fraction": module_fraction,
        "string_mismatch_fraction": string_fraction,
        "module_mismatch_source": settings["sources"]["module_mismatch_fraction"],
        "string_mismatch_source": settings["sources"]["string_mismatch_fraction"],
    }


# Optional circuit/AC extension. No extension is added to legacy defaults or
# effective ledger metadata: requested provenance belongs to the run audit.
def _finite_number(value, name, *, positive=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not isfinite(value)
    ):
        raise ValueError(f"{name} must be a finite number")
    if positive and value <= 0:
        raise ValueError(f"{name} must be positive")
    return float(value)


def validate_ac_segment(segment):
    if not isinstance(segment, dict):
        raise ValueError("AC segment must be a cable or percentage object")
    mode = segment.get("mode")
    if mode == "percent":
        allowed = {"mode", "loss_fraction", "reference"}
        if segment.get("reference") == "custom":
            allowed.add("reference_power_w")
        elif segment.get("reference") != "rated_ac":
            raise ValueError(
                "AC percentage must name rated_ac or custom reference power"
            )
        if set(segment) != allowed:
            raise ValueError(
                "AC percentage requires its fraction and named reference only"
            )
        _number(segment["loss_fraction"], "AC loss fraction")
        if "reference_power_w" in segment:
            _finite_number(
                segment["reference_power_w"], "AC reference power", positive=True
            )
    elif mode == "cable":
        allowed = {
            "mode",
            "length_one_way_m",
            "cross_section_per_phase_mm2",
            "material",
            "line_voltage_v",
            "conductor_temperature_c",
            "phase_system",
            "power_factor",
        }
        if set(segment) != allowed:
            raise ValueError(
                "Cable requires one-way length, per-phase area, material, line voltage, conductor temperature, phase system and power factor"
            )
        for key in (
            "length_one_way_m",
            "cross_section_per_phase_mm2",
            "line_voltage_v",
        ):
            _finite_number(segment[key], key, positive=True)
        temp = _finite_number(
            segment["conductor_temperature_c"], "Conductor temperature"
        )
        if not 0 <= temp <= 100:
            raise ValueError("Conductor temperature must be between 0 and 100 °C")
        if not isinstance(segment["material"], str) or segment["material"] not in {
            "copper",
            "aluminium",
        }:
            raise ValueError("Cable material must be copper or aluminium")
        if (
            segment["phase_system"] != "balanced_three_phase"
            or type(segment["power_factor"]) not in (int, float)
            or segment["power_factor"] != 1
        ):
            raise ValueError(
                "Cable loss supports balanced three-phase operation at unity power factor only"
            )
    else:
        raise ValueError("Choose cable or percent AC segment mode")
    return deepcopy(segment)


def validate_circuit_overrides(value, *, allow_empty=False):
    if not isinstance(value, dict) or set(value) - {"binding", "inverters", "mppts"}:
        raise ValueError("Circuit overrides require a binding and inverter/MPPT maps")
    binding = value.get("binding")
    if (
        not isinstance(binding, dict)
        or set(binding) - {"electrical_revision_id", "topology_sha256"}
        or not isinstance(binding.get("electrical_revision_id"), str)
        or not binding["electrical_revision_id"].strip()
    ):
        raise ValueError(
            "Circuit overrides require the current electrical revision binding"
        )
    digest = binding.get("topology_sha256")
    if digest is not None and (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(c not in "0123456789abcdef" for c in digest)
    ):
        raise ValueError("Circuit topology fingerprint must be a SHA-256 digest")
    count = 0
    for kind in ("inverters", "mppts"):
        rows = value.get(kind, {})
        if not isinstance(rows, dict):
            raise ValueError(f"{kind} overrides must be keyed by canonical IDs")
        allowed = {"dc_wiring_stc_fraction", "module_quality_fraction"} | (
            {"ac_wiring"} if kind == "inverters" else set()
        )
        for key, row in rows.items():
            if (
                not isinstance(key, str)
                or not key.strip()
                or not isinstance(row, dict)
                or not row
                or set(row) - allowed
            ):
                raise ValueError(f"Invalid {kind} override: {key}")
            count += 1
            for field, scalar in row.items():
                if field == "ac_wiring":
                    validate_ac_segment(scalar)
                elif field == "module_quality_fraction":
                    q = _finite_number(scalar, "Module quality")
                    if not -1 < q < 1:
                        raise ValueError(
                            "Module quality must be between -100% and 100%, exclusive; negative means gain"
                        )
                else:
                    _number(scalar, "DC wiring fraction")
    if not count and not allow_empty:
        raise ValueError("Remove empty circuit overrides to inherit project values")
    return deepcopy(value)


def has_circuit_extensions(settings):
    return (
        isinstance(settings, Mapping)
        and isinstance(settings.get("overrides"), Mapping)
        and bool(EXTENSION_KEYS & settings["overrides"].keys())
    )


def legacy_loss_settings(settings):
    validate_loss_settings(settings)
    result = deepcopy(settings)
    for key in EXTENSION_KEYS:
        result["overrides"].pop(key, None)
    return result


def circuit_topology_sha256(scene, electrical):
    """Canonical target graph; immutable snapshot IDs and display names are excluded."""
    fields = {
        "inverter_instances": (
            "inverter_instance_id",
            "inverter_definition_revision_id",
            "enabled",
        ),
        "mppt_instances": (
            "mppt_instance_id",
            "inverter_instance_id",
            "index",
            "enabled",
            "connected_string_ids",
        ),
        "strings": (
            "string_id",
            "enabled",
            "target_mppt_instance_id",
            "module_instance_ids",
            "polarity",
        ),
        "module_instances": (
            "module_instance_id",
            "module_definition_revision_id",
            "enabled",
        ),
    }
    graph = {}
    for kind, keys in fields.items():
        source = scene if kind == "module_instances" else electrical
        graph[kind] = sorted(
            ({k: deepcopy(v[k]) for k in keys if k in v} for v in source.get(kind, [])),
            key=lambda v: str(v.get(keys[0])),
        )
    for tracker in graph["mppt_instances"]:
        if "connected_string_ids" in tracker:
            tracker["connected_string_ids"] = sorted(tracker["connected_string_ids"])
    return sha256(
        json.dumps(
            graph, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _validate_override_targets(block, electrical):
    for kind, collection, id_key in (
        ("inverters", "inverter_instances", "inverter_instance_id"),
        ("mppts", "mppt_instances", "mppt_instance_id"),
    ):
        targets = {t[id_key]: t for t in electrical.get(collection, [])}
        for target in block.get(kind, {}):
            if target not in targets:
                raise ValueError(
                    f"Loss override targets a removed or unknown {kind[:-1]} {target}; reset it or reload and rebind"
                )


def bind_circuit_overrides(settings, scene, electrical):
    result = deepcopy(settings)
    block = result["overrides"].get("circuit_overrides")
    if block is not None:
        validate_circuit_overrides(block)
        if (
            block["binding"]["electrical_revision_id"]
            != electrical["electrical_revision_id"]
        ):
            raise ValueError(
                "Loss overrides use a stale electrical revision; reload and explicitly rebind or reset"
            )
        _validate_override_targets(block, electrical)
        digest = circuit_topology_sha256(scene, electrical)
        if block["binding"].get("topology_sha256", digest) != digest:
            raise ValueError(
                "Loss override topology fingerprint does not match the current design"
            )
        block["binding"]["topology_sha256"] = digest
    return result


def resolve_ac_segment(segment, *, rated_power_w, inverter_definitions=()):
    segment = validate_ac_segment(segment)
    rated = _finite_number(rated_power_w, "Rated AC reference power", positive=True)
    if segment["mode"] == "percent":
        reference = segment.get("reference_power_w", rated)
        coefficient = segment["loss_fraction"] / reference
        if (
            not isfinite(coefficient)
            or segment["loss_fraction"] > 0
            and coefficient == 0
        ):
            raise ValueError(
                "AC reference power produces a non-finite loss coefficient"
            )
        return {
            **segment,
            "reference_power_w": reference,
            "quadratic_coefficient_per_w": coefficient,
        }
    for definition in inverter_definitions:
        limits = definition.get("ac_limits", {})
        if definition.get("phase_configuration") != "three_phase":
            raise ValueError("Cable loss requires a pinned three-phase inverter")
        if limits.get("nominal_ac_voltage_v") != segment["line_voltage_v"]:
            raise ValueError(
                "Cable line-to-line voltage must match the pinned inverter/combiner bus; mixed voltages are unsupported"
            )
    rho20, alpha = (
        (0.017241, 0.00393) if segment["material"] == "copper" else (0.028264, 0.00403)
    )
    rho = rho20 * (1 + alpha * (segment["conductor_temperature_c"] - 20))
    resistance = (
        rho * segment["length_one_way_m"] / segment["cross_section_per_phase_mm2"]
    )
    try:
        denominator = segment["line_voltage_v"] ** 2
        coefficient = resistance / denominator
    except (OverflowError, ZeroDivisionError) as exc:
        raise ValueError(
            "Cable voltage cannot produce a finite representable loss coefficient"
        ) from exc
    if not all(isfinite(v) and v > 0 for v in (rho, resistance, coefficient)):
        raise ValueError(
            "Cable inputs produce a non-finite resistance or loss coefficient"
        )
    return {
        **segment,
        "material_policy": "conductor_properties.v1",
        "resistivity_20_ohm_mm2_m": rho20,
        "temperature_coefficient_per_c": alpha,
        "resistivity_ohm_mm2_m": rho,
        "resistance_per_phase_ohm": resistance,
        "reference_power_w": rated,
        "quadratic_coefficient_per_w": coefficient,
    }


def resolve_circuit_loss_settings(
    settings, scene, electrical, components, *, module_quality_override=None, detailed=False
):
    """Shared identity, precedence and exact-redundancy resolver. Never edits inputs."""
    if not has_circuit_extensions(settings):
        return None
    validate_loss_settings(settings)
    base = resolve_loss_settings(legacy_loss_settings(settings))
    block = settings["overrides"].get("circuit_overrides", {})
    if block:
        _validate_override_targets(block, electrical)
        if block["binding"].get("topology_sha256") != circuit_topology_sha256(
            scene, electrical
        ):
            targets = sorted(
                set(block.get("inverters", {})) | set(block.get("mppts", {}))
            )
            raise ValueError(
                "Loss override binding is stale after topology changes; explicitly rebind or reset: "
                + ", ".join(targets)
            )
    from engine.simulation.execution_groups import build_simulation_execution_plan, execution_units

    plan = build_simulation_execution_plan(scene, electrical, detailed=detailed)
    used = {g["inverter_instance_id"] for g in execution_units(plan)}
    mppts = {m["mppt_instance_id"]: m for m in electrical.get("mppt_instances", [])}
    inverters = {
        i["inverter_instance_id"]: i for i in electrical.get("inverter_instances", [])
    }
    modules = {m["module_instance_id"]: m for m in scene.get("module_instances", [])}
    strings = {s["string_id"]: s for s in electrical.get("strings", [])}
    circuits, inv_audit, active = {}, {}, False
    participating = []
    for iid in sorted(used):
        inv = inverters[iid]
        definition = components[inv["inverter_definition_revision_id"]]
        participating.append(definition)
        row = block.get("inverters", {}).get(iid, {})
        rated = definition["ac_limits"]["nominal_ac_power_w"]
        inherited_ac = {
            "mode": "percent",
            "loss_fraction": base["values"]["ac_wiring_nominal_fraction"],
            "reference": "rated_ac",
        }
        ac_input = row.get("ac_wiring", inherited_ac)
        ac = resolve_ac_segment(
            ac_input, rated_power_w=rated, inverter_definitions=[definition]
        )
        # Input equality, never coefficient closeness. A one-ULP fraction is active.
        redundant = (
            ac_input["mode"] == "percent"
            and ac_input["loss_fraction"] == inherited_ac["loss_fraction"]
            and (
                ac_input["reference"] == "rated_ac"
                or ac_input.get("reference_power_w") == rated
            )
        )
        ac.update(
            source=(
                "inverter_override"
                if "ac_wiring" in row
                else base["sources"]["ac_wiring_nominal_fraction"]
            ),
            active=not redundant,
        )
        active |= ac["active"]
        inv_audit[iid] = {
            "name": inv.get("name", iid),
            "nominal_ac_power_w": rated,
            "ac_wiring": ac,
        }
    for mid, mppt in sorted(mppts.items()):
        iid = mppt["inverter_instance_id"]
        if iid not in used or not mppt.get("enabled"):
            continue
        ids = [
            sid
            for sid in mppt.get("connected_string_ids", [])
            if sid in strings and strings[sid].get("enabled")
        ]
        if not ids:
            continue
        row = block.get("inverters", {}).get(iid, {})
        specific = block.get("mppts", {}).get(mid, {})
        f = specific.get(
            "dc_wiring_stc_fraction",
            row.get("dc_wiring_stc_fraction", base["values"]["dc_wiring_stc_fraction"]),
        )
        source = (
            "mppt_override"
            if "dc_wiring_stc_fraction" in specific
            else (
                "inverter_override"
                if "dc_wiring_stc_fraction" in row
                else base["sources"]["dc_wiring_stc_fraction"]
            )
        )
        quality, origins = {}, {}
        for sid in ids:
            for module_id in strings[sid]["module_instance_ids"]:
                module = components[modules[module_id]["module_definition_revision_id"]]
                inherited_q = module_quality_override
                inherited_origin = "configuration_override"
                if inherited_q is None:
                    pinned_quality = (module.get("quality") or {}).get(
                        "default_module_quality_loss_fraction"
                    )
                    inherited_q = pinned_quality if pinned_quality is not None else 0.0
                    inherited_origin = (
                        "pinned_module"
                        if pinned_quality is not None
                        else "generic_default_zero"
                    )
                q = specific.get(
                    "module_quality_fraction",
                    row.get("module_quality_fraction", inherited_q),
                )
                quality[module_id] = q
                origins[module_id] = (
                    "mppt_override"
                    if "module_quality_fraction" in specific
                    else (
                        "inverter_override"
                        if "module_quality_fraction" in row
                        else inherited_origin
                    )
                )
                active |= q != inherited_q
        active |= f != base["values"]["dc_wiring_stc_fraction"]
        circuits[mid] = {
            "inverter_instance_id": iid,
            "mppt_instance_id": mid,
            "mppt_index": mppt["index"],
            "dc_wiring_stc_fraction": f,
            "dc_wiring_source": source,
            "module_quality_by_module": quality,
            "module_quality_sources": origins,
        }
    plant_input = settings["overrides"].get("plant_ac_wiring")
    plant = None
    if plant_input is not None:
        plant = resolve_ac_segment(
            plant_input,
            rated_power_w=sum(i["nominal_ac_power_w"] for i in inv_audit.values()),
            inverter_definitions=participating,
        )
        plant["active"] = plant["quadratic_coefficient_per_w"] != 0
        active |= plant["active"]
    return {
        "schema_name": "CircuitLossResolution",
        "schema_version": "0.1",
        "active": bool(active),
        "requested_overrides": {
            k: deepcopy(v)
            for k, v in settings["overrides"].items()
            if k in EXTENSION_KEYS
        },
        "binding": deepcopy(block.get("binding")),
        "circuits": circuits,
        "inverters": inv_audit,
        "plant_ac_wiring": plant,
    }


def circuit_execution_context(resolution, inverter_id):
    if resolution is None or not resolution["active"]:
        return None
    return {
        "inverter_instance_id": inverter_id,
        "circuits": {
            c["mppt_index"]: c
            for c in resolution["circuits"].values()
            if c["inverter_instance_id"] == inverter_id
        },
        "ac_wiring": resolution["inverters"][inverter_id]["ac_wiring"],
        "plant_ac_wiring": resolution["plant_ac_wiring"],
    }


def completed_circuit_loss_audit(resolution, backend):
    """Attach actual fixed references and AC boundary totals to immutable run evidence."""
    result = deepcopy(resolution)
    ledger = backend.electrical.ledger
    references = ledger.metadata.get("resolved_loss_settings", {}).get("circuits", {})
    for mid, circuit in result["circuits"].items():
        index = str(circuit["mppt_index"])
        reference = references.get(
            circuit["inverter_instance_id"] + ":" + index, references.get(index, {})
        )
        for key in (
            "reference_voltage_v",
            "reference_current_a",
            "resistance_ohm",
            "module_quality_fraction",
            "module_revision_id",
            "method",
        ):
            if key in reference:
                circuit[key] = deepcopy(reference[key])
    rows = ledger.summary.set_index("channel")
    result["ac_summary"] = {
        "inverter_subtotal_energy_wh": float(
            rows.loc["ac_wiring", "downstream_energy_kwh"]
        )
        * 1000,
        **{
            key
            + "_loss_energy_wh": (
                float(rows.loc[key, "loss_energy_kwh"]) * 1000
                if key in rows.index
                else 0.0
            )
            for key in (
                "plant_ac_wiring",
                "transformer_iron",
                "transformer_copper",
                "unavailability",
            )
        },
        "pcc_energy_wh": float(rows.loc["unavailability", "downstream_energy_kwh"])
        * 1000,
    }
    return result


class CircuitLossSettingsError(ValueError):
    """Invalid new circuit loss inputs, including detailed evidence bindings."""


def resolve_detailed_circuit_quality(resolution, module_inputs):
    """Evidence-bound downstream scalars per selected MPPT; no IV allocation."""
    if resolution is None or not resolution["active"]:
        return None
    output = {}
    for mid, circuit in resolution["circuits"].items():
        effective, declarations = set(), {}
        for module_id, quality in circuit["module_quality_by_module"].items():
            payload = module_inputs[module_id]
            payload = payload.replay() if hasattr(payload, "replay") else payload
            evidence = payload["evidence"]
            declaration = evidence.get(
                "module_quality_declaration", {"relationship": "unknown"}
            )
            relationship = declaration["relationship"]
            if quality != 0 and relationship == "unknown":
                raise CircuitLossSettingsError(
                    f"MPPT {mid}: nonzero module quality requires calibration-independence evidence"
                )
            if (
                quality != 0
                and declaration.get("module_quality_loss_fraction") != quality
            ):
                raise CircuitLossSettingsError(
                    f"MPPT {mid}: module quality declaration does not bind the resolved signed quality value"
                )
            factor = (
                quality if relationship == "separate_from_parameterization" else 0.0
            )
            effective.add(factor)
            declarations[module_id] = {
                "evidence_id": evidence.get("evidence_id"),
                "declaration": deepcopy(declaration),
                "resolved_module_quality_loss_fraction": quality,
            }
        if len(effective) != 1:
            raise CircuitLossSettingsError(
                f"MPPT {mid}: different effective module-quality factors within one circuit are unsupported; use separate MPPTs"
            )
        output[mid] = {
            "applied_module_quality_fraction": effective.pop(),
            "quality_declarations": declarations,
        }
    return output
