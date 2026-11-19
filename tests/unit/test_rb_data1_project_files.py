"""DATA1: project export/import, rolling and protected backups, corruption handling, schema migration."""
import io
import json
import zipfile

import pytest

import apps.api.migrations as migrations
from apps.api.project_store import BACKUPS_KEPT, PROTECTED_KEPT
from tests.unit.test_rb_fix_s2_honest_preflight import Project
from tests.unit.test_rb_ux1_imagery import overlay, png


@pytest.fixture
def p(tmp_path):
    project = Project(tmp_path, 18)
    asset = project.client.post(project.url + "/imagery/assets", params={"filename": "roof.png"}, content=png(400, 300)).json()["asset_id"]
    assert project.client.put(project.url + "/imagery", json=overlay(asset)).status_code == 200
    run = project.client.post(project.url + "/simulate", json={})
    assert run.status_code == 200, run.text
    return project


def tree(root):
    return {str(f.relative_to(root)): f.read_bytes() for f in sorted(root.rglob("*")) if f.is_file()} if root.is_dir() else {}


def state(p):
    return {"bundle": p.path.read_bytes(), "weather": tree(p.study.weather.root / p.pid), "runs": tree(p.study.run_root / p.pid),
            "imagery": tree(p.service.imagery.root / p.pid)}


def export(p, include_results=True):
    response = p.client.get(p.url + "/export", params={"include_results": include_results})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip" and ".rawibumi" in response.headers["content-disposition"]
    return response.content


def import_(p, data, replace=False):
    return p.client.post("/api/projects/import", params={"filename": "x.rawibumi", "replace": replace}, content=data)


def delete(p):
    assert p.client.request("DELETE", p.url, params={"confirm": p.pid}).status_code == 200


def test_round_trip_is_byte_identical_and_the_view_matches(p):
    before, view = state(p), p.client.get(p.url).json()
    data = export(p)
    delete(p)
    assert not p.path.exists() and not (p.service.store.root / ".backups" / p.pid).exists()
    response = import_(p, data)
    assert response.status_code == 200, response.text
    imported = state(p)
    for key in ("weather", "runs", "imagery"):
        assert imported[key] == before[key]
    original_bundle, imported_bundle = json.loads(before["bundle"]), json.loads(imported["bundle"])
    for run in imported_bundle["simulation_runs"]:
        assert run.pop("origin") == "imported"
    for run in original_bundle["simulation_runs"]:
        run.pop("origin", None)
    assert imported_bundle == original_bundle
    after = p.client.get(p.url).json()
    normalized = json.loads(json.dumps(after["bundle"]))
    original_view = json.loads(json.dumps(view["bundle"]))
    for run in normalized["simulation_runs"]:
        assert run.pop("origin") == "imported"
    for run in original_view["simulation_runs"]:
        run.pop("origin", None)
    assert normalized == original_view
    for key in ("design_fingerprint", "identity"):
        assert after[key] == view[key]
    assert after["history"]["past"] == [] and after["history"]["reason"] == "barrier"


def test_without_results_runs_keep_summaries_and_refuse_package_routes(p):
    run_id = p.bundle()["simulation_runs"][-1]["simulation_run_id"]
    summary = p.bundle()["simulation_runs"][-1]["summary_result"]
    data = export(p, include_results=False)
    names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    assert not any(n.startswith("runs/") for n in names)
    delete(p)
    assert import_(p, data).status_code == 200
    run = p.client.get(p.url).json()["bundle"]["simulation_runs"][-1]
    assert run["package_omitted"] is True and run["summary_result"] == summary
    refused = p.client.get(p.url + f"/runs/{run_id}/exports/schema")
    assert refused.status_code == 422 and "wasn't included" in json.dumps(refused.json())


def test_collision_needs_replace_and_replace_takes_a_protected_backup(p):
    data = export(p)
    p.service.update_project(p.pid, name="Changed after export")
    saved = state(p)
    refused = import_(p, data)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "project_exists"
    assert state(p) == saved
    replaced = import_(p, data, replace=True)
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["bundle"]["project"]["name"] == "S2 preflight"
    protected = [b for b in p.service.store.backups(p.pid) if b["protected"]]
    assert [b["reason"] for b in protected] == ["import-replace"]
    assert json.loads(p.service.store.read_backup(p.pid, protected[0]["backup_id"]))["project"]["name"] == "Changed after export"


def rewrite(data, mutate):
    source = zipfile.ZipFile(io.BytesIO(data))
    members = {n: source.read(n) for n in source.namelist()}
    mutate(members)
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in members.items():
            archive.writestr(name, value)
    return out.getvalue()


def remanifest(members):
    import hashlib
    manifest = json.loads(members["manifest.json"])
    manifest["members"] = [{"path": n, "bytes": len(v), "sha256": hashlib.sha256(v).hexdigest()} for n, v in members.items() if n != "manifest.json"]
    members["manifest.json"] = json.dumps(manifest).encode()


