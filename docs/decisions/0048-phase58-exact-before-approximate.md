# ADR 0048 — Preserve reference shading solvers and accelerate exact queries before approximate sampling

**Status:** Accepted by Phase 5.8  
**Date:** 2026-09-24

## Context

Phase 5.3 through Phase 5.7 established auditable reference geometry solvers for
direct beam, sky diffuse, and ground/albedo visibility.

Those solvers repeatedly perform direction-independent work for each directional
query. Annual execution magnifies this cost.

The Phase-5.0 contract also anticipated angular-bin caching, but that is an
approximation and should not be conflated with exact execution acceleration.

A separate contract issue existed: non-null
`sun_position_resolution_seconds` was accepted even though geometry-aware
runtime did not consume it.

## Decision

1. Keep the Phase-5.3 through Phase-5.7 reference solvers executable as permanent
   correctness oracles.
2. Define `cache_policy.mode=none` as the reference path.
3. Define `cache_policy.mode=exact` as exact prepared-query acceleration.
4. Precompute only direction-independent receiver and occluder state:
   receiver basis/polygon/area/planarity, participation filtering, and
   receiver-front face clipping.
5. Keep directional projection, receiver intersection, polygon union, and all
   physical tolerances unchanged per query.
6. Preserve beam diagnostics on the reference path.
7. Cache exact static sky and ground ShadingResult payloads in a bounded
   process-local LRU cache.
8. Activate the existing ShadingCacheManifest contract for cache provenance.
9. Bind static cache identity to compiled geometry hash, full shading
   configuration hash, solver manifest hash, receiver set, channel, and source
   execution-plan provenance.
10. Do not add a naive annual per-sun beam result cache without measured reuse.
11. Do not activate angular-bin approximation in Phase 5.8.
12. Do not map fidelity level implicitly to angular resolution or sampling.
13. Freeze current annual sampling as every canonical simulation
    solar-evaluation timestamp.
14. Fail closed when non-null `sun_position_resolution_seconds` requests
    unimplemented temporal coarsening.
15. Measure performance on synthetic, R1, and R4 cases, but do not make noisy
    wall-time speed thresholds a CI correctness gate.
16. Require exact reference-vs-prepared numerical parity as the CI gate.

## Consequences

Positive:

- exact mode can accelerate annual shading without changing physics;
- reference mode remains available for auditing and regression;
- sky/ground static work can be reused safely;
- cache invalidation is explicit and machine-auditable;
- performance claims are measured rather than assumed;
- approximate sampling remains clearly labeled and future-extensible;
- requested but unsupported temporal coarsening can no longer be silently
  ignored.

Trade-offs:

- process-local static cache does not yet persist across worker processes;
- prepared state consumes memory proportional to receiver/eligible-face count;
- direct-beam result caching remains intentionally absent;
- angular bins and temporal interpolation remain unavailable;
- the current homogeneous electrical execution boundary remains unchanged.

## Revisit condition

A future phase may add persistent cache storage, exact spatial indexing, or
explicit angular/temporal approximation. Any such change must preserve the
reference path, expose approximation provenance, and demonstrate numerical or
bounded-error behavior against the Phase-5.3 through Phase-5.8 oracle suite.
