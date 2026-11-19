# RawiBumi — Phase 6.2 Canonical Module Topology & Capability Resolution


**Status:** IN PROGRESS — project pinning, API selection, local asset import, and browser capability surface implemented  
**Date:** 27 September 2026  
**Parent:** Phase 6.1 Electrical Shading Contract & Canonical Boundary  
**Scope:** production integration of frozen Phase-6.1 topology/capability contracts; no mismatch solver


## 1. Objective


Phase 6.2 turns the Phase-6.1 contract objects into component-library and product
integration primitives without moving any physics authority into the UI/API.


The integration remains:


```text
ModuleDefinition revision
+ optional explicitly selected ModuleTopologyDefinition revision
+ ResolvedComponentModel
+ optional validated ElectricalParameterizationEvidence(region_substring)
+ optional validated ElectricalParameterizationEvidence(cell)
        ↓
Phase-6.1 upstream validation boundaries
        ↓
pure electrical-shading capability resolver
        ↓
product-facing available/maximum fidelity + findings
```


## 2. Frozen rules carried from Phase 6.1


- topology is separately revisioned and bound to one exact ModuleDefinition revision;
- no topology is inferred from cell count, bypass count, half-cell flags, or layout codes;
- a missing topology lowers capability but does not invalidate the module;
- topology presence does not establish region/cell electrical parameterization;
- whole-module SDM parameters are not silently divided into substring/cell parameters;
- raw ModuleDefinition capability booleans do not authorize detailed electrical shading;
- bypass assumptions remain explicit and visible;
- capability resolution remains fail-closed and deterministic;
- product/project state selects and pins validated assets but is not a new physics authority.


## 3. Component-library integration


### 3.1 `components/topology_library.py`


The production integration layer provides:


- immutable topology asset hashing/indexing;
- SourceRecord indexing and actual source-ID resolution for topology/parameterization assets;
- exact module-revision lookup;
- explicit topology selection;
- duplicate revision conflict detection;
- parameterization-evidence indexing;
- normal `ResolvedComponentModel` integration;
- Phase-6.1 topology/bypass/parameterization validation orchestration;
- product-facing fidelity/capability result assembly.


The integration layer calls the established Phase-6.1 validators and pure resolver.
It does not duplicate them.


### 3.2 Explicit synthetic reference topology


`components/reference/module-topology-uat-550.json` is an explicit RawiBumi-owned
reference topology bound to:


```text
mod-rawibumi-uat-550-r1
```


It is not generated from PAN counts or a layout token. Its source resolves to
`components/reference/source-topology-uat-550.json`, a canonical SourceRecord that
identifies the fixture as maintainer-authored synthetic data rather than
manufacturer truth.


Its bypass devices use an explicit synthetic simulation assumption for constant
forward drop. The assumption remains surfaced as an assumption rather than
presented as manufacturer component truth.


## 4. Project persistence and replay boundary


Phase 6.2 adds two optional fields to the canonical `ProjectWorkspaceBundle`:


```text
pinned_electrical_shading_assets
  module_topologies{}
  electrical_parameterization_evidence{}
  sources{}


electrical_shading_selections{}
```


They are optional at schema level so pre-6.2 project bundles remain loadable. The
API service upgrades old bundles in memory to empty Phase-6.2 collections.


Once a selection exists, the persistence boundary is stricter:


```text
selection module revision must be project-pinned
selected topology revision must be project-pinned
selected parameterization evidence must be project-pinned
all topology/evidence source IDs must resolve to project-pinned SourceRecords
selection identity hash must match the stored selection fields
```


A reopened selected study therefore does not depend on whichever topology or
evidence happens to exist in the current global catalog.


Selection state is product/simulation state only. It does not mutate SceneRevision
or ElectricalDesignRevision.


## 5. API integration


The project API exposes:


```text
GET  /api/projects/{project_id}/electrical-shading/capability
POST /api/projects/{project_id}/electrical-shading/selection
POST /api/projects/{project_id}/electrical-shading/assets/import
```


