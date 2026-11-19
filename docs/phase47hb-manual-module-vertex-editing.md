# OpenSIMPV — Phase 4.7H-B Manual Module and Vertex Editing

**Status:** Implementation specification  
**Date:** 2026-09-24  
**Parent:** Phase 4 Engineering Design Environment  
**Predecessor:** Phase 4.7H-A Module Identity and Topology Impact Hardening

## 1. Purpose

Phase 4.7H-B closes the Phase-4 editor-maturity gap between generated engineering layouts and engineer-authored manual adjustment.

The governing distinction is:

~~~text
explicit manual edit of an existing object
→ preserve object identity
→ change canonical geometry

explicit generated rebuild
→ replacement semantics
→ preserve identity only for equivalent generated placement
~~~

This distinction is required so a user can generate a PV layout, manually adjust it, save/reload it, and retain the engineering meaning of electrical references without allowing later automation to silently reinterpret identity.

## 2. Manual Module Identity

An engineer-authored move or rotation of an existing ModuleInstance preserves:

~~~text
module_instance_id
module_definition_revision_id
pv_field_id
string membership
~~~

The edit changes canonical geometry.

The module is marked:

~~~text
metadata.manual_position_override = true
metadata.manual_edit_version = opensimpv-manual-layout-edit-0.1
metadata.identity_origin = manual_edit_preserved
~~~

The PVField becomes:

~~~text
layout_source = generated_then_edited
layout_status = manual
~~~

The previous generated packing input hash is retained as provenance under field metadata, while the active packing_input_hash becomes null because the current module coordinates are no longer the direct output of that pack.

Generated row/column information remains lineage only after manual editing.

## 3. Manual Module Move

PVFieldPackingSession.move_module() accepts an explicit target XY position.

Optional snapping uses the existing deterministic SnapEngine.

Supported behavior includes:

~~~text
target coordinate
snap tolerance
enabled snap kinds
user grid spacing
temporary snap override
~~~

The module itself is excluded from module-edge snap candidates.

The edit is atomic and undoable.

After the edit, the current field conflict report is returned without reverting the engineer's choice.

Therefore:

~~~text
manual edit causes overlap
→ edit remains canonical draft state
→ conflict is visible
→ engineer decides next action
~~~

## 4. Manual Module Rotation

PVFieldPackingSession.rotate_module() changes the module's canonical plan azimuth:

~~~text
ModuleInstance.transform.rotation_z_deg
~~~

The ModuleInstance ID is preserved.

The field remains a manual layout.

This individual module azimuth now propagates to:

~~~text
GeneratedScene3D
Engineering Validation orientation mismatch checks
~~~

Generated modules remain equivalent to field azimuth because the packing engine writes the field azimuth into each generated module transform.

## 5. Electrical Topology Semantics

Manual movement does not invalidate StringCircuit membership merely because geometry changed.

If a moved module belongs to a string, the manual edit report returns:

~~~text
membership_status = identity_preserved_geometry_changed
~~~

The ElectricalDesignRevision is not mutated.

This differs from a generated rebuild:

~~~text
manual move
→ same ModuleInstance ID
→ existing string reference remains the same object reference

generated rebuild to a different placement
→ old ModuleInstance identity invalidated
→ stale string membership reported by PVFieldLayoutImpactReport
~~~

Electrical validity may still change because orientation or other physical conditions changed. Phase 4.7 validation remains responsible for such engineering findings.

## 6. Identity Resurrection Guard

A subtle collision exists when placement-derived generated IDs and manual identity preservation interact.

Example:

~~~text
generated module at location A
ID = hash(A)

engineer manually moves same object to B
ID remains hash(A)

later explicit rebuild places a generated module at A
provisional generated ID = hash(A)
~~~

Without an additional guard, the rebuild would reuse the manually moved object's ID even though the pre-rebuild physical placement was B.

Phase 4.7H-B therefore adds deterministic replacement identity disambiguation:

~~~text
if generated provisional ID
collides with an old non-equivalent ModuleInstance ID
→ create deterministic replacement ID
→ old identity remains invalidated
~~~

Replacement identity is versioned independently:

~~~text
opensimpv-module-replacement-identity-0.1
~~~

This preserves both rules:

~~~text
manual move preserves object identity

