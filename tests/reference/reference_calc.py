"""Independent analytical reference functions for OpenSIMPV validation v0.1.

These functions intentionally do not call production-engine functions. They provide
small analytical references for early validation and regression tests.
"""
from __future__ import annotations
import math


def rectangle_area(width_m: float, height_m: float) -> float:
    return width_m * height_m


def module_footprint(width_m: float, height_m: float, orientation: str) -> tuple[float, float]:
    if orientation == "portrait":
        return width_m, height_m
    if orientation == "landscape":
        return height_m, width_m
    raise ValueError("orientation must be 'portrait' or 'landscape'")


def ghi_identity(dni_w_m2: float, dhi_w_m2: float, zenith_deg: float) -> float:
    return dni_w_m2 * max(math.cos(math.radians(zenith_deg)), 0.0) + dhi_w_m2


def poa_beam(dni_w_m2: float, aoi_deg: float) -> float:
    return dni_w_m2 * max(math.cos(math.radians(aoi_deg)), 0.0)


def inverter_constant_efficiency(pdc_w: float, efficiency: float) -> float:
    return pdc_w * efficiency


def inverter_clip(potential_ac_w: float, ac_limit_w: float) -> tuple[float, float]:
    output = min(potential_ac_w, ac_limit_w)
    return output, max(potential_ac_w - ac_limit_w, 0.0)


def dc_ac_ratio(installed_dc_w: float, nominal_ac_w: float) -> float:
    return installed_dc_w / nominal_ac_w


def cable_i2r_loss(current_a: float, resistance_ohm: float) -> float:
    return current_a**2 * resistance_ohm


def wall_shadow_length(height_m: float, solar_elevation_deg: float) -> float:
    if not 0.0 < solar_elevation_deg < 90.0:
        raise ValueError("solar elevation must be between 0 and 90 degrees")
    return height_m / math.tan(math.radians(solar_elevation_deg))


def axis_aligned_overlap_area(ax0: float, ay0: float, ax1: float, ay1: float, bx0: float, by0: float, bx1: float, by1: float) -> float:
    overlap_x = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    overlap_y = max(0.0, min(ay1, by1) - max(ay0, by0))
    return overlap_x * overlap_y


def shaded_fraction(module_area_m2: float, shadow_intersection_area_m2: float) -> float:
    return shadow_intersection_area_m2 / module_area_m2


def interval_energy_wh(power_w: float, duration_s: float) -> float:
    return power_w * duration_s / 3600.0


def specific_yield_kwh_per_kwp(energy_kwh: float, installed_dc_kwp: float) -> float:
    return energy_kwh / installed_dc_kwp


def loss_ledger(initial: float, losses: list[float]) -> float:
    return initial - sum(losses)


def reconcile(upstream: float, losses: list[float], transformations: list[float], downstream: float) -> float:
    expected = upstream - sum(losses) + sum(transformations)
    return downstream - expected