Capability is derived without mutating design authority. Selection is explicit and
records requested/resolved fidelity, fallback policy, fallback result, topology and
evidence identities, assumption IDs, findings, and a deterministic selection hash.


The import endpoint accepts explicit local/user JSON assets plus SourceRecords. It
validates the asset through the existing Phase-6.1 contract, resolves every source
ID, rejects conflicting same-ID payloads, and pins accepted assets to the project.
It never infers topology from module metadata.


## 6. Product/browser integration


The browser type model now carries:


- module electrical-shading capability summary;
- explicit topology summaries;
- pinned electrical-shading assets;
- persisted per-module-revision electrical-shading selections.


The Electrical panel exposes the minimum Phase-6.2 selection surface:


```text
module revision
+ explicit topology revision (or none)
+ requested fidelity
+ fail-closed / explicit-lower-fidelity policy
→ persisted requested/resolved selection state
```


This is capability/selection UI only. It does not activate electrical mismatch
physics. The Simulation panel continues to identify the executable numerical path
as the existing Phase-5 geometry-aware worker.


## 7. Capability behavior


Topology alone does not unlock Level 2.


```text
validated detailed SDM
+ selected trusted topology
+ bypass readiness
+ validated region/sub-string parameterization evidence
= Level 2 eligible
```


Level 3 additionally requires cell/half-cell topology resolution plus separately
validated cell-level parameterization evidence. Grouped-cell topology remains
capped below Level 3 even if unrelated cell evidence is supplied.


No automatic topology choice or silent fidelity downgrade is permitted.


## 8. Acceptance coverage


Phase-6.2 focused tests cover or shall cover:


1. exact topology revision indexing and duplicate-conflict rejection;
2. no automatic topology selection or metadata inference;
3. stale module/topology binding rejection;
4. topology without region parameterization remains below Level 2;
5. parameterization evidence cannot fabricate detailed-SDM readiness;
6. Level 2/3 gates consume the frozen Phase-6.1 evidence boundaries;
7. explicit bypass assumptions remain surfaced;
8. dangling topology/parameterization source IDs fail closed;
9. reference catalog exposes topology without auto-upgrading module fidelity;
10. project selection pins topology/evidence/source assets separately from ordinary component pins;
11. save/reopen preserves exact selection identity;
12. stored selection hash tampering is rejected;
13. a stored selected asset missing from project pins is rejected even if the global catalog still contains it;
14. pre-6.2 project bundles remain schema-compatible and are upgraded to empty Phase-6.2 state;
15. local/user JSON import requires explicit SourceRecords and contract-valid assets;
16. browser/API selection remains a product-state operation and does not mutate canonical Scene/ElectricalDesign authority.


## 9. Remaining Phase 6.2 work


The remaining work before Phase-6.2 closure is validation and reference-depth
hardening rather than another architectural layer:


- execute the complete focused Phase-6.2 suite against the Drive working repository;
- run Phase-6.1 regression/compatibility tests against the same Drive baseline;
- perform the browser TypeScript/Vite build from the real Drive package tree;
- add at least one explicit validated region/sub-string parameterization reference asset if a scientifically defensible source/derivation fixture is available; otherwise keep the reference catalog capped below Level 2 rather than fabricate one;
- freeze the Phase-6.2 closure handover and Phase-6.3 input contract.


## 10. Non-goals


Phase 6.2 still does not implement:


- ElectricalRegionMap derivation;
- local irradiance mapping;
- substring/cell parameter derivation algorithms;
- bypass-state solution;
- nonuniform module IV;
- string IV aggregation;
- MPPT operating-point physics.


Those remain later Phase-6 tranches.




## 8. Phase 6.3 handoff


Phase 6.3 consumes only explicit project-pinned topology selections. Its derived
`ElectricalRegionMap` is not a library asset and not editable design authority; it is
recomputed from the current canonical Scene/compiled geometry plus the saved topology
revision. The handoff does not authorize topology inference or electrical mismatch
physics.