# 2D scene editor subsystem

This directory owns the canonical Scene schema and the Phase-4.2 constrained 2D engineering editor kernel.

## Files

- scene.schema.json — canonical immutable Scene-revision serialization.
- geometry2d.py — deterministic planar geometry primitives.
- primitives.py — native surface, obstacle and reference-line constructors.
- snapping.py — visible deterministic snap resolution.
- editor.py — atomic editing session/command behavior and Scene revision commit.
- serialization.py — deterministic canonical Scene JSON and SHA-256 hashing.

## Governing rules

- local XY metres are authoritative;
- map/screen pixels are never construction geometry;
- accepted edits become a new Scene revision;
- selection and undo/redo are not simulation inputs;
- failed commands leave the draft unchanged;
- snaps provide visible feedback and can be overridden;
- exact dimension overrides preserve source provenance;
- Phase 4.2 does not pack or repack PV modules.

See docs/2d-constrained-scene-editor.md.
