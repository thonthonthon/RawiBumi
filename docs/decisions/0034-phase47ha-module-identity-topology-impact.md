# ADR 0034 — Generated module identity follows placement, not occupied row/column

**Status:** Accepted  
**Date:** 2026-09-24

## Context

The Phase-4.3 packer originally used occupied row/column addresses as ModuleInstance IDs. This made fresh packing deterministic but allowed an explicit rebuild to reuse the same ID for a different physical placement.

Because electrical strings reference ModuleInstance IDs, row/column identity could silently reinterpret existing electrical topology after layout changes.

## Decision

1. Occupied row/column is no longer canonical generated ModuleInstance identity.
2. Fresh generated modules receive deterministic placement-derived IDs.
3. The placement identity is versioned.
4. An existing ID survives a generated rebuild only when the generated placement fingerprint is unchanged.
5. Existing legacy row/column IDs are preserved on a no-op/equivalent rebuild for backward compatibility.
6. Generated grid row/column metadata remains lineage information for old/new pairing.
7. Changed generated placements receive new IDs.
8. Layout rebuilds produce a deterministic `PVFieldLayoutImpactReport`.
9. Strings referencing invalidated old IDs are reported as stale.
10. Electrical topology is never silently rewritten by a layout rebuild.
11. Component-driven rebuilds expose the same layout/topology impact.
12. Manual engineer-authored movement is deferred to Phase 4.7H-B and is not forced to use generated-replacement semantics.
13. Canonical Z is not part of the placement fingerprint until Phase 4.7H-C resolves 2D/3D height authority.

## Consequences

A string can no longer remain apparently valid merely because a changed module happens to occupy the same row/column ordinal after repacking.

No-op rebuilds remain backward compatible, including existing Phase-4.3 row/column IDs.

Topology repair remains explicit and engineer-controlled.

The design→simulation integration in Phase 4.8 can now distinguish a stable electrical reference from one invalidated by a generated layout replacement.
