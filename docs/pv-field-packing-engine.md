# RawiBumi — PV Field and Packing Engine v0.1


**Status:** Phase 4.3 implementation specification  
**Date:** 2026-09-24  
**Parent:** Engineering Design Environment Specification v0.1  
**Scope:** deterministic PV field placement over canonical Phase-4 scene geometry


## 1. Purpose


Phase 4.3 converts exact Phase-4.2 surfaces and obstacles into reproducible PV field/module placements.


The subsystem is intentionally a constrained PV packing engine, not a generic two-dimensional optimization/CAD solver.


The governing interaction rule is:


```text
geometry change
≠
automatic PV field rebuild
```


A geometry change may make a layout invalid. RawiBumi reports that condition. The engineer explicitly invokes `Rebuild Field` or another packing command if a new layout is wanted.


## 2. Canonical authority


Packing consumes:


```text
Scene surface/exclusion/obstacle geometry
+
pinned ModuleDefinition revision
+
PVField engineering parameters
+
packing-command version
```


and produces:


```text
PVField
+
deterministic ModuleInstance coordinates
+
row/table membership
+
packing input hash
```


The module revision is pinned. Mechanical dimensions come from the component revision and are never visually stretched to make a layout fit.


For reproducibility, the PVField stores the exact physical and packed module footprint used by the packing command in addition to the component revision reference.


## 3. Phase-4.3 two-dimensional basis


Packing is performed in the canonical support-surface 2-D engineering plane.


The stored module footprint is:


```text
portrait:
  packed width  = component mechanical width
  packed height = component mechanical height


landscape:
  packed width  = component mechanical height
  packed height = component mechanical width
```


`tilt_deg` remains a canonical PVField parameter but Phase 4.3 does not project tilt into independent 3-D geometry. Deterministic 3-D generation, roof slope and height geometry are Phase 4.4.


This prevents Phase 4.3 from inventing a second height model before the Phase-4.4 contract exists.


## 4. Field parameters


The implemented contract includes:


```text
module definition revision
portrait / landscape orientation
field azimuth
module tilt
module gap X
module gap Y
row pitch
mounting height
perimeter setback
obstacle setback
walkway / exclusion rules
row alignment
optional requested row count
optional requested modules per row
table arrangement
```


### Row pitch


`row_pitch_m` is the centre-to-centre spacing of consecutive packing rows in the support-surface 2-D plane.


It must satisfy:


```text
row_pitch_m >= packed_module_height_m + module_gap_y_m
```


A configuration that would overlap consecutive rows fails closed.


### Table arrangement


The first table contract supports:


```text
modules_per_table_x
table_gap_x_m
```


Modules within a table use `module_gap_x_m`. Adjacent tables may use the separate table gap.


More complex table topology can extend the table configuration without changing module placement identity.


## 5. Deterministic grid and identities


The packer builds a field-aligned coordinate frame:


```text
field +Y = field azimuth
field +X = row direction
```


Candidate placements are evaluated in deterministic row-major order.


Phase 4.7H-A hardens generated module identity. Occupied row/column order remains packing lineage, but is no longer canonical object identity.


Fresh generated IDs use a versioned placement fingerprint:


```text
<field-id>-m-<placement-hash-prefix>
```


An existing ID survives an explicit generated rebuild only when the generated physical placement is equivalent. Existing legacy Phase-4.3 row/column IDs are preserved on an equivalent/no-op rebuild so migration does not invalidate topology unnecessarily.


Changed/new generated placements receive new deterministic IDs. Grid-row/grid-column metadata remains available for deterministic old/new pairing in `PVFieldLayoutImpactReport`.


For identical authoritative inputs and the same packing/identity algorithm versions, the resulting module IDs, coordinates, row/table indices and packing hash are identical.


## 6. Setbacks and exclusions


### Perimeter setback


A module footprint must be wholly inside the support polygon and must satisfy the configured minimum geometric distance from the support boundary.


The setback check is geometric and independent of map zoom/rendering resolution.


### Exclusion surfaces


By default, canonical surfaces of these types are treated as hard exclusions when they intersect the support area:


```text
exclusion_area
walkway
```


The command contract can instead use explicit surface IDs.


### Obstacles


By default, scene obstacles intersecting the support footprint are treated as hard exclusions. An additional `obstacle_setback_m` may be applied around them.


The resolved exclusion/obstacle IDs are recorded on the generated field.


### Edge-specific setbacks


The canonical schema continues to allow edge-specific setback metadata, but the Phase-4.3 deterministic packer fails closed if such a rule is supplied because a versioned general polygon-offset semantics has not yet been frozen.


This is preferable to silently approximating a construction setback.


## 7. Commands


The renderer-neutral Phase-4.3 command set is:


```text
Fill Area
Find Maximum Modules
Orient to Edge
Align Rows
Equalize Spacing
Change Orientation
Rebuild Field
```


