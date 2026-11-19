"""User-editable CSV adapters for module and inverter component data.

These CSV formats are deliberately source-format independent. They produce canonical partial
component fragments which can be merged with PAN/OND or any future open source through the
multi-source overlay layer.

Blank cells mean "not supplied". They never mean zero.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any

from components.source_overlay import ComponentSourceFragment


def _rows(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV header is missing")
    return [
        {key: (value or "").strip() for key, value in row.items()}
        for row in reader
        if any((value or "").strip() for value in row.values())
    ]


def _float(row: dict[str, str], key: str) -> float | None:
    value = row.get(key, "")
    if value == "":
        return None
    number = float(value)
    if number != number or number in {float("inf"), float("-inf")}:
        raise ValueError(f"{key} must be finite")
    return number


def _int(row: dict[str, str], key: str) -> int | None:
    value = row.get(key, "")
    return None if value == "" else int(value)


def _bool(row: dict[str, str], key: str) -> bool | None:
    value = row.get(key, "").strip().lower()
    if value == "":
        return None
    if value in {"true", "1", "yes", "y"}:
        return True
    if value in {"false", "0", "no", "n"}:
        return False
    raise ValueError(f"{key} must be true/false, yes/no, or 1/0")


def _put(target: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    if value is None or value == "":
        return
    current = target
    for key in path[:-1]:
        current = current.setdefault(key, {})
    current[path[-1]] = value


def _source_meta(
    row: dict[str, str],
    fallback: str,
    default_priority: int,
) -> dict[str, Any]:
    source_id = row.get("source_id") or fallback
    priority_text = row.get("source_priority", "")
    source_priority = int(priority_text) if priority_text else default_priority
    return {
        "source_id": source_id,
        "source_kind": row.get("source_kind") or "user_supplied",
        "source_url": row.get("source_url") or None,
        "priority": source_priority,
        "notes": row.get("source_notes") or None,
        "license_spdx": row.get("license_spdx") or None,
        "license_url": row.get("license_url") or None,
        "attribution": row.get("attribution") or None,
    }


def parse_module_component_csv(
    text: str,
    *,
    priority: int = 100,
) -> list[ComponentSourceFragment]:
    fragments: list[ComponentSourceFragment] = []
    for index, row in enumerate(_rows(text), start=1):
        manufacturer = row.get("manufacturer", "")
        model = row.get("model", "")
        if not manufacturer or not model:
            raise ValueError(f"module row {index}: manufacturer and model are required")

        data: dict[str, Any] = {"manufacturer": manufacturer, "model": model}
        _put(data, ("family",), row.get("family"))
        _put(data, ("technology",), row.get("technology"))

        for col, key in (
            ("width_mm", "width_m"),
            ("height_mm", "height_m"),
            ("thickness_mm", "thickness_m"),
        ):
            value = _float(row, col)
            if value is not None:
                _put(data, ("mechanical", key), value / 1000.0)
        _put(data, ("mechanical", "mass_kg"), _float(row, "mass_kg"))

        for col, key in (
            ("nominal_power_w", "nominal_power_w"),
            ("pmp_w", "pmp_w"),
            ("voc_v", "voc_v"),
            ("isc_a", "isc_a"),
            ("vmp_v", "vmp_v"),
            ("imp_a", "imp_a"),
            ("reference_irradiance_w_m2", "reference_irradiance_w_m2"),
            ("reference_cell_temperature_c", "reference_cell_temperature_c"),
        ):
            _put(data, ("stc", key), _float(row, col))

        # If Pmp is omitted but the actual MPP coordinates are supplied, the value is
        # deterministic and source-independent.
        stc = data.get("stc") or {}
        if stc.get("pmp_w") is None and stc.get("vmp_v") is not None and stc.get("imp_a") is not None:
            stc["pmp_w"] = stc["vmp_v"] * stc["imp_a"]
            data["stc"] = stc

        alpha_abs = _float(row, "alpha_isc_a_per_c")
        beta_abs = _float(row, "beta_voc_v_per_c")
        gamma_abs = _float(row, "gamma_pmp_w_per_c")
        alpha_pct = _float(row, "alpha_isc_pct_per_c")
        beta_pct = _float(row, "beta_voc_pct_per_c")
        gamma_pct = _float(row, "gamma_pmp_pct_per_c")

        if alpha_abs is None and alpha_pct is not None and stc.get("isc_a") is not None:
            alpha_abs = alpha_pct / 100.0 * stc["isc_a"]
        if beta_abs is None and beta_pct is not None and stc.get("voc_v") is not None:
            beta_abs = beta_pct / 100.0 * stc["voc_v"]
        if gamma_abs is None and gamma_pct is not None and stc.get("pmp_w") is not None:
            gamma_abs = gamma_pct / 100.0 * stc["pmp_w"]

        _put(data, ("temperature_coefficients", "alpha_isc_per_c"), alpha_abs)
        _put(data, ("temperature_coefficients", "beta_voc_per_c"), beta_abs)
        _put(data, ("temperature_coefficients", "gamma_pmp_per_c"), gamma_abs)
        if any(value is not None for value in (alpha_abs, beta_abs, gamma_abs)):
            _put(data, ("temperature_coefficients", "coefficient_basis"), "absolute")

        for col, key in (
            ("physical_cell_count", "physical_cell_count"),
            ("cell_rows", "cell_rows"),
            ("cell_columns", "cell_columns"),
            ("cells_in_series", "cells_in_series"),
            ("cells_in_parallel", "cells_in_parallel"),
            ("bypass_diode_count", "bypass_diode_count"),
        ):
            _put(data, ("cell_architecture", key), _int(row, col))
        _put(data, ("cell_architecture", "half_cell"), _bool(row, "half_cell"))

        for col, key in (
            ("max_system_voltage_v", "max_system_voltage_v"),
            ("max_series_fuse_a", "max_series_fuse_a"),
            ("operating_temperature_min_c", "operating_temperature_min_c"),
            ("operating_temperature_max_c", "operating_temperature_max_c"),
        ):
            _put(data, ("limits", key), _float(row, col))

        bifaciality = _float(row, "bifaciality_factor")
        if bifaciality is not None:
            _put(data, ("bifacial", "enabled"), True)
            _put(data, ("bifacial", "bifaciality_factor"), bifaciality)

        sdm_type = row.get("sdm_model_type", "")
        sdm_columns = {
            "r_series_ohm": "sdm_r_series_ohm",
            "r_shunt_ref_ohm": "sdm_r_shunt_ref_ohm",
            "r_shunt_0_ohm": "sdm_r_shunt_0_ohm",
            "r_shunt_exp": "sdm_r_shunt_exp",
            "gamma_ref": "sdm_gamma_ref",
            "mu_gamma": "sdm_mu_gamma",
            "photocurrent_ref_a": "sdm_photocurrent_ref_a",
            "saturation_current_ref_a": "sdm_saturation_current_ref_a",
            "energy_bandgap_ref_ev": "sdm_energy_bandgap_ref_ev",
        }
        parameters = {
            key: value
            for key, col in sdm_columns.items()
            if (value := _float(row, col)) is not None
        }
        if parameters:
            data["electrical_models"] = [{
                "model_type": sdm_type or "pvsyst_singlediode",
                "model_version": row.get("sdm_model_version") or "user_supplied",
                "parameter_set": parameters,
                "verification_state": "source_attached",
            }]

        source = _source_meta(
            row,
            f"user-module:{manufacturer}:{model}:{index}",
            priority,
        )
        fragments.append(ComponentSourceFragment(data=data, **source))
    return fragments


def parse_inverter_component_csv(
    text: str,
    *,
    priority: int = 100,
) -> list[ComponentSourceFragment]:
    fragments: list[ComponentSourceFragment] = []
    for index, row in enumerate(_rows(text), start=1):
        manufacturer = row.get("manufacturer", "")
        model = row.get("model", "")
        if not manufacturer or not model:
            raise ValueError(f"inverter row {index}: manufacturer and model are required")

        data: dict[str, Any] = {"manufacturer": manufacturer, "model": model}
        _put(data, ("family",), row.get("family"))
        _put(data, ("inverter_type",), row.get("inverter_type"))
        _put(data, ("phase_configuration",), row.get("phase_configuration"))

        for col, key in (
            ("max_dc_voltage_v", "max_dc_voltage_v"),
            ("nominal_dc_voltage_v", "nominal_dc_voltage_v"),
            ("startup_voltage_v", "startup_voltage_v"),
            ("shutdown_voltage_v", "shutdown_voltage_v"),
            ("min_voltage_for_nominal_power_v", "min_voltage_for_nominal_power_v"),
        ):
            _put(data, ("dc_limits", key), _float(row, col))

        for col, key in (
            ("nominal_ac_power_w", "nominal_ac_power_w"),
            ("max_ac_power_w", "max_ac_power_w"),
            ("nominal_ac_voltage_v", "nominal_ac_voltage_v"),
            ("nominal_frequency_hz", "nominal_frequency_hz"),
            ("nominal_ac_current_a", "nominal_ac_current_a"),
            ("max_ac_current_a", "max_ac_current_a"),
            ("max_ac_apparent_power_va", "max_ac_apparent_power_va"),
        ):
            _put(data, ("ac_limits", key), _float(row, col))

        for col, key, parser in (
            ("mppt_count", "count", _int),
            ("total_input_count", "total_input_count", _int),
            ("input_count_per_mppt", "input_count_per_mppt", _int),
            ("mppt_min_voltage_v", "min_operating_voltage_v", _float),
            ("mppt_max_voltage_v", "max_operating_voltage_v", _float),
            ("mppt_nominal_voltage_v", "nominal_voltage_v", _float),
            ("mppt_max_operating_current_a", "max_operating_current_a", _float),
            ("mppt_max_short_circuit_current_a", "max_short_circuit_current_a", _float),
        ):
            _put(data, ("mppt_template", key), parser(row, col))

        for col, key in (
            ("minimum_input_power_w", "minimum_input_power_w"),
            ("startup_power_w", "startup_power_w"),
            ("shutdown_power_w", "shutdown_power_w"),
            ("standby_loss_w", "standby_loss_w"),
            ("night_loss_w", "night_loss_w"),
        ):
            _put(data, ("operating_thresholds", key), _float(row, col))

        for col, key in (
            ("nominal_pv_array_power_w", "nominal_pv_array_power_w"),
            ("max_pv_array_power_w", "max_pv_array_power_w"),
            ("max_pv_current_a", "max_pv_current_a"),
        ):
            _put(data, ("array_sizing_limits", key), _float(row, col))

        metrics = {}
        for col, key in (
            ("max_efficiency_pct", "max_efficiency_fraction"),
            ("european_efficiency_pct", "european_efficiency_fraction"),
            ("cec_efficiency_pct", "cec_efficiency_fraction"),
        ):
            value = _float(row, col)
            if value is not None:
                metrics[key] = value / 100.0
        constant = _float(row, "constant_efficiency_pct")
        if constant is not None:
            data["efficiency_model"] = {
                "model_type": "constant",
                "efficiency_fraction": constant / 100.0,
            }
            if metrics:
                data["efficiency_model"]["reference_metrics"] = metrics
        elif metrics:
            # Reference metrics are useful provenance/refinement data, but by themselves
            # they are not an executable efficiency model.
            data["efficiency_model"] = {"reference_metrics": metrics}

        for col, key in (
            ("derating_tpmax_c", "max_power_temperature_c"),
            ("derating_tpnom_c", "nominal_power_temperature_c"),
            ("derating_tlim1_c", "limit1_temperature_c"),
            ("derating_plim1_w", "limit1_power_w"),
            ("derating_absolute_limit_c", "absolute_limit_temperature_c"),
        ):
            _put(data, ("temperature_derating_model", key), _float(row, col))
        if data.get("temperature_derating_model"):
            data["temperature_derating_model"].setdefault("temperature_basis", "unknown")
            data["temperature_derating_model"].setdefault("source_model", "user_supplied")

        source = _source_meta(
            row,
            f"user-inverter:{manufacturer}:{model}:{index}",
            priority,
        )
        fragments.append(ComponentSourceFragment(data=data, **source))
    return fragments


def parse_inverter_efficiency_curve_csv(
    text: str,
    *,
    priority: int = 110,
) -> list[ComponentSourceFragment]:
    grouped: dict[tuple[str, str, str, str, str | None], list[dict[str, str]]] = defaultdict(list)
    for index, row in enumerate(_rows(text), start=1):
        manufacturer = row.get("manufacturer", "")
        model = row.get("model", "")
        if not manufacturer or not model:
            raise ValueError(f"efficiency row {index}: manufacturer and model are required")
        source = _source_meta(
            row,
            f"user-inverter-efficiency:{manufacturer}:{model}",
            priority,
        )
        key = (
            manufacturer,
            model,
            source["source_id"],
            source["source_kind"],
            source["source_url"],
            source["priority"],
            source["notes"],
            source["license_spdx"],
            source["license_url"],
            source["attribution"],
        )
        grouped[key].append(row)

    fragments: list[ComponentSourceFragment] = []
    for (
        manufacturer,
        model,
        source_id,
        source_kind,
        source_url,
        source_priority,
        source_notes,
        license_spdx,
        license_url,
        attribution,
    ), rows in grouped.items():
        by_voltage: dict[float, list[dict[str, float]]] = defaultdict(list)
        for row in rows:
            voltage = _float(row, "dc_voltage_v")
            pdc = _float(row, "dc_power_w")
            pac = _float(row, "ac_power_w")
            eta_pct = _float(row, "efficiency_pct")
            if voltage is None or pdc is None:
                raise ValueError("dc_voltage_v and dc_power_w are required")
            if pac is None and eta_pct is None:
                raise ValueError("provide ac_power_w or efficiency_pct")
            if pac is None:
                pac = pdc * eta_pct / 100.0
            eta = pac / pdc if pdc > 0 else 0.0
            by_voltage[voltage].append({
                "dc_power_w": pdc,
                "ac_power_w": pac,
                "efficiency_fraction": eta,
            })

        curves = []
        for voltage in sorted(by_voltage):
            points = sorted(by_voltage[voltage], key=lambda point: point["dc_power_w"])
            curves.append({"dc_voltage_v": voltage, "points": points})

        data = {
            "manufacturer": manufacturer,
            "model": model,
            "efficiency_model": {
                "model_type": "voltage_dependent_curves",
                "curve_power_basis": "dc_input_to_ac_output",
                "voltage_interpolation": "linear",
                "curves": curves,
            },
        }
        fragments.append(ComponentSourceFragment(
            source_id=source_id,
            source_kind=source_kind,
            source_url=source_url,
            priority=source_priority,
            notes=source_notes,
            license_spdx=license_spdx,
            license_url=license_url,
            attribution=attribution,
            data=data,
        ))
    return fragments
