# RawiBumi — Electrical Topology Editor v0.1


**Status:** Phase 4.6 implementation specification  
**Date:** 2026-09-24  
**Parent:** Engineering Design Environment Specification v0.1


## 1. Purpose


Phase 4.6 makes the existing canonical electrical topology editable through the design environment.


V1 chain:


```text
ModuleInstance
    ↓
StringCircuit
    ↓
MPPTInstance
    ↓
InverterInstance
    ↓
PCC
```


Full MV design is outside V1.


## 2. Canonical Authority


The editor operates directly on an `ElectricalDesignRevision` draft.


It does not maintain a second browser-only electrical model.


The accepted draft is serialized using the same canonical entities already consumed by the simulation runtime:


```text
inverter_instances
mppt_instances
strings
connections
pcc_definition
```


Electrical edits are revisioned independently from Scene edits.


## 3. Draft State


The original schema required every StringCircuit to already have an MPPT target.


That conflicts with the required interaction:


```text
select modules
→ Create String
→ later assign MPPT
```


Phase 4.6 therefore permits:


```text
target_mppt_instance_id = null
enabled = false
```


for canonical draft strings.


This does not relax simulation behavior. The existing runtime still requires enabled strings to have reciprocal MPPT assignment.


## 4. Add Inverter


Adding an inverter requires an exact `InverterDefinition.revision_id`.


The editor resolves that revision through the Phase-4.5 component contract and creates:


- one `InverterInstance`;
- the exact number of `MPPTInstance` objects represented by the pinned inverter revision;
- a deterministic MPPT definition reference per index;
- an optional inverter→PCC connection.


Example deterministic MPPT IDs:


```text
inv-1-mppt-01
inv-1-mppt-02
...
```


The component definition remains immutable.


## 5. Manual String Creation


The primary operation is:


```text
select ordered modules
→ Create String
```


The supplied module order is preserved as the series order in `module_instance_ids`.


Rules:


- every module must exist in the canonical Scene;
- every selected module must be enabled;
- module IDs in one string are unique;
- a module cannot belong to two strings;
- the new string starts unassigned and disabled.


The editor does not infer a different series order.


## 6. Manual MPPT Assignment


Primary operation:


```text
select strings
→ Assign MPPT
```


Assignment updates both canonical directions atomically:


```text
StringCircuit.target_mppt_instance_id
MPPTInstance.connected_string_ids
```


Reassignment removes the string from its previous MPPT before adding it to the new MPPT.


If a verified physical input count exists in the pinned inverter revision, the editor prevents assignment beyond that connector count.


This is a structural topology constraint, not the Phase-4.7 electrical-current check.


## 7. Topology Inspection


The derived topology view exposes:


```text
Inverter 1


  MPPT 1
    String 1
    String 2


  MPPT 2
    String 3
    String 4
```


Each string summary includes module count and enabled state.


Unassigned draft strings are shown separately.


The topology view is derived and renderer-neutral.


## 8. Explicit Automation


Automation is command-based and never reactive.


### 8.1 Suggest String Length


This is advisory and non-mutating.


Phase 4.6 uses reference/STC values only:


- module Voc;
- module Vmp;
- inverter absolute max DC voltage;
- MPPT operating-voltage range;
- module max-system voltage where available;
- inverter nominal DC voltage where available.


It returns:


```text
minimum modules/string at STC
maximum modules/string at STC
recommended reference-condition count
```


The recommendation is not an electrical-validity result.


The response explicitly defers:


```text
Voc @ minimum design temperature
Vmpp @ low temperature
Vmpp @ high temperature
MPPT current
Isc
DC/AC ratio
```


to Phase 4.7.


### 8.2 Create Strings


Explicit deterministic command.


Inputs include:


- selected module IDs;
- string length;
- ordering strategy;
- ID prefix;
- remainder policy.


Supported initial ordering:


```text
selection
row_major
```


`selection` preserves user order.


`row_major` sorts by field, row, column and module ID.


Default remainder behavior fails closed rather than silently creating an unequal final string.


### 8.3 Assign Strings


Explicit deterministic balanced assignment.


The implementation reuses the Phase-3 `balanced_string_assignment()` and `validate_mppt_assignment()` helpers.


The command will not move unselected strings already occupying the target inverter. The engineer must explicitly invoke Balance MPPT for redistribution.


### 8.4 Balance MPPT


Explicitly redistributes all currently assigned strings on one inverter across its MPPTs.


No balancing occurs after unrelated edits or component changes.


## 9. Structural Consistency Report


`ElectricalTopologyConsistencyReport` checks topology integrity, including:


- unknown module referenced by string;
- enabled string without MPPT;
- unknown MPPT target;
- non-reciprocal string↔MPPT relationship;
- one module used by multiple strings;
- MPPT referencing unknown string;
- MPPT referencing unknown inverter;
- MPPT not listed by its inverter;
- inverter MPPT list differing from canonical MPPT instances.


Unassigned disabled strings are reported as `draft`, not structural errors.


This report is intentionally not the Phase-4.7 engineering-validation report.


## 10. PCC


The Phase-4.6 factory requires a PCC identifier.


When configured, adding an inverter creates a direct inverter→PCC canonical connection.


V1 does not attempt MV collection-system authoring.


## 11. Revisioning


The editor uses atomic full-revision snapshots for undo/redo.


`commit_revision()` creates a new electrical revision identity:


```text
new electrical_revision_id
revision_number
supersedes_revision_id
change_summary
created_at
created_by
status
```


A commit is blocked when structural consistency contains an error.


Disabled unassigned draft strings may remain present because they are not active runtime topology.


## 12. Simulation Compatibility


The Phase-4.6 regression suite passes an editor-generated topology directly into the existing Phase-3 canonical simulation topology resolver.


The generated topology resolves successfully without adapter translation.


This freezes the exit criterion:


```text
topology authored by the design environment
=
topology consumed by the simulation engine
```


for the supported V1 scope.


## 13. Explicit Boundaries


Phase 4.6 does not evaluate:


- Voc at minimum design temperature;
- Vmpp low/high-temperature operating window;
- MPPT operating current;
- Isc / Isc per MPPT;
- total inverter input current;
- DC/AC ratio;
- unequal string-length severity;
- orientation mismatch;
- unsupported simulation capability severity.


These remain Phase 4.7.


Phase 4.6 also does not implement full MV design or automatic component substitution.


## 14. Exit Criterion


Phase 4.6 is complete when a user can create, edit, inspect, serialize, reload and revision the canonical V1 electrical topology through the engineering environment, and an equivalent editor-generated topology is accepted by the existing simulation engine without translation.