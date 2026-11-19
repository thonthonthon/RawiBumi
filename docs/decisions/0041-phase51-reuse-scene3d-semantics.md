# ADR 0041 — Phase-5 shading geometry compiler reuses GeneratedScene3D semantics

**Status:** Accepted by Phase 5.1  
**Date:** 2026-09-24

## Context

Phase 4 already defines deterministic surface planes, height datums, obstacle
extrusion, module axes, module normals and module corners.

Reimplementing those semantics inside a shading subsystem would create two
independent interpretations of the same canonical Scene.

Phase 5 also needs stable numerical hashing independent of presentation/UI state.

## Decision

1. `compile_shading_geometry()` consumes the canonical Scene.
2. It invokes the existing Phase-4 `generate_scene3d()` geometry path.
3. Resolved module receiver/occluder geometry is copied from that derived
   artifact rather than independently reconstructed.
4. Native obstacle extrusion uses the same GeneratedScene3D base/top vertices.
5. Compiled geometry is sorted and deterministically hashed.
6. The geometry-payload hash covers only numerical shading geometry and bounds.
7. Source Scene hash and compiler/height-model versions remain separate
   provenance inputs.
8. Imported mesh geometry is not approximated from its footprint.
9. Polygon holes are not silently filled.
10. Surface occlusion is not inferred because canonical Surface currently lacks
    an explicit shading-participation field.

## Consequences

### Positive

- Phase-4 and Phase-5 module geometry cannot drift independently;
- save/reload determinism can be proven with hashes;
- later beam/sky/ground solvers share one numerical geometry artifact;
- unsupported geometry remains visible rather than silently simplified.

### Deliberate limitations

- surface occlusion remains a later contract decision;
- imported meshes require an adapter;
- polygon holes require future triangulation or richer face representation;
- no shading physics is executed in this ADR/tranche.
