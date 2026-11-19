from pathlib import Path

import pytest

from components.candidates import build_module_candidate
from components.pan import map_pan, parse_pan_text
from components.pan.semantics import (
    MODULE_QUALITY_METHOD,
    assemble_module_semantics,
)
from engine.optical import IAM_NONE, IAM_TABULATED
from engine.simulation import resolve_module_runtime_inputs


ROOT = Path(__file__).resolve().parents[2]
JINKO_SOURCE_ID = "src-manufacturer-jinko-jkm550m-72hl4-v"


def _jinko_module():
    text = (
        ROOT
        / "tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN"
    ).read_text(encoding="utf-8")
    mapping = map_pan(parse_pan_text(text))
    return build_module_candidate(
        mapping,
        candidate_id="cand-phase38a-jinko",
        module_definition_id="mod-jinko-jkm550m-72hl4-v",
        revision_id="mod-jinko-jkm550m-72hl4-v-r1",
        source_id=JINKO_SOURCE_ID,
    )["canonical_data"]


def test_pan_module_runtime_defaults_are_consumed_from_canonical_component():
    module = _jinko_module()

    resolved = resolve_module_runtime_inputs(module)

    assert resolved.alpha_absorption == pytest.approx(0.90)
    assert resolved.iam_model_id == IAM_TABULATED
    assert resolved.iam_profile is not None
    assert resolved.iam_profile.interpolation_method == "cubic"
    assert resolved.iam_profile.theta_ref_deg == (
        0.0,
        30.0,
        50.0,
        60.0,
        70.0,
        75.0,
        80.0,
        85.0,
        90.0,
    )
    assert resolved.iam_profile.iam_ref[-2:] == pytest.approx((0.743, 0.0))
    assert resolved.module_quality_loss_fraction == pytest.approx(-0.0075)

    metadata = resolved.metadata
    assert metadata["alpha_absorption"]["source"] == (
        "module_definition.optical.absorptance_fraction"
    )
    assert metadata["iam"]["source"] == "module_definition.optical.iam"
    assert metadata["iam"]["profile_point_count"] == 9
    assert metadata["module_quality_loss_fraction"]["source"] == (
        "module_definition.quality.default_module_quality_loss_fraction"
    )
    assert metadata["module_quality_loss_fraction"]["method"] == MODULE_QUALITY_METHOD


def test_explicit_simulation_overrides_take_precedence_over_component_defaults():
    module = _jinko_module()

    resolved = resolve_module_runtime_inputs(
        module,
        alpha_absorption=0.88,
        iam_model_id=IAM_NONE,
        module_quality_loss_fraction=0.0,
    )

    assert resolved.alpha_absorption == pytest.approx(0.88)
    assert resolved.iam_model_id == IAM_NONE
    assert resolved.iam_profile is None
    assert resolved.module_quality_loss_fraction == pytest.approx(0.0)
    assert resolved.metadata["alpha_absorption"]["source"] == "configuration_override"
    assert resolved.metadata["iam"]["source"] == "configuration_override"
    assert resolved.metadata["module_quality_loss_fraction"]["source"] == (
        "configuration_override"
    )


def test_missing_optional_module_fields_use_explicitly_reported_generic_fallbacks():
    resolved = resolve_module_runtime_inputs({})

    assert resolved.alpha_absorption == pytest.approx(0.90)
    assert resolved.iam_model_id == IAM_NONE
    assert resolved.iam_profile is None
    assert resolved.module_quality_loss_fraction == pytest.approx(0.0)
    assert resolved.metadata["alpha_absorption"]["source"] == (
        "documented_generic_default_0.90"
    )
    assert resolved.metadata["iam"]["source"] == "no_component_iam"
    assert resolved.metadata["module_quality_loss_fraction"]["source"] == (
        "generic_default_zero"
    )


def test_iam_profile_override_without_model_id_is_rejected_as_ambiguous():
    module = _jinko_module()
    profile = resolve_module_runtime_inputs(module).iam_profile
    assert profile is not None

    with pytest.raises(ValueError, match="iam_profile requires an explicit iam_model_id"):
        resolve_module_runtime_inputs(module, iam_profile=profile)


def test_pvsyst_tolerance_default_preserves_signed_gain_and_loss_convention():
    plus_only = {
        "quality": {
            "nameplate_power_tolerance": {
                "lower_fraction": 0.0,
                "upper_fraction": 0.03,
            }
        }
    }
    symmetric = {
        "quality": {
            "nameplate_power_tolerance": {
                "lower_fraction": -0.03,
                "upper_fraction": 0.03,
            }
        }
    }

    plus_result, plus_derivations, plus_warnings = assemble_module_semantics(
        plus_only
    )
    symmetric_result, symmetric_derivations, symmetric_warnings = (
        assemble_module_semantics(symmetric)
    )

    assert not plus_warnings
    assert not symmetric_warnings
    assert plus_result["quality"]["default_module_quality_loss_fraction"] == pytest.approx(
        -0.0075
    )
    assert symmetric_result["quality"][
        "default_module_quality_loss_fraction"
    ] == pytest.approx(0.015)
    assert plus_derivations[0]["method"] == MODULE_QUALITY_METHOD
    assert symmetric_derivations[0]["method"] == MODULE_QUALITY_METHOD
