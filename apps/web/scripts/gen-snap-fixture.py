#!/usr/bin/env python3
"""Generate the snapping parity fixture from the engine's SnapEngine.

Writes apps/web/tests/fixtures/snap-cases.json. The unit test
tests/unit/snap.test.ts runs the browser port (src/canvas/plan/snap.ts) on the
same cases and expects the same answers. Re-run after any change to
geometry/scene/snapping.py:

    python3 apps/web/scripts/gen-snap-fixture.py

Read-only with respect to the engine: it imports SnapEngine and calls it.
"""

from __future__ import annotations

import importlib.util
import json
import math
import random
import sys
import types
from pathlib import Path

# The repository root: the nearest folder above apps/web that holds geometry/scene.
# Normally parents[3]; a staged copy in its own folder resolves to the real root.
ROOT = next(
    (p for p in Path(__file__).resolve().parents[3:] if (p / "geometry" / "scene").is_dir()),
    Path(__file__).resolve().parents[3],
)
OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "snap-cases.json"
SEED = 20261022
CASES = 600


def load_snap_engine():
    """Import geometry.scene.snapping; fall back to loading the two files directly."""
    sys.path.insert(0, str(ROOT))
    try:
        from geometry.scene.snapping import SNAP_KINDS, SnapEngine  # type: ignore

        return SnapEngine, SNAP_KINDS
    except Exception:  # pragma: no cover - partial checkouts
        scene_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "geometry" / "scene"
        pkg = types.ModuleType("snapscene")
        pkg.__path__ = [str(scene_dir)]
        sys.modules["snapscene"] = pkg
        for name in ("geometry2d", "snapping"):
            spec = importlib.util.spec_from_file_location(f"snapscene.{name}", scene_dir / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[f"snapscene.{name}"] = mod
            spec.loader.exec_module(mod)
        snapping = sys.modules["snapscene.snapping"]
        return snapping.SnapEngine, snapping.SNAP_KINDS


def rot(p, c, a):
    s, co = math.sin(a), math.cos(a)
    x, y = p[0] - c[0], p[1] - c[1]
    return (c[0] + x * co - y * s, c[1] + x * s + y * co)


def rect(rng):
    x, y = rng.uniform(-20, 20), rng.uniform(-20, 20)
    w, h = rng.uniform(1, 12), rng.uniform(1, 8)
    a = rng.choice([0.0, 0.0, rng.uniform(-math.pi, math.pi)])
    c = (x + w / 2, y + h / 2)
    return [rot(p, c, a) for p in [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]


def triangle(rng):
    x, y = rng.uniform(-20, 20), rng.uniform(-20, 20)
    return [(x, y), (x + rng.uniform(2, 9), y + rng.uniform(-2, 2)), (x + rng.uniform(-2, 4), y + rng.uniform(2, 9))]


def polyline(rng):
    x, y = rng.uniform(-20, 20), rng.uniform(-20, 20)
    pts = [(x, y)]
    for _ in range(rng.randint(1, 3)):
        x, y = x + rng.uniform(-8, 8), y + rng.uniform(-8, 8)
        pts.append((x, y))
    return pts


def r(p):
    return [round(p[0], 6), round(p[1], 6)]



def write_fixture(doc: dict) -> None:
    """One case per line: compact, and a regenerated fixture diffs line by line."""
    cases = doc.pop("cases")
    head = json.dumps(doc, separators=(",", ":"))[:-1]
    body = ",\n".join(json.dumps(c, separators=(",", ":")) for c in cases)
    OUT.write_text(f'{head},"cases":[\n{body}\n]}}\n')

def main():
    SnapEngine, kinds_all = load_snap_engine()
    kinds_all = sorted(kinds_all)
    rng = random.Random(SEED)
    cases = []
    for case in range(CASES):
        surfaces = [[r(p) for p in (rect(rng) if rng.random() < 0.7 else triangle(rng))] for _ in range(rng.randint(1, 4))]
        obstacles = [[r(p) for p in rect(rng)] for _ in range(rng.randint(0, 2))]
        lines = [[r(p) for p in polyline(rng)] for _ in range(rng.randint(0, 2))]
        scene = {
            "surfaces": [{"surface_id": f"s{i}", "boundary_2d": {"vertices": v}} for i, v in enumerate(surfaces)],
            "obstacles": [{"obstacle_id": f"o{i}", "footprint": {"vertices": v}} for i, v in enumerate(obstacles)],
            "reference_lines": [{"reference_line_id": f"l{i}", "vertices": v} for i, v in enumerate(lines)],
        }
        if rng.random() < 0.1 and surfaces:
            scene["surfaces"][0]["visible"] = False
        supplemental = {}
        if rng.random() < 0.3:
            supplemental["module_edge"] = [(f"m{i}", tuple(r(a)), tuple(r(b))) for i, (a, b) in enumerate((rect(rng)[0], rect(rng)[1]) for _ in range(rng.randint(1, 6)))]
        if rng.random() < 0.2:
            supplemental["row_edge"] = [(f"row{i}", tuple(r(a)), tuple(r(b))) for i, (a, b) in enumerate((rect(rng)[0], rect(rng)[2]) for _ in range(rng.randint(1, 3)))]

        # Query near a chosen kind of feature, so every snap kind is exercised.
        rings = [(v, True) for v in surfaces + obstacles] + [(v, False) for v in lines]
        edges = [(v[i], v[(i + 1) % len(v)]) for v, closed in rings for i in range(len(v) if closed else len(v) - 1)]
        all_pts = [p for v, _ in rings for p in v]
        roll = rng.random()
        base = None
        if roll < 0.2 and all_pts:
            base = rng.choice(all_pts)
        elif roll < 0.35 and edges:
            a, b = rng.choice(edges)
            base = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        elif roll < 0.55 and len(edges) > 1:
            hits = []
            for i in range(len(edges)):
                for j in range(i + 1, len(edges)):
                    (x1, y1), (x2, y2) = edges[i]
                    (x3, y3), (x4, y4) = edges[j]
                    den = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
                    if abs(den) < 1e-9:
                        continue
                    t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / den
                    u = -((x1 - x2) * (y1 - y3) - (y1 - y2) * (x1 - x3)) / den
                    if 0.05 < t < 0.95 and 0.05 < u < 0.95:
                        hits.append((x1 + t * (x2 - x1), y1 + t * (y2 - y1)))
            if hits:
                base = rng.choice(hits)
        elif roll < 0.7 and edges:
            a, b = rng.choice(edges)
            t = rng.random()
            base = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
        elif roll < 0.8 and supplemental:
            _, a, b = rng.choice(supplemental[rng.choice(sorted(supplemental))])
            base = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if base is None:
            base = (rng.uniform(-25, 25), rng.uniform(-25, 25))
        noise = rng.choice([0.0, 0.0, 0.01, 0.1, 0.4, 1.5])
        point = (round(base[0] + rng.uniform(-noise, noise), 6), round(base[1] + rng.uniform(-noise, noise), 6))

        tolerance = rng.choice([0.0, 0.05, 0.2, 0.5, 1.0, 2.5])
        enabled = kinds_all if rng.random() < 0.5 else sorted(rng.sample(kinds_all, rng.randint(1, len(kinds_all))))
        grid = rng.choice([None, None, None, 0.5, 1.0, 0.25]) if "user_grid" in enabled else None
        anchor = direction = None
        if rng.random() < 0.4:
            anchor = (round(point[0] + rng.uniform(-5, 5), 6), round(point[1] + rng.uniform(-5, 5), 6))
            direction = (round(rng.uniform(-1, 1), 6), round(rng.uniform(-1, 1), 6))
            if direction == (0.0, 0.0):
                direction = (1.0, 0.0)
        override = rng.random() < 0.05

        engine = SnapEngine(scene, supplemental_edges=supplemental)
        res = engine.resolve(
            point,
            tolerance_m=tolerance,
            enabled_kinds=enabled,
            override=override,
            grid_spacing_m=grid,
            anchor=anchor,
            reference_direction=direction,
        )
        items = (
            [{"id": s["surface_id"], "points": s["boundary_2d"]["vertices"], "closed": True, "visible": s.get("visible", True)} for s in scene["surfaces"]]
            + [{"id": o["obstacle_id"], "points": o["footprint"]["vertices"], "closed": True} for o in scene["obstacles"]]
            + [{"id": l["reference_line_id"], "points": l["vertices"], "closed": False} for l in scene["reference_lines"]]
        )
        cases.append(
            {
                "case": case,
                "items": items,
                "supplemental": {k: [[s, list(a), list(b)] for s, a, b in v] for k, v in supplemental.items()},
                "point": list(point),
                "options": {
                    "toleranceM": tolerance,
                    "enabled": enabled,
                    "override": override,
                    "gridSpacingM": grid,
                    "anchor": list(anchor) if anchor else None,
                    "referenceDirection": list(direction) if direction else None,
                },
                "expected": {
                    "applied": res.applied,
                    "point": list(res.snapped_point),
                    "kind": res.kind,
                    "sourceId": res.source_entity_id,
                    "featureIndex": res.feature_index,
                },
            }
        )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write_fixture({"generator": "scripts/gen-snap-fixture.py", "seed": SEED, "engine": "geometry/scene/snapping.py", "cases": cases})
    applied = sum(1 for c in cases if c["expected"]["applied"])
    by_kind = {}
    for c in cases:
        by_kind[c["expected"]["kind"]] = by_kind.get(c["expected"]["kind"], 0) + 1
    print(f"Wrote {OUT.relative_to(ROOT)}: {len(cases)} cases, {applied} snapped; by kind {by_kind}")


if __name__ == "__main__":
    main()
