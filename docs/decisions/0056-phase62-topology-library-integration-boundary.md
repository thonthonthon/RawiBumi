# ADR 0056 — Phase-6.2 Topology Library Integration Boundary

**Status:** Accepted  
**Date:** 27 September 2026

## Context

Phase 6.1 freezes ModuleTopologyDefinition, parameterization evidence, detailed-SDM
evidence, bypass-model evidence, and the pure capability resolver. Phase 6.2 must
make those contracts usable by the component library and product without creating
a second validation authority or silently deriving topology from incomplete module
metadata.

## Decision

1. Module topology remains a separately revisioned library asset keyed by
   `ModuleTopologyDefinition.revision_id` and bound to one exact
   `module_definition_revision_id`.
2. A ModuleDefinition may exist and remain usable without topology.
3. Product/library code may list topology revisions for a module but shall not
   silently choose among multiple revisions.
4. Topology is never inferred from cell count, bypass count, half-cell flags,
   source layout codes, or whole-module electrical parameters.
5. Region/sub-string and cell parameterization are separate evidence-bearing assets.
6. Topology and parameterization `source_ids` must resolve to actual canonical
   `SourceRecord` objects at the library-integration boundary; a nonempty dangling ID
   array is insufficient provenance.
7. The integration layer consumes `ResolvedComponentModel` as the detailed-SDM
   authority and calls the frozen Phase-6.1 validation producers before invoking
   the pure capability resolver.
8. The API/UI may present the resulting capability state, findings, assumption IDs,
   and available fidelity levels, but it is not itself a validation authority.
9. Explicit simulation assumptions are allowed only when the underlying Phase-6.1
   contract classifies them as such; they must remain visible.
10. Missing topology/evidence lowers capability and never invalidates lower-fidelity
   module use.
11. Phase 6.2 introduces no production mismatch or IV-assembly solver.

## Consequences

- component-library topology can evolve independently while projects remain pinned
  to exact revisions;
- future reference/vendor topology ingestion has an explicit place to live;
- users can understand why a module is limited to Level 0/1/2/3;
- Phase 6.3 can consume selected validated topology without reinterpreting library
  metadata.
