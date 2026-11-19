"""Raw PAN parsing entry points.

Semantic mapping into ModuleDefinition is intentionally a separate future layer.
"""

from __future__ import annotations

from pathlib import Path

from components.panond_raw import RawPanOndDocument, parse_panond_bytes, parse_panond_text, read_panond


def parse_pan_text(text: str, *, encoding: str = "utf-8") -> RawPanOndDocument:
    return parse_panond_text(text, format="pan", encoding=encoding)


def parse_pan_bytes(data: bytes, *, encoding: str = "utf-8-sig") -> RawPanOndDocument:
    return parse_panond_bytes(data, format="pan", encoding=encoding)


def read_pan(path: str | Path, *, encoding: str = "utf-8-sig") -> RawPanOndDocument:
    return read_panond(path, format="pan", encoding=encoding)
