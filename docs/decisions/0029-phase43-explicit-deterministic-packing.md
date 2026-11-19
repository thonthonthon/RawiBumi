# ADR 0029 — Phase-4.3 packing is explicit, deterministic, and non-reactive

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4.3 must generate reproducible PV module coordinates while preserving the product rule that the engineer remains authoritative.

A reactive constraint system that automatically repacks a field after a roof, exclusion, obstacle, component or spacing change would make the visible design state unstable and would break the distinction between an engineering decision and a software suggestion.

The platform also needs enough packing provenance to reproduce a layout and to determine when a previously generated layout is stale.

## Decision

1. PV packing is invoked only by explicit commands.
2. Geometry changes do not automatically regenerate module placements.
3. The packer consumes canonical local-metric Scene geometry and a pinned ModuleDefinition revision.
4. Component mechanical dimensions determine module footprint; modules are never stretched.
5. Phase 4.3 packs in the support-surface 2-D plane. Independent 3-D tilt/height geometry remains Phase 4.4.
6. Packing uses a versioned deterministic row-major grid.
7. Generated module IDs are deterministic from field/row/column identity.
8. The PVField stores the exact footprint dimensions used and the packing command version.
9. A SHA-256 packing-input hash fingerprints support/exclusion geometry, component footprint and packing parameters.
10. Conflict validation is non-mutating.
11. Moving an obstacle may produce a conflict report but cannot move/repack modules.
12. Rebuild Field is the explicit operation that replaces generated placements.
13. Module-edge and row-edge snaps extend the existing Phase-4.2 SnapEngine rather than creating a second snap model.
14. Unsupported edge-specific setback semantics fail closed rather than being silently approximated.

## Consequences

Positive consequences are deterministic save/reload behavior, clear stale-layout detection, stable manual edits, testable packing semantics, direct compatibility with immutable Scene revisions, and no hidden design changes.

Trade-offs are that v0.1 is a constrained grid packer rather than a mathematical global optimizer, complex polygon offset/setback rules remain deferred, tilt does not yet create independent 3-D footprint geometry, and some engineer-triggered changes require a subsequent explicit rebuild.

## Rejected alternatives

Continuous automatic repacking was rejected because it violates engineer authority. Pixel/render-space packing was rejected because local metric geometry is authoritative. Generic CAD constraint solving was rejected as outside product scope. Treating Find Maximum Modules as a proven global optimum was rejected because arbitrary polygon packing requires a substantially different optimization contract and validation basis.
