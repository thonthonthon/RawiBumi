"""DEC-29 changes only the electrical structural-repair refusal's representation."""

import pytest

from tests.unit.test_rb_fix_s5_electrical_commands import (
    project, _broken_string, _command, _ids, _post,
)


def test_preexisting_repair_refusal_is_structured_and_never_saves(project):
    command = _broken_string(project)
    before = project.path.read_bytes()
    result = _post(project, [command])
    assert result.status_code == 422
    detail = result.json()["detail"]
    assert detail["message"] == (
        "Electrical design has structural consistency errors; repair them in this batch "
        "(for example with delete_string or unassign_strings) before committing (1 errors)."
    )
    assert "[" not in detail["message"]
    assert len(detail["findings"]) == 1
    finding = detail["findings"][0]
    assert finding["code"] == "string_unknown_module"
    assert finding["entity_id"] == "legacy"
    assert finding["origin"] == "pre-existing"
    assert "missing-legacy-module" in finding["message"]
    assert project.path.read_bytes() == before


@pytest.mark.parametrize("kind,parameters", [
    ("delete_string", {"string_id": "not-a-string"}),
    ("assign_strings_to_mppt", {"string_ids": ["missing"], "mppt_instance_id": "missing"}),
    ("create_string", {"module_instance_ids": ["not-a-module"]}),
])
def test_other_command_refusals_still_have_string_details(project, kind, parameters):
    before = project.path.read_bytes()
    result = _post(project, [_command(kind, parameters, "other-refusal")])
    assert result.status_code == 422
    assert isinstance(result.json()["detail"], str)
    assert result.json()["detail"].startswith(f"command 0 (other-refusal, {kind}):")
    assert project.path.read_bytes() == before
