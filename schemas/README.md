# Canonical schemas

Cross-domain JSON Schemas live here. Subsystem-owned schemas remain with their subsystem, for example `components/schema/` and `weather/schema/`.

These files implement the v0.1 engineering anchors. External formats such as PAN, OND, TMY3, EPW, MET, CSV, and imported geometry are adapter inputs and must not redefine canonical field names.

All top-level serialized canonical objects are versioned with `schema_name` and `schema_version`.


## Simulation resolution schemas

Phase 1 adds:

- `simulation-assumption.schema.json` — one explicit selection/fallback/limitation record;
- `resolved-component-model.schema.json` — resolved module or inverter model contract;
- `simulation-model-resolution.schema.json` — combined module/inverter resolution for a
  simulation configuration.

These objects are intended to be persisted with immutable simulation runs so model selection
does not need to be reconstructed from future library state.


## Phase 3.8E execution/result schemas

Phase 3.8E adds:

- `project-revision.schema.json` — standalone immutable project-revision execution input;
- `simulation-run.schema.json` — immutable simulation execution record;
- `result-dataset-reference.schema.json` — content-addressed Parquet result reference;
- `summary-result.schema.json` — canonical KPI/energy/loss summary;
- `reproducibility-manifest.schema.json` — pinned revisions, models, numerical options, transformations, and hashes.

The standard high-volume result remains external columnar storage. JSON metadata references
the Parquet object rather than embedding interval arrays.


## Phase 3.9 attribution schema

`pvsyst-attribution-report.schema.json` defines the machine-readable result of
one PVsyst 8.1.6 attribution case, including readiness blockers, frozen-tolerance
metric comparisons, monthly-grid comparison, earliest non-passing stage, known
difference candidates, and reference metrics deliberately excluded from current
acceptance mapping.


## Phase 4.0 design contracts

Phase 4.0 freezes the boundary between canonical engineering design state, derived design feedback, and editor-only workspace state.

- `design-validation-report.schema.json` — validation result pinned to exact project, scene, and electrical revisions;
- `design-suggestion.schema.json` — explicit actual/suggested/source/override semantics;
- `geometry/scene/scene.schema.json` — existing v0.1 `Scene` serialization, now explicitly the logical SceneRevision contract;
- `electrical/schema/electrical-design.schema.json` — existing v0.1 `ElectricalDesignRevision` serialization, now explicitly the logical ElectricalTopologyRevision contract;
- `apps/web/schema/design-workspace-state.schema.json` — editor-only state and deliberately outside the canonical simulation registry.

`SimulationRun` now uses `scene_revision_id` consistently with ProjectRevision and ReproducibilityManifest.


## Phase 4.1 site/map/coordinate schemas

Phase 4.1 formalizes the spatial reference boundary used by the future editor:

- `geometry/coordinates/local-coordinate-system.schema.json` — WGS84-anchored rotated ENU local metric frame;
- `geometry/coordinates/map-layer-configuration.schema.json` — provider-agnostic map/aerial/orthophoto/grid references and attribution metadata;
- `schemas/project.schema.json` — Project.site now pins geodetic true north and a LocalCoordinateSystem;
- `geometry/scene/scene.schema.json` — Scene.map_layer_configuration now validates against the Phase-4.1 provider/map contract.

Map zoom, viewport, selection, and layer visibility remain UI-only workspace state. Canonical scene geometry remains local metric.


## Phase 4.2 constrained scene-editor schemas

Phase 4.2 extends the Scene/editor boundary without creating a parallel geometry model:

- geometry/scene/scene.schema.json now persists building footprints, reference/construction/dimension lines, lock/visibility/group state, and edge dimensional provenance;
- apps/web/schema/scene-editor-command.schema.json defines the renderer-neutral editor command envelope;
- apps/web/schema/design-workspace-state.schema.json carries snap feedback, snap override preferences, and undo/redo depth as UI-only state.

Selection, snap markers, editor history, and commands are not simulation inputs. Accepted engineering changes are committed as a new Scene revision.


## Phase 4.3 PV field packing schemas

Phase 4.3 adds explicit packing contracts without making UI commands simulation inputs:

- `geometry/scene/scene.schema.json` explicitly describes packing parameters, stored module footprint, row layouts, exclusion resolution, packing version/hash and layout status while retaining backward-compatible older layout labels;
- `apps/web/schema/pv-field-command.schema.json` defines renderer-neutral explicit packing commands;
- `schemas/pv-field-conflict-report.schema.json` defines non-mutating stale-layout and geometry-conflict reporting.

Generated module coordinates remain canonical Scene data. Packing command envelopes and advisory search results remain interaction state.


## Phase 4.4 height/3D contracts

Phase 4.4 keeps 3D geometry derived from the canonical Scene rather than creating a parallel editable model.

- `geometry/scene/scene.schema.json` now defines the optional surface elevation-reference datum and constrains planar surfaces to slope < 90 degrees;
- `geometry/scene3d/generated-scene3d.schema.json` defines the deterministic, non-authoritative 3D verification artifact.

If a surface has no stored elevation reference, `base_elevation_m` is interpreted at the boundary centroid. A stored explicit XY datum may replace that default. Generated 3D state is not a simulation/editing authority and may be discarded/recreated from the same Scene revision.


## Phase 4.5 component-aware design contracts

Phase 4.5 resolves exact component revisions into design-facing properties and separates proposed revision analysis from explicit mutation.

New contracts:

- `components/schema/component-binding-manifest.schema.json` — deterministic exact-revision binding manifest for PV fields and inverter instances;
- `components/schema/component-revision-impact.schema.json` — non-mutating consequence report for proposed module/inverter revisions;
- `apps/web/schema/component-revision-command.schema.json` — explicit revision analyze/apply command envelope.

A component change may expose geometry, string-revalidation, MPPT-topology, AC-rating or simulation-capability consequences. It never silently repairs the design.


## Phase 4.6 electrical topology contracts

Phase 4.6 edits the existing canonical `ElectricalDesignRevision` rather than defining a separate UI electrical model.

- `electrical/schema/electrical-design.schema.json` now permits `target_mppt_instance_id=null` for disabled draft strings created before MPPT assignment;
- `apps/web/schema/electrical-topology-command.schema.json` defines explicit manual/automation topology commands;
- `apps/web/schema/electrical-topology-view.schema.json` defines the derived inverter→MPPT→string inspection tree;
- `electrical/schema/electrical-topology-consistency-report.schema.json` defines structural topology findings;
- `electrical/schema/string-length-suggestion.schema.json` defines STC/reference-condition-only string-length advice.

Simulation/runtime assignment remains stricter: enabled strings must be reciprocally assigned to an MPPT.


## Phase 4.7 engineering-validation contracts

Phase 4.7 keeps validation derived and non-mutating.

- `schemas/engineering-validation-configuration.schema.json` requires explicit minimum/maximum cell temperatures and design irradiance;
- `schemas/validation-finding.schema.json` retains the frozen canonical severity field and adds optional human-facing `classification` values `INFO / RECOMMENDATION / WARNING / INVALID`;
- `schemas/design-validation-report.schema.json` remains the canonical report envelope pinned to exact project, Scene, electrical revision and rule-set IDs.

`INVALID` maps to the existing `severity=blocking_error` for backward compatibility. Warnings and recommendations do not block simulation.
