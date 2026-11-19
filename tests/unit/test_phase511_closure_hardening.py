import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

from engine.simulation.artifacts import canonical_object_sha256
from engine.simulation.design import (
    load_design_state_package,
    persist_design_state_package,
)
from geometry.shading import compile_shading_geometry


ROOT = Path(__file__).resolve().parents[2]


def _load(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _phase49c():
    return _load(
        "tests/unit/test_phase49c_reference_projects.py",
        "_opensimpv_phase49c_for_phase511",
    )


def _phase58h():
    return _load(
        "tests/unit/test_phase58h_preannual_hardening.py",
        "_opensimpv_phase58h_for_phase511",
    )


@pytest.mark.parametrize("case_id", ["R1", "R2", "R3", "R4", "R5"])
def test_phase511_reference_family_save_reload_preserves_scene_and_compiled_geometry(
    case_id,
    tmp_path,
):
    phase49c = _phase49c()
    ref = phase49c._reference(case_id)

    original_scene_sha = canonical_object_sha256(ref["scene"])
    original_compiled = compile_shading_geometry(ref["scene"])
    original_geometry_sha = original_compiled["geometry_payload_sha256"]

    saved = persist_design_state_package(
        tmp_path / case_id,
        scene=ref["scene"],
        electrical_design=ref["electrical"],
        project_revision=ref["project_revision"],
        simulation_configuration=ref["configuration"],
        design_validation_report=ref["validation"],
    )
    loaded = load_design_state_package(saved)

    reopened_scene_sha = canonical_object_sha256(loaded.scene)
    reopened_compiled = compile_shading_geometry(loaded.scene)
    reopened_geometry_sha = reopened_compiled["geometry_payload_sha256"]

    assert reopened_scene_sha == original_scene_sha
    assert reopened_geometry_sha == original_geometry_sha
    assert reopened_compiled == original_compiled


def test_phase511_save_reload_compile_shade_run_preserves_short_r4_identities(
    tmp_path,
):
    phase58h = _phase58h()
    phase55, ref, project, weather, config = phase58h._r4_ground_context(
        "r4-phase511-roundtrip"
    )
    config = deepcopy(config)
    config["simulation_configuration_id"] = "simcfg-phase511-r4-roundtrip"
    config["shading_configuration"]["cache_policy"] = {"mode": "none"}

    scene_sha = canonical_object_sha256(ref["scene"])
    config_sha = canonical_object_sha256(config)
    geometry_sha = compile_shading_geometry(ref["scene"])[
        "geometry_payload_sha256"
    ]

    before = phase55._run(
        ref,
        project,
        weather,
        config,
        tmp_path,
        "phase511-r4-before",
    )

    saved = persist_design_state_package(
        tmp_path / "saved-r4",
        scene=ref["scene"],
        electrical_design=ref["electrical"],
        project_revision=project,
        simulation_configuration=config,
        design_validation_report=ref["validation"],
    )
    loaded = load_design_state_package(saved)

    loaded_ref = deepcopy(ref)
    loaded_ref["scene"] = loaded.scene
    loaded_ref["electrical"] = loaded.electrical_design
    loaded_ref["validation"] = loaded.design_validation_report

    assert canonical_object_sha256(loaded.scene) == scene_sha
    assert canonical_object_sha256(loaded.simulation_configuration) == config_sha
    assert (
        compile_shading_geometry(loaded.scene)["geometry_payload_sha256"]
        == geometry_sha
    )

    after = phase55._run(
        loaded_ref,
        loaded.project_revision,
        weather,
        loaded.simulation_configuration,
        tmp_path,
        "phase511-r4-after",
    )

    assert before.simulation_run["input_hash"] == after.simulation_run["input_hash"]
    assert (
        before.simulation_run["result_reference"]["logical_content_sha256"]
        == after.simulation_run["result_reference"]["logical_content_sha256"]
    )
    assert (
        before.simulation_run["shading_result"]["physical_result_sha256"]
        == after.simulation_run["shading_result"]["physical_result_sha256"]
    )
    assert (
        before.simulation_run["shading_result"]["shading_result_id"]
        == after.simulation_run["shading_result"]["shading_result_id"]
    )


def test_phase511_closure_manifest_freezes_required_regression_family():
    import yaml

    manifest = yaml.safe_load(
        (
            ROOT
            / "tests/benchmarks/phase511_closure_matrix_20260925.yaml"
        ).read_text(encoding="utf-8")
    )

    assert manifest["phase"] == "5.11 Closure Hardening"
    assert manifest["phase5_exit_gate"]["status"] == "closed_for_current_scope"
    assert manifest["physics_boundary"]["new_shading_physics"] is False
    assert manifest["physics_boundary"]["phase6_electrical_mismatch"] is False

    required = {
        "simple_unobstructed_rooftop",
        "multi_roof",
        "ground_mounted_fixed_tilt",
        "rooftop_obstacle_shading",
        "multiple_orientation",
        "pvsyst_vc0_vc5_external_family",
        "analytical_shadow_microcases",
    }
    assert set(manifest["regression_family"]) == required

    reproducibility = manifest["reproducibility_gate"]
    for field in (
        "scene_hash",
        "compiled_geometry_hash",
        "configuration_identity",
        "shading_result_identity",
        "simulation_run_input_hash",
        "annual_output_deterministic_tolerance",
    ):
        assert reproducibility[field] is True

    performance = manifest["performance_evidence"]
    environment_policy = performance["environment_policy"]
    assert environment_policy["environment_metadata_recorded"] is True
    assert {
        "python_version",
        "platform",
        "machine",
        "logical_cpu_count",
        "github_actions",
        "runner_os",
        "runner_arch",
    }.issubset(set(environment_policy["required_metadata"]))

    for field in (
        "compile_time",
        "beam_query_cost",
        "sky_view_cost",
        "annual_shading_runtime",
        "cache_hit_behavior",
        "memory_use",
    ):
        assert performance[field]["recorded"] is True
        assert performance[field]["universal_threshold"] is False
