# OpenSIMPV — Phase 5.2 Receiver & Simulation Execution Group Foundation v0.1

**Status:** Phase-5.2 implementation anchor  
**Date:** 24 September 2026  
**Scope:** Derived irradiance/electrical execution grouping between canonical topology and numerical workers  
**Production shadow solver:** Not included  
**Detailed electrical mismatch:** Not included

## 1. Objective

Phase 5.2 removes the architectural assumption that the entire project must be
flattened into one common irradiance geometry state before numerical execution.

The new boundary is:

```text
Canonical Scene
+
ElectricalDesignRevision
+
CompiledShadingGeometry
        ↓
SimulationExecutionGroupPlan
        ↓
legacy homogeneous adapter
or
future multi-group geometry-aware worker
```

The execution-group plan is derived runtime state only.

It does not modify canonical engineering state.

## 2. Why this tranche exists

Before Phase 5.2, the canonical numerical adapter gathered project-wide sets of:

```text
module revision
string length
tilt
azimuth
albedo
```

and rejected the design unless those sets collapsed to one common value.

That behavior prevented the runtime architecture from carrying spatially distinct
irradiance states even when they were electrically separable.

Phase 5.2 replaces that global flattening rule with deterministic execution-group
classification.

## 3. Authority boundary

```text
Scene
= canonical physical/design geometry

ElectricalDesignRevision
= canonical electrical topology

CompiledShadingGeometry
= derived numerical geometry

SimulationExecutionGroupPlan
= derived execution topology
```

The plan is explicitly:

```text
authority = derived_execution_only
```

It is not editable engineering state.

## 4. Grouping signature

Strings are grouped when they share the same execution-state signature:

```text
inverter instance
module definition revision
module count per string
surface tilt
surface azimuth
resolved albedo
```

MPPT identity is deliberately **not** part of the grouping signature.

Reason:

Homogeneous strings connected to multiple MPPTs still represent the same
irradiance/electrical execution state and should remain one group.

MPPT identity is retained separately so heterogeneous groups sharing the same
MPPT can be detected.

## 5. Why module count per string is part of the signature

The current numerical worker uses one scalar:

```text
modules_in_series
```

Therefore two otherwise identical strings with different series length are not
the same current execution state.

If those strings are on separate MPPTs, they may become separate execution
groups.

If those states share one MPPT, the plan marks the MPPT heterogeneous.

No project-wide identical-string-length assumption is required by the grouping
architecture itself.

## 6. Albedo resolution

Each module resolves albedo in this priority order:

```text
support Surface.albedo
→ SimulationConfiguration.numerical_options.albedo
→ documented generic default 0.20
```

The execution-group key uses the resolved numerical albedo value.

Provenance is retained separately as:

```text
albedo_sources[]
```

Therefore two physically identical 0.20 states may share one execution group
even if one comes from an explicit surface value and another from an explicit
simulation fallback.

The provenance is not discarded.

## 7. Receiver linkage

The canonical runtime now compiles the Scene through the Phase-5.1 compiler:

```text
Scene
→ CompiledShadingGeometry
```

and passes that artifact into the execution-group planner.

Each group may therefore retain:

```text
receiver_ids
missing_receiver_module_ids
compiled_geometry_hash
```

Phase 5.2 does not require every legacy unshaded module to have resolved shading
receiver geometry.

Missing receiver linkage remains explicit in the plan and becomes a stricter
requirement only when geometry-aware shading execution is activated.

## 8. String homogeneity rule

One electrical string is a series-coupled object.

Therefore Phase 5.2 does not split one string across multiple execution groups.

If modules inside one string span different:

```text
module revisions
orientations
albedos
```

the planner emits:

```text
execution_group_string_spans_irradiance_states
```

and the plan becomes invalid.

This is an electrical boundary, not a geometry limitation.

## 9. Execution classes

The plan classifies the canonical design into exactly one of:

### homogeneous_single_group

```text
all enabled strings
→ one execution group
```

This class remains compatible with the existing homogeneous numerical backend.

### separable_multi_group

```text
multiple execution groups
+
no MPPT contains more than one group
```

These groups are electrically separable at the MPPT boundary.

Phase 5.2 preserves them explicitly.

The legacy backend still cannot execute them in one run.

### electrically_coupled_heterogeneous

```text
multiple execution groups
share at least one MPPT
```

This requires higher-fidelity electrical interaction modeling.

It remains outside Phase 5.

### invalid

The canonical topology cannot be reduced to valid homogeneous execution groups.

Examples include a single string spanning multiple irradiance states or missing
required canonical references.

## 10. Same-MPPT boundary

If different execution states share one MPPT, the planner emits:

```text
execution_group_mppt_heterogeneous
```

The canonical runtime maps that condition to:

```text
SIMULATION_SCOPE_HETEROGENEOUS_MPPT_EXECUTION_GROUPS
```

This is an explicit Phase-6 electrical-physics boundary.

It is no longer reported as a generic one-orientation limitation.

## 11. Separable multi-group boundary

If multiple groups are on distinct MPPTs, the canonical design is considered
groupable.

