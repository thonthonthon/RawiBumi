# ADR 0028 — Phase-4.2 editor kernel operates directly on canonical Scene drafts

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4.2 requires deterministic geometry manipulation, exact dimensions, snapping, undo/redo, and save/reload behavior.

Two architecture risks are creating a separate browser-only geometry model that later has to synchronize with canonical Scene JSON, and putting transient selection, snap markers, or command history into the simulation-facing model.

## Decision

1. The editor kernel operates on a deep-copied draft of the canonical Scene.
2. Engineering edits modify canonical-shape objects directly in local metric XY.
3. The original pinned Scene revision is never mutated.
4. A completed editing session emits a new Scene revision.
5. Selection, active interaction state, snap feedback, and undo/redo remain workspace/session state.
6. Undo/redo initially uses complete draft-Scene snapshots.
7. Every mutating command is atomic and rolls back completely on failure.
8. Exact dimension provenance is stored with the affected canonical edge.
9. Snap resolution is deterministic and returns visible feedback metadata.
10. Snapping never changes geometry until an explicit editor command is completed.
11. Module-edge and row-edge snaps are extension points for Phase 4.3; Phase 4.2 does not generate modules.
12. The engineering kernel is renderer/framework independent.

## Consequences

Positive consequences are one engineering geometry representation, direct save/reload, frontend technology independence, safe undo rollback, traceable dimension overrides, and a stable extension surface for Phase 4.3.

Trade-offs are higher memory use from complete-scene snapshots, no user-facing graphical browser runtime yet, no complex polygon-boolean editor, and no mechanical-CAD constraint solver.

## Rejected alternatives

A separate browser geometry authority was rejected because it creates competing sources of engineering truth. Persisting undo history in Scene was rejected because undo state is interaction state. Auto-applying snaps after placement was rejected because snaps must be visible and overridable. PV packing was kept out because the handoff separates it into Phase 4.3.
