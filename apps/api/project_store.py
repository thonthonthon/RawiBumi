"""Filesystem-backed product-shell project storage."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
import shutil
from threading import RLock
import time
from typing import Any
from .safe_paths import PATTERNS, InvalidStorePath, safe_component, contained, bundle_identifiers


_SAFE_PROJECT_ID = re.compile(PATTERNS["project"])
_BACKUP_ID = re.compile(PATTERNS["backup"])
BACKUPS_KEPT = 20  # rolling, per project (DATA1 D3)
PROTECTED_KEPT = 10  # before an import-replace, a restore or a schema upgrade
REQUIRED_KEYS = ("schema_name", "schema_version", "project", "scene", "electrical_design", "pinned_components",
                 "site_workspace_bootstrap", "workspace_state", "weather_selection", "simulation_runs", "updated_at")


def project_system_summary(bundle: dict[str, Any]) -> dict[str, Any]:
    """USE3b: what the projects page shows when a row expands (fetched per project, so the list stays as cheap as it
    was): the PV and inverters by model, and the last successful run."""
    from collections import Counter

    from components.design_integration import module_nameplate_w

    pinned = bundle.get("pinned_components") or {}
    modules = Counter(m.get("module_definition_revision_id") for m in bundle.get("scene", {}).get("module_instances", [])
                      if m.get("enabled", True))
    inverters = Counter(i.get("inverter_definition_revision_id")
                        for i in (bundle.get("electrical_design") or {}).get("inverter_instances", []) if i.get("enabled", True))

    def module_row(revision: str, count: int) -> dict[str, Any]:
        definition = (pinned.get("modules") or {}).get(revision) or {}
        try:
            rating = float(module_nameplate_w(definition))
        except Exception:  # noqa: BLE001 - a missing pinned definition only hides the rating
            rating = None
        return {"model": definition.get("model") or revision, "manufacturer": definition.get("manufacturer"),
                "count": count, "rating_w": rating}

    def inverter_row(revision: str, count: int) -> dict[str, Any]:
        definition = (pinned.get("inverters") or {}).get(revision) or {}
        power = (definition.get("ac_limits") or {}).get("nominal_ac_power_w")
        return {"model": definition.get("model") or revision, "manufacturer": definition.get("manufacturer"),
                "count": count, "rating_w": float(power) if power is not None else None}

    module_rows = [module_row(r, c) for r, c in sorted(modules.items(), key=lambda x: str(x[0]))]
    inverter_rows = [inverter_row(r, c) for r, c in sorted(inverters.items(), key=lambda x: str(x[0]))]
    runs = [r for r in bundle.get("simulation_runs") or [] if r.get("status") in {"completed", "completed_with_warnings"} and r.get("summary_result")]
    last = runs[-1] if runs else None
    summary = (last or {}).get("summary_result") or {}
    return {
        "modules": module_rows,
        "dc_kwp": sum((m["rating_w"] or 0.0) * m["count"] for m in module_rows) / 1000.0,
        "inverters": inverter_rows,
        "ac_kw": sum((i["rating_w"] or 0.0) * i["count"] for i in inverter_rows) / 1000.0,
        "last_run": None if last is None else {
            "simulation_run_id": last.get("simulation_run_id"),
            "period_start_time": summary.get("period_start_time"), "period_end_time": summary.get("period_end_time"),
            "energy_kwh": (summary.get("total_energy_wh") or 0.0) / 1000.0,
            "annual": summary.get("annual_energy_wh") is not None,
            "specific_yield_kwh_kwp": (summary.get("specific_yield_wh_per_wp") or 0.0),
            "performance_ratio": summary.get("performance_ratio"),
        },
    }


class ProjectNotFoundError(KeyError):
    pass


class ProjectCorruptError(ValueError):
    """The project file exists but can't be read as a project bundle."""

    def __init__(self, project_id: str, reason: str) -> None:
        super().__init__(f"Project {project_id} can't be read: {reason}")
        self.project_id = project_id
        self.reason = reason


