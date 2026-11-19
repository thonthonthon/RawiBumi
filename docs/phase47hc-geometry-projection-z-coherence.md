# OpenSIMPV — Phase 4.7H-C 2D ↔ 3D Geometry / Projection / Z Coherence

**Status:** Implementation specification  
**Date:** 2026-09-24  
**Parent:** Phase 4 Engineering Design Environment  
**Predecessor:** Phase 4.7H-B Manual Module and Vertex Editing

## 1. Purpose

Phase 4.7H-C freezes the geometric meaning of canonical PV design coordinates before Design → Simulation integration and before Phase 5 near-shading consumes the Scene.

The unresolved questions were:

~~~text
what does boundary_2d mean on a sloped surface?
what do ModuleInstance X/Y represent?
what does ModuleInstance Z represent?
what 2-D footprint is used for a tilted physical module?
does 3-D use projected dimensions or physical module dimensions?
~~~

These are now explicit.

## 2. Canonical coordinate authority

OpenSIMPV keeps one editable engineering coordinate frame:

~~~text
X = horizontal local engineering X
Y = horizontal local engineering Y
Z = elevation
~~~

Surface boundary_2d is the horizontal engineering-plan projection. It is not a support-surface UV coordinate system.

No hidden second 2-D coordinate basis is introduced. This preserves direct consistency with map geometry, survey plan geometry, orthophoto alignment, snapping, exclusion polygons, obstacle footprints, manual vertex editing, and PV module plan placement.

## 3. Surface height model

A planar surface is resolved by:

~~~text
boundary_2d
base_elevation_m
slope_deg
azimuth_deg
elevation_reference
~~~

The shared canonical resolver is:

~~~text
geometry.scene.surface_plane.SurfacePlane
~~~

Both canonical Scene maintenance and derived 3-D generation use this same implementation. SurfacePlane is no longer a 3-D-only interpretation.

## 4. Module canonical center coordinates

For a ModuleInstance, position_x_m and position_y_m are horizontal engineering-plan coordinates.

Canonical center Z is:

~~~text
position_z_m
=
support_surface_elevation(position_x_m, position_y_m)
+
mounting_height_m
~~~

mounting_height_m is the vertical Z offset from the support plane at module center XY to the module center. It is not a surface-normal distance.

Generated modules record:

~~~text
metadata.position_z_basis
=
support_plane_plus_vertical_mounting_height
~~~

## 5. Z synchronization

Canonical Z is maintained whenever authoritative Scene geometry changes.

SceneEditorSession mutation re-synchronizes module center Z from the current support surface, current module XY, and current field mounting height.

This is derived-coordinate maintenance only. It does not alter module X/Y, ModuleInstance ID, PVField membership, row/column lineage, StringCircuit membership, or MPPT assignment.

Therefore editing a pitched roof vertex may update module Z without replacing the module object.

## 6. Manual module movement

A manual move continues to preserve ModuleInstance identity.

After changing module X/Y, position_z_m is recomputed from the support plane and mounting height in the same atomic operation.

This ensures a manually moved module on a sloped roof cannot retain a stale elevation.

## 7. Physical module plane versus 2-D packing footprint

Component dimensions remain physical dimensions.

For portrait orientation:

~~~text
physical plane width  = component width
physical plane height = component height
~~~

For landscape:

~~~text
physical plane width  = component height
physical plane height = component width
~~~

These physical plane dimensions are used by GeneratedScene3D. They are not reduced by tilt.

## 8. Horizontal plan projection

The canonical 2-D packing footprint is the horizontal projection of the physical tilted module plane.

For the current one-axis tilt convention:

~~~text
plan projection width
=
physical oriented plane width

plan projection height
=
physical oriented plane height × cos(tilt)
~~~

The row axis is horizontal. The downhill module-plane axis contains the tilt.

Therefore the projected 2-D rectangle is exactly the XY projection of the four 3-D module corners.

## 9. ModuleFootprint v0.2 semantics

Packing command version:

~~~text
opensimpv-packing-0.2
~~~

New packing basis:

~~~text
horizontal_plan_projection
~~~

Module footprint stores both domains:

~~~text
physical_width_m
physical_height_m

packed_width_m
packed_height_m
~~~

The legacy names packed_width_m / packed_height_m remain readable and represent the oriented physical module-plane dimensions.

New explicit fields:

~~~text
tilt_deg
plan_projection_width_m
plan_projection_height_m
packing_basis = horizontal_plan_projection
~~~

2-D packing, setbacks, overlap checks and snap edges use the plan-projection dimensions.

3-D generation uses the oriented physical dimensions.

## 10. Legacy Phase-4.3 footprint compatibility

Legacy scenes may contain:

~~~text
packing_basis = support_surface_2d
packed_width_m
packed_height_m
~~~

