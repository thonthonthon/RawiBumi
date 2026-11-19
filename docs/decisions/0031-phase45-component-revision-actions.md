# ADR 0031 — Component revision changes use analyze → explicit apply

**Status:** Accepted  
**Date:** 2026-09-24

## Context

PV module and inverter definitions already carry immutable revision IDs, but Phase 4 requires those revisions to become active engineering inputs rather than passive metadata.

A module revision can change dimensions, STC properties, string limits and available models. An inverter revision can change DC/MPPT limits, topology, AC power and efficiency behavior.

Silently replacing a revision and repairing the design would violate the established engineer-authority rule.

## Decision

1. Scene and ElectricalDesign continue to pin exact component revision IDs.
2. Component-facing design properties are resolved from the exact revision through deterministic snapshots.
3. Proposed revision changes are analyzed first and do not mutate.
4. Module change analysis evaluates the proposed physical footprint against current module centers, support boundaries, exclusions, obstacles and setbacks.
5. Module change analysis previews an explicit Phase-4.3 rebuild and reports module-count changes.
6. Existing strings referencing the changed field are identified but never automatically changed.
7. Applying a module revision can either keep coordinates or explicitly invoke Rebuild Field.
8. Inverter change analysis normalizes the proposed MPPT topology and compares it with the current ElectricalDesign.
9. Applying an inverter revision keeps the current topology in Phase 4.5; automatic MPPT/string reconstruction is deferred to Phase 4.6.
10. Detailed electrical limit evaluation is deferred to Phase 4.7; Phase 4.5 exposes the exact limits and marks revalidation requirements.
11. All explicit apply operations are atomic and undoable.
12. No component recommendation/ranking is introduced.

## Consequences

Component revisions now materially control geometry, electrical-design inputs and simulation capability while remaining immutable library records.

A design can intentionally retain a now-conflicting layout/topology after an explicit revision change, but the conflict state is visible rather than silently repaired.

Phase 4.6 and 4.7 can build on stable exact-revision contracts instead of re-resolving component semantics independently.
