# ADR 0038 — ProjectRevision remains the Design → Simulation pinning boundary

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 3.8E already established ProjectRevision + SimulationConfiguration as the canonical simulation entry point.

Phase 4 adds Scene editing, PV packing, component binding, electrical topology and engineering validation. The integration risk is creating a separate editor-specific simulation input model or allowing UI state to leak into physics.

DesignValidationReport also introduces a derived gate that must be traceable without becoming an independent physics source of truth.

## Decision

1. ProjectRevision remains the canonical design-to-simulation pinning boundary.
2. Scene and ElectricalDesignRevision remain independently revisioned and are referenced by ProjectRevision.
3. Weather revision is explicitly pinned before simulation.
4. Component revisions are resolved from IDs already stored in Scene and ElectricalDesignRevision.
5. SimulationConfiguration remains a separate explicit execution configuration.
6. DesignWorkspaceState is not accepted by the simulation bridge.
7. The Phase-4 high-level execution path requires a DesignValidationReport for the exact Project/Scene/Electrical revisions.
8. The current engineering rule-set ID must match the report.
9. A blocking or inconsistent validation report stops before numerical execution and produces a failed SimulationRun.
10. Non-blocking design findings are preserved as run evidence.
11. DesignValidationReport ID, rule set and canonical hash are recorded in SimulationRun/ReproducibilityManifest.
12. The validation report is derived evidence and is excluded from the numerical combined input hash.
13. The existing run_canonical_simulation worker remains the numerical authority.
14. Unsupported numerical scopes remain explicit blockers rather than being flattened.
15. Integrated design execution must reproduce the direct canonical result for equivalent inputs.

## Consequences

The editor can evolve without creating a second physics contract.

Historical SimulationRun objects continue to reference immutable engineering revisions.

A validation policy update can change launch evidence without falsely changing the identity of unchanged numerical physics inputs.

Phase 4.9 can now test broader project/save/reload workflows against one stable execution boundary.