def check_bundle_bytes(project_id: str, raw: bytes) -> dict[str, Any]:
    """Parse and check a project file's bytes; raises ProjectCorruptError with a reason a person can act on."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProjectCorruptError(project_id, "the file is not UTF-8 text") from exc
    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProjectCorruptError(project_id, f"the file is not valid JSON ({exc.msg} at line {exc.lineno})") from exc
    if not isinstance(bundle, dict):
        raise ProjectCorruptError(project_id, "the file does not contain a project object")
    if bundle.get("schema_name") != "ProjectWorkspaceBundle":
        raise ProjectCorruptError(project_id, "the file is not a RawiBumi project")
    missing = [key for key in REQUIRED_KEYS if key not in bundle]
    if missing:
        raise ProjectCorruptError(project_id, f"required parts are missing: {', '.join(missing)}")
    try:
        if isinstance(bundle["project"], dict):
            safe_component(bundle["project"].get("project_id"), "project")
        if not isinstance(bundle["project"], dict) or bundle["project"].get("project_id") != project_id:
            raise ProjectCorruptError(project_id, "the project identity does not match its file")
        bundle_identifiers(bundle)
    except InvalidStorePath as exc:
        # The value itself is never echoed: it may be arbitrary text from a hand-edited file.
        raise ProjectCorruptError(project_id, "the file contains an invalid resource identifier") from exc
    return bundle


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


class FileProjectStore:
    """Atomic JSON project-bundle store for the first self-hosted product shell."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._lock = RLock()

    @staticmethod
    def validate_project_id(project_id: str) -> str:
        return safe_component(str(project_id), "project")

    def path_for(self, project_id: str) -> Path:
        value = self.validate_project_id(project_id)
        return contained(self.root, self.root / f"{value}.json")

    def save(self, bundle: dict[str, Any]) -> dict[str, Any]:
        bundle_identifiers(bundle)
        project = bundle.get("project") or {}
        project_id = self.validate_project_id(str(project.get("project_id") or ""))
        path = self.path_for(project_id)
        payload = json.dumps(
            bundle,
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        with self._lock:
            _write_atomic(path, payload)
            # Every saved version is also a rolling backup (DATA1 D3), so a damaged project file never loses the
            # latest save: the newest backup is the current state, the next one the state before it.
            self._backup(project_id, payload)
        return deepcopy(bundle)

    def load(self, project_id: str) -> dict[str, Any]:
        path = self.path_for(project_id)
        with self._lock:
            if not path.exists():
                raise ProjectNotFoundError(project_id)
            return check_bundle_bytes(project_id, path.read_bytes())

    # ---- backups (DATA1) ----------------------------------------------------
    def backup_dir(self, project_id: str) -> Path:
        return contained(self.root, self.root / ".backups" / self.validate_project_id(project_id))

    def _backup(self, project_id: str, payload: bytes, protected: str | None = None) -> str:
        try:
            revision = str(int(json.loads(payload)["project"]["project_revision"]["revision_number"]))
        except (ValueError, KeyError, TypeError, UnicodeDecodeError):
            revision = "x"
        now = time.time_ns()
        stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime(now // 1_000_000_000)) + f"{(now // 1000) % 1_000_000:06d}Z"
        backup_id = f"{stamp}-r{revision}" + (f"-protected-{protected}" if protected else "")
        safe_component(backup_id, "backup")
        directory = self.backup_dir(project_id)
        _write_atomic(contained(directory, directory / f"{backup_id}.json"), payload)
        kept, limit = (PROTECTED_KEPT, True) if protected else (BACKUPS_KEPT, False)
        same_kind = [b for b in self.backups(project_id) if b["protected"] == limit]
        for old in same_kind[kept:]:
            contained(directory, directory / f"{safe_component(old['backup_id'], 'backup')}.json").unlink(missing_ok=True)
        return backup_id

    def protect(self, project_id: str, reason: str) -> str | None:
        """A protected backup of the current file before a replacing operation; None when there is no file."""
        path = self.path_for(project_id)
        with self._lock:
            return self._backup(project_id, path.read_bytes(), protected=reason) if path.exists() else None

    def backups(self, project_id: str) -> list[dict[str, Any]]:
        """Newest first."""
        directory = self.backup_dir(project_id)
        rows = []
        for path in directory.glob("*.json") if directory.is_dir() else []:
            match = _BACKUP_ID.fullmatch(path.stem)
            if match:
                contained(directory, path)
                rows.append({"backup_id": path.stem, "saved_at": match[1], "revision_number": None if match[2] == "x" else int(match[2]),
                             "protected": match[3] is not None, "reason": match[4], "bytes": path.stat().st_size})
        return sorted(rows, key=lambda row: row["backup_id"][:22], reverse=True)

    def read_backup(self, project_id: str, backup_id: str) -> bytes:
        try:
            safe_component(backup_id, "backup")
        except InvalidStorePath as exc:
            # A malformed backup ID names nothing: keep the existing 404, as for any unknown backup.
            raise ProjectNotFoundError(f"{project_id} backup") from exc
        directory = self.backup_dir(project_id)
        path = contained(directory, directory / f"{backup_id}.json")
        if path.is_symlink() or not path.is_file():
            raise ProjectNotFoundError(f"{project_id} backup {backup_id}")
        return path.read_bytes()

    def write_raw(self, project_id: str, payload: bytes) -> None:
        """Replace the project file with already-checked bytes (restore and import); also kept as a rolling backup."""
        path = self.path_for(project_id)
        check_bundle_bytes(project_id, payload)
        with self._lock:
            _write_atomic(path, payload)
            self._backup(project_id, payload)

    def delete(self, project_id: str) -> None:
        path = self.path_for(project_id)
        with self._lock:
            if self.root.is_symlink() or path.is_symlink():
                raise ValueError("project bundle is outside project storage or uses a symlink")
            root = self.root.resolve()
            if not path.resolve().is_relative_to(root):
                raise ValueError("project bundle is outside project storage or uses a symlink")
            if not path.exists():
                raise ProjectNotFoundError(project_id)
            path.unlink()
            backups = self.backup_dir(project_id)
            if backups.is_dir() and not backups.is_symlink():
                shutil.rmtree(backups)

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.root.exists():
                return []
            rows: list[dict[str, Any]] = []
            for path in sorted(self.root.glob("*.json")):
                if not _SAFE_PROJECT_ID.fullmatch(path.stem):
                    continue
                contained(self.root, path)
                try:
                    bundle = check_bundle_bytes(path.stem, path.read_bytes())
                    project = bundle["project"]
                    site = project["site"]
                    rows.append(
                        {
                            "project_id": project["project_id"],
                            "name": project["name"],
                            "status": project["status"],
                            "latitude_deg": site["latitude_deg"],
                            "longitude_deg": site["longitude_deg"],
                            "timezone": site["timezone"],
                            "updated_at": bundle.get("updated_at"),
                        }
                    )
                except (KeyError, TypeError, ProjectCorruptError) as exc:
                    # Never hide a damaged project: list it so it can be restored from a backup.
                    if _SAFE_PROJECT_ID.fullmatch(path.stem):
                        rows.append({"project_id": path.stem, "name": path.stem, "status": "unreadable",
                                     "reason": exc.reason if isinstance(exc, ProjectCorruptError) else "the project data is incomplete",
                                     "latitude_deg": None, "longitude_deg": None, "timezone": None, "updated_at": None})
            return sorted(
                rows,
                key=lambda item: (
                    str(item.get("updated_at") or ""),
                    str(item["project_id"]),
                ),
                reverse=True,
            )
