from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from electrical.mppt import (
    aggregate_mppt_bank,
    aggregate_parallel_strings,
    balanced_string_assignment,
    total_mppt_power_w,
    validate_mppt_assignment,
)
from electrical.string import (
    StringElectricalResult,
    build_identical_string_bank,
    calculate_identical_series_string,
)
from engine.module import ModuleElectricalResult


ROOT = Path(__file__).resolve().parents[2]


def _module_result():
    index = pd.date_range(
        "2026-03-21T10:00:00+07:00",
        periods=2,
        freq="1h",
    )
    frame = pd.DataFrame(
        {
            "evaluation_time": index + pd.Timedelta(minutes=30),
            "effective_irradiance_w_m2": [1000.0, 0.0],
            "incident_poa_global_w_m2": [1000.0, 0.0],
            "cell_temperature_c": [50.0, 30.0],
            "isc_a": [14.0, 0.0],
            "voc_v": [46.0, 0.0],
            "imp_a": [13.0, 0.0],
            "vmp_v": [37.5, 0.0],
            "pmp_w": [487.5, 0.0],
            "module_efficiency_fraction": [0.19, 0.0],
            "module_efficiency_on_effective_irradiance_fraction": [0.19, 0.0],
            "pmp_identity_relative_error": [0.0, 0.0],
            "active": [True, False],
        },
        index=index,
    )
    return ModuleElectricalResult(
        frame=frame,
        metadata={"model_id": "module.synthetic"},
    )


def test_identical_series_string_scales_voltage_power_and_preserves_current():
    module = _module_result()

    result = calculate_identical_series_string(
        module,
        string_id="S01",
        modules_in_series=18,
    )
    active = result.frame.iloc[0]
    night = result.frame.iloc[1]

    assert active["string_isc_a"] == pytest.approx(14.0)
    assert active["string_imp_a"] == pytest.approx(13.0)
    assert active["string_voc_v"] == pytest.approx(46.0 * 18)
    assert active["string_vmp_v"] == pytest.approx(37.5 * 18)
    assert active["string_pmp_w"] == pytest.approx(487.5 * 18)
    assert active["string_pmp_w"] == pytest.approx(
        active["string_vmp_v"] * active["string_imp_a"],
        abs=1e-12,
    )
    assert night["string_pmp_w"] == 0.0
    assert result.metadata["modules_in_series"] == 18
    assert result.metadata["aggregation_scope"] == "identical_module_states_only"


def test_string_bank_requires_unique_ids():
    with pytest.raises(ValueError, match="unique"):
        build_identical_string_bank(
            _module_result(),
            string_ids=["S01", "S01"],
            modules_in_series=18,
        )


@pytest.mark.parametrize(
    ("string_count", "expected_counts"),
    [
        (12, [2, 2, 1, 1, 1, 1, 1, 1, 1, 1]),
        (14, [2, 2, 2, 2, 1, 1, 1, 1, 1, 1]),
        (16, [2, 2, 2, 2, 2, 2, 1, 1, 1, 1]),
        (18, [2, 2, 2, 2, 2, 2, 2, 2, 1, 1]),
    ],
)
def test_balanced_assignment_matches_phase3_reference_distribution(
    string_count,
    expected_counts,
):
    ids = [f"S{index:02d}" for index in range(1, string_count + 1)]
    assignment = balanced_string_assignment(
        ids,
        mppt_count=10,
        total_input_count=20,
    )

    assert [len(assignment[index]) for index in range(1, 11)] == expected_counts
    assert [item for index in range(1, 11) for item in assignment[index]] == ids


def test_assignment_validation_requires_each_string_exactly_once():
    ids = ["S01", "S02", "S03"]

    with pytest.raises(ValueError, match="more than one"):
        validate_mppt_assignment(
            {1: ["S01", "S02"], 2: ["S02", "S03"]},
            string_ids=ids,
            mppt_count=2,
        )

    with pytest.raises(ValueError, match="not assigned"):
        validate_mppt_assignment(
            {1: ["S01"], 2: ["S02"]},
            string_ids=ids,
            mppt_count=2,
        )


def test_assignment_enforces_only_verified_input_limits():
    ids = ["S01", "S02", "S03"]
    # Without a verified per-MPPT input limit, two strings on MPPT 1 are allowed.
    normalized = validate_mppt_assignment(
        {1: ["S01", "S02"], 2: ["S03"]},
        string_ids=ids,
        mppt_count=2,
        total_input_count=4,
        input_count_per_mppt=None,
    )
    assert normalized[1] == ("S01", "S02")

    with pytest.raises(ValueError, match="per-MPPT input count"):
        validate_mppt_assignment(
            {1: ["S01", "S02"], 2: ["S03"]},
            string_ids=ids,
            mppt_count=2,
            total_input_count=4,
            input_count_per_mppt=1,
        )


