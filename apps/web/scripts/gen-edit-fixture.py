#!/usr/bin/env python3
"""Generate the exact-edit parity fixture from the engine's geometry2d.

Writes apps/web/tests/fixtures/edit-cases.json for tests/unit/edit.test.ts
(src/canvas/plan/edit.ts). Re-run after changing geometry/scene/geometry2d.py:

    python3 apps/web/scripts/gen-edit-fixture.py
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
from pathlib import Path

# The repository root: the nearest folder above apps/web that holds geometry/scene.
# Normally parents[3]; a staged copy in its own folder resolves to the real root.
ROOT = next(
    (p for p in Path(__file__).resolve().parents[3:] if (p / "geometry" / "scene").is_dir()),
    Path(__file__).resolve().parents[3],
)
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "edit-cases.json"


def load():
    sys.path.insert(0, str(ROOT))
    try:
        from geometry.scene import geometry2d  # type: ignore

        return geometry2d
    except Exception:  # pragma: no cover - partial checkouts
        path = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "geometry" / "scene") / "geometry2d.py"
        spec = importlib.util.spec_from_file_location("geometry2d", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod



def write_fixture(doc: dict) -> None:
    """One case per line: compact, and a regenerated fixture diffs line by line."""
    cases = doc.pop("cases")
    head = json.dumps(doc, separators=(",", ":"))[:-1]
    body = ",\n".join(json.dumps(c, separators=(",", ":")) for c in cases)
    OUT.write_text(f'{head},"cases":[\n{body}\n]}}\n')

def main():
    g = load()
    rng = random.Random(20261022)
    cases = []
    for n in range(300):
        k = rng.randint(3, 7)
        cx, cy, rad = rng.uniform(-30, 30), rng.uniform(-30, 30), rng.uniform(1, 15)
        angles = sorted(rng.uniform(0, 2 * math.pi) for _ in range(k))
        if rng.random() < 0.5:
            angles.reverse()
        pts = [(round(cx + rad * math.cos(a), 6), round(cy + rad * math.sin(a), 6)) for a in angles]
        closed = rng.random() < 0.8
        op = rng.choice(["length", "azimuth", "rotate"])
        edge = rng.randrange(len(pts) if closed else len(pts) - 1)
        preserve = rng.choice(["start", "end", "midpoint"])
        if op == "length":
            value = round(rng.uniform(0.1, 20), 4)
            out = g.set_edge_length(pts, edge, value, preserve=preserve, closed=closed)
        elif op == "azimuth":
            value = round(rng.uniform(-400, 400), 3)
            out = g.set_edge_azimuth(pts, edge, value, preserve=preserve, closed=closed)
        else:
            value = round(rng.uniform(-400, 400), 3)
            origin = (round(rng.uniform(-30, 30), 6), round(rng.uniform(-30, 30), 6))
            out = g.rotate_points_clockwise(pts, origin, value)
            cases.append({"case": n, "op": op, "points": pts, "origin": list(origin), "value": value, "expected": [list(p) for p in out]})
            continue
        cases.append({"case": n, "op": op, "points": pts, "edge": edge, "preserve": preserve, "closed": closed, "value": value, "expected": [list(p) for p in out]})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_fixture({"generator": "scripts/gen-edit-fixture.py", "engine": "geometry/scene/geometry2d.py", "cases": cases})
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(cases)} cases")


if __name__ == "__main__":
    main()
