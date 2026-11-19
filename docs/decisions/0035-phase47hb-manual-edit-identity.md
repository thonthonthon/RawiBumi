# ADR 0035 — Manual edits preserve object identity; generated rebuilds use replacement semantics

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4 requires both deterministic generation and direct engineer adjustment.

Phase 4.7H-A established that generated rebuilds must not reuse a ModuleInstance ID for a different generated physical placement.

Manual editing introduces a different operation: the engineer is explicitly moving an existing engineering object.

Treating that manual move as deletion/recreation would unnecessarily invalidate electrical references. Treating later generated rebuilds as the same object would silently reinterpret those references.

## Decision

1. Explicit manual module move preserves ModuleInstance ID.
2. Explicit manual module plan rotation preserves ModuleInstance ID.
3. Manual edits mark manual_position_override=true.
4. A field containing manual module edits uses layout_status=manual.
5. The active generated packing hash is cleared; the last generated hash is retained as provenance metadata.
6. Generated row/column/table information becomes lineage, not proof of current geometric alignment.
7. StringCircuit membership remains identity-valid after manual movement because it still references the same ModuleInstance.
8. ElectricalDesignRevision is never automatically rewritten by manual geometry editing.
9. Manual module azimuth is read from ModuleInstance.transform.rotation_z_deg by 3D generation and engineering orientation validation.
10. Generated rebuilds continue to use Phase-4.7H-A replacement semantics.
11. If a generated placement-derived ID collides with a manually moved old object ID at a non-equivalent placement, a deterministic replacement ID is generated instead of resurrecting the old identity.
12. Explicit vertex editing preserves the edited surface/obstacle/reference object identity.
13. Vertex edits validate polygon/line geometry before mutation and fail closed if invalid.
14. Snapping may exclude the edited entity to prevent self-snapping.
15. Per-module tilt and canonical Z semantics are deferred.

## Consequences

Users can generate a layout, move individual modules, edit site vertices, save/reload, and retain electrical object references.

Automation remains explicit and cannot silently erase manual engineering intent.

A later rebuild can intentionally replace the manual layout while producing correct identity/topology consequences.
