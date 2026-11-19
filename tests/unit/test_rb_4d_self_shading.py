"""RB-4D: browser runs always include module self-shading (row-to-row), and each new run records it."""
import json

from tests.unit.test_rb_fix_s2_honest_preflight import Project


def test_generated_field_run_records_module_self_shading(tmp_path):
    p = Project(tmp_path, 18)
    assert all(f.get("field_kind") != "explicit_layout" for f in p.bundle()["scene"]["pv_fields"])
    response = p.client.post(p.url + "/simulate", json={})
    assert response.status_code == 200, response.text
    record = response.json()
    assert record["module_self_shading"] is True
    assert p.bundle()["simulation_runs"][-1]["module_self_shading"] is True
    # The immutable run package records the configuration the engine actually used.
    manifest = json.loads(next((p.study.run_root / p.pid / record["simulation_run_id"]).rglob("reproducibility-manifest.json")).read_text())
    assert manifest["shading_configuration"]["self_shading_enabled"] is True
