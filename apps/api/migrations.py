"""Project bundle schema versions (DATA1): ordered upgraders, and a clear refusal of files from a newer app."""
from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable

CURRENT_SCHEMA_VERSION = "0.1"

# version -> (next version, upgrade). Each step returns a new bundle at `next version`, never mutating its input.
# There is no released predecessor of 0.1 yet; the first real upgrader is added here with its own test.
MIGRATIONS: dict[str, tuple[str, Callable[[dict[str, Any]], dict[str, Any]]]] = {}


class ProjectVersionError(ValueError):
    def __init__(self, project_id: str, version: str, *, newer: bool) -> None:
        message = (f"This project was saved by a newer RawiBumi (schema {version}). Update the app to open it." if newer
                   else f"This project uses an unknown schema version {version!r}.")
        super().__init__(message)
        self.project_id = project_id
        self.version = version
        self.newer = newer


def _key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def migrate(bundle: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """The bundle at CURRENT_SCHEMA_VERSION and the steps applied ("0.0->0.1"); the input is not changed."""
    project_id = str((bundle.get("project") or {}).get("project_id") or "")
    version = str(bundle.get("schema_version"))
    try:
        newer = _key(version) > _key(CURRENT_SCHEMA_VERSION)
    except ValueError:
        raise ProjectVersionError(project_id, version, newer=False) from None
    if newer:
        raise ProjectVersionError(project_id, version, newer=True)
    current, applied = bundle, []
    while version != CURRENT_SCHEMA_VERSION:
        if version not in MIGRATIONS:
            raise ProjectVersionError(project_id, version, newer=False)
        target, upgrade = MIGRATIONS[version]
        current = upgrade(deepcopy(current))
        if current.get("schema_version") != target:
            raise RuntimeError(f"migration {version}->{target} did not set schema_version")
        applied.append(f"{version}->{target}")
        version = target
    return current, applied
