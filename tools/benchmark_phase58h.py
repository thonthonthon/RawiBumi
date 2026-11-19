#!/usr/bin/env python3
"""Phase-5.8H pre-annual hardening benchmarks.

Timing is engineering evidence, not a CI threshold. The script fails only when:
- prepared exact self-shading geometry diverges from the reference solver; or
- annual-scale receiver-factor streaming violates its bounded-row contract.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from time import perf_counter

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.simulation.artifacts import ReceiverFactorParquetSink
from geometry.shading import (
    calculate_direct_beam_shadow,
    calculate_prepared_direct_beam_shadow,
    compile_shading_geometry,
    prepare_directional_receiver,
    sun_vector_from_azimuth_elevation,
)


def _load_phase49c():
    path = ROOT / "tests/unit/test_phase49c_reference_projects.py"
    spec = importlib.util.spec_from_file_location(
        "_opensimpv_phase49c_phase58h_bench",
        path,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load Phase-4.9C reference fixture")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _module_receiver_ids(compiled):
    return sorted(
        str(item["receiver_id"])
        for item in compiled["receivers"]
        if item.get("enabled") is True
        and item.get("source_entity_type") == "module_instance"
    )


def _measure_r4_self_shading(direction_count: int):
    phase49c = _load_phase49c()
    ref = phase49c._reference("R4")
    compiled = compile_shading_geometry(ref["scene"])
    receiver_ids = _module_receiver_ids(compiled)

    directions = [
        sun_vector_from_azimuth_elevation(
            (45.0 + index * 270.0 / max(direction_count, 1)) % 360.0,
            (18.0, 35.0, 55.0)[index % 3],
        )
        for index in range(direction_count)
    ]

    reference_results = []
    start = perf_counter()
    for direction in directions:
        for receiver_id in receiver_ids:
            reference_results.append(
                calculate_direct_beam_shadow(
                    compiled,
                    receiver_id=receiver_id,
                    sun_vector_xyz=direction,
                    self_shading_enabled=True,
                )
            )
    reference_seconds = perf_counter() - start

    prepare_start = perf_counter()
    prepared = {
        receiver_id: prepare_directional_receiver(
            compiled,
            receiver_id=receiver_id,
            self_shading_enabled=True,
        )
        for receiver_id in receiver_ids
    }
    prepare_seconds = perf_counter() - prepare_start

    exact_results = []
    query_start = perf_counter()
    for direction in directions:
        for receiver_id in receiver_ids:
            exact_results.append(
                calculate_prepared_direct_beam_shadow(
                    prepared[receiver_id],
                    sun_vector_xyz=direction,
                )
            )
    query_seconds = perf_counter() - query_start

    if reference_results != exact_results:
        for index, (left, right) in enumerate(
            zip(reference_results, exact_results)
        ):
            if left != right:
                raise AssertionError(
                    "R4 self-shading exact/reference mismatch at query "
                    f"{index}, receiver={left.get('receiver_id')}"
                )
        raise AssertionError("R4 self-shading exact/reference length mismatch")

    total_exact = prepare_seconds + query_seconds
    return {
        "case": "R4_self_shading_enabled",
        "receiver_count": len(receiver_ids),
        "compiled_occluder_count": len(compiled.get("occluders", [])),
        "direction_count": len(directions),
        "query_count": len(receiver_ids) * len(directions),
        "reference_seconds": reference_seconds,
        "exact_prepare_seconds": prepare_seconds,
        "exact_query_seconds": query_seconds,
        "exact_total_seconds": total_exact,
        "query_only_speedup": (
            reference_seconds / query_seconds if query_seconds > 0 else None
        ),
        "first_run_total_speedup": (
            reference_seconds / total_exact if total_exact > 0 else None
        ),
        "physics_parity": True,
        "self_shading_enabled": True,
    }


def _annual_receiver_factor_chunk(
    *,
    interval_start: pd.DatetimeIndex,
    receiver_ids: np.ndarray,
) -> pd.DataFrame:
    receiver_count = len(receiver_ids)
    interval_count = len(interval_start)
    repeated_interval_ns = np.repeat(
        interval_start.asi8,
        receiver_count,
    )
    repeated_evaluation_ns = repeated_interval_ns + 30 * 60 * 1_000_000_000
    tiled_receivers = np.tile(receiver_ids, interval_count)

    return pd.DataFrame(
        {
            "interval_start": pd.to_datetime(repeated_interval_ns, utc=True),
            "evaluation_time": pd.to_datetime(repeated_evaluation_ns, utc=True),
            "receiver_id": tiled_receivers,
            "receiver_area_m2": np.full(
                interval_count * receiver_count,
                2.58,
                dtype=float,
            ),
            "beam_visibility_factor": np.ones(
                interval_count * receiver_count,
                dtype=float,
            ),
            "quality_flags_json": np.full(
                interval_count * receiver_count,
                "[]",
                dtype=object,
            ),
            "shading_result_id": np.full(
                interval_count * receiver_count,
                "shading-result:annual-scale-fixture",
                dtype=object,
            ),
            "sky_visibility_factor": np.full(
                interval_count * receiver_count,
                0.95,
                dtype=float,
            ),
            "circumsolar_visibility_factor": np.ones(
                interval_count * receiver_count,
                dtype=float,
            ),
            "horizon_visibility_factor": np.full(
                interval_count * receiver_count,
                0.92,
                dtype=float,
            ),
            "ground_visibility_factor": np.full(
                interval_count * receiver_count,
                0.98,
                dtype=float,
            ),
        }
    )


def _measure_annual_receiver_factor_streaming():
    receiver_count = 216
    annual_intervals = 8760
    intervals_per_chunk = 24
    receiver_ids = np.array(
        [f"receiver:module:m{index:03d}" for index in range(receiver_count)],
        dtype=object,
    )
    index = pd.date_range(
        "2025-01-01T00:00:00Z",
        periods=annual_intervals,
        freq="h",
    )

    with TemporaryDirectory(prefix="opensimpv-phase58h-") as directory:
        output = Path(directory)
        sink = ReceiverFactorParquetSink(
            output_directory=output,
            simulation_run_id="phase58h-annual-scale",
        )
        start = perf_counter()
        for offset in range(0, annual_intervals, intervals_per_chunk):
            chunk_index = index[offset : offset + intervals_per_chunk]
            sink.write(
                _annual_receiver_factor_chunk(
                    interval_start=chunk_index,
                    receiver_ids=receiver_ids,
                )
            )
        reference = sink.finalize()
        elapsed = perf_counter() - start

        expected_rows = receiver_count * annual_intervals
        maximum_expected_chunk = receiver_count * intervals_per_chunk
        if reference["row_count"] != expected_rows:
            raise AssertionError(
                f"annual streaming row count {reference['row_count']} "
                f"!= {expected_rows}"
            )
        if sink.max_chunk_rows > maximum_expected_chunk:
            raise AssertionError(
                "receiver-factor streaming exceeded configured benchmark chunk "
                f"bound: {sink.max_chunk_rows} > {maximum_expected_chunk}"
            )

        return {
            "case": "R4_equivalent_annual_receiver_factor_stream",
            "receiver_count": receiver_count,
            "interval_count": annual_intervals,
            "row_count": reference["row_count"],
            "expected_row_count": expected_rows,
            "chunk_count": sink.chunk_count,
            "max_chunk_rows": sink.max_chunk_rows,
            "bounded_chunk_rows": True,
            "file_byte_size": reference["byte_size"],
            "logical_content_sha256": reference["logical_content_sha256"],
            "elapsed_seconds": elapsed,
        }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Use two R4 self-shading directions; annual persistence scale is unchanged.",
    )
    args = parser.parse_args()

    result = {
        "benchmark_id": "opensimpv.phase58h.preannual_hardening.v0.1",
        "quick": bool(args.quick),
        "timing_is_acceptance_gate": False,
        "physics_parity_is_acceptance_gate": True,
        "annual_row_scale_is_acceptance_gate": True,
        "results": [
            _measure_r4_self_shading(2 if args.quick else 6),
            _measure_annual_receiver_factor_streaming(),
        ],
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
