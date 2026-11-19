# RawiBumi — Height Model and 3D Verification v0.1


**Status:** Phase 4.4 implementation specification  
**Date:** 2026-09-24  
**Parent:** Engineering Design Environment Specification v0.1


## 1. Role


Phase 4.4 generates a deterministic 3D verification representation from the same canonical Scene used by the 2D engineering editor.


The governing product rule remains:


```text
2D = engineering editing authority
3D = inspection and verification
```


The 3D representation is not an independent modeling environment.


## 2. Derived artifact


The generated artifact is `GeneratedScene3D`.


It records:


- source Scene ID and revision;
- source Scene canonical hash;
- height-model generator version;
- generation-input hash;
- resolved 3D surface planes;
- vertical obstacle/parapet geometry;
- 3D reference lines;
- resolved module centers, axes, normals and corners;
- 3D bounds;
- deterministic height findings.


It explicitly carries:


```text
authority = derived_verification_only
editable = false
mesh_editing_supported = false
```


No generated 3D vertex becomes a competing source of engineering truth.


## 3. Surface height datum


The source specifications require surface elevation, slope and azimuth but do not define the exact elevation datum for a sloped polygon.


Phase 4.4 freezes this ambiguity explicitly.


Default:


```text
base_elevation_m
=
surface plane elevation at the polygon boundary centroid
```


Optional explicit datum:


```text
elevation_reference:
  mode: explicit_xy
  x_m: ...
  y_m: ...
```


The point is in canonical local engineering XY metres.


This makes the plane independent from polygon start-vertex ordering.


## 4. Surface slope and azimuth


Engineering azimuth convention:


```text
0°   = North
90°  = East
clockwise positive
```


For a surface, `azimuth_deg` is the downhill/facing direction.


Given reference point `r`, point `p`, slope `β`, and unit downhill vector `d`:


```text
z(p) = z_ref - tan(β) × dot(p-r, d)
```


Therefore elevation decreases in the facing/downhill direction and rises opposite it.


A vertical 90° surface is not represented as a Surface; walls/parapets belong to obstacle primitives. Phase 4.4 therefore tightens canonical surface slope to:


```text
0° <= slope < 90°
```


## 5. Obstacles and parapets


Native obstacle footprints are vertically extruded.


```text
base Z = base_elevation_m
top Z  = base_elevation_m + height_m
```


This covers the initial Phase-4.4 requirements for:


- box/extruded obstacle height;
- wall height;
- parapet height;
- pole/cylinder-style parametric footprints;
- simplified-tree footprint verification.


General mesh editing is not introduced.


## 6. Module geometry


Module dimensions remain derived from the pinned component revision. For Phase-4.3-generated fields, the exact physical footprint used is persisted in `PVField.module_footprint`.


The 3D generator uses:


```text
physical_width_m
physical_height_m
field azimuth
field tilt
mounting_height_m
support-surface plane
module-instance XY anchor
```


Module physical dimensions are preserved in 3D; the module is never stretched to preserve a 2D projected rectangle.


The generated module contains:


- center XYZ;
- row-axis unit vector;
- downhill module-plane unit vector;
- upward normal;
- four physical corners;
- minimum and maximum vertical clearance to the support plane.


## 7. Mounting height semantics


Phase 4.4 defines `mounting_height_m` as the vertical Z offset between:


```text
support-plane elevation at module center
and
module center
```


This is deterministic and directly inspectable.


For a flush module whose tilt/azimuth match the support plane, every module corner has the same support clearance.


## 8. Height findings


The generated artifact may report deterministic findings including:


```text
surface height unresolved
obstacle height unresolved
module field/support unresolved
module physical geometry unresolved
negative mounting height
module intersects support plane
```


Findings do not silently change engineering geometry.


A pre-4.3/manual Scene without stored module footprint can still generate a deterministic 3D artifact; the affected module is marked unresolved rather than inventing dimensions.


## 9. Determinism


Generation is keyed by:


```text
canonical Scene JSON
+
height-model generator version
```


Identical inputs produce identical:


- planes;
- vertices;
- module corners;
- findings;
- bounds;
- generated JSON;
- generated artifact hash.


Entity output is ID-sorted so rendering/input list order does not alter semantic output ordering.


## 10. Rendering boundary


Phase 4.4 provides renderer-neutral geometry only.


A browser implementation may later render it with Three.js or another suitable engine, but rendering technology must not redefine coordinates, heights, normals or module dimensions.


The existing `DesignWorkspaceState.mode = "3d"` already provides a UI-state boundary for a future view.


## 11. Imported geometry


Optional imported 3D geometry remains a convenience/reference path.


Phase 4.4 does not implement generic imported-mesh editing or make imported meshes mandatory for ordinary rooftop or ground-mounted workflows.


## 12. Relationship to Phase 5


Phase 4.4 prepares stable geometry for Phase 5, but it does not compute:


- sun-vector intersections;
- beam shadows;
- diffuse obstruction;
- sky-view factors;
- albedo visibility;
- annual shading loss;
- electrical mismatch.


The distinction remains:


```text
deterministic 3D geometry
≠
near-shading physics
```


## 13. Regression gate


Automated tests cover:


- flat-surface constant elevation;
- pitched-plane analytical elevation;
- surface normal convention;
- centroid default datum;
- explicit XY elevation datum;
- obstacle and parapet extrusion;
- physical module width/height preservation;
- module tilt and normal;
- flush module clearance on matching roof plane;
- module/support penetration finding;
- source Scene non-mutation;
- deterministic generated hash;
- old/manual layout unresolved behavior;
- generated schema validity;
- 3D bounds;
- vertical-surface schema rejection;
- entity-order-stable generated output.


## 14. Exit criterion


Phase 4.4 is complete when every schema-valid canonical 2D Scene can deterministically produce a non-authoritative 3D verification artifact, with unsupported/unresolved physical details reported explicitly rather than invented.


The next phase may then connect component revision changes more deeply into layout consequences without changing this 2D→3D authority boundary.




## Phase 4.7H-C coherence update


The surface-plane calculation is now shared canonical geometry in `geometry/scene/surface_plane.py`, not a 3-D-only interpretation.


`ModuleInstance.transform.position_z_m` is the canonical module-center elevation. It must equal:


~~~text
support plane Z at module XY
+
PVField.mounting_height_m
~~~


where mounting height is a vertical offset.


GeneratedScene3D uses the canonical stored Z, independently recomputes the expected Z, and reports `module_center_z_inconsistent` if they differ.


3-D module width/height always use the oriented physical component dimensions. The horizontal XY projection of the resulting 3-D corners is exposed and must match the v0.2 2-D packing footprint. This removes the former ambiguity where the same `packed_*` dimensions served both 2-D packing and 3-D physical geometry.