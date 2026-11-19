"""DATA1: one-file project export (.rawibumi, a ZIP) and its checked, staged import.

An archive holds manifest.json (every member with its size and sha256), project.json, the project's weather
revisions and the snapshots they reference, its overlay images, and, optionally, its saved run packages. Import
verifies the archive before anything is written, and writes through a staging directory so a failure leaves nothing.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any
import zipfile
from .safe_paths import (PATTERNS, safe_component, contained, relative_member,
                         bundle_identifiers, snapshot_hashes, run_identifiers)

FORMAT = "rawibumi-project"
FORMAT_VERSION = 1
MAX_MEMBERS = 5000
MAX_UNCOMPRESSED = 2 * 1024**3
MAX_RATIO = 200  # a member may expand at most 200x (zip-bomb guard)
_SNAPSHOT = re.compile(r"sha256/[0-9a-f]{2}/" + PATTERNS["hash"] + PATTERNS["snapshot_suffix"])
OMITTED = "This run's result package wasn't included in the imported file."


class ArchiveError(ValueError):
    def __init__(self, message: str, *, status: int = 422, code: str = "archive_invalid") -> None:
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tree(root: Path, prefix: str) -> list[tuple[str, Path]]:
    if not root.is_dir():
        return []
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            continue
        contained(root, path)
        relative_member(path.relative_to(root).as_posix())
        if path.is_file():
            rows.append((f"{prefix}/{path.relative_to(root).as_posix()}", path))
    return rows


def _snapshot_refs(manifest: Any) -> set[str]:
    return snapshot_hashes(manifest)


def export_project(service, study, project_id: str, *, include_results: bool) -> tuple[str, bytes]:
    from .study import ENGINE_VERSION
    """(filename, ZIP bytes). The bundle is read under the store lock, so the archive is one consistent state."""
    with service.store._lock:
        bundle = service.get_bundle(project_id)
        members: list[tuple[str, bytes]] = []
        if not include_results:
            for run in bundle.get("simulation_runs", []):
                run["package_omitted"] = True
        members.append(("project.json", json.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode()))
        safe_component(project_id, "project")
        weather_root = contained(study.weather.root, study.weather.root / project_id)
        snapshots: set[str] = set()
        for name, path in _tree(weather_root, "weather"):
            data = path.read_bytes()
            members.append((name, data))
            if name.endswith("acquisition-manifest.json"):
                snapshots |= _snapshot_refs(json.loads(data))
        for digest in sorted(snapshots):
            safe_component(digest, "hash")
            directory = contained(study.snapshots.root, study.snapshots.root / "sha256" / digest[:2])
            for path in sorted(directory.glob(f"{digest}.*")):
                contained(directory, path)
                safe_component(path.suffix, "snapshot_suffix")
                members.append((f"weather-snapshots/{path.relative_to(study.snapshots.root).as_posix()}", path.read_bytes()))
        imagery_root = contained(service.imagery.root, service.imagery.root / project_id)
        members += [(name, path.read_bytes()) for name, path in _tree(imagery_root, "imagery")]
        if include_results:
            run_root = contained(study.run_root, study.run_root / project_id)
            members += [(name, path.read_bytes()) for name, path in _tree(run_root, "runs")]
    manifest = {"format": FORMAT, "format_version": FORMAT_VERSION, "exported_at": datetime.now(timezone.utc).isoformat(),
                "engine_version": ENGINE_VERSION, "project_id": project_id,
                "project_name": bundle["project"].get("name"), "schema_name": bundle["schema_name"],
                "schema_version": bundle["schema_version"], "include_results": include_results,
                "members": [{"path": n, "bytes": len(d), "sha256": _sha(d)} for n, d in members]}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        for name, data in members:
            archive.writestr(name, data)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(bundle["project"].get("name") or "project")).strip("_")[:60] or "project"
    return f"{safe}-{project_id}.rawibumi", buffer.getvalue()


def _read_checked(data: bytes) -> tuple[dict[str, Any], dict[str, bytes]]:
    """The manifest and every member's bytes, after the safety and integrity checks; nothing is written."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ArchiveError("This is not a RawiBumi project file (not a ZIP archive).") from exc
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ArchiveError(f"The project file has more than {MAX_MEMBERS} entries.")
    total = 0
    for info in infos:
        name = info.filename
        relative_member(name)
        path = PurePosixPath(name)
        if name.startswith("/") or "\\" in name or ".." in path.parts or ":" in name or not name or name.endswith("/"):
            raise ArchiveError("The project file contains an invalid resource path.")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise ArchiveError("The project file contains an invalid resource path.")
        total += info.file_size
        if total > MAX_UNCOMPRESSED or (info.compress_size and info.file_size / max(info.compress_size, 1) > MAX_RATIO and info.file_size > 1024 * 1024):
            raise ArchiveError("The project file expands beyond the allowed size.")
    names = {i.filename for i in infos}
    if "manifest.json" not in names:
        raise ArchiveError("The project file has no manifest.")
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ArchiveError("The project file's manifest is unreadable.") from exc
    if manifest.get("format") != FORMAT or manifest.get("format_version") != FORMAT_VERSION:
        raise ArchiveError("This is not a RawiBumi project file of a supported format.")
    listed = {m["path"]: m for m in manifest.get("members", [])}
    if set(listed) != names - {"manifest.json"} or "project.json" not in listed:
        raise ArchiveError("The project file's contents do not match its manifest.")
    contents: dict[str, bytes] = {}
    for name, entry in listed.items():
        member = archive.read(name)
        if len(member) != entry.get("bytes") or _sha(member) != entry.get("sha256"):
            raise ArchiveError(f"The project file is damaged: {name} does not match its checksum.")
        contents[name] = member
    return manifest, contents