The current legacy worker still blocks execution with:

```text
SIMULATION_SCOPE_MULTIPLE_EXECUTION_GROUPS_NOT_EXECUTABLE
```

This blocker means:

> The canonical topology is valid and spatially/electrically separable, but the
> current legacy backend still accepts only one homogeneous execution group.

This blocker is temporary implementation scope, not a physical invalidity.

## 12. Historical one-orientation blocker

Phase 5.2 removes the old project-wide runtime rejection:

```text
SIMULATION_SCOPE_REQUIRES_ONE_ORIENTATION
```

from canonical topology interpretation.

Different orientations are now represented as distinct execution groups.

The current R5 multi-orientation reference progresses from:

```text
global one-orientation rejection
```

to:

```text
valid separable multi-group topology
→ legacy backend multi-group blocker
```

## 13. Historical one-albedo and one-module-revision flattening

The same architectural change applies to:

```text
multiple albedos
multiple module revisions
different string lengths
```

These differences are represented through execution groups rather than rejected
globally before topology classification.

If they share one MPPT, the plan marks electrical heterogeneity.

If they are separable by MPPT, they remain valid multiple groups awaiting a
multi-group numerical worker.

## 14. Determinism

The planner is deterministic.

Execution groups contain stable sorted collections:

```text
string_ids
module_instance_ids
receiver_ids
missing_receiver_module_ids
pv_field_ids
support_surface_ids
mppt_instance_ids
mppt_indices
albedo_sources
```

Each group receives:

```text
execution_group_payload_sha256
execution_group_id
```

The complete plan receives:

```text
execution_plan_payload_sha256
execution_plan_id
```

Equivalent collection reordering does not change the plan.

## 15. Machine-readable artifact

Schema:

```text
schemas/simulation-execution-group-plan.schema.json
```

Builder:

```text
engine/simulation/execution_groups.py
```

Public API:

```python
build_simulation_execution_plan(...)
```

## 16. Canonical runtime integration

`engine/simulation/canonical.py` now:

1. resolves canonical inverter/string/MPPT consistency;
2. compiles the Scene into `CompiledShadingGeometry`;
3. builds `SimulationExecutionGroupPlan`;
4. classifies the topology;
5. only adapts to the legacy homogeneous worker when exactly one valid group is
   present.

The old direct project-wide orientation/albedo/module-revision flattening logic
is removed from the canonical topology boundary.

## 17. Legacy homogeneous adaptation

For:

```text
execution_class = homogeneous_single_group
group_count = 1
```

the single execution group is converted back into the existing scalar runtime
configuration:

```text
module revision
tilt
azimuth
albedo
modules in series
string IDs
MPPT assignments
```

Therefore the existing numerical kernel is not rewritten in Phase 5.2.

This preserves R1-R3 numerical behavior.

## 18. Run provenance

Completed runs now record:

```text
execution_group_plan_id
execution_group_plan_payload_sha256
execution_group_class
execution_group_count
```

inside the model manifest and therefore the reproducibility manifest.

Multi-group failed runs include execution-plan identity and group details in the
blocking finding context.

The grouping layer is therefore not hidden runtime behavior.

## 19. Albedo fallback assumptions

If any member of the active homogeneous group uses:

```text
documented_generic_default_0.20
```

the existing albedo fallback assumption remains recorded.

A group may preserve multiple equal-value albedo provenance sources without
losing that assumption evidence.

## 20. Validation evidence

Phase-5.2 tests prove:

1. homogeneous strings on multiple MPPTs remain one execution group;
2. different orientations on separate MPPTs become separable groups;
3. different orientations on the same MPPT become electrically coupled
   heterogeneous groups;
4. one string spanning different orientations is invalid rather than split;
5. different albedos form separate execution groups;
6. receiver IDs and compiled geometry hash can be retained from Phase 5.1;
7. collection reordering does not change the plan;
8. equal resolved albedo with different provenance can remain one group;
9. the plan validates against its JSON Schema;
10. R1-R3 existing supported reference runs remain under full repository
    regression;
11. R5 current runtime blocker changes from the historical global orientation
    blocker to the explicit multi-group backend boundary.

## 21. Deliberate deferrals

Phase 5.2 does **not** implement:

```text
multi-group numerical execution
beam shadow projection
module shading factors
diffuse sky obstruction
ground obstruction
same-MPPT heterogeneous IV interaction
bypass-diode behavior
string IV reconstruction
MPPT operating-point interaction
multiple inverter execution
```

## 22. Exit gate

Phase 5.2 is complete when:

```text
canonical topology
→ deterministic execution groups
→ explicit electrical separability classification
```

and:

```text
R1-R3
→ one execution group
→ existing numerical behavior preserved

R5
→ two orientation groups
→ separability preserved
→ no global orientation flattening
```

After closure:

```text
──────── PHASE 5.2 EXECUTION GROUP FOUNDATION STABLE ────────
```

The next tranche may implement the first correct direct-beam shadow kernel
against the stable compiled geometry and receiver identities without redesigning
topology grouping.
