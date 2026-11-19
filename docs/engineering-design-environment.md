# RawiBumi — Engineering Design Environment Specification v0.1


**Status:** Phase 4.0 canonical-contract specification  
**Date:** 2026-09-23  
**Scope:** Engineering Design Environment contracts only; no frontend interaction implementation


## 1. Purpose


Phase 4.0 freezes the boundary between editor/workspace state and canonical engineering state before Phase 4.1 map/coordinate implementation or Phase 4.2 editing UI work.


The governing product rules are:


- the engineer is authoritative;
- automation is explicit;
- suggestions do not silently mutate engineering state;
- canonical geometry is dimensionally exact;
- UI state is not simulation state;
- scene and electrical state are revisioned independently;
- simulation consumes canonical revisions only;
- save/reload must preserve engineering intent exactly.


## 2. Scope


Phase 4.0 defines four logical artifacts:


1. **SceneRevision** — immutable scene/geometry engineering state.
2. **ElectricalTopologyRevision** — immutable module/string/MPPT/inverter topology state.
3. **DesignValidationReport** — derived validation output for one pinned design state.
4. **DesignWorkspaceState** — editor-only presentation and interaction state.


It also freezes:


- actual-versus-suggested value semantics;
- revision behavior;
- the design-to-simulation interface;
- the separation between canonical, derived, and UI-only state.


Phase 4.0 does **not** implement maps, geographic transforms, the 2D editor, PV packing, 3D rendering, electrical-editing UI, or the Phase-5 near-shading solver.


## 3. Compatibility mapping


The repository already contains validated Phase-3 canonical serializations. Phase 4.0 does not create parallel replacements for them.


| Logical Phase-4 artifact | v0.1 serialized canonical object | Revision identity |
|---|---|---|
| SceneRevision | `Scene` | `Scene.revision_id` |
| ElectricalTopologyRevision | `ElectricalDesignRevision` | `ElectricalDesignRevision.electrical_revision_id` |
| DesignValidationReport | `DesignValidationReport` | `design_validation_report_id` |
| DesignWorkspaceState | `DesignWorkspaceState` | `workspace_state_id` |


Therefore, “SceneRevision” and “ElectricalTopologyRevision” are architectural roles. The existing `schema_name` values remain stable in v0.1 to avoid breaking the already validated Phase-3 execution path.


A future schema-version migration may rename serialized objects, but that must be an explicit migration rather than an incidental Phase-4 refactor.


## 4. State partitions


### 4.1 Canonical engineering state


Canonical state is sufficient to reproduce engineering meaning without an editor session.


It includes, as applicable:


- project and site identity;
- scene revision;
- surfaces, obstacles, PV fields, and module instances;
- pinned component revisions;
- electrical topology revision;
- weather revision;
- simulation configuration;
- explicit engineering assumptions and overrides.


Canonical state may be used by physics and validation.


### 4.2 Derived advisory/validation state


Derived state includes:


- design suggestions;
- validation findings;
- design validation reports;
- packing previews;
- future design heuristics.


Derived state may describe or recommend changes but is not authoritative engineering state.


### 4.3 UI-only workspace state


Workspace state includes:


- current editor mode;
- viewport/camera;
- selected entities;
- active tool;
- snap preferences;
- layer visibility;
- panel layout.


Workspace state must not contain authoritative geometry, dimensions, component selections, string assignments, or simulation parameters.


Physics must never require `DesignWorkspaceState`.


## 5. SceneRevision contract


The logical SceneRevision is serialized as the existing `Scene` object.


Required identity remains:


```text
scene_id
project_id
revision_id
coordinate_system_id
```


Revision metadata may include:


```text
revision_number
created_at
created_by
supersedes_revision_id
status
change_summary
```


The engineering payload contains:


```text
surfaces
obstacles
pv_fields
module_instances
```


Rules:


- `revision_id` is immutable once referenced by a ProjectRevision or SimulationRun.
- scene edits create a new scene revision;
- module-instance dimensions are determined by the pinned component revision, not arbitrary scaling;
- map pixels and screen coordinates are never canonical geometry;
- local engineering coordinates are the geometry authority once created;
- Phase 4.1 will freeze the detailed site/geographic/local transform contract.


## 6. ElectricalTopologyRevision contract


The logical ElectricalTopologyRevision is serialized as the existing `ElectricalDesignRevision` object.