Commands are explicit interaction operations, not background behavior.


### Fill Area


Builds module instances using the current field parameters.


### Find Maximum Modules


Evaluates supported deterministic packing alternatives without mutating engineering state. It is advisory; accepting a different orientation/layout requires an explicit command.


The current v0.1 search compares the supported portrait/landscape deterministic-grid candidates under the field's other frozen parameters. It is not presented as a proof of the global optimum over arbitrary continuous placement.


### Orient to Edge


Aligns either the field row axis or field column axis to a selected support edge, then performs the explicitly requested rebuild.


### Align Rows


Supported row-envelope alignment policies are:


```text
start
center
end
```


### Equalize Spacing


The initial command supports:


- equal horizontal spacing based on the support envelope and current module count per row;
- equal row pitch based on the support envelope and current row count.


The command fails if the resulting spacing would violate physical module dimensions or configured minimum gap.


### Change Orientation


Explicitly switches portrait/landscape and rebuilds the field.


### Rebuild Field


Replaces the field's generated module instances from the current authoritative geometry and parameters.


## 8. Conflict detection without mutation


`PVFieldConflictReport` inspects current module placements against current scene geometry.


It checks:


```text
packing input hash changed
module outside support/perimeter setback
module overlapping exclusion/walkway
module overlapping obstacle
module violating obstacle setback
module-module positive-area overlap
```


The report never moves a module.


Example:


```text
Obstacle moved
→ current ModuleInstances remain unchanged
→ report: packing_inputs_changed
→ report: module_obstacle_overlap
→ engineer chooses Keep Current Layout or Rebuild Field
```


This is the central Phase-4.3 manual-authority rule.


## 9. Packing input hash


The packing-input SHA-256 includes the material inputs to placement:


- packing command version;
- support boundary and base elevation;
- pinned module revision and dimensions;
- orientation, azimuth and tilt;
- gaps, row pitch and mounting height;
- setbacks;
- table configuration;
- packing parameters;
- exclusion rules;
- resolved current exclusion/obstacle geometry.


Generated module coordinates are outputs and are not fed back into the input hash.


This makes stale-layout detection deterministic.


## 10. Snapping integration


Phase 4.3 supplies real `module_edge` and `row_edge` supplemental geometry to the Phase-4.2 `SnapEngine`.


No second snapping engine is introduced.


## 11. Undo / redo


`PVFieldPackingSession` uses complete Scene snapshots for atomic command undo/redo, matching the deterministic behavior chosen for Phase 4.2.


A failed packing command restores the exact pre-command Scene.


## 12. Explicit exclusions from Phase 4.3


Phase 4.3 does not implement:


```text
3-D roof/module geometry
tilt projection / shadow geometry
near-shading calculation
row-pitch optimization from annual shading
component revision replacement workflow
stringing
MPPT assignment
electrical validation
trackers
structural rules
generic polygon Boolean editing
continuous hidden repacking
```


Those belong to later phases.


## 13. Regression gate


The automated Phase-4.3 suite covers:


- portrait/landscape physical footprint resolution;
- exact rectangular reference packing;
- deterministic repeated packing;
- perimeter setback;
- exclusions and obstacle setback;
- table grouping;
- advisory maximum-module search without mutation;
- explicit orientation changes and undo/redo;
- Orient to Edge;
- row alignment;
- equal spacing;
- obstacle movement without silent module movement;
- conflict reporting;
- explicit rebuild;
- module-edge and row-edge snapping;
- canonical schema validation;
- save/reload canonical identity.


## 14. Exit criterion


Phase 4.3 is complete when:


```text
identical:
  surface geometry
  component revision
  field parameters
  packing command version


produce identical:
  module identities
  module coordinates
  row/table assignments
  packing input hash
```


and a changed obstacle/surface can invalidate the existing field without silently changing it.


The resulting canonical scene is then ready for Phase 4.4 deterministic height/3-D verification.




## Phase 4.7H-C geometry basis clarification


Phase 4.7H-C upgrades the packing geometry basis to `rawibumi-packing-0.2`.


Canonical Scene X/Y and all `boundary_2d` geometry are horizontal engineering-plan coordinates. The packing engine therefore uses the horizontal projection of the physical tilted module plane:


~~~text
plan width  = oriented physical plane width
plan height = oriented physical plane height × cos(tilt)
~~~


The stored legacy fields `packed_width_m` and `packed_height_m` remain the oriented physical module-plane dimensions for compatibility. New fields `plan_projection_width_m` and `plan_projection_height_m` are used for packing, overlap, setback and snap-edge geometry.


Module gap, row pitch, perimeter setback and obstacle setback are horizontal-plan distances in v0.1.


Generated module center Z is canonicalized as support-plane elevation at module XY plus the field's vertical mounting-height offset. An explicit rebuild is still required to change XY packing after support geometry changes.