generated replacement never silently resurrects
a non-equivalent pre-rebuild identity
~~~

## 7. Vertex Editing

SceneEditorSession.move_vertex() provides explicit single-vertex editing for:

~~~text
surface polygons
obstacle polygons
reference lines
~~~

The operation supports deterministic snapping and snap override.

The edited entity itself is excluded from snap candidates so a vertex does not silently snap back to its own geometry.

Before mutation:

~~~text
closed polygons
→ polygon validity checked

reference lines
→ zero-length segments rejected
~~~

Invalid edits fail closed:

~~~text
Scene unchanged
undo history unchanged
~~~

Accepted edits:

~~~text
geometry_source = user_override
edge provenance refreshed
last_vertex_edit metadata recorded
~~~

Parameterized obstacle dimensions are marked no longer authoritative after direct vertex manipulation.

## 8. Snapping Exclusion

SnapEngine now accepts:

~~~text
exclude_entity_ids
~~~

Excluded scene entities are removed from vertex/edge/midpoint/intersection candidate generation.

Excluded supplemental edge sources are also ignored.

This is used by manual editing to avoid self-snapping artifacts while retaining the existing visible deterministic snap-selection rules.

## 9. Conflict Behavior

Manual module editing does not silently constrain the engineer back to a generated-valid position.

After each manual module move/rotation:

~~~text
validate_field_layout()
~~~

is run.

Possible visible conflicts include:

~~~text
module outside support/setback
module-exclusion overlap
module-obstacle overlap
module-obstacle setback
module-module overlap
~~~

The canonical draft may remain in conflict.

This is intentional.

The engineer can undo, move again, or explicitly rebuild.

## 10. Save / Reload

Manual state is canonical Scene data, not workspace-only state.

The following must survive canonical JSON serialization and reload:

~~~text
ModuleInstance ID
manual XY
manual azimuth
manual_position_override
manual edit provenance
PVField manual layout status
edited polygon vertices
geometry provenance
~~~

A committed new Scene revision preserves these values and produces the same canonical hash after reload.

## 11. New Report

Manual module operations return:

~~~text
ManualModuleEditReport
~~~

with:

~~~text
module identity
edit kind
before transform
after transform
identity_preserved = true
manual_position_override = true
field layout status
field conflict report
affected string memberships
electrical_design_mutated = false
snap feedback
~~~

Schema:

~~~text
schemas/manual-module-edit-report.schema.json
~~~

## 12. Command Surface

Scene editor command additions:

~~~text
move_vertex
~~~

PV field command additions:

~~~text
move_module
rotate_module
~~~

These remain command/session envelopes.

Accepted results become canonical Scene state.

## 13. Downstream Orientation Rule

For module plan azimuth, the canonical effective value is now:

~~~text
ModuleInstance.transform.rotation_z_deg
~~~

Generated layouts initialize that value from:

~~~text
PVField.azimuth_deg
~~~

Manual rotation may then override the individual module value.

GeneratedScene3D and Phase-4.7 MPPT orientation validation both consume the module-level value.

Tilt remains field-level in v0.1.

Per-module tilt editing is not introduced in 4.7H-B.

## 14. Explicit Exclusions

Phase 4.7H-B does not resolve:

~~~text
canonical module Z semantics
support-plane UV versus horizontal XY packing semantics
2D footprint versus tilted 3D projection equivalence
per-module manual tilt
automatic row/table reindexing after manual movement
automatic electrical rewiring
automatic MPPT reassignment
~~~

Those remain outside this hardening pass.

The geometry/Z issues belong to Phase 4.7H-C.

## 15. Exit Criterion

Phase 4.7H-B is complete when:

1. a generated module can be explicitly moved while keeping its ModuleInstance identity;
2. existing StringCircuit membership continues to reference that same object;
3. manual movement/rotation produces visible geometry conflicts rather than silent correction;
4. manual module azimuth is visible in 3D and electrical orientation validation;
5. a later generated rebuild cannot reuse the moved object's identity for a non-equivalent placement;
6. a surface/obstacle/reference vertex can be explicitly moved with snapping and validation;
7. manual edits are atomic and undoable;
8. manual edits survive Scene commit, canonical serialization and reload without changing identity or coordinates.
