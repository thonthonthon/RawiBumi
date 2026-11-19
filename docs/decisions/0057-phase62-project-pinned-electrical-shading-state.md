# ADR 0057 — Phase-6.2 Project-Pinned Electrical-Shading Selection State

**Status:** Accepted  
**Date:** 27 September 2026

## Context

ADR 0056 places ModuleTopologyDefinition and ElectricalParameterizationEvidence in
the component-library integration layer and requires explicit selection. A project
that merely stores selected IDs but resolves those IDs from the current global
catalog on reopen is not reproducible: catalog revisions may be added, removed, or
changed independently of the saved project.

Phase 6.2 therefore needs a persistence boundary that keeps simulation/product
selection separate from Scene/ElectricalDesign authority while pinning every asset
needed to reproduce that selection.

## Decision

1. `ProjectWorkspaceBundle` may contain a dedicated
   `pinned_electrical_shading_assets` object with exact topology, parameterization
   evidence, and SourceRecord payloads.
2. The same bundle may contain `electrical_shading_selections`, keyed by exact
   ModuleDefinition revision ID.
3. These fields are optional in schema v0.1 so pre-6.2 saved projects remain
   readable. The service upgrades an older bundle to empty collections in memory.
4. Once a selection is stored, every selected asset becomes project-pinned:
   - ModuleDefinition revision in `pinned_components.modules`;
   - selected ModuleTopologyDefinition revision;
   - selected region/cell ElectricalParameterizationEvidence;
   - every SourceRecord referenced by those topology/evidence assets.
5. Reopen validation checks that selected IDs resolve from those project pins. A
   current catalog copy is not accepted as a substitute for a missing replay pin.
6. Selection identity is hashed from the exact module/topology/evidence IDs,
   requested/resolved fidelity, fallback policy, and state version. Hash mismatch
   is a persistence-integrity error.
7. Fail-closed remains the default fidelity policy. Explicit lower-fidelity
   fallback must be requested and recorded.
8. User/local JSON topology or parameterization evidence may be imported only as an
   explicit asset plus explicit SourceRecord payloads. The existing Phase-6.1
   semantic validators remain the authority. Import never derives topology from
   counts/layout metadata.
9. Project electrical-shading state is simulation/product selection state. It does
   not alter SceneRevision or ElectricalDesignRevision.
10. Browser controls may display and write this selection state, but cannot
    manufacture capability evidence or activate a solver that the engine does not
    implement.

## Consequences

- selected Phase-6.2 capability state is replayable without catalog drift;
- old projects remain readable without migration failures;
- topology/evidence provenance travels with saved projects;
- deletion of a project pin or tampering with selection identity fails closed;
- imported user topology has a canonical provenance path without being mistaken
  for manufacturer truth;
- Phase 6.3 can consume a selected topology revision from project state without
  redefining component/library authority.
