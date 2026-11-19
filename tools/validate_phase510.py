#!/usr/bin/env python3
"""Emit the deterministic Phase-5.10 validation-oracle evidence summary."""

from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from validation.shading.phase510 import (  # noqa: E402
    build_external_oracle_evidence,
    load_pvsyst_vc_oracle,
    phase510_validation_hierarchy_manifest,
)


def main() -> int:
    oracle_path = (
        ROOT
        / "tests/benchmarks/phase49b_shaded_reference_matrix_20260924.yaml"
    )
    oracle = load_pvsyst_vc_oracle(oracle_path)
    evidence = build_external_oracle_evidence(oracle)

    if not evidence["source_reconciliation_pass"]:
        raise SystemExit("Phase 5.10 external oracle channel reconciliation failed")
    if not evidence["directional_signatures"]["VC2_east_morning_dominant"]:
        raise SystemExit("Phase 5.10 VC2 directional signature failed")
    if not evidence["directional_signatures"]["VC3_west_afternoon_dominant"]:
        raise SystemExit("Phase 5.10 VC3 directional signature failed")
    if not evidence["combined_case_nonadditivity"]["VC4_is_not_simple_sum"]:
        raise SystemExit("Phase 5.10 VC4 non-additivity evidence failed")
    if not evidence["combined_case_nonadditivity"]["VC5_is_not_simple_sum"]:
        raise SystemExit("Phase 5.10 VC5 non-additivity evidence failed")

    print(
        json.dumps(
            {
                "benchmark_id": "opensimpv.phase510.validation_matrix.v0.1",
                "hierarchy": phase510_validation_hierarchy_manifest(),
                "external_oracle": evidence,
                "quantitative_external_parity_claimed": False,
                "timing_is_acceptance_gate": False,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
