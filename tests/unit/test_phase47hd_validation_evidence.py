from copy import deepcopy
from pathlib import Path

import pytest

from components.candidates import build_module_candidate
from components.pan import map_pan, parse_pan_text
from validation.engineering import compare_temperature_model_paths


ROOT = Path(__file__).resolve().parents[2]


def _pan_module(path: str, *, revision_id: str):
    text = (ROOT / path).read_text(encoding="utf-8")
    mapping = map_pan(parse_pan_text(text))
    candidate = build_module_candidate(
        mapping,
        candidate_id=f"cand-{revision_id}",
        module_definition_id=f"def-{revision_id}",
        revision_id=revision_id,
        source_id=f"src-{revision_id}",
    )
    data = candidate["canonical_data"]
    assert data["capability_flags"]["detailed_sdm_ready"] is True
    return data


@pytest.mark.parametrize(
    ("path", "revision_id"),
    (
        (
            "tests/fixtures/panond/synthetic_module.pan",
            "mod-hd-synthetic-r1",
        ),
        (
            "tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN",
            "mod-hd-jinko-r1",
        ),
    ),
)
def test_linear_fallback_guard_band_is_anchored_to_validated_detailed_models(
    path,
    revision_id,
):
    module = _pan_module(path, revision_id=revision_id)
    evidence = compare_temperature_model_paths(
        module,
        minimum_cell_temperature_c=-10.0,
        maximum_cell_temperature_c=70.0,
        design_irradiance_w_m2=1000.0,
    )

    assert evidence["detailed_model_basis"] == "validated_pvsyst_singlediode"
    assert evidence["maximum_voltage_relative_error"] <= 0.05
    assert evidence["maximum_current_relative_error"] <= 0.05


def test_detailed_path_requires_detailed_sdm_ready_capability():
    detailed = _pan_module(
        "tests/fixtures/panond/synthetic_module.pan",
        revision_id="mod-hd-capability-r1",
    )
    degraded = deepcopy(detailed)
    degraded["capability_flags"]["detailed_sdm_ready"] = False

    with pytest.raises(ValueError, match="detailed_sdm_ready=true"):
        compare_temperature_model_paths(
            degraded,
            minimum_cell_temperature_c=-10.0,
            maximum_cell_temperature_c=70.0,
            design_irradiance_w_m2=1000.0,
        )
