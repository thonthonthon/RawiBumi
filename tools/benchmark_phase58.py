#!/usr/bin/env python3
"""Measured Phase-5.8 reference-vs-exact shading benchmark.

The benchmark is evidence, not a flaky CI performance gate. It fails only on
physics mismatch. Timing and speedup are reported as JSON for engineering review.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from geometry.shading import (
    calculate_direct_beam_shadow,
    calculate_prepared_direct_beam_shadow,
    compile_shading_geometry,
    prepare_directional_receiver,
    sun_vector_from_azimuth_elevation,
)


HASH = "d" * 64


def _load_phase49c():
    path = ROOT / "tests/unit/test_phase49c_reference_projects.py"
    spec = importlib.util.spec_from_file_location("_opensimpv_phase49c_bench", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Phase-4.9C reference fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_receiver_ids(compiled: dict[str, Any]) -> list[str]:
    return sorted(
        str(item["receiver_id"])
        for item in compiled["receivers"]
        if item.get("enabled") is True
        and item.get("source_entity_type") == "module_instance"
    )


def _directions(count: int):
    elevations = (12.0, 25.0, 45.0, 65.0)
    result = []
    for index in range(count):
        azimuth = (index + 0.5) * 360.0 / count
        elevation = elevations[index % len(elevations)]
        result.append(
            sun_vector_from_azimuth_elevation(azimuth, elevation)
        )
    return result


def _run_reference(compiled, receiver_ids, directions):
    output = []
    start = perf_counter()
    for direction in directions:
        for receiver_id in receiver_ids:
            output.append(
                calculate_direct_beam_shadow(
                    compiled,
                    receiver_id=receiver_id,
                    sun_vector_xyz=direction,
                    self_shading_enabled=False,
                )
            )
    elapsed = perf_counter() - start
    return elapsed, output


def _run_exact(compiled, receiver_ids, directions):
    prep_start = perf_counter()
    prepared = {
        receiver_id: prepare_directional_receiver(
            compiled,
            receiver_id=receiver_id,
            self_shading_enabled=False,
        )
        for receiver_id in receiver_ids
    }
    prepare_elapsed = perf_counter() - prep_start

    output = []
    query_start = perf_counter()
    for direction in directions:
        for receiver_id in receiver_ids:
            output.append(
                calculate_prepared_direct_beam_shadow(
                    prepared[receiver_id],
                    sun_vector_xyz=direction,
                )
            )
    query_elapsed = perf_counter() - query_start
    return prepare_elapsed, query_elapsed, output


def _assert_same(reference, exact):
    if len(reference) != len(exact):
        raise AssertionError("reference/exact output lengths differ")
    for index, (left, right) in enumerate(zip(reference, exact)):
        if left != right:
            raise AssertionError(
                f"reference/exact result mismatch at query {index}: "
                f"{left['receiver_id']}"
            )


def _measure(name, compiled, receiver_ids, direction_count):
    directions = _directions(direction_count)
    reference_seconds, reference = _run_reference(
        compiled, receiver_ids, directions
    )
    prepare_seconds, exact_query_seconds, exact = _run_exact(
        compiled, receiver_ids, directions
    )
    _assert_same(reference, exact)

    exact_total = prepare_seconds + exact_query_seconds
    return {
        "case": name,
        "receiver_count": len(receiver_ids),
        "direction_count": len(directions),
        "query_count": len(receiver_ids) * len(directions),
        "compiled_occluder_count": len(compiled.get("occluders", [])),
        "reference_seconds": reference_seconds,
        "exact_prepare_seconds": prepare_seconds,
        "exact_query_seconds": exact_query_seconds,
        "exact_total_seconds": exact_total,
        "query_only_speedup": (
            reference_seconds / exact_query_seconds
            if exact_query_seconds > 0.0
            else None
        ),
        "first_run_total_speedup": (
            reference_seconds / exact_total
            if exact_total > 0.0
            else None
        ),
        "physics_parity": True,
    }


def _synthetic_compiled(module_occluder_count: int):
    receiver = {
        "receiver_id": "receiver:module:r0",
        "source_entity_type": "module_instance",
        "source_entity_id": "r0",
        "receiver_type": "module_plane",
        "vertices_3d": [
            [0.0, -1.0, -1.0],
            [0.0, 1.0, -1.0],
            [0.0, 1.0, 1.0],
            [0.0, -1.0, 1.0],
        ],
        "center_xyz": [0.0, 0.0, 0.0],
        "normal_xyz": [1.0, 0.0, 0.0],
        "area_m2": 4.0,
        "enabled": True,
        "pv_field_id": "field",
        "support_surface_id": "surface",
        "module_instance_id": "r0",
        "metadata": {},
    }

    occluders = []
    for index in range(module_occluder_count):
        x = 10.0 + index * 0.01
        occluders.append(
            {
                "occluder_id": f"occluder:module:m{index:05d}",
                "source_entity_type": "module_instance",
                "source_entity_id": f"m{index:05d}",
                "geometry_type": "polygon_faces",
                "faces": [
                    {
                        "face_id": f"module:{index}:face",
                        "vertices_3d": [
                            [x, -0.5, -0.5],
                            [x, 0.5, -0.5],
                            [x, 0.5, 0.5],
                            [x, -0.5, 0.5],
                        ],
                        "normal_xyz": [-1.0, 0.0, 0.0],
                    }
                ],
                "bounds_3d": {
                    "min_xyz": [x, -0.5, -0.5],
                    "max_xyz": [x, 0.5, 0.5],
                },
                "shading_enabled": True,
                "metadata": {},
            }
        )

    # One physical obstacle remains eligible when module self-shading is disabled.
    occluders.append(
        {
            "occluder_id": "occluder:obstacle:block",
            "source_entity_type": "obstacle",
            "source_entity_id": "block",
            "geometry_type": "polygon_faces",
            "faces": [
                {
                    "face_id": "block:west",
                    "vertices_3d": [
                        [1.0, -0.4, -2.0],
                        [1.0, 0.4, -2.0],
                        [1.0, 0.4, 2.0],
                        [1.0, -0.4, 2.0],
                    ],
                    "normal_xyz": [-1.0, 0.0, 0.0],
                }
            ],
            "bounds_3d": {
                "min_xyz": [1.0, -0.4, -2.0],
                "max_xyz": [1.0, 0.4, 2.0],
            },
            "shading_enabled": True,
            "metadata": {},
        }
    )

    return {
        "source_scene_revision_id": "scene-synthetic-phase58",
        "geometry_payload_sha256": HASH,
        "receivers": [receiver],
        "occluders": occluders,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="CI-sized benchmark",
    )
    args = parser.parse_args()

    if args.quick:
        synthetic_modules = 600
        synthetic_directions = 48
        reference_directions = 6
    else:
        synthetic_modules = 1500
        synthetic_directions = 160
        reference_directions = 16

    phase49c = _load_phase49c()

    r1 = phase49c._reference("R1")
    r4 = phase49c._reference("R4")
    compiled_r1 = compile_shading_geometry(r1["scene"])
    compiled_r4 = compile_shading_geometry(r4["scene"])

    results = [
        _measure(
            "synthetic_high_irrelevant_module_count",
            _synthetic_compiled(synthetic_modules),
            ["receiver:module:r0"],
            synthetic_directions,
        ),
        _measure(
            "R1",
            compiled_r1,
            _module_receiver_ids(compiled_r1),
            reference_directions,
        ),
        _measure(
            "R4",
            compiled_r4,
            _module_receiver_ids(compiled_r4),
            reference_directions,
        ),
    ]

    payload = {
        "benchmark_id": "opensimpv.phase58.exact_prepared.v0.1",
        "quick": bool(args.quick),
        "timing_is_acceptance_gate": False,
        "physics_parity_is_acceptance_gate": True,
        "results": results,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
