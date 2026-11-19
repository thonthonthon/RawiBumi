import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from components.candidates import build_module_candidate
from components.iv_reference import (
    DATASET_SCHEMA_PATH,
    RESULT_SCHEMA_PATH,
    IVReferenceValidationConfig,
    _summary_residuals,
    attach_reference_validation,
    load_iv_reference_dataset,
    parse_iv_summary_csv,
    parse_iv_summary_csv_bytes,
    parse_pvlib_pvsyst_demo_bytes,
    validate_pvsyst_sdm_against_reference,
)
from components.pan import parse_pan_text
from components.pan.mapper import map_pan


ROOT = Path(__file__).resolve().parents[2]


def _text(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _module():
    mapping = map_pan(parse_pan_text(_text("tests/fixtures/panond/synthetic_module.pan")))
    candidate = build_module_candidate(
        mapping,
        candidate_id="candidate-ivref",
        module_definition_id="module-ivref",
        revision_id="module-ivref-r1",
        source_id="src-pan-001",
    )
    return candidate["canonical_data"]


def _pvlib_mitsubishi_fitted_model():
    """PVsyst SDM parameters distributed with pvlib's measured-IV regression data.

    These parameters are derived from the same measurement campaign and therefore
    must never qualify as independent validation evidence.
    """
    return {
        "module_definition_id": "module-mitsubishi-pv-ue125mf5n-pvlib-fit",
        "revision_id": "module-mitsubishi-pv-ue125mf5n-pvlib-fit-r1",
        "source_ids": ["src-pvlib-pvsyst-demo-model-v0.15.2"],
        "source_group_ids": ["sandia-mitsubishi-pv-ue125mf5n-outdoor-campaign"],
        "electrical_models": [{
            "model_type": "pvsyst_singlediode",
            "model_version": "pvlib-regression-fit",
            "parameter_set": {
                "alpha_sc_a_per_c": 0.0054,
                "gamma_ref": 1.0580,
                "mu_gamma": 0.0053585,
                "photocurrent_ref_a": 7.6626,
                "saturation_current_ref_a": 2.1003e-09,
                "r_shunt_ref_ohm": 236.57,
                "r_shunt_0_ohm": 886.22,
                "r_shunt_exp": 5.5,
                "r_series_ohm": 0.25483,
                "cells_in_series": 36,
                "energy_bandgap_ref_ev": 2.1798,
                "reference_irradiance_w_m2": 1000.0,
                "reference_cell_temperature_c": 25.0
            }
        }],
        "capability_flags": {}
    }


def test_iv_reference_schemas_are_valid_draft_2020_12():
    for path in (DATASET_SCHEMA_PATH, RESULT_SCHEMA_PATH):
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_canonical_iv_reference_fixture_validates():
    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    assert dataset["dataset_id"] == "ivref-synthetic-001"
    assert len(dataset["points"]) == 3
    assert len(dataset["points"][1]["iv_curve"]) == 11


def test_summary_csv_import_builds_canonical_dataset():
    dataset = parse_iv_summary_csv(
        _text("tests/fixtures/iv_reference/synthetic_reference_matrix.csv"),
        dataset_id="ivref-csv-001",
        revision_id="ivref-csv-001-r1",
        name="CSV reference matrix",
        source_id="src-synthetic-csv",
        source_kind="synthetic_reference",
        measurement_context={
            "irradiance_quantity": "effective_irradiance",
            "temperature_quantity": "cell_temperature",
        },
    )
    assert len(dataset["points"]) == 3
    assert dataset["points"][0]["point_id"] == "G200-T0"
    assert dataset["points"][1]["summary"]["pmp_w"] == pytest.approx(305.2207439830166)
    assert dataset["points"][1]["iv_curve"] is None


def test_reference_matrix_validates_summary_points_and_full_curve():
    module = _module()
    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    result = validate_pvsyst_sdm_against_reference(
        module,
        dataset,
        validation_id="ivval-synthetic-001",
    )

    assert result["status"] == "passed"
    assert result["passed"] is True
    assert result["qualification"] == "synthetic_regression"
    assert result["coverage"]["reference_point_count"] == 3
    assert result["coverage"]["curve_count"] == 1
    assert result["aggregate"]["point_passed_count"] == 3
    assert result["aggregate"]["curve_evaluated_count"] == 1
    assert result["aggregate"]["curve_passed_count"] == 1
    assert result["aggregate"]["max_curve_current_nrmse_by_isc"] < 1e-8

    curve = result["point_results"][1]["curve_result"]
    assert curve["sample_count"] == 11
    assert curve["current_nrmse_by_isc"] < 1e-8


def test_bad_reference_summary_is_rejected_without_changing_model():
    module = _module()
    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    dataset = deepcopy(dataset)
    dataset["points"][0]["summary"]["pmp_w"] *= 1.10

    result = validate_pvsyst_sdm_against_reference(
        module,
        dataset,
        validation_id="ivval-bad-summary",
    )

    assert result["status"] == "failed"
    assert result["passed"] is False
    first = result["point_results"][0]
    assert first["reference_quality_passed"] is False
    assert any(
        item["rule_id"] == "IVREF_PMP_VMP_IMP_MISMATCH"
        for item in first["reference_findings"]
    )


def test_bad_full_curve_fails_curve_metric():
    module = _module()
    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    dataset = deepcopy(dataset)
    for sample in dataset["points"][1]["iv_curve"]:
        sample["current_a"] *= 0.90

    result = validate_pvsyst_sdm_against_reference(
        module,
        dataset,
        validation_id="ivval-bad-curve",
    )

    assert result["status"] == "failed"
    assert result["passed"] is False
    curve = result["point_results"][1]["curve_result"]
    assert curve["passed"] is False
    assert curve["current_nrmse_by_isc"] > curve["tolerance"]


def test_distinct_laboratory_source_can_qualify_as_independent_and_attach_flag():
    module = _module()
    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    dataset = deepcopy(dataset)
    dataset["dataset_id"] = "ivref-test-independent"
    dataset["revision_id"] = "ivref-test-independent-r1"
    dataset["source_id"] = "src-lab-independent-001"
    dataset["source_kind"] = "laboratory_iv"
    dataset["measurement_context"]["standard_or_method"] = "test-only independence classification"

    result = validate_pvsyst_sdm_against_reference(
        module,
        dataset,
        validation_id="ivval-independent-test",
    )

    assert result["passed"] is True
    assert result["qualification"] == "independent_reference_validation"

    updated = attach_reference_validation(module, result)
    assert updated["capability_flags"]["independent_iv_validated"] is True
    model = updated["electrical_models"][0]
    assert model["reference_validations"][-1]["validation_id"] == "ivval-independent-test"


def test_same_source_cannot_qualify_as_independent():
    module = _module()
    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    dataset = deepcopy(dataset)
    dataset["dataset_id"] = "ivref-test-same-source"
    dataset["revision_id"] = "ivref-test-same-source-r1"
    dataset["source_id"] = "src-pan-001"
    dataset["source_kind"] = "laboratory_iv"

    result = validate_pvsyst_sdm_against_reference(
        module,
        dataset,
        validation_id="ivval-same-source-test",
    )

    assert result["passed"] is True
    assert result["qualification"] == "same_source_validation"

    updated = attach_reference_validation(module, result)
    assert updated["capability_flags"]["independent_iv_validated"] is False



def test_real_measured_mitsubishi_subset_ingests_with_hash_and_provenance():
    raw_path = (
        ROOT
        / "tests/fixtures/iv_reference/real"
        / "mitsubishi_pv_ue125mf5n_sandia_subset.csv"
    )
    manifest = json.loads(
        (
            ROOT
            / "tests/fixtures/iv_reference/real"
            / "dataset-manifest.json"
        ).read_text(encoding="utf-8")
    )
    source_index_map = [
        item["source_index"]
        for item in manifest["subset"]["subset_index_to_source_index"]
    ]

    dataset = parse_pvlib_pvsyst_demo_bytes(
        raw_path.read_bytes(),
        dataset_id=manifest["dataset_id"],
        revision_id=manifest["dataset_id"] + "-r1",
        name="Mitsubishi PV-UE125MF5N Sandia measured IV subset",
        filename=raw_path.name,
        source_id="src-pvlib-pvsyst-demo-v0.15.2",
        source_index_map=source_index_map,
        source_kind="field_iv",
        source_url=manifest["source"]["url"],
        source_git_blob_sha=manifest["source"]["git_blob_sha"],
        license_spdx=manifest["redistribution"]["license_spdx"],
        license_url=manifest["redistribution"]["license_url"],
        attribution=manifest["redistribution"]["attribution"],
        provenance={
            "source_group_id": "sandia-mitsubishi-pv-ue125mf5n-outdoor-campaign",
            "derived_from_source_ids": [],
            "original_repository": manifest["source"]["repository"],
            "original_revision": manifest["source"]["revision"],
            "measurement_reference_url": manifest["measurement_reference"]["url"],
            "redistribution_license_spdx": manifest["redistribution"]["license_spdx"],
            "redistribution_license_url": manifest["redistribution"]["license_url"],
            "redistribution_note": manifest["redistribution"]["modification"],
        },
        measurement_context={
            "irradiance_quantity": "effective_irradiance",
            "temperature_quantity": "cell_temperature",
            "uncertainty_basis": "unknown",
            "laboratory": "Sandia National Laboratories outdoor testing, Albuquerque NM",
            "standard_or_method": "SAND2015-8598 PVsyst parameter-estimation example",
            "notes": (
                "Cell temperature estimated from three backsheet thermocouples; "
                "effective irradiance measured with a silicon reference cell."
            ),
        },
    )

    assert len(dataset["points"]) == 12
    assert dataset["module_identity"]["manufacturer"] == "Mitsubishi"
    assert dataset["module_identity"]["model"] == "PV-UE125MF5N"
    assert dataset["source_files"][0]["sha256"] == manifest["subset"]["sha256"]
    assert dataset["source_files"][0]["byte_size"] == manifest["subset"]["byte_size"]
    assert dataset["source_files"][0]["license_spdx"] == "BSD-3-Clause"
    assert dataset["ingestion"]["source_record_count"] == 12
    assert dataset["ingestion"]["selected_source_indices"] == source_index_map
    assert dataset["points"][0]["source_index"] == source_index_map[0]
    assert dataset["points"][-1]["source_index"] == source_index_map[-1]
    assert {len(point["iv_curve"]) for point in dataset["points"]} == {56}
    assert {point["source_sample_count"] for point in dataset["points"]} == {56}
    assert all(
        point["summary"]["pmp_w"]
        == pytest.approx(point["summary"]["imp_a"] * point["summary"]["vmp_v"])
        for point in dataset["points"]
    )


def test_summary_csv_bytes_hashes_source_and_imports_uncertainty_columns():
    raw = (
        b"point_id,effective_irradiance_w_m2,cell_temperature_c,"
        b"isc_a,voc_v,imp_a,vmp_v,pmp_w,isc_uncertainty_a,"
        b"voc_uncertainty_v,uncertainty_confidence_fraction\n"
        b"P1,1000,25,10,50,9.5,42,399,0.02,0.10,0.95\n"
    )
    dataset = parse_iv_summary_csv_bytes(
        raw,
        dataset_id="ivref-uncertainty-csv",
        revision_id="ivref-uncertainty-csv-r1",
        name="Measured CSV with uncertainty",
        filename="measurement.csv",
        source_id="src-measurement-csv",
        source_kind="laboratory_iv",
        measurement_context={
            "irradiance_quantity": "effective_irradiance",
            "temperature_quantity": "cell_temperature",
            "uncertainty_basis": "expanded",
        },
    )

    assert dataset["source_files"][0]["byte_size"] == len(raw)
    assert len(dataset["source_files"][0]["sha256"]) == 64
    point = dataset["points"][0]
    assert point["uncertainty"]["isc_a"] == pytest.approx(0.02)
    assert point["uncertainty"]["voc_v"] == pytest.approx(0.10)
    assert point["uncertainty"]["confidence_fraction"] == pytest.approx(0.95)


def test_uncertainty_is_report_only_by_default_and_can_explicitly_expand_tolerance():
    reference = {
        "isc_a": 10.0,
        "voc_v": 50.0,
        "imp_a": 9.0,
        "vmp_v": 40.0,
        "pmp_w": 360.0,
    }
    modeled = dict(reference)
    modeled["voc_v"] = 51.5

    passed_report_only, report_only = _summary_residuals(
        reference,
        modeled,
        IVReferenceValidationConfig(voc_relative_tolerance=0.02),
        uncertainty={"voc_v": 2.0},
        uncertainty_basis="expanded",
    )
    assert passed_report_only is False
    assert report_only["voc_v"]["uncertainty_used_for_acceptance"] is False
    assert report_only["voc_v"]["uncertainty_normalized_absolute_error"] == pytest.approx(0.75)

    passed_expanded, expanded = _summary_residuals(
        reference,
        modeled,
        IVReferenceValidationConfig(
            voc_relative_tolerance=0.02,
            uncertainty_policy="expand_tolerance",
        ),
        uncertainty={"voc_v": 2.0},
        uncertainty_basis="expanded",
    )
    assert passed_expanded is True
    assert expanded["voc_v"]["uncertainty_used_for_acceptance"] is True
    assert expanded["voc_v"]["effective_absolute_tolerance"] == pytest.approx(2.0)


def test_source_group_prevents_false_independence_when_source_ids_differ():
    module = _module()
    module["source_group_ids"] = ["campaign-shared-001"]

    dataset = load_iv_reference_dataset(
        ROOT / "tests/fixtures/iv_reference/synthetic_reference_matrix.json"
    )
    dataset = deepcopy(dataset)
    dataset["dataset_id"] = "ivref-source-group-test"
    dataset["revision_id"] = "ivref-source-group-test-r1"
    dataset["source_id"] = "src-different-id"
    dataset["source_kind"] = "field_iv"
    dataset["provenance"] = {
        "source_group_id": "campaign-shared-001",
        "derived_from_source_ids": [],
    }

    result = validate_pvsyst_sdm_against_reference(
        module,
        dataset,
        validation_id="ivval-source-group-test",
    )

    assert result["passed"] is True
    assert result["qualification"] == "same_source_validation"



def test_real_measured_subset_exercises_summary_and_curve_validation_without_false_independence():
    raw_path = (
        ROOT
        / "tests/fixtures/iv_reference/real"
        / "mitsubishi_pv_ue125mf5n_sandia_subset.csv"
    )
    manifest = json.loads(
        (
            ROOT
            / "tests/fixtures/iv_reference/real"
            / "dataset-manifest.json"
        ).read_text(encoding="utf-8")
    )
    source_index_map = [
        item["source_index"]
        for item in manifest["subset"]["subset_index_to_source_index"]
    ]
    dataset = parse_pvlib_pvsyst_demo_bytes(
        raw_path.read_bytes(),
        dataset_id=manifest["dataset_id"],
        revision_id=manifest["dataset_id"] + "-r1",
        name="Mitsubishi PV-UE125MF5N Sandia measured IV subset",
        filename=raw_path.name,
        source_id="src-pvlib-pvsyst-demo-v0.15.2",
        source_index_map=source_index_map,
        source_kind="field_iv",
        provenance={
            "source_group_id": "sandia-mitsubishi-pv-ue125mf5n-outdoor-campaign",
            "derived_from_source_ids": [],
        },
    )
    config = IVReferenceValidationConfig(
        # Match the published pvlib regression tolerances for the first 3000
        # source curves. These tolerances apply to summary points only.
        isc_relative_tolerance=0.003,
        voc_relative_tolerance=0.019,
        imp_relative_tolerance=0.021,
        vmp_relative_tolerance=0.029,
        pmp_relative_tolerance=0.038,
        # Full-curve NRMSE is an OpenSIMPV diagnostic; pvlib's upstream fit
        # regression does not claim a tolerance for this metric.
        curve_current_nrmse_tolerance=0.080,
    )

    # First reproduce the evidence boundary pvlib actually tests: the fitted
    # model versus Isc/Voc/Imp/Vmp/Pmp for curves in upstream indices 0..2999.
    summary_dataset = deepcopy(dataset)
    for point in summary_dataset["points"]:
        point["iv_curve"] = None
    summary_result = validate_pvsyst_sdm_against_reference(
        _pvlib_mitsubishi_fitted_model(),
        summary_dataset,
        validation_id="ivval-real-pvlib-summary-same-campaign",
        config=config,
    )

    assert summary_result["qualification"] == "same_source_validation"
    assert summary_result["status"] in {"passed", "failed"}
    assert summary_result["coverage"]["reference_point_count"] == 12
    assert summary_result["coverage"]["curve_count"] == 0
    assert len(summary_result["point_results"]) == 12
    assert set(summary_result["aggregate"]["max_summary_absolute_relative_error"]) == {
        "isc_a", "voc_v", "imp_a", "vmp_v", "pmp_w"
    }
    assert not any(
        item.get("rule_id") == "IVREF_MODEL_EVALUATION_FAILED"
        for item in summary_result["findings"]
    )

    # Exercise OpenSIMPV's stricter optional full-curve metric separately.
    # We deliberately do not require the upstream/reference parameter file to
    # pass OpenSIMPV's chosen tolerances: pvlib fits its own model during its
    # regression test and does not claim full-curve NRMSE acceptance for this
    # published parameter set. This fixture's purpose is real-data ingestion,
    # provenance, and numerical execution without fabricating evidence.
    curve_result = validate_pvsyst_sdm_against_reference(
        _pvlib_mitsubishi_fitted_model(),
        dataset,
        validation_id="ivval-real-pvlib-curves-same-campaign",
        config=config,
    )

    assert curve_result["qualification"] == "same_source_validation"
    assert curve_result["coverage"]["reference_point_count"] == 12
    assert curve_result["coverage"]["curve_count"] == 12
    assert curve_result["aggregate"]["curve_evaluated_count"] == 12
    assert curve_result["aggregate"]["max_curve_current_nrmse_by_isc"] is not None
    assert curve_result["status"] in {"passed", "failed"}
