# OpenSIMPV — Phase 4.8 Design → Simulation Integration

**Status:** Implementation specification  
**Date:** 2026-09-24  
**Parent:** Phase 4 Engineering Design Environment  
**Predecessor:** Phase 4.7H-D Engineering Validation Evidence Hardening

## 1. Purpose

Phase 4.8 connects the complete Phase-4 engineering design environment to the existing canonical simulation worker without creating a second design model.

The workflow is:

~~~text
Project
  ↓
Scene revision
  ↓
PV layout
  ↓
ElectricalDesignRevision
  ↓
Engineering validation
  ↓
Weather revision
  ↓
ProjectRevision
  ↓
SimulationConfiguration
  ↓
SimulationRun
~~~

The numerical kernel remains the previously validated canonical Phase-3.8E execution path.

Phase 4.8 adds the design-side bridge and the validation gate.

## 2. Authority boundary

Simulation consumes only canonical, revisioned engineering inputs.

The simulation identity remains based on:

~~~text
ProjectRevision
Scene revision
ElectricalDesignRevision
component revisions referenced by the design
WeatherDataset revision
SimulationConfiguration
engine version
~~~

DesignWorkspaceState is not accepted by the bridge or worker.

Viewport, selection, zoom, active tools, layer visibility and other editor state therefore cannot affect simulation identity.

## 3. ProjectRevision construction

Phase 4.8 adds:

~~~text
build_project_revision_from_design()
~~~

It pins:

~~~text
scene_revision_id
electrical_revision_id
weather_dataset_revision_id
~~~

into one ProjectRevision.

It rejects inconsistent project identity and electrical objects already bound to a different project_revision_id.

It does not rewrite Scene or ElectricalDesignRevision.

## 4. SimulationConfiguration construction

Phase 4.8 adds:

~~~text
build_simulation_configuration_from_design()
~~~

The configuration explicitly records:

~~~text
project revision
weather revision
simulation timestep
model selections
loss model IDs
shading configuration
numerical options
output configuration
optional start/end time
~~~

Defaults used by numerical execution remain visible in the configuration or the reproducibility manifest.

No editor-state value is copied into SimulationConfiguration.

## 5. Component revision store

Phase 4.8 adds:

~~~text
referenced_component_revision_ids()
build_design_revision_store()
~~~

The referenced component set is derived from canonical:

~~~text
PVField.module_definition_revision_id
ModuleInstance.module_definition_revision_id
InverterInstance.inverter_definition_revision_id
~~~

Every referenced revision must exist under its exact revision ID.

Missing revisions fail before numerical execution.

Extra component records in the caller's broader library do not become physics inputs unless referenced by the design.

## 6. Design validation gate

Phase 4.8 requires a DesignValidationReport before the high-level design execution path enters the numerical worker.

The report must match exactly:

~~~text
project_revision_id
scene_revision_id
electrical_revision_id
~~~

and must use the current engineering rule set:

~~~text
opensimpv.engineering_validation.v0.2
~~~

A stale report cannot validate a new design revision.

## 7. Blocking behavior

If the matching DesignValidationReport contains a blocking finding:

~~~text
blocking_simulation = true
→ SimulationRun(status=failed)
→ no numerical backend execution
→ no time-series result
~~~

The run package still preserves the blocking evidence.

The bridge also fails closed if:

~~~text
validation report schema is invalid
validation report revision identity is stale
validation report rule set is stale
status/blocking flag disagrees with blocking findings
SimulationConfiguration pins another ProjectRevision
~~~

## 8. Non-blocking findings

INFO, RECOMMENDATION and WARNING findings from the exact DesignValidationReport are carried into the SimulationRun evidence set.

They do not by themselves prevent physics.

They may cause the completed run to be marked completed_with_warnings.

## 9. Validation report is derived evidence, not physics state

DesignValidationReport is derived from the canonical design.

Therefore its identity/hash is recorded for traceability, but it is not inserted into the numerical combined input hash.

This is deliberate.

For identical:

~~~text
ProjectRevision
Scene
ElectricalDesignRevision
components
weather
SimulationConfiguration
engine version
~~~

the physics input hash and logical numerical result remain identical whether the caller enters through:

~~~text
run_validated_design_simulation()
~~~

or the lower-level canonical:

~~~text
run_canonical_simulation()
~~~

provided the design validation report is non-blocking.

## 10. SimulationRun traceability