Required identity remains:


```text
electrical_revision_id
project_id
```


Its V1 topology is:


```text
ModuleInstance
  -> StringCircuit
  -> MPPTInstance
  -> InverterInstance
  -> PCC
```


Revision metadata may include:


```text
revision_number
created_at
created_by
supersedes_revision_id
status
change_summary
```


Rules:


- topology edits create a new electrical revision;
- scene edits do not silently rewrite electrical assignments;
- automation such as Create Strings or Balance MPPT is an explicit command;
- unsupported topology is reported, not silently simplified.


## 7. Actual and suggested values


The handoff concepts are frozen, but they are intentionally **not co-located in one mutable value wrapper**.


### 7.1 Actual value


The authoritative actual value is the field stored on the canonical target object.


Examples:


```text
PVField.row_pitch_m
Surface.base_elevation_m
StringCircuit.module_instance_ids
```


### 7.2 Suggested value


A suggested value exists only in a `DesignSuggestion`.


Phase 4.0 freezes these fields:


```text
actual_value
actual_source
suggested_value
suggestion_source
override_state
```


`actual_value` in the suggestion is a snapshot used to show what the suggestion was evaluated against. It is not a second source of truth.


### 7.3 Source semantics


`actual_source` describes where the current engineering value originated, such as:


```text
component_revision
map_measurement
field_measurement
imported_geometry
user_input
derived
command_result
unknown
```


`suggestion_source` describes the advisory producer, such as:


```text
heuristic
command
optimization
validation_rule
user
unknown
```


### 7.4 Override semantics


`override_state` is one of:


```text
not_overridden
user_overridden
accepted_suggestion
```


Accepting a suggestion creates an explicit engineering change and therefore a new affected revision. It never mutates a previously pinned revision.


## 8. DesignValidationReport contract


A DesignValidationReport is derived from an exact design state.


It pins:


```text
project_revision_id
scene_revision_id
electrical_revision_id
rule_set_id
```


It contains:


- generated time;
- overall status;
- severity counts;
- `ValidationFinding[]`;
- explicit `blocking_simulation` state.


Validation does not mutate the design.


A warning or recommendation does not automatically block simulation. Blocking behavior remains governed by explicit blocking findings and supported-configuration rules.


## 9. DesignWorkspaceState contract


`DesignWorkspaceState` is owned by the web/editor layer.


Allowed examples:


- plan/3D/shading/electrical mode;
- plan viewport centre and pixels-per-metre;
- 3D camera;
- selection;
- active tool;
- snap enable/disable state;
- layer visibility;
- panel expansion.


Forbidden as authoritative workspace-only storage:


- roof vertices;
- module coordinates;
- row pitch;
- component revision selection;
- string membership;
- MPPT assignment;
- inverter limits;
- simulation model choice.


If a workspace action changes engineering state, the result is written to a canonical revision.


## 10. Revision behavior


Canonical engineering state follows revision rather than overwrite.


```text
Scene edit
  -> new Scene revision


Electrical edit
  -> new ElectricalDesignRevision


Accepted suggestion
  -> new affected revision(s)


Component upgrade
  -> new affected project/design revision after explicit user action
```


A `ProjectRevision` pins the scene and electrical revisions used by simulation.


Old `SimulationRun` objects remain immutable.


## 11. Design -> Simulation interface


The frozen interface is:


```text
canonical project/site state
  -> Scene revision
  -> PV fields + module instances
  -> ElectricalDesignRevision
  -> ProjectRevision
  -> SimulationConfiguration
  -> SimulationRun
```


For the current engine:


```text
ProjectRevision.scene_revision_id
ProjectRevision.electrical_revision_id
ProjectRevision.weather_dataset_revision_id
```


resolve the immutable inputs consumed by the simulation worker.


`SimulationRun` uses the same term `scene_revision_id`; the older `geometry_revision_id` spelling is retired by Phase 4.0.


The editor workspace is not part of this interface.


## 12. Determinism and serialization


Phase 4 design objects must be deterministic engineering records.


Required properties:


- SI engineering values remain numerical, not pixel-derived;
- identical canonical JSON produces identical engineering interpretation;
- save/reload does not alter revision identity, geometry, topology, or findings;
- suggestions and workspace state can be discarded without changing simulation inputs;
- hashes and reproducibility manifests refer to canonical revisions, not editor presentation state.


