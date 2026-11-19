# Electrical topology editor

Phase 4.6 edits canonical `ElectricalDesignRevision` drafts.

Canonical V1 chain:

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

Core API:

- `new_electrical_design()`
- `ElectricalTopologyEditorSession`
- deterministic canonical JSON/hash helpers

Manual operations:

- add inverter from an exact pinned revision;
- create string from an ordered module selection;
- assign/reassign strings to a specific MPPT;
- unassign strings;
- delete strings;
- inspect inverter/MPPT/string hierarchy;
- undo/redo;
- commit a new ElectricalDesignRevision.

Explicit automation:

- Suggest String Length;
- Create Strings;
- Assign Strings;
- Balance MPPT.

Automation never runs implicitly.

An unassigned string is valid canonical draft state:

```text
target_mppt_instance_id = null
enabled = false
```

Simulation/runtime topology remains stricter. An enabled string must be reciprocally assigned to an MPPT.

Phase 4.6 checks structural topology only. Temperature-corrected voltage/current limits, DC/AC ratio and related findings remain Phase 4.7.
