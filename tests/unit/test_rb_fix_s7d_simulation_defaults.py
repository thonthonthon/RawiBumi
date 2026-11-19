"""The browser reads exactly the options used to build real run configurations."""

from fastapi.testclient import TestClient

from apps.api.server import create_app
from apps.api.study import _phase5_configuration
from engine.simulation.design import build_project_revision_from_design
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def test_defaults_equal_real_run_configuration_and_need_no_project(tmp_path):
    # The endpoint must also work before any project/weather exists.
    client = TestClient(create_app(store_root=tmp_path / "empty" / "projects"))
    response = client.get("/api/simulation-defaults")
    assert response.status_code == 200
    defaults = response.json()
    project = Project(tmp_path / "run")
    bundle = project.bundle()
    electrical = project.study._simulation_electrical_snapshot(
        bundle["electrical_design"], project_revision_id="s7d-run", snapshot_id="s7d-electrical"
    )
    revision = build_project_revision_from_design(
        bundle["scene"], electrical, project_revision_id="s7d-run", revision_number=1,
        weather_dataset_revision_id=bundle["weather_selection"]["revision_id"],
        change_summary="S7d real-run configuration comparison.",
    )
    configuration = _phase5_configuration(revision, configuration_id="s7d-defaults-test")
    assert defaults["simulation_timestep_seconds"] == configuration["simulation_timestep_seconds"] == 3600
    for key in ("albedo", "thermal", "losses"):
        assert defaults[key] == configuration["numerical_options"][key]
    assert set(defaults) == {"albedo", "thermal", "losses", "simulation_timestep_seconds", "not_modelled", "module_quality", "loss_settings", "optics_thermal_settings", "shading_accuracy"}
    assert defaults["not_modelled"] == []
    assert defaults["loss_settings"]["defaults_id"] == "recommended_defaults.v2"
    assert defaults["loss_settings"]["values"]["soiling"]["monthly_fractions"] == [0.03] * 12
    assert defaults["module_quality"] == {"source": "pinned_module_definition", "fallback_loss_fraction": 0.0}
    # Mutating a response cannot change subsequent defaults or real runs.
    defaults["thermal"]["u_c_w_m2k"] = -999
    assert client.get("/api/simulation-defaults").json()["thermal"] == configuration["numerical_options"]["thermal"]
