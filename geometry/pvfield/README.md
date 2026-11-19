# PV field packing

Phase 4.3 implements deterministic PV field/module placement over canonical Scene geometry.

Core APIs:

- `PVFieldPackingSession` — explicit command session with atomic undo/redo;
- `pack_field()` — deterministic row-major packing;
- `validate_field_layout()` — non-mutating stale/conflict inspection;
- `packing_snap_edges()` — module-edge and row-edge geometry for the Phase-4.2 SnapEngine.

Engineering rules:

- local metric/support-surface geometry is authoritative;
- module dimensions come from a pinned `ModuleDefinition` revision;
- portrait/landscape footprint is never stretched;
- packing is explicit, never reactive to unrelated geometry edits;
- tilt is retained as a field parameter while independent 3-D height geometry remains Phase 4.4;
- unsupported edge-specific setback semantics fail closed;
- identical inputs plus packing command version reproduce identical module placements.

See `docs/pv-field-packing-engine.md` and ADR 0029.
