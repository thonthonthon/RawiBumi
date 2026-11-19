"""Ordered text-object decoding; engineering interpretation lives in gated adapters."""

from dataclasses import dataclass, field
from pathlib import Path
import math
import re


class SourceError(ValueError):
    pass


@dataclass
class Node:
    kind: str
    tag: str
    line: int
    records: list[tuple[str, str]] = field(default_factory=list)
    children: list["Node"] = field(default_factory=list)

    def values(self, key):
        return [v for k, v in self.records if k == key]

    def one(self, key, default=None):
        values = self.values(key)
        if len(values) > 1:
            raise SourceError(f"duplicate scalar key: {self.kind}.{key}")
        return values[0] if values else default

    def number(self, key):
        try:
            value = float(self.one(key))
        except (ValueError, TypeError) as exc:
            raise SourceError(f"missing or invalid number: {self.kind}.{key}") from exc
        if not math.isfinite(value):
            raise SourceError(f"non-finite number: {self.kind}.{key}")
        return value

    def integer(self, key):
        value = self.number(key)
        if value != int(value) or value < 0:
            raise SourceError(f"invalid count: {self.kind}.{key}")
        return int(value)

    def walk(self, kind=None):
        if kind is None or self.kind == kind:
            yield self
        for child in self.children:
            yield from child.walk(kind)


def read_objects(source: Path | bytes) -> Node:
    raw = source if isinstance(source, bytes) else Path(source).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        if b"PVObject_" not in raw:
            raise SourceError("unrecognized text object source")
        text = raw.decode("cp1252")
    roots, stack = [], []
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if re.match(r"^PVObject_[^=]*=", line):
            tag, kind = line.split("=", 1)
            node = Node(kind.strip(), tag.strip(), lineno)
            (stack[-1].children if stack else roots).append(node)
            stack.append(node)
        elif line.startswith("End of PVObject "):
            kind = line.removeprefix("End of PVObject ").strip()
            if not stack or stack[-1].kind != kind:
                raise SourceError("unbalanced object terminator")
            stack.pop()
        elif "=" in line and stack:
            key, value = line.split("=", 1)
            stack[-1].records.append((key.strip(), value.strip()))
        elif stack:
            # Legacy typed-block/list markers have no equals sign. Preserve
            # them as unsupported records rather than discarding source text.
            stack[-1].records.append(("__unparsed_structure__", line))
        else:
            raise SourceError(f"unrecognized structural line {lineno}")
    if stack or len(roots) != 1:
        raise SourceError("incomplete or multiple root objects")
    return roots[0]


def vector(value, *, size=None):
    try:
        parts = [float(v.strip()) for v in value.rstrip(",").split(",")]
    except (ValueError, AttributeError) as exc:
        raise SourceError("invalid numeric vector") from exc
    if (
        not all(math.isfinite(x) for x in parts)
        or size is not None
        and len(parts) != size
    ):
        raise SourceError("invalid numeric vector length or value")
    return parts
