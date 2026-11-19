# ADR 0049 — Separate deterministic shading provenance from execution telemetry and stream annual receiver factors

**Status:** Accepted by Phase 5.8H  
**Date:** 2026-09-24

## Context

Phase 5.8 introduced exact prepared shading acceleration and process-local static
sky/ground caching.

A pre-annual audit found two classes of risk:

1. runtime-dependent cache metrics were embedded in model/reproducibility
   provenance, so cold and warm runs could describe the same model differently;
2. receiver-level shading factors were accumulated entirely in memory, which is
   unsuitable for million-row annual datasets.

Additional hardening was needed around full cache identity, ShadingResult storage
semantics, nighttime beam execution, and model-resolution identity.

## Decision

1. Preserve all Phase-5.3 through Phase-5.8 shading equations and reference solvers.
2. Separate deterministic acceleration manifest from volatile execution telemetry.
3. Store volatile cache and streaming metrics only in SimulationRun execution
   telemetry, not ReproducibilityManifest.model_manifest.
4. Derive component model-resolution identity from pinned component/model inputs,
   never from SimulationRun ID.
5. Bind exact static cache identity to the complete execution-plan payload SHA-256.
6. Validate cache payload provenance and channel/storage contracts on both put and hit.
7. Add execution-plan hash to ShadingCacheManifest and invalidation basis.
8. Stream large receiver-factor datasets in bounded deterministic chunks.
9. Use logical-content SHA-256, not Parquet byte identity, to prove streaming and
   in-memory persistence equivalence.
10. Select streaming deterministically from working-interval count × receiver count.
11. Use an exact global below-horizon scalar shortcut while retaining full reference
    execution for diagnostics.
12. Harden ShadingResult so inline and dataset-reference storage are mutually exclusive.
13. Require record-count reconciliation with the selected storage mode.
14. Batch-build canonical standard result DataFrames to avoid fragmentation.
15. Prove full beam+sky+ground reference/exact parity before Phase 5.9.
16. Prove cold/warm physical and deterministic-provenance parity before Phase 5.9.
17. Measure R4 module self-shading explicitly.
18. Exercise the complete 216 × 8760 receiver-row persistence scale before Phase 5.9.
19. Do not assign a non-null annual shading-energy-loss KPI until its counterfactual
    semantics are explicitly frozen.

## Consequences

Positive:

- cache warmth no longer changes scientific/model provenance;
- run IDs no longer alter component-model resolution identity;
- static cache identity uses full cryptographic execution-plan provenance;
- million-row annual receiver datasets no longer require one giant Python list/DataFrame;
- exact nighttime geometry work is substantially reduced;
- annual ShadingResult dataset-reference work can start from a stricter contract;
- self-shading and annual artifact scale are measured rather than assumed.

Trade-offs:

- streaming Parquet may have different physical file bytes than an in-memory single-write
  Parquet file even when logical content is identical;
- small runs retain the in-memory factor DataFrame intentionally for developer ergonomics;
- process-local static cache remains nonpersistent across workers;
- full annual electrical multi-group execution remains outside Phase 5.

## Revisit condition

Phase 5.9 may build annual ShadingResult dataset references and annual loss
counterfactuals on top of these rules. Phase 6 may replace the homogeneous
area-weighted electrical approximation, but must not reintroduce volatile execution
state into scientific provenance.
