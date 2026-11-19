"""UX1 imagery: per-project overlay image assets and the persisted MapLayerConfiguration contract.

Images are context only. Bytes are checked by signature and header dimensions; pixels are never decoded.
"""
from __future__ import annotations

from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import re
import struct
import tempfile
from typing import Any

MAX_IMAGE_BYTES = 10 * 1000 * 1000
MAX_IMAGE_SIDE_PX = 8192
from .safe_paths import safe_component, contained, InvalidStorePath
# The project names the browser-held key; it never holds a key. A template carries `{key}`, never a literal.
_CREDENTIAL = re.compile(r"browser-key:[a-z0-9-]{1,32}")
_LITERAL_KEY = re.compile(r"(?i)[?&](key|apikey|api_key|token|access_token)=(?!\{key\})[^&]+")


class ImageryError(ValueError):
    def __init__(self, message, *, status=422, code="imagery_invalid"):
        super().__init__(message)
        self.status = status
        self.detail = {"message": message, "code": code}


def image_header(data: bytes) -> tuple[str, int, int]:
    """(MIME, width, height) from the PNG, JPEG or WebP header; refuses anything else."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        if len(data) < 24 or data[12:16] != b"IHDR":
            raise ImageryError("The PNG header is incomplete.")
        width, height = struct.unpack(">II", data[16:24])
        return "image/png", width, height
    if data[:3] == b"\xff\xd8\xff":
        i = 2
        while i + 4 <= len(data):
            if data[i] != 0xFF:
                raise ImageryError("The JPEG header is malformed.")
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            length = struct.unpack(">H", data[i + 2:i + 4])[0]
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                if i + 9 > len(data):
                    break
                height, width = struct.unpack(">HH", data[i + 5:i + 9])
                return "image/jpeg", width, height
            i += 2 + length
        raise ImageryError("The JPEG header has no frame size.")
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        chunk = data[12:16]
        if chunk == b"VP8X" and len(data) >= 30:
            return "image/webp", 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
        if chunk == b"VP8L" and len(data) >= 25 and data[20] == 0x2F:
            bits = int.from_bytes(data[21:25], "little")
            return "image/webp", (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        if chunk == b"VP8 " and len(data) >= 30 and data[23:26] == b"\x9d\x01\x2a":
            width, height = struct.unpack("<HH", data[26:30])
            return "image/webp", width & 0x3FFF, height & 0x3FFF
        raise ImageryError("The WebP header is incomplete.")
    raise ImageryError("Only PNG, JPEG or WebP images can be used as an overlay.", code="imagery_unsupported_format")


def check_image(data: bytes) -> tuple[str, int, int]:
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageryError("Overlay images must be no larger than 10 MB.", status=413, code="imagery_too_large")
    mime, width, height = image_header(data)
    if not (1 <= width <= MAX_IMAGE_SIDE_PX and 1 <= height <= MAX_IMAGE_SIDE_PX):
        raise ImageryError(f"Overlay images must be at most {MAX_IMAGE_SIDE_PX} px on each side.", code="imagery_too_large_px")
    return mime, width, height


class ImageryAssetStore:
    """Content-addressed overlay images per project; kept until the project is deleted (UX1 D2)."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def directory(self, project_id: str) -> Path:
        return contained(self.root, self.root / safe_component(project_id, "project")).resolve()

    def _paths(self, project_id: str, asset_id: str) -> tuple[Path, Path]:
        try:
            safe_component(asset_id, "imagery")
        except InvalidStorePath as exc:
            raise ImageryError("Imagery asset not found.", status=404, code="imagery_asset_not_found") from exc
        directory = self.directory(project_id)
        return contained(directory, directory / f"{asset_id}.bin"), contained(directory, directory / f"{asset_id}.json")

    def put(self, project_id: str, filename: str, data: bytes) -> dict[str, Any]:
        mime, width, height = check_image(data)
        digest = hashlib.sha256(data).hexdigest()
        asset_id = f"img-{digest[:24]}"
        blob, meta = self._paths(project_id, asset_id)
        if meta.is_file():
            return json.loads(meta.read_text())
        record = {"asset_id": asset_id, "filename": Path(str(filename)).name[:200] or "image", "mime": mime,
                  "width_px": width, "height_px": height, "bytes": len(data), "sha256": digest,
                  "created_at": datetime.now(timezone.utc).isoformat()}
        blob.parent.mkdir(parents=True, exist_ok=True)
        for path, payload in ((blob, data), (meta, json.dumps(record, sort_keys=True).encode())):
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                handle.write(payload)
                temporary = Path(handle.name)
            os.replace(temporary, path)
        return record

    def record(self, project_id: str, asset_id: str) -> dict[str, Any]:
        blob, meta = self._paths(project_id, asset_id)
        if not (blob.is_file() and meta.is_file()):
            raise ImageryError(f"unknown imagery asset {asset_id}", status=404, code="imagery_asset_not_found")
        return json.loads(meta.read_text())

    def read(self, project_id: str, asset_id: str) -> tuple[dict[str, Any], bytes]:
        record = self.record(project_id, asset_id)
        return record, self._paths(project_id, asset_id)[0].read_bytes()


