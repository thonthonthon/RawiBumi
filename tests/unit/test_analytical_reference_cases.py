import math
from tests.reference.reference_calc import (
    axis_aligned_overlap_area,
    cable_i2r_loss,
    dc_ac_ratio,
    ghi_identity,
    interval_energy_wh,
    inverter_clip,
    inverter_constant_efficiency,
    loss_ledger,
    module_footprint,
    poa_beam,
    reconcile,
    rectangle_area,
    shaded_fraction,
    specific_yield_kwh_per_kwp,
    wall_shadow_length,
)


def test_geo_dim_001():
    assert math.isclose(rectangle_area(40.0, 20.0), 800.0, abs_tol=1e-12)


def test_geo_mod_001():
    assert module_footprint(1.134, 2.382, "portrait") == (1.134, 2.382)
    assert module_footprint(1.134, 2.382, "landscape") == (2.382, 1.134)


def test_irr_id_001():
    expected = 700.0 * math.cos(math.radians(30.0)) + 120.0
    assert math.isclose(ghi_identity(700.0, 120.0, 30.0), expected, rel_tol=1e-12)


def test_irr_beam_001():
    expected = 800.0 * math.cos(math.radians(25.0))
    assert math.isclose(poa_beam(800.0, 25.0), expected, rel_tol=1e-12)


def test_inv_const_001():
    assert inverter_constant_efficiency(100_000.0, 0.98) == 98_000.0


def test_inv_clip_001():
    assert inverter_clip(110_000.0, 100_000.0) == (100_000.0, 10_000.0)


def test_elec_dcac_001():
    assert dc_ac_ratio(150_000.0, 100_000.0) == 1.5


def test_loss_dccable_001():
    assert cable_i2r_loss(10.0, 0.2) == 20.0


def test_geo_shd_001():
    assert math.isclose(wall_shadow_length(2.0, 45.0), 2.0, rel_tol=1e-12)


def test_geo_shd_area_001():
    overlap = axis_aligned_overlap_area(0, 0, 2, 1, 1.5, 0, 2.5, 1)
    assert math.isclose(overlap, 0.5, abs_tol=1e-12)
    assert math.isclose(shaded_fraction(2.0, overlap), 0.25, abs_tol=1e-12)


def test_res_energy_001():
    assert math.isclose(interval_energy_wh(1000.0, 60.0), 16.666666666666668, rel_tol=1e-12)


def test_kpi_yf_001():
    assert specific_yield_kwh_per_kwp(150_000.0, 100.0) == 1500.0


def test_loss_ledger_001():
    assert loss_ledger(100.0, [5.0, 3.0, 4.0, 2.0]) == 86.0


def test_loss_recon_001():
    assert math.isclose(reconcile(100.0, [5.0, 3.0, 4.0, 2.0], [], 86.0), 0.0, abs_tol=1e-12)
