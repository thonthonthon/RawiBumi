"""Shared identifier formats and containment checks for product file stores."""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit


PATTERNS = {
    "project": r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
    "weather": r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}",
    "run": r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}",
    "component": r"[A-Za-z0-9][A-Za-z0-9._-]{0,249}",
    "library_revision": r"(?=.{1,250}$)lib-(?:mod|inv)-[a-z0-9-]+-r[1-9][0-9]*",
    "collection": r"(?:modules|inverters)",
    "hash": r"[0-9a-f]{64}",
    "imagery": r"img-[0-9a-f]{24}",
    "backup": r"(?=.{1,250}$)([0-9]{8}T[0-9]{12}Z)-r([0-9]+|x)(-protected-([a-z-]{1,32}))?",
    "member": r"(?!(?:\.|\.\.)$)[A-Za-z0-9._-]{1,255}",
    "snapshot_suffix": r"\.[a-z]{1,10}",
}


class InvalidStorePath(ValueError):
    def __init__(self):
        super().__init__("Invalid resource identifier or storage path.")


def safe_component(value, kind):
    if not isinstance(value, str) or re.fullmatch(PATTERNS[kind], value) is None:
        raise InvalidStorePath()
    return value


def contained(root, path):
    root, path = Path(root), Path(path)
    try:
        resolved_root, resolved = root.resolve(), path.resolve()
        if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
            raise InvalidStorePath()
    except (OSError, RuntimeError, ValueError) as exc:
        raise InvalidStorePath() from exc
    return path


def relative_member(value):
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise InvalidStorePath()
    parts = value.split("/")
    for part in parts:
        safe_component(part, "member")
    return PurePosixPath(*parts)


def reference_uri(value):
    """Validate recorded references structurally, preserving encoded root names."""
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise InvalidStorePath()
    try:
        uri = urlsplit(value)
        if uri.scheme == "weather-snapshot":
            if uri.netloc != "sha256" or uri.query or uri.fragment:
                raise InvalidStorePath()
            safe_component(uri.path.removeprefix("/"), "hash")
        elif uri.scheme == "file":
            path = unquote(uri.path)
            if uri.netloc or uri.query or uri.fragment or not path.startswith("/") or "\\" in path:
                raise InvalidStorePath()
            if any(part in {".", ".."} for part in path.split("/")):
                raise InvalidStorePath()
        else:
            raise InvalidStorePath()
    except (ValueError, UnicodeError) as exc:
        raise InvalidStorePath() from exc
    return value


def snapshot_hashes(value):
    result = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "sha256" and item is not None:
                result.add(safe_component(item, "hash"))
            elif key == "storage_reference" and isinstance(item, str) and item.startswith("weather-snapshot:"):
                reference_uri(item)
            else:
                result.update(snapshot_hashes(item))
    elif isinstance(value, list):
        for item in value:
            result.update(snapshot_hashes(item))
    return result


def run_identifiers(run):
    safe_component(run["simulation_run_id"], "run")
    for key in ("weather_dataset_revision_id", "weather_revision_id"):
        if run.get(key) is not None:
            safe_component(run[key], "weather")
    for record in (run, run.get("summary_result") or {}):
        for key in ("result_reference", "group_timeseries_reference", "inverter_timeseries_reference"):
            reference = record.get(key) or {}
            if reference.get("uri") is not None:
                reference_uri(reference["uri"])
    for key in ("selected_mppt_result", "dc_attribution_result", "attribution_energy_result"):
        reference = (run.get("detailed_electrical_shading") or {}).get(key) or {}
        if reference.get("artifact") is not None:
            relative_member(reference["artifact"])


def bundle_identifiers(bundle):
    safe_component(bundle["project"]["project_id"], "project")
    selection = bundle.get("weather_selection") or {}
    if selection.get("revision_id") is not None:
        safe_component(selection["revision_id"], "weather")
    revision = bundle["project"].get("project_revision") or {}
    if revision.get("weather_dataset_revision_id") is not None:
        safe_component(revision["weather_dataset_revision_id"], "weather")
    snapshot_hashes(selection.get("manifest"))
    for run in bundle.get("simulation_runs") or []:
        run_identifiers(run)
    for layer in (bundle.get("imagery") or {}).get("layers") or []:
        if layer.get("imported_asset_id") is not None:
            safe_component(layer["imported_asset_id"], "imagery")


def run_package_paths(directory):
    """Check path-bearing metadata before canonical readers open any artifact."""
    directory = Path(directory)
    if directory.is_symlink():
        raise InvalidStorePath()
    for path in directory.rglob("*"):
        contained(directory, path)
        if path.is_symlink():
            raise InvalidStorePath()
    manifest_path = directory / "run-package-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text())
        safe_component(manifest["simulation_run_id"], "run")
        for item in manifest.get("artifacts") or []:
            contained(directory, directory / relative_member(item["relative_path"]))
    run_path = directory / "simulation-run.json"
    if run_path.is_file():
        run_identifiers(json.loads(run_path.read_text()))
    for name, key, folder in (
        ("detailed-electrical-interval-index.json", "intervals", "detailed-electrical-intervals"),
        ("detailed-attribution-diagnostic-index.json", "rows", "detailed-attribution-diagnostic-chunks"),
    ):
        path = directory / name
        if path.is_file():
            record = json.loads(path.read_text())
            for item in (record.get(key) or {}).get("chunks") or []:
                contained(directory / folder, directory / folder / relative_member(item["path"]))
    summary = directory / "summary-result.json"
    if summary.is_file():
        run_identifiers(json.loads(summary.read_text()))