def test_parallel_mppt_sums_current_power_and_keeps_common_voltage():
    module = _module_result()
    bank = build_identical_string_bank(
        module,
        string_ids=["S01", "S02"],
        modules_in_series=18,
    )

    result = aggregate_parallel_strings(
        bank,
        mppt_index=1,
        string_ids=["S01", "S02"],
        min_operating_voltage_v=200.0,
        max_operating_voltage_v=1000.0,
        max_operating_current_a=None,
    )
    active = result.frame.iloc[0]
    night = result.frame.iloc[1]

    assert active["mppt_vmp_v"] == pytest.approx(37.5 * 18)
    assert active["mppt_voc_v"] == pytest.approx(46.0 * 18)
    assert active["mppt_imp_a"] == pytest.approx(13.0 * 2)
    assert active["mppt_isc_a"] == pytest.approx(14.0 * 2)
    assert active["mppt_pmp_w"] == pytest.approx(487.5 * 18 * 2)
    assert active["mppt_pmp_w"] == pytest.approx(
        active["mppt_vmp_v"] * active["mppt_imp_a"],
        abs=1e-12,
    )
    assert bool(active["voltage_within_window"]) is True
    assert bool(active["voltage_below_min"]) is False
    assert bool(active["voltage_above_max"]) is False
    assert pd.isna(active["operating_current_above_limit"])

    assert bool(night["active"]) is False
    assert bool(night["voltage_below_min"]) is False
    assert bool(night["voltage_above_max"]) is False
    assert result.metadata["operating_current_limit_known"] is False


def test_mppt_voltage_and_known_current_constraint_flags_are_non_clipping():
    module = _module_result()
    bank = build_identical_string_bank(
        module,
        string_ids=["S01", "S02"],
        modules_in_series=18,
    )

    result = aggregate_parallel_strings(
        bank,
        mppt_index=1,
        string_ids=["S01", "S02"],
        min_operating_voltage_v=700.0,
        max_operating_voltage_v=1000.0,
        max_operating_current_a=25.0,
    )
    active = result.frame.iloc[0]

    assert bool(active["voltage_below_min"]) is True
    assert bool(active["voltage_within_window"]) is False
    assert bool(active["operating_current_above_limit"]) is True
    # Phase 3.5 flags constraints but does not alter the MPP state.
    assert active["mppt_vmp_v"] == pytest.approx(675.0)
    assert active["mppt_imp_a"] == pytest.approx(26.0)
    assert active["mppt_pmp_w"] == pytest.approx(17550.0)


def test_mismatched_parallel_string_voltage_requires_future_full_iv_aggregation():
    module = _module_result()
    bank = build_identical_string_bank(
        module,
        string_ids=["S01", "S02"],
        modules_in_series=18,
    )
    altered = bank["S02"].frame.copy()
    altered.loc[altered.index[0], "string_vmp_v"] += 5.0
    bank["S02"] = StringElectricalResult(
        string_id="S02",
        frame=altered,
        metadata=bank["S02"].metadata,
    )

    with pytest.raises(ValueError, match="full IV aggregation"):
        aggregate_parallel_strings(
            bank,
            mppt_index=1,
            string_ids=["S01", "S02"],
        )


def test_mppt_bank_preserves_independent_trackers_and_total_power_only():
    module = _module_result()
    ids = [f"S{index:02d}" for index in range(1, 13)]
    strings = build_identical_string_bank(
        module,
        string_ids=ids,
        modules_in_series=18,
    )
    assignments = balanced_string_assignment(
        ids,
        mppt_count=10,
        total_input_count=20,
    )

    mppts = aggregate_mppt_bank(
        strings,
        assignments,
        mppt_count=10,
        total_input_count=20,
        input_count_per_mppt=None,
        min_operating_voltage_v=200.0,
        max_operating_voltage_v=1000.0,
        max_operating_current_a=None,
    )

    assert len(mppts) == 10
    total = total_mppt_power_w(mppts)
    assert total.iloc[0] == pytest.approx(487.5 * 18 * 12)
    assert total.iloc[1] == 0.0


def test_phase3_contract_marks_mppt_assignment_as_opensimpv_not_pvsyst_source():
    suite = yaml.safe_load(
        (ROOT / "tests/benchmarks/phase3_unshaded.yaml").read_text(
            encoding="utf-8"
        )
    )
    family = next(
        item
        for item in suite["families"]
        if item["family_id"] == "SYS-PVSYST-V816-UNSHADED"
    )
    inverter = family["shared_configuration"]["inverter"]

    assert inverter["mppt_count"] == 10
    assert inverter["total_dc_input_count"] == 20
    assert inverter["input_count_per_mppt"] is None
    assert inverter["verified_mppt_operating_current_limit_a"] is None

    expected = {
        12: [2, 2, 1, 1, 1, 1, 1, 1, 1, 1],
        14: [2, 2, 2, 2, 1, 1, 1, 1, 1, 1],
        16: [2, 2, 2, 2, 2, 2, 1, 1, 1, 1],
        18: [2, 2, 2, 2, 2, 2, 2, 2, 1, 1],
    }
    for case in family["cases"]:
        count = case["configuration"]["strings"]
        assignment = case["configuration"]["opensimpv_mppt_assignment"]
        assert assignment["source_claim"] == "not_pvsyst_reported"
        assert assignment["mppt_string_counts"] == expected[count]
        assert sum(assignment["mppt_string_counts"]) == count
        assert case["configuration"]["modules_total"] == count * 18