def validate_imagery(config: Any, *, project_id: str, assets: ImageryAssetStore) -> None:
    """Server rules on top of the MapLayerConfiguration schema (UX1 scope 3). Raises ImageryError."""
    if config is None:
        return
    from geometry.coordinates import MapLayerConfiguration
    error = next(_schema_validator().iter_errors(config), None)
    if error is not None:
        path = ".".join(map(str, error.absolute_path))
        raise ImageryError(f"imagery{'.' + path if path else ''}: {error.message}")
    try:
        MapLayerConfiguration.from_mapping(config)
    except (ValueError, KeyError, TypeError) as exc:
        raise ImageryError(str(exc)) from exc
    providers = {p["provider_id"]: p for p in config["providers"]}
    kinds = [p["provider_kind"] for p in config["providers"]]
    if kinds.count("xyz_raster") > 1 or kinds.count("uploaded_asset") > 1:
        raise ImageryError("Use at most one custom imagery provider and one uploaded overlay.")
    for provider in config["providers"]:
        if provider["provider_kind"] not in {"xyz_raster", "uploaded_asset"}:
            raise ImageryError(f"provider kind {provider['provider_kind']} is not used for project imagery")
        template = provider.get("tile_url_template")
        if provider["provider_kind"] == "xyz_raster":
            if not (isinstance(template, str) and template.startswith("https://") and all(t in template for t in ("{z}", "{x}", "{y}"))):
                raise ImageryError("A tile URL template must use https:// and contain {z}, {x} and {y}.")
            if _LITERAL_KEY.search(template):
                raise ImageryError("Put the key in the key field; the template must use {key}, so no key is saved.", code="imagery_key_in_template")
        reference = provider.get("credential_reference")
        if reference is not None and not _CREDENTIAL.fullmatch(str(reference)):
            raise ImageryError("credential_reference must name the browser-held key (browser-key:…); the key itself is never stored.", code="imagery_credential_invalid")
    for layer in config["layers"]:
        if layer["layer_type"] not in {"aerial_imagery", "orthophoto"}:
            raise ImageryError(f"layer type {layer['layer_type']} is not used for project imagery")
        provider = providers.get(layer["provider_id"])
        if layer["layer_type"] == "aerial_imagery" and (provider is None or provider["provider_kind"] != "xyz_raster"):
            raise ImageryError("an aerial imagery layer needs the custom imagery provider")
        if layer["layer_type"] == "orthophoto":
            try:
                record = assets.record(project_id, str(layer["imported_asset_id"]))
            except ImageryError as exc:
                raise ImageryError(f"overlay image {layer['imported_asset_id']} is not uploaded to this project", code="imagery_asset_not_found") from exc
            reference = layer["orthophoto_georeference"]
            if (reference["image_width_px"], reference["image_height_px"]) != (record["width_px"], record["height_px"]):
                raise ImageryError("the georeference image size must match the uploaded image")
            values = [v for point in reference["control_points"] for v in point.values()] + [reference.get("rms_error_m") or 0]
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                raise ImageryError("control points must be finite numbers")



@lru_cache(maxsize=1)
def _schema_validator():
    from jsonschema import Draft202012Validator, FormatChecker
    schema = json.loads((Path(__file__).resolve().parents[2] / "geometry/coordinates/map-layer-configuration.schema.json").read_text())
    return Draft202012Validator(schema, format_checker=FormatChecker())