## 13. Phase-4.0 acceptance criteria


Phase 4.0 is complete when:


1. the logical SceneRevision and ElectricalTopologyRevision roles are explicitly frozen against the existing serialized schemas;
2. `DesignValidationReport` has a machine-readable schema and fixture;
3. `DesignWorkspaceState` has a machine-readable UI-only schema and fixture;
4. design suggestion semantics distinguish actual and suggested values, their sources, and override state;
5. ProjectRevision remains the design-to-simulation pinning boundary;
6. SimulationRun uses `scene_revision_id` consistently;
7. automated tests prove workspace state is absent from simulation/canonical execution inputs;
8. the complete design contracts validate as JSON without frontend code.


After this gate passes, Phase 4.1 may implement site, map, and coordinate behavior against these contracts.




## 14. Phase 4.1 implementation status


Phase 4.1 is implemented by the site/map/coordinate foundation in `geometry/coordinates/`.


Frozen behavior:


- site coordinates use WGS84 geographic latitude/longitude;
- canonical scene geometry uses local metric coordinates;
- the local frame is WGS84 ECEF-derived tangent-plane ENU with optional clockwise project rotation;
- true-north azimuth remains explicit;
- EPSG:3857 and world pixels are map context only;
- map-provider configuration is renderer-independent and retains attribution/license metadata;
- uploaded orthophotos are referenced through ImportedAsset and calibrated into local XY with affine control points;
- geographic, map-pixel, and orthophoto measurements resolve to local metres before reporting engineering dimensions.


The Phase-4.1 regression gate covers zoom independence, reversible geographic/local transforms, rotation, rooftop and ground-site scale, zone-boundary continuity, orthophoto calibration, and precision.


Phase 4.2 may now build the constrained 2D editor on this spatial foundation.




## 15. Phase 4.2 implementation status


Phase 4.2 implements the deterministic constrained 2D engineering editor kernel in geometry/scene/.


Implemented behavior includes native site/surface polygons, building footprints, exclusions, simple obstacle primitives, reference/dimension lines, selection, move/rotate/copy/array/mirror/delete, exact dimensions and angles, elevation edits, align/distribute/group/lock/hide, atomic undo/redo, deterministic snapping, and Scene revision commit.


Dimensional overrides preserve material provenance. A map-derived edge can become an explicit user override while retaining its prior value. Consequential changes to adjacent edges are recomputed and marked derived rather than leaving stale values.


Workspace-only state now includes snap feedback and editor history. It remains outside simulation inputs.


The Phase-4.2 acceptance fixture reconstructs a survey rooftop with exclusions and obstacles, commits a new Scene revision, serializes/reloads it with the same canonical hash, and intentionally leaves pv_fields and module_instances empty. Deterministic PV packing remains Phase 4.3.


The current repository does not yet contain a React/TypeScript graphical browser runtime. Phase 4.2 therefore freezes and validates engineering/editor semantics plus web-facing command/workspace contracts without claiming a completed graphical UI.




## 16. Phase 4.3 implementation status


Phase 4.3 implements the deterministic PV field/packing kernel in `geometry/pvfield/`.


Implemented behavior includes pinned module mechanical footprint resolution, portrait/landscape packing, field azimuth, row pitch, module gaps, mounting elevation, perimeter/obstacle setbacks, exclusion/walkway rules, basic table grouping, deterministic row/module identities, explicit Fill Area / Find Maximum Modules / Orient to Edge / Align Rows / Equalize Spacing / Change Orientation / Rebuild Field commands, module/row snapping integration, atomic packing undo/redo, and SHA-256 packing-input identity.


The critical manual-authority behavior is enforced: moving a surface/obstacle does not rebuild a PV field. Existing module coordinates remain unchanged and `PVFieldConflictReport` exposes stale inputs, boundary/setback violations, exclusions and obstacle overlaps. Repacking occurs only after an explicit packing command.


Phase 4.3 packs the physical module footprint in the canonical support-surface 2D plane. `tilt_deg` remains an engineering parameter; deterministic 3D height/tilt geometry is intentionally deferred to Phase 4.4.


The v0.1 `Find Maximum Modules` command compares supported deterministic-grid alternatives and is advisory. It is not represented as a proof of the global optimum for arbitrary continuous polygon packing.




## 17. Phase 4.4 implementation status


