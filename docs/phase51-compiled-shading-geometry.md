# OpenSIMPV — Phase 5.1 Compiled Shading Geometry v0.1

**Status:** Phase-5.1 implementation anchor  
**Date:** 24 September 2026  
**Scope:** Canonical Scene → deterministic CompiledShadingGeometry  
**Production shadow solver:** Not included

## 1. Objective

Phase 5.1 implements the deterministic geometry-compiler boundary frozen in
Phase 5.0:

```text
Canonical SceneRevision
        ↓
existing Phase-4 height/module geometry semantics
        ↓
CompiledShadingGeometry
```

The canonical Scene remains authoritative. The compiled artifact is derived
numerical state only.

## 2. Reuse rule

The compiler calls the existing Phase-4 `generate_scene3d()` path rather than
re-deriving module height, surface plane, module normal, or module-corner
semantics independently.

This prevents a second geometry interpretation.

## 3. Compiler identity

```text
compiler_id      = opensimpv.shading_geometry_compiler.native
compiler_version = 0.1
contract_version = 0.1
```

The compilation-input hash includes:

```text
Phase-5 contract version
compiler ID/version
canonical Scene hash
Phase-4 height-model version
GeneratedScene3D generation-input hash
```

## 4. Receiver compilation

Phase 5.1 compiles:

- every resolved ModuleInstance plane as a `module_plane` receiver;
- every Surface with `shading_receiver=true` as an `aggregate_plane`
  receiver when its current polygon can be represented without holes.

Module receiver geometry is copied from the existing Phase-4 generated module:

```text
center_xyz
normal_xyz
corners_3d
PV-field lineage
support-surface lineage
module revision lineage
row / column / table lineage
```

No module plane is reconstructed independently.

## 5. Occluder compilation

Phase 5.1 compiles:

- resolved module planes as module occluder records;
- canonical native obstacles as polygon-face vertical extrusions.

Module occluders remain present even before self-shading is evaluated.
Participation is controlled later by `self_shading_enabled`.

Obstacle `shading_enabled` is preserved exactly in the compiled artifact.

## 6. Native obstacle scope

The native v0.1 compiler accepts canonical footprint extrusions for:

```text
box
cylinder
extruded_polygon
parapet
wall
pole
simplified_tree
```

The compiler treats the canonical footprint as the geometry authority; it does
not invent additional curve/detail semantics beyond the Scene representation.

## 7. Imported mesh boundary

`imported_mesh` is **not** replaced by a footprint extrusion.

If an imported-mesh obstacle reaches the native compiler before a mesh adapter
exists:

```text
obstacle_compile_failed
```

is emitted as an error and that obstacle is omitted from the occluder set.

This is deliberate fail-closed behavior.

## 8. Polygon-hole boundary

The current Phase-5.0 face contract does not encode polygon holes.

Therefore a surface receiver or obstacle footprint with holes is not silently
filled.

The compiler emits an explicit error and omits the unsupported compiled entity.

A future triangulation/mesh adapter may remove this limitation.

## 9. Surface-occluder boundary

Phase 5.1 does **not** infer that a Surface is an occluder.

Reason:

```text
canonical Surface currently has no shading_enabled engineering field
```

Using `visible` would incorrectly mix UI state with physics.

Using `shading_receiver` would incorrectly mix receiver and occluder roles.

Therefore surface occlusion remains unresolved until an explicit engineering
contract is introduced or a later tranche demonstrates a safe equivalent.

This is an intentional limitation, not zero shading.

## 10. Obstacle receivers

The current Phase-5 receiver contract is PV/surface oriented and does not include
Obstacle as a receiver type.

If a canonical obstacle has `receiver_enabled=true`, Phase 5.1 emits:

```text
obstacle_receiver_not_supported_phase51
```

as a warning instead of silently claiming support.

## 11. Geometry payload hash

`geometry_payload_sha256` hashes exactly:

```text
coordinate_basis
receivers
occluders
bounds_3d
```

It intentionally excludes source provenance and findings.

Consequently, semantically identical compiled geometry may retain the same
geometry-payload hash even if the canonical Scene serialization changes only in
collection ordering.

The full compiled artifact hash remains sensitive to provenance.

## 12. Deterministic ordering

Before hashing, the compiler sorts:

```text
receivers  by receiver_id
occluders  by occluder_id
findings   by severity/code/entity/message
```

Obstacle face IDs are deterministic.

## 13. Findings

Phase-4 GeneratedScene3D findings are carried into the compiled artifact with a:

```text
scene3d.<original_code>
```

prefix.

Phase-5.1 compiler findings additionally cover unsupported/unresolved receiver
and occluder compilation.

No unresolved geometry is silently substituted.

## 14. Bounds

`CompiledShadingGeometry.bounds_3d` is calculated from the compiled shading
payload itself:

```text
receiver vertices
+
occluder face vertices
```

It is not copied from GeneratedScene3D, because that artifact may contain
verification-only geometry not participating in shading.

## 15. Validation evidence

Phase-5.1 tests verify:

1. source Scene is not mutated;
2. compiled artifact validates against the Phase-5.0 schema;
3. module receivers reproduce Phase-4 GeneratedScene3D corners, centers and
   normals exactly;
4. module planes become self-shading-capable occluder records;
5. native box obstacles compile to deterministic closed polygon faces;
6. explicit surface receivers compile without becoming surface occluders;
7. repeated compilation is deterministic;
8. canonical JSON save/reload reproduces the same compiled artifact;
9. collection reordering preserves geometry-payload identity while changing
   canonical Scene provenance identity;
10. disabled obstacle shading state is preserved;
11. imported meshes fail explicitly;
12. polygon holes fail explicitly;
13. unresolved modules are omitted from receiver geometry and reported.

## 16. Deliberate deferrals

Not implemented in Phase 5.1:

```text
beam shadow projection
polygon shadow clipping
ray intersection
surface-occluder semantics
imported mesh adapter
hole triangulation
receiver/execution electrical grouping
sky obstruction
ground obstruction
spatial acceleration
annual shading cache
geometry-aware SimulationRun
electrical mismatch
```

## 17. Exit gate

Phase 5.1 is complete when:

```text
same canonical Scene
→ same CompiledShadingGeometry
→ same geometry_payload_sha256
```

and compiler geometry is demonstrably inherited from Phase-4 geometry semantics.

After closure:

```text
──────── PHASE 5.1 COMPILED SHADING GEOMETRY STABLE ────────
```

Phase 5.2 may begin the receiver/execution-group foundation without redefining
geometry.