Phase 4.8 adds optional run fields:

~~~text
design_validation_report_id
design_validation_report_sha256
design_validation_rule_set_id
~~~

The same evidence is written into ReproducibilityManifest for completed runs.

The complete DesignValidationReport is persisted in the integrated run package as:

~~~text
design-validation-report.json
~~~

## 11. Existing canonical worker remains authoritative

Phase 4.8 does not replace the Phase-3.8E worker.

The bridge ultimately calls:

~~~text
run_canonical_simulation()
~~~

The worker still performs:

~~~text
canonical schema validation
revision resolution
component resolution
execution-scope validation
weather QC
temporal preprocessing
physics execution
result packaging
hashing
reproducibility recording
~~~

## 12. Current numerical execution scope remains explicit

The current executable numerical scope remains:

~~~text
fixed_tilt_unshaded_homogeneous_single_inverter.v0.1
~~~

Therefore a Phase-4 design may be valid engineering state but still be unsupported by the current numerical backend.

Examples include current runtime limitations such as:

~~~text
multiple enabled inverters
mixed module component revisions
mixed orientations in the current unshaded adapter
unequal string lengths
non-none geometric shading
~~~

Such designs are blocked explicitly by execution-scope findings.

They are not flattened into an invented equivalent system.

## 13. Immutability

Old SimulationRun packages remain immutable.

The integrated path uses the same run-directory immutability rule as the canonical worker.

Re-running a different design requires a new:

~~~text
Scene revision
Electrical revision when applicable
ProjectRevision
DesignValidationReport
SimulationRun ID
~~~

Historical runs continue to resolve their old revisions.

## 14. Reference equivalence gate

The Phase-4.8 executable reference case is constructed through Phase-4 APIs:

~~~text
SceneEditorSession
        ↓
PVFieldPackingSession
        ↓
ElectricalTopologyEditorSession
        ↓
validate_engineering_design()
        ↓
build_project_revision_from_design()
        ↓
build_simulation_configuration_from_design()
        ↓
run_validated_design_simulation()
~~~

The reference uses:

~~~text
flat rooftop
18 modules
one string
one MPPT assignment
one inverter
explicit weather revision
unshaded current numerical scope
~~~

The integrated result is compared with an equivalent direct canonical execution.

Required equality:

~~~text
combined physics input hash
logical result hash
standard time-series values
summary energy
~~~

Run-level validation metadata may differ because the integrated path carries the design validation evidence.

## 15. UI independence regression

Changing a hypothetical editor workspace:

~~~text
selection
zoom
active tool
~~~

does not change the generated SimulationConfiguration or its canonical hash.

The bridge has no DesignWorkspaceState parameter.

## 16. New APIs

~~~text
DesignSimulationPreparation

build_project_revision_from_design()
build_simulation_configuration_from_design()
referenced_component_revision_ids()
build_design_revision_store()
design_validation_gate()
prepare_design_simulation()
run_validated_design_simulation()
~~~

Location:

~~~text
engine/simulation/design.py
~~~

## 17. New regression coverage

Phase 4.8 covers:

~~~text
Phase-4-authored design executes end-to-end
integrated design result equals direct canonical result
physics input hash equality
logical result hash equality
time-series equality
summary energy equality
validation report identity/hash persistence
blocking design validation stops before physics
stale validation report cannot gate new Scene revision
UI workspace state is absent from simulation identity
~~~

## 18. Explicit exclusions

Phase 4.8 does not add:

~~~text
near-shading physics
multi-inverter numerical execution
mixed-orientation numerical execution
new module or inverter physics
automatic model substitution
background design redesign
distributed job infrastructure
database/object-store job persistence
Phase-5 shading integration
~~~

Those remain separate development concerns.

## 19. Exit criterion

Phase 4.8 is complete when:

1. a project built through Phase-4 design APIs can pin exact Scene, Electrical, Weather and component revisions;
2. an exact non-blocking DesignValidationReport is required by the high-level design launch path;
3. blocking or stale design validation prevents numerical execution;
4. DesignWorkspaceState is not an execution input;
5. validation-report identity is traceable without changing the physics input hash;
6. the Phase-4-authored reference design produces the same physics input hash and numerical result as the equivalent direct canonical fixture;
7. the complete repository validation suite passes.

After this gate, Phase 4.9 may focus on reference-project breadth, save/reload and UX/reproducibility hardening.
