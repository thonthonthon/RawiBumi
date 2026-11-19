"""Raw OND parsing entry points.

Semantic mapping into InverterDefinition, MPPTDefinition, and efficiency models is
intentionally a separate future layer.
"""

from __future__ import annotations

from pathlib import Path

from components.panond_raw import RawPanOndDocument, parse_panond_bytes, parse_panond_text, read_panond


def parse_ond_text(text: str, *, encoding: str = "utf-8") -> RawPanOndDocument:
    return parse_panond_text(text, format="ond", encoding=encoding)


def parse_ond_bytes(data: bytes, *, encoding: str = "utf-8-sig") -> RawPanOndDocument:
    return parse_panond_bytes(data, format="ond", encoding=encoding)


def read_ond(path: str | Path, *, encoding: str = "utf-8-sig") -> RawPanOndDocument:
    return read_panond(path, format="ond", encoding=encoding)
