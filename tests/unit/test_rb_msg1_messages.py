"""RB-MSG1: useful shortage totals and visible, non-blocking hash failures."""
from copy import deepcopy

import pytest

from electrical.topology import ElectricalTopologyEditorSession
from tests.unit.test_phase46_electrical_topology_editor import INVERTER, MODULE, _design, _scene, _session
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def _owner_session():
    scene = _scene()
    module = scene["module_instances"][0]
    scene["module_instances"] = [
        {**deepcopy(module), "module_instance_id": f"m-{i:03d}", "row_index": 0, "column_index": i}
        for i in range(182)
    ]
    definition = deepcopy(INVERTER)
    definition["mppt_template"].update(count=13, total_input_count=26)
    session = ElectricalTopologyEditorSession(
        scene, _design(), module_definitions={MODULE["revision_id"]: MODULE},
        inverter_definitions={definition["revision_id"]: definition},
    )
    session.add_inverter(inverter_instance_id="inv-02", inverter_definition_revision_id=definition["revision_id"], name="INV-02")
    session.apply_mppt_layout("inv-02", [[14]] * 13)
    return session


@pytest.mark.parametrize("release", [False, True])
@pytest.mark.parametrize("restricted", [False, True])
def test_owner_shortage_reports_whole_layout_and_inverter_pool(release, restricted):
    session = _owner_session()
    before = session.canonical_json()
    with pytest.raises(ValueError) as error:
        session.apply_mppt_layout("inv-02", [[18]] * 13, release_modules=release,
                                  sources=[["field-1"]] * 13 if restricted else None)
    expected = "not enough unstrung modules: this layout needs 234 modules; 182 are available for INV-02."
    if restricted:
        expected += f" MPPT {11 if release else 1} source fields field-1 need 18 modules; 182 are available."
    expected += " Use fewer or shorter strings."
    if not release:
        expected += " Its current strings hold 182 of them; apply from the Systems table or the Electrical step to re-use them."
    assert str(error.value) == expected
    assert session.canonical_json() == before


@pytest.mark.parametrize("pool", [None, ["field-1"]])
def test_source_shortage_counts_only_its_fields_and_enabled_free_modules(pool):
    scene = _scene()
    scene["pv_fields"].append({**deepcopy(scene["pv_fields"][0]), "pv_field_id": "field-2"})
    for module in scene["module_instances"][4:]:
        module["pv_field_id"] = "field-2"
    scene["module_instances"][0]["enabled"] = False
    session = ElectricalTopologyEditorSession(
        scene, _design(), module_definitions={MODULE["revision_id"]: MODULE},
        inverter_definitions={INVERTER["revision_id"]: INVERTER},
    )
    session.add_inverter(inverter_instance_id="inv", inverter_definition_revision_id=INVERTER["revision_id"], name="INV")
    with pytest.raises(ValueError) as error:
        session.apply_mppt_layout("inv", [[5], [0]], pv_field_ids=pool, sources=[["field-1"], None])
    assert str(error.value) == (
        f"not enough unstrung modules: this layout needs 5 modules; {3 if pool else 7} are available for INV."
        " MPPT 1 source fields field-1 need 5 modules; 3 are available. Use fewer or shorter strings."
    )


def test_shortage_includes_kept_reusable_free_and_held_modules_once():
    session = _session()
    session.add_inverter(inverter_instance_id="inv", inverter_definition_revision_id=INVERTER["revision_id"], name="INV")
    ids = [m["module_instance_id"] for m in _scene()["module_instances"]]
    for name, members in zip(["kept", "reuse", "held"], [ids[:2], ids[2:4], ids[4:6]]):
        session.create_string(string_id=name, module_instance_ids=members)
    session.assign_strings_to_mppt(["kept"], mppt_instance_id="inv-mppt-01")
    session.assign_strings_to_mppt(["held"], mppt_instance_id="inv-mppt-02")
    with pytest.raises(ValueError) as error:
        session.apply_mppt_layout("inv", [[2, 2], [3]])
    assert str(error.value) == (
        "not enough unstrung modules: this layout needs 7 modules; 8 are available for INV. Use fewer or shorter strings."
        " Its current strings hold 2 of them; apply from the Systems table or the Electrical step to re-use them."
    )


@pytest.mark.parametrize("exception", [KeyError, ValueError, TypeError, AttributeError, OverflowError, IndexError])
def test_unhashable_field_is_warned_without_blocking_readiness(tmp_path, monkeypatch, exception):
    project = Project(tmp_path, 18)
    assert project.study.execution_readiness(project.pid)["ready"]

    def broken_hash(scene, field):
        raise exception("broken packing input")

    monkeypatch.setattr("apps.api.execution_readiness.packing_input_hash", broken_hash)
    ready = project.study.execution_readiness(project.pid)
    warnings = [f for f in ready["findings"] if f["rule_id"] == "SCENE_PV_FIELD_LAYOUT_UNCHECKED"]
    assert ready["ready"] and len(warnings) == 1
    field_id = project.bundle()["scene"]["pv_fields"][0]["pv_field_id"]
    assert warnings[0]["severity"] == "warning" and warnings[0]["entity_id"] == field_id
    assert warnings[0]["message"] == (
        f"PV field {field_id}: its layout could not be compared with its packing inputs "
        f"({exception('broken packing input')}). Re-fill it if the roof or obstacles changed."
    )
