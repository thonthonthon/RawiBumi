# ADR 0050 — Separate annual shading artifact, physical-result identity, and run-package completion

**Status:** Accepted by Phase 5.9 implementation  
**Date:** 2026-09-24

## Context

Phase 5.8H made exact annual geometry execution reproducible and bounded-memory,
but deliberately left annual product/artifact semantics to Phase 5.9.

The remaining ambiguities were:

1. `SimulationRun.shading_receiver_factor_reference` named a Parquet dataset,
   while `ShadingResult` already defined the canonical shading artifact contract;
2. exact `cache_policy.mode=none` and `exact` are physically equivalent but
   remain intentionally different canonical execution configurations;
3. receiver-factor logical rows contain per-snapshot ShadingResult IDs, so the
   complete dataset logical hash is not a valid none-vs-exact physical identity;
4. `SummaryResult.shading_energy_loss_wh` had no frozen geometric counterfactual;
5. a run directory had no last-write completion record, so interruption could leave
   a plausible-looking partial package.

## Decision

1. Keep the Phase-5.3 through Phase-5.8H beam, sky, ground, and exact-acceleration
   equations unchanged.
2. Publish one annual/long-run dataset-reference `ShadingResult` for each
   geometry-aware SimulationRun.
3. `ShadingResult.dataset_reference` is the authoritative receiver-factor dataset.
4. Retain `SimulationRun.shading_receiver_factor_reference` as a compatibility
   alias, but require exact object equality with `ShadingResult.dataset_reference`.
5. Preserve the existing canonical SimulationConfiguration/input hash unchanged,
   including `cache_policy`.
6. Add a separate scientific shading-configuration identity that normalizes only
   the exact execution choices `cache_policy.mode=none` and `exact` to common
   exact-physics semantics.
7. Preserve the complete receiver-factor logical hash for storage/reproducibility.
8. Add a receiver-factor physical-content hash that excludes only the execution/
   configuration-derived snapshot ID columns:
   - `shading_result_id`
   - `sky_shading_result_id`
   - `ground_shading_result_id`
9. Derive `ShadingResult.physical_result_sha256` from physical geometry/model
   provenance plus receiver-factor physical content, not from storage URI,
   Parquet bytes, cache telemetry, or execution-derived snapshot IDs.
10. Quantify complete-year geometric near-shading energy loss only by an explicit
    same-model PCC-energy counterfactual:
    - same weather;
    - same design;
    - same IAM/optical model;
    - same thermal model;
    - same electrical model;
    - same non-shading losses;
    - geometric beam/sky/ground visibility forced clear.
11. Do not interpret this counterfactual as Phase-6 electrical mismatch/bypass loss.
12. Persist a `run-package-manifest.json` last, after all other run artifacts.
13. A missing, malformed, incomplete, or hash-inconsistent package manifest means
    the run package is not consumable and must be rebuilt.
14. A completed package is immutable under its SimulationRun ID.
15. Do not activate angular-bin shading or multi-group electrical aggregation in
    Phase 5.9.

## Consequences

Positive:

- annual shading now has one canonical product artifact rather than two competing
  dataset identities;
- none/exact can remain auditable execution configurations while still sharing a
  scientific physical-result identity when their factor physics is identical;
- full logical dataset identity is not falsely conflated with physical equivalence;
- `shading_energy_loss_wh` has an explicit, reproducible reference state;
- interrupted run directories are distinguishable from completed packages;
- annual artifact recovery is fail-closed.

Trade-offs:

- none/exact receiver-factor Parquet datasets may have different complete logical
  hashes because snapshot IDs retain full configuration provenance;
- full-year geometry-aware runs that publish a shading-energy counterfactual execute
  the downstream unshaded chain once more;
- package-manifest byte identity is run/path specific and is not a scientific
  equivalence criterion;
- completed run IDs cannot be reused to overwrite prior artifacts.

## Revisit condition

Phase 6 may introduce electrical mismatch/bypass loss and therefore a different
electrical shading-loss decomposition. It must preserve the Phase-5 geometric
counterfactual as a distinct quantity.

A future approximate angular/temporal shading cache may require a different
scientific-identity normalization rule. Exact `none`/`exact` normalization must
not be generalized to approximate policies without validation.