without explicit projected dimensions.

They remain readable.

The v0.2 resolver reconstructs:

~~~text
plan_projection_width_m
=
legacy packed_width_m

plan_projection_height_m
=
legacy packed_height_m × cos(current field tilt)
~~~

No legacy file rewrite is required merely to inspect the design. An explicit rebuild writes the new footprint basis.

## 11. Packing distances

For Phase 4 v0.1, the following are horizontal-plan distances:

~~~text
module_gap_x_m
module_gap_y_m
row_pitch_m
perimeter_setback_m
obstacle_setback_m
~~~

This is deliberate because the editor authority is horizontal engineering XY.

A future UI may offer input conversion from roof-plane/surface distances, but such conversion must be explicit and must not create a second hidden canonical coordinate frame.

## 12. 90-degree tilt

The Scene schema can represent tilt up to 90° for general canonical data.

Deterministic 2-D area packing requires:

~~~text
0 <= tilt < 90°
~~~

because a 90° physical module has zero horizontal projected height.

The packing engine therefore rejects 90° for plan-projection packing rather than inventing an epsilon footprint.

## 13. GeneratedScene3D authority

GeneratedScene3D remains:

~~~text
derived_verification_only
editable = false
~~~

For modules, it now distinguishes physical plane dimensions, horizontal plan projection dimensions, canonical center Z, expected support-derived center Z, and center-Z residual.

3-D center Z is taken from the canonical Scene. The generator independently calculates the expected support-derived Z.

If they differ:

~~~text
module_center_z_inconsistent
→ error finding
~~~

The generator reports the inconsistency rather than silently overriding canonical Scene state.

## 14. Projection verification

GeneratedScene3D records:

~~~text
plan_projection_width_m
plan_projection_height_m
plan_projection_corners_xy
~~~

The projected corners are directly derived from the physical 3-D module corners.

For a coherent design:

~~~text
2-D packing rectangle
=
XY projection of 3-D physical module plane
~~~

within numerical tolerance.

A stored projected footprint inconsistent with physical dimensions and tilt produces:

~~~text
module_plan_projection_inconsistent
→ error finding
~~~

## 15. Support-plane edits

If a support boundary, elevation, slope, azimuth or elevation reference changes:

~~~text
module XY remains unchanged
module identity remains unchanged
module Z is re-synchronized
packing_input_hash comparison becomes stale
PV field conflict report exposes packing_inputs_changed
~~~

The editor does not silently repack modules.

This preserves the governing rule:

~~~text
support geometry changed
→ existing field may need review
→ engineer decides whether to rebuild
~~~

## 16. Identity boundary

Module generated identity continues to exclude Z.

Rationale:

~~~text
same ModuleInstance
same support surface
same plan XY
same orientation/tilt/mounting relationship
+
support elevation/slope changes
~~~

does not necessarily mean the engineering object was replaced.

Z is a canonical derived coordinate of that same object.

Generated replacement identity remains governed by Phase 4.7H-A / H-B plan-placement semantics.

## 17. Height-model version

Derived 3-D height model version becomes:

~~~text
opensimpv-height3d-0.2
~~~

The support-plane implementation itself is versioned:

~~~text
opensimpv-surface-plane-0.1
~~~

This makes the geometry interpretation traceable in GeneratedScene3D.

## 18. Regression gate

Phase 4.7H-C regression coverage includes:

~~~text
physical plane vs projected footprint dimensions
legacy footprint reconstruction
2-D packing polygon = XY projection of 3-D corners
pitched-roof canonical module Z
manual move on pitched roof updates Z
support vertex edit re-synchronizes Z
module identity preserved through support edit
packing_inputs_changed remains visible
stale canonical Z is reported by 3-D
canonical save/reload hash invariance
~~~

## 19. Explicit exclusions

Phase 4.7H-C does not implement:

~~~text
near-shading ray tracing
terrain mesh following
non-planar roof surfaces
surface-local UV editing
per-module tilt editing
structural mounting geometry
rail/clamp geometry
roof-plane-distance authoring mode
~~~

These are separate concerns.

## 20. Exit criterion

Phase 4.7H-C is complete when:

1. one canonical horizontal XY coordinate meaning is used by map, 2-D editor, PV packing and 3-D projection;
2. tilted module 2-D packing footprint exactly matches the horizontal projection of its physical 3-D plane;
3. physical module dimensions remain unchanged in 3-D;
4. canonical module center Z equals support-plane Z at module XY plus vertical mounting height;
5. manual movement and support geometry edits maintain that Z invariant without automatic repacking;
6. stale canonical Z is detectable rather than silently reinterpreted;
7. legacy Phase-4.3 footprint data remains readable;
8. save/reload remains deterministic.
