"""S2: real validator parity and execution-plan-based exclusion disclosure."""

from copy import deepcopy
import json
from pathlib import Path
from time import perf_counter

from fastapi.testclient import TestClient
from jsonschema import ValidationError

from apps.api.execution_readiness import (
    design_validation_readiness_findings,
    phase5_execution_readiness,
)
from apps.api.server import create_app
from apps.api.study import _validation_configuration
from engine.simulation.detailed_inputs import DetailedInputError
from validation.engineering import validate_engineering_design
from components.design_integration import module_nameplate_w  # D14: the DC nameplate basis


ROOT = Path(__file__).resolve().parents[2]
MODULE = "mod-rawibumi-uat-550-r1"
INVERTER = "inv-rawibumi-uat-150k-r1"


class Project:
    def __init__(self, tmp_path, count=20, *, weather=True, strings=True, string_length=None):
        self.app = create_app(store_root=tmp_path / "projects")
        self.service = self.app.state.project_service
        self.study = self.app.state.study_service
        self.client = TestClient(self.app)
        bundle = self.service.create_project(name="S2 preflight", latitude_deg=-6.2,
            longitude_deg=106.8, timezone_name="Asia/Jakarta", elevation_m=25)
        self.pid = bundle["project"]["project_id"]
        self.url = f"/api/projects/{self.pid}"
        self.path = self.service.store.path_for(self.pid)
        view = self.service.add_surface_rectangle(self.pid, name="Exact-count roof",
            origin_x_m=0, origin_y_m=0, width_m=1 + count * 1.154 - 0.01,
            height_m=3.45, base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
        surface_id = view["bundle"]["scene"]["surfaces"][0]["surface_id"]
        self.service.create_pv_field(self.pid, name="Exact-count field", support_surface_id=surface_id,
            module_definition_revision_id=MODULE, tilt_deg=10, row_pitch_m=3.2,
            perimeter_setback_m=0.5, obstacle_setback_m=0.3)
        assert len(self.bundle()["scene"]["module_instances"]) == count
        view = self.service.add_inverter(self.pid, inverter_definition_revision_id=INVERTER, name="INV")
        inverter_id = view["bundle"]["electrical_design"]["inverter_instances"][0]["inverter_instance_id"]
        if strings:
            self.service.create_strings(self.pid, string_length=string_length or count,
                allow_shorter_remainder=True)
            created = self.bundle()["electrical_design"]["strings"]
            self.service.assign_strings(self.pid, inverter_instance_id=inverter_id,
                string_ids=[s["string_id"] for s in created[:6]])
        if weather:
            self.study.acquire_weather(self.pid, source_id="open_meteo_archive_era5",
                start_date="2025-01-01", end_date="2025-01-01", raw_response=(
                    ROOT / "tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json"
                ).read_bytes())

    def bundle(self):
        return self.service.get_bundle(self.pid)

    def readiness(self):
        response = self.client.get(self.url + "/execution-readiness")
        assert response.status_code == 200, response.text
        return response.json()

    def direct_validation(self):
        bundle = self.bundle()
        electrical = self.study._simulation_electrical_snapshot(bundle["electrical_design"],
            project_revision_id="browser-preflight", snapshot_id="browser-preflight-electrical")
        return validate_engineering_design(bundle["scene"], electrical,
            project_revision_id="browser-preflight",
            component_revisions={**bundle["pinned_components"]["modules"], **bundle["pinned_components"]["inverters"]},
            configuration=_validation_configuration(), design_validation_report_id="browser-preflight",
            generated_at="2026-10-29T00:00:00Z")


def _exclusion(readiness):
    return next(f for f in readiness["findings"] if f["rule_id"] == "MODULES_NOT_SIMULATED")


def _assert_plan_count(bundle, readiness):
    placed = {m["module_instance_id"] for m in bundle["scene"]["module_instances"] if m.get("enabled", True)}
    simulated = {mid for g in readiness["execution_plan"]["groups"] for mid in g["module_instance_ids"]}
    warning = _exclusion(readiness)
    assert warning["context"]["module_count"] == len(placed - simulated)
    assert warning["context"]["module_instance_ids"] == sorted(placed - simulated)[:200]
    assert warning["context"]["omitted_module_count"] == max(0, len(placed - simulated) - 200)
    assert warning["severity"] == "warning"
    assert readiness["findings"][-1] == warning
    return warning


def test_01_validation_blocker_returns_preflight_422_without_saving(tmp_path):
    project = Project(tmp_path, 21)
    before = project.path.read_bytes()
    ready = project.readiness()
    assert not ready["ready"]
    finding = next(f for f in ready["findings"] if f["rule_id"] == "STRING_VOC_EXCEEDS_INVERTER_MAX_DC")
    assert finding["severity"] == "blocking_error" and finding["category"] == "design_validation"
    context = finding["context"]
    assert context["measured_value"] > context["limit_value"]
    assert context["unit"] == "V"
    response = project.client.post(project.url + "/simulate", json={})
    assert response.status_code == 422
    assert "simulation execution preflight failed" in response.json()["detail"]
    assert project.client.get(project.url + "/runs").json() == []
    assert project.path.read_bytes() == before


def test_02_readiness_blockers_equal_direct_validator_for_audit_counts(tmp_path):
    for count in (21, 24, 5, 4):
        project = Project(tmp_path / str(count), count)
        report = project.direct_validation()
        expected = {f["rule_id"] for f in report["findings"] if f["severity"] == "blocking_error"}
        ready = project.readiness()
        actual = {f["rule_id"] for f in ready["findings"] if f["severity"] == "blocking_error"}
        assert expected and actual == expected, (count, actual, expected)
        assert not ready["ready"]


def test_03_valid_twenty_module_string_and_lossless_actionable_mapping(tmp_path, monkeypatch):
    project = Project(tmp_path)
    ready = project.readiness()
    assert ready["ready"]
    assert not any(f["severity"] in {"blocking_error", "info"} for f in ready["findings"])
    assert any(f["severity"] == "info" for f in project.direct_validation()["findings"])
    # Pin the mapper's order, retained evidence, omission of ephemeral fields,
    # detached context, and non-blocking treatment of severity=error.
    findings = [{
        "rule_id": rule, "severity": severity, "entity_id": "entity", "message": rule,
        "category": "electrical", "classification": "WARNING", "measured_value": 10,
        "limit_value": 9, "unit": "V", "context": {"evidence": [1]},
        "finding_id": "per-call", "generated_at": "per-call", "project_revision_id": "per-call",
        "resolved_at": "per-call", "resolution_note": "per-call",
    } for rule, severity in (("Z_WARNING", "warning"), ("A_ERROR", "error"), ("INFO", "info"))]
    mapped = design_validation_readiness_findings({"findings": findings})
    assert [f["rule_id"] for f in mapped] == ["Z_WARNING", "A_ERROR"]
    assert mapped[0] == {
        "rule_id": "Z_WARNING", "severity": "warning", "category": "design_validation",
        "entity_id": "entity", "message": "Z_WARNING", "context": {
            "validation_category": "electrical", "classification": "WARNING", "measured_value": 10,
            "limit_value": 9, "unit": "V", "context": {"evidence": [1]},
        },
    }
    mapped[0]["context"]["context"]["evidence"].append(2)
    assert findings[0]["context"] == {"evidence": [1]}
    monkeypatch.setattr("apps.api.study.validate_engineering_design", lambda *a, **k: {"findings": findings})
    assert project.readiness()["ready"] is True


def test_04_validation_does_not_require_weather(tmp_path):
    project = Project(tmp_path, 21, weather=False)
    ready = project.readiness()
    rules = {f["rule_id"] for f in ready["findings"]}
    assert {"EXECUTION_WEATHER_REVISION_REQUIRED", "STRING_VOC_EXCEEDS_INVERTER_MAX_DC"} <= rules
    assert not ready["ready"]


def test_05_validation_or_snapshot_failure_is_reported_without_raising(tmp_path, monkeypatch):
    project = Project(tmp_path, weather=False)
    before = project.path.read_bytes()
    for error in (ValueError("injected value error"), KeyError("injected missing key"),
                  TypeError("injected type error"), ValidationError("injected schema error")):
        def fail(*args, **kwargs):
            raise error
        with monkeypatch.context() as context:
            context.setattr("apps.api.study.validate_engineering_design", fail)
            ready = project.readiness()
        unavailable = [f for f in ready["findings"] if f["rule_id"] == "DESIGN_VALIDATION_UNAVAILABLE"]
        assert len(unavailable) == 1 and unavailable[0]["severity"] == "blocking_error"
        assert str(error) in unavailable[0]["message"]
        assert any(f["rule_id"] == "EXECUTION_WEATHER_REVISION_REQUIRED" for f in ready["findings"])
        assert not ready["ready"]
    with monkeypatch.context() as context:
        def fail_snapshot(*args, **kwargs):
            raise ValueError("injected snapshot failure")
        context.setattr(project.study, "_simulation_electrical_snapshot", fail_snapshot)
        assert "injected snapshot failure" in next(f["message"] for f in project.readiness()["findings"]
            if f["rule_id"] == "DESIGN_VALIDATION_UNAVAILABLE")
    assert project.path.read_bytes() == before


def test_06_remainder_is_disclosed_without_blocking_ready_design(tmp_path):
    project = Project(tmp_path, 119, string_length=19)
    ready = project.readiness()
    assert ready["ready"], ready["findings"]
    warning = _assert_plan_count(project.bundle(), ready)
    assert warning["context"]["module_count"] == 5
    assert warning["context"]["by_reason"] == {"string_unassigned": 5}
    assert warning["context"]["stc_power_w"] == 5 * module_nameplate_w(project.bundle()["pinned_components"]["modules"][MODULE])
    assert warning["context"]["stc_power_incomplete"] is False
    assert "5 placed modules (2.75 kWp STC)" in warning["message"]


def test_07_unstrung_modules_disabled_placements_and_unpinned_power(tmp_path):
    project = Project(tmp_path, strings=False)
    bundle = project.bundle()
    ready = project.readiness()
    assert _assert_plan_count(bundle, ready)["context"]["by_reason"] == {"unstrung": 20}
    bundle["scene"]["module_instances"][0]["enabled"] = False
    bundle["pinned_components"]["modules"] = {}
    ready = phase5_execution_readiness(bundle)
    warning = _assert_plan_count(bundle, ready)
    assert warning["context"]["by_reason"] == {"unstrung": 19}
    assert warning["context"]["stc_power_w"] == 0
    assert warning["context"]["stc_power_incomplete"] is True
    for pmp in ("invalid", None, float("nan"), -1):
        bundle["pinned_components"]["modules"][MODULE] = deepcopy(project.service.catalog["modules"][MODULE])
        bundle["pinned_components"]["modules"][MODULE]["stc"].pop("nominal_power_w", None)  # D14: make pmp_w the basis under test
        bundle["pinned_components"]["modules"][MODULE]["stc"]["pmp_w"] = pmp
        warning = _assert_plan_count(bundle, phase5_execution_readiness(bundle))
        assert warning["context"]["stc_power_w"] == 0
        assert warning["context"]["stc_power_incomplete"] is True


def test_08_exclusion_reason_precedence_and_missing_or_disabled_targets(tmp_path):
    project = Project(tmp_path, 119, string_length=19)
    original = project.bundle()
    for missing in (False, True):
        bundle = deepcopy(original)
        electrical = bundle["electrical_design"]
        assigned = [s for s in electrical["strings"] if s["target_mppt_instance_id"] is not None]
        # One string retains its target but is disabled; the other two on that
        # MPPT see the missing/disabled MPPT before the inverter condition.
        assigned[0]["enabled"] = False
        target = assigned[0]["target_mppt_instance_id"]
        if missing:
            electrical["mppt_instances"] = [m for m in electrical["mppt_instances"] if m["mppt_instance_id"] != target]
            electrical["inverter_instances"] = []
        else:
            next(m for m in electrical["mppt_instances"] if m["mppt_instance_id"] == target)["enabled"] = False
            electrical["inverter_instances"][0]["enabled"] = False
        warning = _assert_plan_count(bundle, phase5_execution_readiness(bundle))
        assert warning["context"]["by_reason"] == {
            "string_disabled": 19, "mppt_missing_or_disabled": 38,
            "inverter_missing_or_disabled": 57, "string_unassigned": 5,
        }
        assert warning["context"]["module_count"] == 119


def test_08b_execution_plan_fallback_keeps_exact_excluded_count_and_error_codes(tmp_path, monkeypatch):
    project = Project(tmp_path)
    bundle = project.bundle()
    field = deepcopy(bundle["scene"]["pv_fields"][0])
    field.update(pv_field_id="different-irradiance-field", tilt_deg=float("nan"))
    bundle["scene"]["pv_fields"].append(field)
    bundle["scene"]["module_instances"][0]["pv_field_id"] = field["pv_field_id"]
    ready = phase5_execution_readiness(bundle)
    warning = _assert_plan_count(bundle, ready)
    assert warning["context"]["by_reason"] == {"execution_plan_excluded": 20}
    assert warning["context"]["plan_finding_codes"] == ["execution_group_irradiance_state_invalid"]
    plan = deepcopy(ready["execution_plan"])
    plan["findings"].append({"severity": "error", "code": "execution_group_mppt_heterogeneous",
        "entity_id": None, "context": {"mppt_instance_ids": [bundle["electrical_design"]["strings"][0]["target_mppt_instance_id"]]}})
    plan["findings"].append({"severity": "error", "code": "unrelated_error", "entity_id": "unrelated", "context": {}})
    monkeypatch.setattr("apps.api.execution_readiness.build_simulation_execution_plan", lambda *a, **k: plan)
    warning = _assert_plan_count(bundle, phase5_execution_readiness(bundle))
    assert warning["context"]["plan_finding_codes"] == [
        "execution_group_irradiance_state_invalid", "execution_group_mppt_heterogeneous",
    ]
    plan["findings"] = [plan["findings"][-1]]
    assert _exclusion(phase5_execution_readiness(bundle))["context"]["plan_finding_codes"] == ["unrelated_error"]


def test_09_fully_assigned_design_has_no_exclusion_warning(tmp_path):
    project = Project(tmp_path)
    assert not any(f["rule_id"] == "MODULES_NOT_SIMULATED" for f in project.readiness()["findings"])


def test_10_detailed_paths_keep_parent_findings_with_warning_last(tmp_path, monkeypatch):
    from tests.unit.test_phase69b_browser_launch import setup_project, REQUEST
    app, pid, original = setup_project(tmp_path)
    service, study = app.state.project_service, app.state.study_service
    request = REQUEST["electrical_shading_configuration"]
    assert study.execution_readiness(pid, request)["findings"] == []
    blocked = {"rule_id": "EXISTING_VALIDATION", "severity": "blocking_error", "entity_id": "existing",
               "category": "electrical", "message": "existing detailed validation", "generated_at": "retain-me"}
    for path in ("weather_missing", "validation_blocked", "success", "detailed_error", "fallback"):
        with monkeypatch.context() as context:
            report = {"blocking_simulation": path == "validation_blocked",
                      "findings": [blocked] if path == "validation_blocked" else []}
            context.setattr("apps.api.study.validate_engineering_design", lambda *a, **k: report)
            def resolve(*args, **kwargs):
                if path in {"detailed_error", "fallback"}:
                    raise DetailedInputError("existing unsupported detailed input")
            context.setattr("apps.api.study._resolve", resolve)
            local_request = {**request, "fallback_policy": "explicit_lower_fidelity" if path == "fallback" else "fail_closed"}
            bundle = deepcopy(original)
            if path == "weather_missing":
                bundle["weather_selection"] = None
            service.store.save(bundle)
            baseline = study.execution_readiness(pid, local_request)
            if path == "validation_blocked":
                assert baseline["findings"] == [blocked]
            elif path == "weather_missing":
                assert baseline["findings"] == [{
                    "rule_id": "EXECUTION_WEATHER_REVISION_REQUIRED", "severity": "blocking_error",
                    "category": "execution_readiness", "entity_id": None,
                    "message": "Acquire or select a pinned WeatherDataset revision before simulation.", "context": {},
                }]
            elif path == "success":
                assert baseline["findings"] == [] and baseline["ready"] is True
            else:
                assert baseline["findings"] == [{
                    "rule_id": "DETAILED_EXECUTION_PREFLIGHT", "severity": "warning" if path == "fallback" else "blocking_error",
                    "category": "execution", "message": "existing unsupported detailed input",
                }]
                assert baseline["ready"] is (path == "fallback")
            extra = deepcopy(bundle["scene"]["module_instances"][0])
            extra["module_instance_id"] = "unstrung-detailed-module"
            extra["transform"]["position_x_m"] += 100
            bundle["scene"]["module_instances"].append(extra)
            service.save_bundle(bundle)
            with_warning = study.execution_readiness(pid, local_request)
            assert with_warning["findings"][:-1] == baseline["findings"]
            assert with_warning["findings"][-1]["rule_id"] == "MODULES_NOT_SIMULATED"
            assert with_warning["findings"][-1]["context"]["by_reason"] == {"unstrung": 1}
            assert with_warning["ready"] == baseline["ready"]
            assert with_warning["execution_class"] == baseline["execution_class"]


def test_11_legacy_readiness_is_byte_deterministic_and_read_only(tmp_path):
    project = Project(tmp_path, 21)
    before = project.path.read_bytes()
    a = project.client.get(project.url + "/execution-readiness")
    b = project.client.get(project.url + "/execution-readiness")
    assert a.status_code == b.status_code == 200
    assert a.content == b.content
    assert not any(key in json.dumps(a.json()) for key in (
        '"finding_id"', '"generated_at"', '"resolved_at"', '"resolution_note"',
    ))
    assert project.path.read_bytes() == before


def test_12_two_thousand_modules_readiness_under_two_seconds(tmp_path, record_property):
    project = Project(tmp_path, 2000, string_length=20)
    start = perf_counter()
    ready = project.readiness()
    elapsed = perf_counter() - start
    record_property("readiness_2000_modules_seconds", elapsed)
    assert elapsed < 2.0, f"2,000-module readiness took {elapsed:.3f}s; escalate, do not relax the bound"
    assert _assert_plan_count(project.bundle(), ready)["context"]["module_count"] == 1880
