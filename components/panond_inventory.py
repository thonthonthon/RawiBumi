"""Field-inventory utilities for representative PAN/OND corpora."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from components.panond_raw import RawPanOndDocument


def build_field_inventory(
    named_documents: Iterable[tuple[str, RawPanOndDocument]],
) -> list[dict[str, object]]:
    aggregate: dict[tuple[str, ...], dict[str, object]] = {}

    for name, document in named_documents:
        for field in document.fields:
            entry = aggregate.setdefault(
                field.path,
                {
                    "path": list(field.path),
                    "key": field.key,
                    "occurrences": 0,
                    "files": set(),
                    "example_values": [],
                    "indent_valid": True,
                },
            )
            entry["occurrences"] = int(entry["occurrences"]) + 1
            entry["files"].add(name)
            entry["indent_valid"] = bool(entry["indent_valid"]) and field.indent_valid
            if field.value_raw not in entry["example_values"] and len(entry["example_values"]) < 5:
                entry["example_values"].append(field.value_raw)

    result: list[dict[str, object]] = []
    for path in sorted(aggregate):
        entry = aggregate[path]
        entry["files"] = sorted(entry["files"])
        result.append(entry)
    return result