@pytest.mark.parametrize("name,mutate", [
    ("traversal", lambda m: (m.__setitem__("../escape.txt", b"x"), remanifest(m))),
    ("absolute", lambda m: (m.__setitem__("/abs.txt", b"x"), remanifest(m))),
    ("hash", lambda m: m.__setitem__("project.json", m["project.json"] + b" ")),
    ("unlisted", lambda m: m.__setitem__("weather/extra.json", b"{}")),
    ("no_manifest", lambda m: m.pop("manifest.json")),
    ("foreign_tree", lambda m: (m.__setitem__("projects/other.json", b"{}"), remanifest(m))),
    ("unknown_run", lambda m: (m.__setitem__("runs/run-unknown/x.json", b"{}"), remanifest(m))),
    ("bad_snapshot", lambda m: (m.__setitem__("weather-snapshots/sha256/00/" + "0" * 64 + ".json", b"{}"), remanifest(m))),
    ("newer_schema", lambda m: (m.__setitem__("project.json", m["project.json"].replace(b'"schema_version": "0.1"', b'"schema_version": "9.0"', 1)), remanifest(m))),
    ("not_a_project", lambda m: (m.__setitem__("project.json", b'{"schema_name": "Other"}'), remanifest(m))),
])
def test_hostile_or_damaged_archives_write_nothing(p, name, mutate):
    data = rewrite(export(p), mutate)
    delete(p)
    response = import_(p, data)
    assert response.status_code in (409, 422), (name, response.text)
    assert not p.path.exists() and not state_dirs(p)


def state_dirs(p):
    return [d for d in (p.study.weather.root / p.pid, p.study.run_root / p.pid, p.service.imagery.root / p.pid) if d.exists()]


def test_zip_bomb_and_non_zip_are_refused(p):
    assert import_(p, b"not a zip").status_code == 422
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", "{}")
        archive.writestr("bomb.bin", b"\0" * (300 * 1024 * 1024))
    response = import_(p, out.getvalue())
    assert response.status_code == 422 and "expands beyond" in response.json()["detail"]["message"]


def test_rolling_backups_keep_twenty_and_protected_ten(p):
    for i in range(BACKUPS_KEPT + 5):
        p.service.update_project(p.pid, description=f"edit {i}")
    rolling = [b for b in p.service.store.backups(p.pid) if not b["protected"]]
    assert len(rolling) == BACKUPS_KEPT
    # The newest backup is the current saved state; the next one the state before it.
    newest = json.loads(p.service.store.read_backup(p.pid, rolling[0]["backup_id"]))
    assert newest["project"]["description"] == f"edit {BACKUPS_KEPT + 4}"
    assert json.loads(p.service.store.read_backup(p.pid, rolling[1]["backup_id"]))["project"]["description"] == f"edit {BACKUPS_KEPT + 3}"
    for _ in range(PROTECTED_KEPT + 3):
        p.service.store.protect(p.pid, "restore")
    assert len([b for b in p.service.store.backups(p.pid) if b["protected"]]) == PROTECTED_KEPT
    listed = p.client.get(p.url + "/backups").json()
    assert listed == p.service.store.backups(p.pid)
    delete(p)
    assert not (p.service.store.root / ".backups" / p.pid).exists()


def test_restore_is_checked_protected_and_a_history_barrier(p):
    p.service.update_project(p.pid, name="Second name")
    backup = [b for b in p.service.store.backups(p.pid) if not b["protected"]][1]
    restored = p.client.post(p.url + f"/backups/{backup['backup_id']}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["bundle"]["project"]["name"] == "S2 preflight"
    assert restored.json()["history"]["past"] == []
    assert [b["reason"] for b in p.service.store.backups(p.pid) if b["protected"]] == ["restore"]
    assert p.client.post(p.url + "/backups/not-a-backup/restore").status_code == 404


def test_corrupt_file_is_listed_refused_clearly_and_restorable(p):
    p.service.update_project(p.pid, name="Good state")
    p.path.write_bytes(b'{"schema_name": "ProjectWorkspaceBundle", "truncated')
    row = next(r for r in p.client.get("/api/projects").json() if r["project_id"] == p.pid)
    assert row["status"] == "unreadable" and "not valid JSON" in row["reason"]
    refused = p.client.get(p.url)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "project_unreadable"
    backup = p.client.get(p.url + "/backups").json()[0]["backup_id"]
    restored = p.client.post(p.url + f"/backups/{backup}/restore")
    assert restored.status_code == 200, restored.text
    assert restored.json()["bundle"]["project"]["name"] == "Good state"


def test_migration_chain_persists_once_with_a_protected_backup_and_newer_is_refused(p, monkeypatch):
    def upgrade(bundle):
        bundle["schema_version"] = "0.1"
        bundle["project"]["description"] = (bundle["project"].get("description") or "") + " [upgraded]"
        return bundle
    monkeypatch.setitem(migrations.MIGRATIONS, "0.0", ("0.1", upgrade))
    raw = json.loads(p.path.read_bytes())
    raw["schema_version"] = "0.0"
    p.path.write_text(json.dumps(raw))
    view = p.client.get(p.url).json()
    assert view["bundle"]["schema_version"] == "0.1" and view["bundle"]["project"]["description"].endswith("[upgraded]")
    assert json.loads(p.path.read_bytes())["schema_version"] == "0.1"
    assert [b["reason"] for b in p.service.store.backups(p.pid) if b["protected"]] == ["schema-upgrade"]
    p.client.get(p.url)
    assert [b["reason"] for b in p.service.store.backups(p.pid) if b["protected"]] == ["schema-upgrade"]
    raw = json.loads(p.path.read_bytes())
    raw["schema_version"] = "0.2"
    p.path.write_text(json.dumps(raw))
    saved = p.path.read_bytes()
    refused = p.client.get(p.url)
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "project_too_new"
    assert "newer RawiBumi" in refused.json()["detail"]["message"] and p.path.read_bytes() == saved