Phase 4.4 implements deterministic height resolution and renderer-neutral 3D verification in `geometry/scene3d/`.


Implemented behavior includes surface elevation planes, slope/downhill azimuth, centroid or explicit-XY height datum, obstacle/parapet vertical extrusion, reference-line elevation, module physical width/height preservation, field azimuth/tilt, mounting height, module plane axes/normals/corners, 3D bounds, deterministic generation hashes, and explicit height findings.


The 3D artifact is deliberately marked `derived_verification_only`, `editable=false`, and `mesh_editing_supported=false`. Editing remains in the canonical 2D Scene.


The original specifications did not define where `base_elevation_m` applies on a sloped polygon. Phase 4.4 freezes the compatibility default as the polygon boundary centroid; projects may instead store an explicit local-XY elevation datum.


A vertical 90-degree plane is not a canonical Surface; walls/parapets remain obstacle primitives. This makes the planar height equation finite and deterministic.


Phase 4.4 does not implement ray intersection, shadow projection, diffuse obstruction, sky-view factors, or electrical shading. Those remain Phase 5+.




## 18. Phase 4.5 implementation status


Phase 4.5 implements component-aware design integration through `components/design_integration.py`.


Exact module and inverter revisions resolve to deterministic design-facing property snapshots. Proposed revision changes produce `ComponentRevisionImpactReport` without mutating Scene or ElectricalDesign.


For modules, the hypothetical proposed footprint is evaluated against existing module centers, support boundaries, exclusions, obstacles and setbacks. The existing Phase-4.3 packer is also used to preview an explicit rebuild. Existing strings referencing the changed field are identified and marked for review when electrical/string properties or rebuild module count change.


Explicit module actions are: keep the current revision, apply the proposed revision while retaining current coordinates, or apply the revision and explicitly rebuild the field.


For inverters, DC/MPPT/AC/efficiency properties and normalized MPPT topology are compared against the current electrical design. Phase 4.5 may explicitly bind the new revision while keeping the current topology, but it never remaps MPPTs or strings automatically; that remains Phase 4.6. Detailed electrical limit validation remains Phase 4.7.


The integration pass also corrected landscape propagation into Phase-4.4 GeneratedScene3D: physical dimensions remain original component dimensions while plane width/height follow the selected portrait/landscape orientation.




## 19. Phase 4.6 implementation status


Phase 4.6 implements a canonical ElectricalDesignRevision editor in `electrical/topology/`.


Implemented manual operations include inverter creation from an exact component revision, StringCircuit creation from ordered module selections, reciprocal string↔MPPT assignment/reassignment, unassignment, deletion, inverter/MPPT/string inspection, atomic undo/redo, deterministic serialization/hash, structural consistency reporting, and electrical revision commit.


Explicit automation includes Suggest String Length, Create Strings, Assign Strings and Balance MPPT. Suggest String Length is deliberately STC/reference-condition advisory only and lists the temperature/current/DC-AC checks deferred to Phase 4.7. The existing Phase-3 balanced MPPT assignment helpers are reused.


Canonical draft strings may be disabled and unassigned (`target_mppt_instance_id=null`) so the required create-string-then-assign workflow is representable. Runtime simulation remains stricter.


The Phase-4.6 exit test passes an editor-generated topology directly into the existing canonical simulation topology resolver and verifies successful resolution without an adapter translation.




## 20. Phase 4.7 implementation status


Phase 4.7 implements deterministic read-only engineering validation in `validation/engineering/`.


The validator consumes an exact Scene revision, ElectricalDesignRevision, exact component revisions, and an explicit EngineeringValidationConfiguration. It does not derive hidden site-temperature assumptions and does not mutate topology or component selection.


Implemented checks include cold-design string Voc, minimum/maximum-temperature Vmpp against each target MPPT window, per-MPPT operating current and Isc, total inverter input current and Isc, DC/AC ratio, unequal string length, orientation mismatch, component/model capability, component-revision consistency, and minimum structural topology reciprocity.


Validated PVsyst single-diode execution is preferred for temperature-dependent module state. If unavailable and policy permits, a visible linear fallback uses beta-Voc, alpha-Isc and gamma-Pmp; because the current component schema has no independent beta-Vmpp field, the fallback explicitly estimates relative beta-Vmpp as relative gamma-Pmp minus relative alpha-Isc and emits a model-downgrade warning. If neither detailed nor fallback calculation is defensible, the design is marked INVALID rather than guessed.


