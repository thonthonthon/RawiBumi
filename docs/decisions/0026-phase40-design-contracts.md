# ADR 0026 — Phase 4.0 Engineering Design Environment contracts

**Status:** Accepted  
**Date:** 2026-09-23

## Context

Phase 4 introduces an engineering design environment on top of the validated Phase-3 numerical core.

The Phase-4 handoff names four logical artifacts:

- SceneRevision;
- ElectricalTopologyRevision;
- DesignValidationReport;
- DesignWorkspaceState.

The repository already contains validated v0.1 serializations named `Scene` and `ElectricalDesignRevision`, and the Phase-3.8E canonical simulation worker consumes them directly.

Renaming those serialized objects during Phase 4.0 would create migration work without changing engineering meaning.

A separate inconsistency does exist: `ProjectRevision` and `ReproducibilityManifest` use `scene_revision_id`, while `SimulationRun` uses `geometry_revision_id` for the same object.

The existing `DesignSuggestion` also uses `current_value`, which is less explicit than the Phase-4 actual-versus-suggested contract.

## Decision

1. Keep `Scene` as the v0.1 serialized schema name and define it as the canonical serialization of the logical **SceneRevision** role.
2. Keep `ElectricalDesignRevision` as the v0.1 serialized schema name and define it as the canonical serialization of the logical **ElectricalTopologyRevision** role.
3. Add optional common revision metadata to both objects without changing their Phase-3 required payload.
4. Add a canonical `DesignValidationReport` schema that pins project, scene, and electrical revisions and wraps ValidationFinding records.
5. Add `DesignWorkspaceState` under the web/editor boundary. It is explicitly non-canonical and cannot be required by simulation.
6. Rename `SimulationRun.geometry_revision_id` to `SimulationRun.scene_revision_id`.
7. Replace `DesignSuggestion.current_value` with `actual_value`, and add `actual_source`, `suggestion_source`, and `override_state`.
8. Keep the authoritative actual engineering value on its target canonical object. The value recorded in DesignSuggestion is only a snapshot used for comparison.
9. Accepting a suggestion creates explicit new engineering revision(s); it does not mutate a pinned revision.

## Consequences

### Positive

- Phase-3 canonical execution remains structurally compatible with existing Scene and ElectricalDesignRevision objects.
- Phase-4 code has an explicit state boundary before frontend implementation starts.
- UI persistence cannot accidentally become a simulation dependency.
- the same scene/electrical revision identifiers are used throughout ProjectRevision, SimulationRun, and reproducibility data.
- actual and suggested values no longer have ambiguous names.

### Costs

- logical artifact names and v0.1 serialized schema names are not identical.
- a future major schema migration may choose to rename serialized Scene/ElectricalDesignRevision objects explicitly.
- code producing SimulationRun must migrate from `geometry_revision_id` to `scene_revision_id`.

## Rejected alternatives

### Rename Scene and ElectricalDesignRevision immediately

Rejected because it changes already validated Phase-3 contracts without adding engineering capability.

### Put viewport, selection, and editor flags inside Scene

Rejected because those values do not affect engineering meaning and would contaminate reproducibility hashes with presentation state.

### Store actual and suggested values as two competing canonical values

Rejected because it creates two sources of truth. The actual value remains canonical; suggestions remain advisory records.
