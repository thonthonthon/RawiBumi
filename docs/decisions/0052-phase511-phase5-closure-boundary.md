# ADR 0052 — Phase 5.11 Phase-5 closure boundary

**Status:** Accepted by Phase 5.11 implementation  
**Date:** 2026-09-25

## Context

Phase 5.0–5.10 established the geometry-aware shading contract, deterministic compiled geometry, receiver grouping, beam/sky/ground solvers, annual execution, cache/persistence semantics, full annual SimulationRun integration, and analytical/external validation.

Phase 5.11 exists to freeze the maturity boundary rather than introduce another physical model.

The planning anchor requires:

- a minimum regression family spanning unobstructed, multi-roof, fixed-tilt ground, obstacle-rich, multi-orientation, VC0–VC5, and analytical shadow cases;
- save → reload → compile geometry → run shading → annual simulation reproducibility;
- preservation of Scene hash, compiled geometry hash, configuration identity, shading-result identity, SimulationRun input hash, and annual output within deterministic tolerance;
- performance evidence for compile, beam, sky, annual shading, cache behavior and memory;
- no universal hardware target.

## Decision

1. Phase 5.11 adds no new shading physics.

2. The Phase-5 closure regression family is frozen in:

       tests/benchmarks/phase511_closure_matrix_20260925.yaml

3. R1–R5 canonical scenes are save/reload/compile regression cases.

4. A short nontrivial R4 path explicitly proves:

       save design
       -> reload
       -> compile shading geometry
       -> run beam+sky+ground shading
       -> run SimulationRun

   while preserving Scene hash, compiled-geometry hash, configuration identity,
   shading physical identity, SimulationRun input hash, and standard-result hash.

5. Full annual closure evidence uses:

       R1 — annual save/reload reproducibility reference
       R4 — annual nontrivial shaded runtime reference

6. Identity-bearing deterministic artifacts use exact SHA-256 equality.

7. The additional annual-energy tolerance is:

       absolute delta <= 1e-6 Wh

   This is a guardrail in addition to content-hash identity, not a substitute for it.

8. Performance evidence records:

       compile time
       beam query cost
       sky-view cost
       annual shading runtime
       cache cold/warm behavior
       memory use

9. Performance numbers are evidence only. No universal threshold is frozen because runner hardware and environment materially affect them. Every benchmark payload must therefore record the execution environment needed for like-for-like review.

10. Unsupported electrical heterogeneity remains explicit. Phase 5.11 does not implement:

       substring/bypass shading
       module shaded-IV interaction
       heterogeneous same-MPPT IV coupling
       bifacial rear irradiance
       Phase-6 electrical mismatch

11. R5 remains valid canonical geometry/design state but is not silently flattened into an electrically homogeneous annual model.

## Consequences

Phase 5 becomes closable against an executable maturity contract rather than a narrative checklist.

Future changes to geometry compilation, shading result identity, cache semantics, annual artifact persistence, or performance architecture must preserve the closure gates or deliberately revise this ADR.

Performance regressions can be investigated using comparable benchmark environments without conflating hardware variance with physics correctness.

## Phase-6 handoff

Phase 6 receives:

- per-module/per-receiver geometric irradiance state;
- preserved receiver identity;
- canonical electrical topology;
- explicit geometric shading channels;
- reproducible annual artifacts.

Phase 6 may then add electrical shading interaction without redesigning the Phase-5 geometry authority.
