# ADR 0044 — Beam-factor snapshots reuse ShadingResult and keep projected geometry diagnostic-only

**Status:** Accepted by Phase 5.4  
**Date:** 2026-09-24

## Context

Phase 5.3 computes one receiver's direct-beam geometric visibility correctly.

Phase 5.4 needs receiver-set orchestration, execution-group linkage, reproducible factor artifacts, and inspectable projected geometry.

Creating a second main factor-result model would duplicate the Phase-5.0 ShadingResult contract.

Embedding full projected polygons in every normal factor record would also make future annual datasets unnecessarily large.

## Decision

1. Reuse ShadingResult as the authoritative derived factor artifact for receiver-set beam snapshots.
2. Keep channels explicit and set Phase-5.4 channels to beam_visibility only.
3. Leave sky and ground factors null rather than fabricating neutral values.
4. Require explicit receiver selection or receiver IDs derived from SimulationExecutionGroupPlan.
5. Bind execution-plan selection to the same CompiledShadingGeometry hash.
6. Normalize and sort receiver IDs before execution and hashing.
7. Add deterministic receiver-set, sun-state, configuration, orchestrator, and payload identities.
8. Keep the Phase-5.3 direct-beam equations unchanged.
9. Collect projected polygons through the same beam calculation path only when diagnostics are explicitly requested.
10. Store detailed projected geometry in a separate BeamShadowDiagnosticArtifact.
11. Mark that artifact derived_diagnostic_only and non-editable.
12. Ensure enabling diagnostics does not change ShadingResult content or identity.
13. Reject requested diffuse, ground, angular-cache, subdivision, or hidden model behavior that Phase 5.4 does not implement.
14. Use R4/VC5 only as a realistic directional integration scene, not as a calibration target.
15. Do not integrate beam factors into annual SimulationRun in this tranche.

## Consequences

Positive:

- one main shading-factor contract is preserved;
- receiver-set factors are deterministic and execution-group aware;
- future caches already have receiver-set and sun-state identities;
- diagnostics can support engineering inspection and future preview without bloating normal output;
- debug geometry cannot diverge from scalar factors through a second solver;
- R4 now exercises the full geometry-to-receiver-factor chain.

Deliberate limitations:

- one sun state per snapshot;
- inline factor records only in this tranche;
- no annual irradiance modification;
- no diffuse or ground visibility;
- no spatial acceleration/cache implementation;
- no electrical mismatch.

## Revisit condition

Projected diagnostic geometry may later be stored externally or streamed to the UI, but it must remain derived/non-authoritative and must not alter the scalar shading-result identity.