def import_project(service, study, data: bytes, *, replace: bool) -> dict[str, Any]:
    """Import a checked archive; the project keeps its ID (DATA1 D1). Returns the project view."""
    from .migrations import migrate
    from .project_store import check_bundle_bytes
    manifest, contents = _read_checked(data)
    project_id = service.store.validate_project_id(str(manifest.get("project_id") or ""))
    bundle, _ = migrate(check_bundle_bytes(project_id, contents["project.json"]))
    bundle_identifiers(bundle)
    from .history import validate_restored_bundle
    from jsonschema import ValidationError
    try:
        validate_restored_bundle(bundle)
    except ValidationError as exc:
        raise ArchiveError(f"The project in the file is not valid: {exc.message}") from exc
    for run in bundle.get("simulation_runs", []):
        run["origin"] = "imported"
    run_ids = {run["simulation_run_id"] for run in bundle.get("simulation_runs", [])}
    trees: dict[str, list[tuple[str, bytes]]] = {"weather": [], "imagery": [], "runs": [], "weather-snapshots": []}
    for name, member in contents.items():
        if name == "project.json":
            continue
        top, _, rest = name.partition("/")
        if top not in trees or not rest:
            raise ArchiveError("The project file contains an invalid resource path.")
        relative_member(rest)
        if top == "weather":
            safe_component(rest.split("/")[0], "weather")
            if rest.endswith("/weather-dataset.json"):
                safe_component(json.loads(member)["revision_id"], "weather")
            if rest.endswith("/acquisition-manifest.json"):
                snapshot_hashes(json.loads(member))
        if top == "weather-snapshots":
            if not _SNAPSHOT.fullmatch(rest) or _sha(member) != PurePosixPath(rest).name.split(".")[0]:
                raise ArchiveError("The project file contains an invalid weather snapshot.")
            safe_component(PurePosixPath(rest).stem, "hash")
        if top == "runs":
            safe_component(rest.split("/")[0], "run")
            if rest.endswith(("/simulation-run.json", "/summary-result.json")):
                run_identifiers(json.loads(member))
            if rest.endswith("/run-package-manifest.json"):
                package = json.loads(member)
                safe_component(package["simulation_run_id"], "run")
                for item in package.get("artifacts") or []:
                    relative_member(item["relative_path"])
        if top == "runs" and rest.split("/")[0] not in run_ids:
            raise ArchiveError("The project file contains results for an unknown run.")
        trees[top].append((rest, member))
    for asset in {rest.split(".")[0] for rest, _ in trees["imagery"]}:
        safe_component(asset, "imagery")
        blob = dict(trees["imagery"]).get(f"{asset}.bin")
        if blob is None or f"img-{_sha(blob)[:24]}" != asset:
            raise ArchiveError(f"The project file contains a damaged overlay image: {asset}.")
    if bundle.get("imagery"):
        from .imagery import ImageryAssetStore, validate_imagery
        staged_assets = tempfile.mkdtemp(prefix="rawibumi-import-imagery-")
        try:
            for rest, member in trees["imagery"]:
                target = contained(Path(staged_assets), Path(staged_assets) / project_id / relative_member(rest))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(member)
            try:
                validate_imagery(bundle["imagery"], project_id=project_id, assets=ImageryAssetStore(Path(staged_assets)))
            except ValueError as exc:
                raise ArchiveError(f"The project's imagery is not valid: {exc}") from exc
        finally:
            shutil.rmtree(staged_assets, ignore_errors=True)
    if not manifest.get("include_results"):
        for run in bundle.get("simulation_runs", []):
            run["package_omitted"] = True

    roots = {"weather": contained(study.weather.root, study.weather.root / project_id),
             "imagery": contained(service.imagery.root, service.imagery.root / project_id),
             "runs": contained(study.run_root, study.run_root / project_id)}
    with study._operation_lock, service.store._lock:
        exists = service.store.path_for(project_id).exists()
        if exists and not replace:
            raise ArchiveError(f"A project with this ID already exists: {bundle['project'].get('name')}.", status=409, code="project_exists")
        if exists:
            study._require_idle(project_id)
            service.store.protect(project_id, "import-replace")
        # Stage every tree beside its destination; then move the originals aside and the staged trees in. Any
        # failure moves the originals back, so an import either completes or leaves the project as it was.
        staged: dict[str, Path] = {}
        aside: dict[str, Path] = {}
        swapped: list[str] = []
        try:
            for top, root in roots.items():
                root.parent.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix=f".import-{project_id}-", dir=root.parent))
                staged[top] = stage
                for rest, member in trees[top]:
                    target = contained(stage, stage / relative_member(rest))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(member)
            for rest, member in trees["weather-snapshots"]:
                target = contained(study.snapshots.root, study.snapshots.root / relative_member(rest))
                if not target.exists():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(member)
            for top, root in roots.items():
                if root.exists():
                    aside[top] = contained(root.parent, root.with_name(f".replaced-{project_id}-{_sha(data)[:12]}"))
                    root.rename(aside[top])
                staged.pop(top).rename(root)
                swapped.append(top)
            payload = json.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode()
            service.store.write_raw(project_id, payload)
        except BaseException:
            for top in swapped:
                shutil.rmtree(roots[top], ignore_errors=True)
            for top, old in aside.items():
                old.rename(roots[top])
            raise
        finally:
            for stage in staged.values():
                shutil.rmtree(stage, ignore_errors=True)
        for old in aside.values():
            shutil.rmtree(old, ignore_errors=True)
        for top, root in roots.items():
            if root.is_dir() and not any(root.iterdir()):
                root.rmdir()
        service.history.clear(project_id, "barrier")
        return service.project_view(project_id)


def restore_backup(service, study, project_id: str, backup_id: str) -> dict[str, Any]:
    """Make a backup the current project: checked first, a protected backup of what it replaces, a history barrier."""
    from .migrations import migrate
    from .project_store import check_bundle_bytes
    from .history import validate_restored_bundle
    from jsonschema import ValidationError
    bundle, _ = migrate(check_bundle_bytes(project_id, service.store.read_backup(project_id, backup_id)))
    bundle_identifiers(bundle)
    try:
        validate_restored_bundle(bundle)
    except ValidationError as exc:
        raise ArchiveError(f"This backup is not a valid project: {exc.message}", code="backup_invalid") from exc
    with study._operation_lock, service.store._lock:
        if not service.store.path_for(project_id).exists():
            from .project_store import ProjectNotFoundError
            raise ProjectNotFoundError(project_id)
        study._require_idle(project_id)
        service.store.protect(project_id, "restore")
        service.store.write_raw(project_id, json.dumps(bundle, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False).encode())
        service.history.clear(project_id, "barrier")
        return service.project_view(project_id)