The human-facing classifications are INFO / RECOMMENDATION / WARNING / INVALID. To preserve the Phase-4.0 ValidationFinding contract, INVALID serializes with the existing severity `blocking_error`; only those findings set `blocking_simulation=true`.


DC/AC ratio has no built-in universal warning threshold. It is informational unless the project supplies explicit advisory min/max values.




## 22. Phase 4.7H-B manual editing hardening


Phase 4.7H-B makes generated layouts directly engineer-editable without weakening the Phase-4.7H-A identity contract.


An explicit manual module move or plan rotation preserves the existing ModuleInstance ID and marks the module with manual_position_override=true. The parent PVField becomes layout_status=manual and layout_source=generated_then_edited. Existing StringCircuit membership remains an identity reference to that same module; ElectricalDesignRevision is not rewritten.


Manual module edits return a ManualModuleEditReport containing before/after transforms, identity-preservation state, affected string memberships, visible snapping feedback, and the current PVField conflict report. Conflicting manual geometry is permitted in canonical draft state so the engineer can inspect, undo, or correct it explicitly.


ModuleInstance.transform.rotation_z_deg is now the effective per-module plan azimuth consumed by GeneratedScene3D and MPPT orientation validation. Generated modules initialize it from PVField.azimuth_deg.


SceneEditorSession now supports explicit move_vertex for surfaces, obstacles and reference lines, including deterministic snapping, self-snap exclusion, pre-mutation geometry validation, atomic undo/redo and user_override provenance.


A deterministic replacement-ID guard prevents a later generated rebuild from reusing a manually moved object's old placement-derived ID unless the pre-rebuild placement is actually equivalent.




## 23. Phase 4.7H-C geometry coherence hardening


Phase 4.7H-C freezes the geometric authority model used by the editor, packing engine and derived 3-D verification.


The canonical editable frame remains horizontal local engineering X/Y with Z as elevation. Surface `boundary_2d` is the horizontal plan projection; RawiBumi does not introduce a hidden support-surface UV editing frame.


A tilted module's 2-D packing footprint is the horizontal projection of its physical module plane. Physical dimensions remain component-derived and are used unchanged in 3-D. For the current one-axis tilt model, projected width equals oriented physical width and projected height equals oriented physical height × cos(tilt).


`ModuleInstance.position_z_m` is canonical module-center elevation and is maintained from the shared support-plane model plus the vertical mounting-height offset. Scene geometry edits re-synchronize this derived coordinate without changing module identity or automatically repacking the field.


GeneratedScene3D uses canonical Z and independently reports support-derived Z residuals. Legacy Phase-4.3 `support_surface_2d` footprints remain readable and are reconstructed into the new plan-projection semantics.




## 24. Phase 4.7H-D validation evidence hardening


Phase 4.7H-D separates numerical evidence grade from rule classification.


Validated PVsyst single-diode results remain the preferred design-temperature evidence and receive no added guard band. The documented linear temperature-coefficient fallback now carries explicit configurable voltage/current uncertainty fractions and is restricted to module reference irradiance.


Absolute equipment maxima use conservative upper evidence and may block. MPPT operating-window checks only block when the complete fallback evidence interval lies outside the allowed window; uncertainty overlap is a warning.


The validator also reports missing total inverter DC operating-current and short-circuit-current limits rather than silently omitting those checks.


Rule set: `rawibumi.engineering_validation.v0.2`.




## 25. Phase 4.8 Design → Simulation integration


Phase 4.8 implements the frozen Phase-4.0 design-to-simulation boundary.


The new bridge constructs ProjectRevision and SimulationConfiguration from exact canonical design revisions, resolves referenced component revisions and weather, requires a matching current DesignValidationReport, and then calls the existing canonical simulation worker.


The validation report is launch evidence, not a second source of physics state. Its ID/hash/rule-set are stored in SimulationRun/ReproducibilityManifest, while the numerical input hash remains based on the pinned canonical engineering inputs and engine version.


A blocking, stale or inconsistent DesignValidationReport prevents numerical execution. UI workspace state is absent from the bridge.


The Phase-4.8 exit regression constructs a rooftop design through Scene/PV-field/electrical editor APIs and proves identical physics input hash, logical result hash, standard time series and summary energy against the equivalent direct canonical execution.