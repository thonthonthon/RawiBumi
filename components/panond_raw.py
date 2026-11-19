"""Lossless raw parser for PVsyst-style PAN and OND text files.

This parser deliberately does not assign engineering semantics or infer numeric types.
It preserves source text, field order, duplicate keys, indentation, and values exactly
enough for a later semantic adapter to make auditable mappings into canonical objects.

The parser design is informed by the public pvlib PAN/OND reader, but OpenSIMPV keeps
an ordered record model rather than reducing the source directly to a nested dict.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

PanOndFormat = Literal["pan", "ond"]


@dataclass(frozen=True)
class RawPanOndLine:
    line_number: int
    raw_line: str
    kind: Literal["blank", "text", "key_value"]
    leading_whitespace: str
    indent_spaces: int
    indent_valid: bool
    depth: int | None
    key: str | None
    value_raw: str | None
    path: tuple[str, ...]

    def as_field_record(self) -> dict[str, object]:
        if self.kind != "key_value" or self.key is None:
            raise ValueError("Only key/value lines can become field records")
        return {
            "line_number": self.line_number,
            "path": list(self.path),
            "key": self.key,
            "value_raw": self.value_raw,
            "indent_spaces": self.indent_spaces,
            "indent_valid": self.indent_valid,
        }


@dataclass(frozen=True)
class RawPanOndDocument:
    format: PanOndFormat
    raw_text: str
    encoding: str
    newline: Literal["lf", "crlf", "cr", "mixed_or_none"]
    lines: tuple[RawPanOndLine, ...]

    @property
    def fields(self) -> tuple[RawPanOndLine, ...]:
        return tuple(line for line in self.lines if line.kind == "key_value")

    @property
    def warnings(self) -> tuple[str, ...]:
        warnings: list[str] = []
        for line in self.lines:
            if line.kind == "key_value" and not line.indent_valid:
                warnings.append(
                    f"Line {line.line_number}: indentation is not a whole number "
                    "of two-space levels or contains a tab."
                )
        return tuple(warnings)

    def raw_field_map(self) -> list[dict[str, object]]:
        return [line.as_field_record() for line in self.fields]


def _detect_newline(text: str) -> Literal["lf", "crlf", "cr", "mixed_or_none"]:
    has_crlf = "\r\n" in text
    stripped = text.replace("\r\n", "")
    has_lf = "\n" in stripped
    has_cr = "\r" in stripped
    kinds = sum((has_crlf, has_lf, has_cr))
    if kinds != 1:
        return "mixed_or_none"
    if has_crlf:
        return "crlf"
    if has_lf:
        return "lf"
    return "cr"


def _line_depth(leading_whitespace: str) -> tuple[int, bool, int | None]:
    if "\t" in leading_whitespace:
        spaces = leading_whitespace.count(" ")
        return spaces, False, None
    spaces = len(leading_whitespace)
    if spaces % 2:
        return spaces, False, None
    return spaces, True, spaces // 2


def parse_panond_text(text: str, *, format: PanOndFormat, encoding: str = "utf-8") -> RawPanOndDocument:
    if format not in ("pan", "ond"):
        raise ValueError("format must be 'pan' or 'ond'")
    lines = text.splitlines()
    if len(lines) > 5000:
        raise ValueError("PAN/OND files must contain no more than 5,000 lines.")

    parsed_lines: list[RawPanOndLine] = []
    stack: list[str] = []

    for line_number, raw_line in enumerate(lines, start=1):
        leading_len = len(raw_line) - len(raw_line.lstrip(" \t"))
        leading = raw_line[:leading_len]
        indent_spaces, indent_valid, depth = _line_depth(leading)
        content = raw_line[leading_len:]

        if content == "":
            parsed_lines.append(
                RawPanOndLine(
                    line_number, raw_line, "blank", leading, indent_spaces,
                    indent_valid, depth, None, None, ()
                )
            )
            continue

        if "=" not in content:
            parsed_lines.append(
                RawPanOndLine(
                    line_number, raw_line, "text", leading, indent_spaces,
                    indent_valid, depth, None, None, ()
                )
            )
            continue

        key_raw, value_raw = content.split("=", 1)
        key = key_raw.strip()
        value = value_raw.strip()

        if indent_valid and depth is not None:
            if len(stack) > depth:
                stack = stack[:depth]
            while len(stack) < depth:
                stack.append("<missing-parent>")
            path = tuple(stack + [key])
            if len(stack) == depth:
                stack.append(key)
            else:
                stack[depth] = key
        else:
            path = (key,)

        parsed_lines.append(
            RawPanOndLine(
                line_number=line_number,
                raw_line=raw_line,
                kind="key_value",
                leading_whitespace=leading,
                indent_spaces=indent_spaces,
                indent_valid=indent_valid,
                depth=depth,
                key=key,
                value_raw=value,
                path=path,
            )
        )

    return RawPanOndDocument(
        format=format,
        raw_text=text,
        encoding=encoding,
        newline=_detect_newline(text),
        lines=tuple(parsed_lines),
    )


def parse_panond_bytes(
    data: bytes,
    *,
    format: PanOndFormat,
    encoding: str = "utf-8-sig",
) -> RawPanOndDocument:
    text = data.decode(encoding)
    return parse_panond_text(text, format=format, encoding=encoding)


def read_panond(
    path: str | Path,
    *,
    format: PanOndFormat,
    encoding: str = "utf-8-sig",
) -> RawPanOndDocument:
    path = Path(path)
    return parse_panond_bytes(path.read_bytes(), format=format, encoding=encoding)


def iter_fields(document: RawPanOndDocument) -> Iterable[RawPanOndLine]:
    return document.fields
