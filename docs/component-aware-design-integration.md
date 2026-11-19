# RawiBumi — Component-Aware Design Integration v0.1


**Status:** Phase 4.5 implementation specification  
**Date:** 2026-09-24  
**Parent:** Engineering Design Environment Specification v0.1


## 1. Purpose


Phase 4.5 connects exact RawiBumi component revisions to the canonical design environment.


A component selection is not merely a display label. The selected revision controls design-facing properties.


For modules:


```text
physical dimensions
STC electrical values
temperature coefficients
string-design limits
available simulation models
capability flags
```


For inverters:


```text
absolute DC limits
MPPT voltage range
MPPT current limits
MPPT Isc limits
MPPT count/topology
AC rating
array-sizing limits
efficiency model
capability flags
```


## 2. Exact Revision Binding


Canonical design objects continue to store exact revision IDs:


```text
PVField.module_definition_revision_id
ModuleInstance.module_definition_revision_id
InverterInstance.inverter_definition_revision_id
```


`ComponentBindingManifest` resolves those references against the available component library and records the design-facing snapshot for each binding.


The manifest is derived and deterministic. It does not duplicate component definitions into Scene or ElectricalDesign.


## 3. Revision Changes Are Two-Step Operations


The governing rule is:


```text
analyze consequence
        ↓
engineer chooses action
        ↓
explicit mutation
```


A proposed component change never mutates the design during analysis.


`ComponentRevisionImpactReport.mutation_performed` is always false.


## 4. Module Revision Impact


A proposed module revision is evaluated against the existing PVField and ModuleInstance coordinates.


The hypothetical check updates only a temporary copy with the proposed physical footprint.


It detects:


```text
module outside support / perimeter setback
module-exclusion overlap
module-obstacle overlap
obstacle-setback violation
module-module overlap
```


It also evaluates whether the current packing parameters can explicitly rebuild the field with the proposed module and previews the resulting module count.


Existing string membership is inspected when an ElectricalDesign is available.


Changed module electrical values or limits produce a string-design revalidation consequence.


A rebuild preview that changes module count explicitly reports that existing string membership must be reviewed.


No string is silently edited.


## 5. Module Actions


### Keep Current Revision


No mutation.


### Apply Revision — Keep Current Layout


Explicitly changes the field/module revision binding while retaining every existing module coordinate.


If packed dimensions are unchanged and there is no geometric conflict, the field can be rebound while remaining geometrically packed.


If dimensions change, the layout is marked:


```text
stale
or
conflict
```


and the old generated packing hash is no longer represented as a current generated result.


### Apply Revision + Rebuild Field


Explicitly changes the module revision and invokes the already-frozen Phase-4.3 deterministic packer.


The Scene changes.


Electrical topology does not.


If module count changes, the impact report already identifies existing strings that require review.


This preserves the Phase-4.6 boundary.


## 6. Inverter Revision Impact


A proposed inverter revision resolves its design-facing limits and a normalized MPPT list.


The analyzer compares the proposed revision with the currently bound revision and the existing ElectricalDesign.


Immediate 4.5 consequences include:


```text
current MPPT indices unavailable on proposed inverter
DC / MPPT limits changed with connected strings
AC rating changed
efficiency model / simulation capability changed
```


Actual Voc/Vmpp/current validation of strings remains Phase 4.7.


The key distinction is:


```text
4.5 exposes the new limit
4.7 evaluates the electrical design against that limit
```


## 7. Inverter Actions


Phase 4.5 supports:


```text
Keep Current Revision
Apply Revision — Keep Current Topology
```


It does not automatically rebuild MPPTs or remap strings.


That would be an electrical-topology editing operation and belongs to Phase 4.6.


If the proposed inverter has fewer MPPTs than the existing design uses, the revision can still be explicitly bound with the current topology retained, but the binding is marked conflict and the topology remains visibly unresolved until the engineer edits it.


## 8. Design-Facing Snapshots


### Module snapshot


Includes:


```text
identity / revision
mechanical width, height, thickness, mass
Pmp / Voc / Isc / Vmp / Imp
temperature coefficients
maximum system voltage
series fuse limit
operating temperature limits
available electrical models
capability flags
```


### Inverter snapshot


Includes:


```text
identity / revision
max / nominal DC voltage
max DC power/current/Isc
startup/shutdown voltage
normalized MPPT definitions
nominal/max AC power
AC voltage/frequency/current
array-sizing limits
efficiency-model type/reference metrics
capability flags
```


These snapshots are derived from the exact bound revision and do not invent missing data.


## 9. Atomicity and Undo/Redo


`ComponentDesignSession` owns a draft Scene and optional ElectricalDesign.


Explicit mutations are atomic across the session state and use snapshot undo/redo.


A failed component action restores both domains exactly.


Analysis operations create no undo entry because they do not mutate.


## 10. Landscape Module Propagation


Phase 4.5 also closes an integration defect exposed while testing revision-aware dimensions.


The Phase-4.4 3D generator now distinguishes:


```text
physical_width_m / physical_height_m
from
plane_width_m / plane_height_m
```


For landscape modules, the plane axes are swapped consistently with the Phase-4.3 packed footprint while the original physical dimensions remain identifiable.


## 11. Schemas


New contracts:


```text
components/schema/component-revision-impact.schema.json
components/schema/component-binding-manifest.schema.json
apps/web/schema/component-revision-command.schema.json
```


The command schema remains renderer-neutral.


## 12. Explicit Exclusions


Phase 4.5 does not implement:


```text
automatic component substitution
automatic string repair
automatic MPPT remapping
Voc at minimum design temperature
Vmpp temperature-window checks
MPPT current validation
DC/AC ratio policy
electrical validation findings
component recommendation/ranking
```


Those are later Phase-4.6/4.7 concerns.


## 13. Exit Criterion


Phase 4.5 is complete when canonical Scene/ElectricalDesign objects reference exact component revisions, the design-facing properties of those revisions are deterministically resolvable, and a proposed component revision change exposes its geometry/topology/model consequences before any mutation.


No component revision change may silently redesign geometry or electrical topology.