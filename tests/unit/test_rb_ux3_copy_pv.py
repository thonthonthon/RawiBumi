"""UX3: paste a roof together with its PV (the UX2 `copy` command with `with_pv`)."""
from copy import deepcopy

import pytest

from geometry.pvfield.explicit import create_explicit_field
from tests.unit.test_rb_fix_s2_honest_preflight import MODULE, Project


def command(roof, dx, dy=0.0, with_pv=True):
    return {"command": {"schema_name": "SceneEditorCommand", "schema_version": "0.1", "command_id": "ux3-paste", "command_type": "copy",
                        "target_entity_ids": [roof], "parameters": {"dx_m": dx, "dy_m": dy, **({"with_pv": True} if with_pv else {})}}}


@pytest.fixture
def p(tmp_path):
    return Project(tmp_path, 18, weather=False, strings=True)


def roof(bundle, name="Exact-count roof"):
    return next(s for s in bundle["scene"]["surfaces"] if s["name"] == name)


def fields_on(bundle, surface_id):
    return [f for f in bundle["scene"]["pv_fields"] if f.get("support_surface_id") == surface_id
            or any(t.get("support_surface_id") == surface_id for t in f.get("tables") or [])]


def modules_of(bundle, field_id):
    return [m for m in bundle["scene"]["module_instances"] if m["pv_field_id"] == field_id]


def test_generated_field_is_refilled_on_the_pasted_roof_unstrung_in_one_undo_step(p):
    before = p.bundle()
    source = roof(before)
    [field] = fields_on(before, source["surface_id"])
    response = p.client.post(p.url + "/scene/commands", json=command(source["surface_id"], 40))
    assert response.status_code == 200, response.text
    view = response.json()
    after = view["bundle"]
    clone = roof(after, "Exact-count roof copy")
    [copy] = fields_on(after, clone["surface_id"])
    assert copy["pv_field_id"] != field["pv_field_id"] and copy["name"] == "Exact-count field copy"
    for key in ("module_definition_revision_id", "orientation", "tilt_deg", "azimuth_deg", "row_pitch_m", "module_gap_x_m", "setback_configuration", "packing_parameters"):
        assert copy[key] == field[key], key
    original, pasted = modules_of(before, field["pv_field_id"]), modules_of(after, copy["pv_field_id"])
    assert len(pasted) == len(original) == 18
    shifted = sorted((round(m["transform"]["position_x_m"] + 40, 9), round(m["transform"]["position_y_m"], 9)) for m in original)
    assert sorted((round(m["transform"]["position_x_m"], 9), round(m["transform"]["position_y_m"], 9)) for m in pasted) == shifted
    strung = {mid for s in after["electrical_design"]["strings"] for mid in s["module_instance_ids"]}
    assert not strung & {m["module_instance_id"] for m in pasted}
    assert after["electrical_design"] == before["electrical_design"]
    assert after["project"]["project_revision"]["revision_number"] == before["project"]["project_revision"]["revision_number"] + 1
    assert view["history"]["past"][-1]["label"] == "Paste Exact-count roof with PV."
    entry = view["history"]["past"][-1]["entry_id"]
    undone = p.client.post(p.url + "/undo", json={"expected_project_revision_id": after["project"]["project_revision"]["project_revision_id"], "expected_entry_id": entry})
    assert undone.status_code == 200, undone.text
    assert undone.json()["bundle"]["scene"]["pv_fields"] == before["scene"]["pv_fields"]
    assert undone.json()["bundle"]["scene"]["module_instances"] == before["scene"]["module_instances"]


def test_without_with_pv_the_copy_is_an_empty_roof_as_before(p):
    source = roof(p.bundle())
    after = p.client.post(p.url + "/scene/commands", json=command(source["surface_id"], 40, with_pv=False)).json()["bundle"]
    assert fields_on(after, roof(after, "Exact-count roof copy")["surface_id"]) == []


def test_overlapping_paste_is_refused_and_nothing_is_written(p):
    source = roof(p.bundle())
    saved = p.path.read_bytes()
    response = p.client.post(p.url + "/scene/commands", json=command(source["surface_id"], 0.4))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["conflicts"]
    assert p.path.read_bytes() == saved


def test_edge_specific_setbacks_are_refused_with_a_reason(p):
    raw = p.bundle()
    raw["scene"]["pv_fields"][0]["setback_configuration"]["edge_specific_setbacks"] = {"0": 1.0}
    p.service.save_bundle(raw, history_mode="neutral")
    saved = p.path.read_bytes()
    response = p.client.post(p.url + "/scene/commands", json=command(roof(raw)["surface_id"], 40))
    assert response.status_code == 422 and "edge-specific setbacks" in response.text
    assert p.path.read_bytes() == saved


def test_explicit_tables_on_that_roof_are_rebuilt_moved_and_other_roofs_tables_stay(tmp_path):
    p = Project(tmp_path, 18, weather=False, strings=False)
    p.service.add_surface_rectangle(p.pid, name="Far roof", origin_x_m=100, origin_y_m=0, width_m=8, height_m=6,
                                    base_elevation_m=6.1, surface_type="flat_roof", usable_for_pv=True)
    raw = p.bundle()
    near, far = roof(raw), roof(raw, "Far roof")
    raw["scene"]["pv_fields"] = [f for f in raw["scene"]["pv_fields"] if f.get("support_surface_id") != near["surface_id"]]
    raw["scene"]["module_instances"] = []
    definitions = p.service._component_definitions(raw, "modules")
    def table(table_id, surface, x):
        return {"table_id": table_id, "anchor_xyz_m": [x, 1.7, 6.1], "anchor_convention": "center", "tilt_deg": 0.0, "azimuth_deg": 180.0,
                "module_definition_revision_id": MODULE, "modules_across": 3, "modules_up": 1, "module_orientation": "portrait",
                "module_gap_across_m": 0.02, "module_gap_up_m": 0.02, "support_surface_id": surface}
    field, modules = create_explicit_field(raw["scene"], definitions, pv_field_id="field-explicit", name="Tables",
                                           tables=[table("t-near", near["surface_id"], 6.0), table("t-far", far["surface_id"], 104.0)], provenance={"source_id": "test"})
    raw["scene"]["pv_fields"].append(field)
    raw["scene"]["module_instances"].extend(modules)
    p.service.save_bundle(raw, history_mode="neutral")
    response = p.client.post(p.url + "/scene/commands", json=command(near["surface_id"], 40, 2))
    assert response.status_code == 200, response.text
    after = response.json()["bundle"]
    clone = roof(after, "Exact-count roof copy")
    [copy] = [f for f in after["scene"]["pv_fields"] if f["pv_field_id"] != "field-explicit"]
    assert copy["field_kind"] == "explicit_layout" and copy["name"] == "Tables copy"
    assert copy["provenance"]["copied_from_pv_field_id"] == "field-explicit"
    [t] = copy["tables"]
    assert t["support_surface_id"] == clone["surface_id"] and t["anchor_xyz_m"] == [46.0, 3.7, 6.1] and t["table_id"] != "t-near"
    assert len(modules_of(after, copy["pv_field_id"])) == 3
    assert next(f for f in after["scene"]["pv_fields"] if f["pv_field_id"] == "field-explicit") == next(
        f for f in raw["scene"]["pv_fields"] if f["pv_field_id"] == "field-explicit")
