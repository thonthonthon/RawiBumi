"""Content-addressed raw weather response storage."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import os
import re
import tempfile

# Kept local: the weather package must not depend on the web API layer (apps/api/safe_paths.py mirrors these).
_DIGEST = re.compile(r"[0-9a-f]{64}")
_SUFFIX = re.compile(r"\.[a-z]{1,10}")


@dataclass(frozen=True)
class RawWeatherSnapshot:
    sha256: str
    byte_size: int
    storage_reference: str
    path: Path


class FileSystemWeatherSnapshotStore:
    """Minimal local snapshot store used by self-hosted/API deployments.

    The public identity is content-addressed. Filesystem paths are implementation
    details and are not required by SimulationRun replay.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def path_for(self, digest: str, *, suffix: str = ".json") -> Path:
        if (not isinstance(digest, str) or not _DIGEST.fullmatch(digest)
                or not isinstance(suffix, str) or not _SUFFIX.fullmatch(suffix)):
            raise ValueError("Invalid weather snapshot identifier.")
        path = self.root / "sha256" / digest[:2] / f"{digest}{suffix}"
        root = self.root.resolve()
        if not path.resolve().is_relative_to(root):
            raise ValueError("Invalid weather snapshot identifier.")
        return path

    def put(self, data: bytes, *, suffix: str = ".json") -> RawWeatherSnapshot:
        digest = sha256(data).hexdigest()
        path = self.path_for(digest, suffix=suffix)
        path.parent.mkdir(parents=True, exist_ok=True)

        if path.exists():
            existing = path.read_bytes()
            if sha256(existing).hexdigest() != digest:
                raise RuntimeError("weather snapshot digest collision/corruption")
        else:
            handle, temp_name = tempfile.mkstemp(
                prefix=f".{digest}.",
                suffix=".tmp",
                dir=path.parent,
            )
            try:
                with os.fdopen(handle, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)

        return RawWeatherSnapshot(
            sha256=digest,
            byte_size=len(data),
            storage_reference=f"weather-snapshot://sha256/{digest}",
            path=path,
        )

    def get(self, digest: str, *, suffix: str = ".json") -> bytes:
        data = self.path_for(digest, suffix=suffix).read_bytes()
        actual = sha256(data).hexdigest()
        if actual != digest:
            raise RuntimeError(
                f"weather snapshot hash mismatch: expected {digest}, got {actual}"
            )
        return data
