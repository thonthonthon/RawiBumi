# RawiBumi — 2D Constrained Scene Editor Foundation v0.1


**Status:** Phase 4.2 implementation specification  
**Date:** 2026-09-24  
**Parent:** Engineering Design Environment Specification v0.1  
**Scope:** Deterministic 2D scene editing semantics and canonical persistence


## 1. Purpose


Phase 4.2 establishes the deterministic engineering-editing kernel used by the future browser plan-view surface.


The editor is a constrained PV engineering geometry editor, not general-purpose CAD.


The Phase-4.2 exit target is a rooftop or ground site reconstructed from survey dimensions, including simple exclusions and obstacles, without requiring PV module placement.


## 2. Authority boundary


The Phase-4.0 and Phase-4.1 boundaries remain unchanged:


workspace interaction -> explicit editor command -> draft canonical Scene -> committed new Scene revision.


Canonical engineering state includes local-metric geometry, surface and obstacle identities, exact dimensions/elevations, persistent visibility/lock/group state, dimensional provenance, and revision identity.


Workspace/session state includes selection, active tool, viewport, snap feedback, snap override state, and undo/redo depth. The simulation engine does not require the editor session or command history.


## 3. Native Phase-4.2 primitives


### 3.1 Site and surface primitives


Supported canonical surface roles are ground, flat roof, pitched roof, custom plane, building footprint, exclusion area, walkway, and reference area. Polygon boundaries remain local XY metres.


### 3.2 Obstacle primitives


Supported native obstacle constructors are box/rectangle, extruded polygon, cylinder, wall, parapet, pole, and simplified tree. These are simple engineering primitives; Phase 4.2 does not add generic solid modeling or mesh editing.


### 3.3 Reference geometry


reference_lines are canonical 2D engineering references for reference lines, construction lines, and dimension lines. They may carry elevation and dimension-source provenance.


### 3.4 PV object boundary


The Scene schema continues to support PV fields and module instances, but the Phase-4.2 acceptance fixture deliberately leaves both arrays empty. PV field generation, module packing, and repacking remain Phase 4.3.


Module-edge and row-edge snapping are deterministic extension points so Phase 4.3 can supply those features without changing the snap contract.


## 4. Editing command set


The editor kernel supports select, multi-select, move, rotate, copy, array, mirror, delete, undo/redo, draw polygon, draw rectangle, draw line, measure, exact dimension, exact angle, elevation, align, distribute, group/ungroup, lock/unlock, and hide/show.


The renderer-neutral SceneEditorCommand envelope is UI/session state. A command itself is not a simulation input.


## 5. Geometry rules


Native polygons fail closed when they have fewer than three unique vertices, zero area, or self-intersection. Accepted polygons retain deterministic vertex identity through subsequent edits.


2D rotation follows the engineering azimuth convention: 0 degrees is North, 90 degrees is East, clockwise positive. Translation, rotation, and mirroring operate directly on local XY metres.


Every mutating command is atomic. If a command fails, the draft Scene is restored exactly to its pre-command state. Array creation is one undoable command even when it creates several entities.


A locked entity cannot be geometrically modified or deleted. Lock does not prevent presentation operations such as hide/show.


## 6. Exact dimensions and provenance


An edge may be measured and then replaced with an exact engineering value. Supported source labels are map_measurement, imported_geometry, component_database, user_override, field_measurement, derived, and unknown.


Example: a map-derived edge of 20.37 m may be replaced by a user-entered exact value of 20.00 m. The canonical geometry becomes 20.00 m while the edge provenance records source=user_override and original_value_m=20.37.


Exact edge edits support predictable anchor policies: preserve start, preserve end, or preserve midpoint. Exact angle editing uses the local engineering azimuth convention.


## 7. Snapping


Supported snap categories are vertex, endpoint, edge, midpoint, intersection, parallel, perpendicular, module edge, row edge, and user grid.


Snap resolution is deterministic. A result explicitly contains the raw point, snapped point, applied flag, snap kind, source entity/feature, snap distance, and visible marker kind.


The snap result does not become canonical geometry until the engineer completes an editing command. A temporary override bypasses snapping without changing stored snap preferences.


## 8. Alignment and distribution


Alignment supports minimum X, maximum X, centre X, minimum Y, maximum Y, and centre Y. Distribution spaces entity centres equally along X or Y while preserving the two outer entities.


These are explicit commands and never run continuously in response to unrelated geometry changes.


## 9. Undo and redo


Undo and redo initially use complete draft-Scene snapshots. This favors deterministic behavior, complete rollback, frontend independence, and clear separation from committed revision history.


Delta-based history may be introduced later without changing the engineering contract.


## 10. Revision commit


The draft editor session does not mutate an already-pinned Scene revision. commit_revision creates a new revision_id, revision_number, supersedes_revision_id, change summary, creator/timestamp, and status. Temporary selection and undo/redo history are then cleared.


## 11. Deterministic persistence


Canonical Scene JSON uses stable key ordering and compact deterministic serialization for hashing.


The acceptance chain is survey dimensions -> editor commands -> canonical Scene revision -> serialize -> reload -> same geometry -> same canonical hash.


## 12. Browser integration boundary


The repository still has no committed React/TypeScript browser runtime. Phase 4.2 therefore implements the engineering/editor kernel and web-facing workspace/command schemas without selecting or bootstrapping a frontend framework.


A future browser layer may use MapLibre, SVG/Canvas/WebGL, or another rendering technology provided it obeys the same command and canonical-state contracts. This does not alter the product requirement that normal use is browser-based.


## 13. Phase-4.2 regression gate


The automated suite covers canonical surface/obstacle/reference primitives; exact dimensions, angles and elevation; map-derived-to-user-override provenance; move/rotate/copy/array/mirror; align/distribute/group/lock/hide/delete; selection and multi-selection; atomic undo/redo; invalid polygon fail-closed behavior; required snap categories or their Phase-4.3 extension interface; visible snap feedback; explicit snap override; Scene revision commit; schema-valid save/reload; deterministic canonical hash; and survey rooftop reconstruction with no PV modules.


## 14. Exit criterion


Phase 4.2 engineering semantics are complete when a simple rooftop or ground site can be recreated from survey dimensions, saved as a canonical Scene revision, reloaded without dimensional drift, and manipulated through the required constrained editing operations.


Phase 4.3 may then add deterministic PV field packing on top of this scene.