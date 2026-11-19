# RawiBumi — Phase 6.4 Milestone Measuring Stick


**Milestone:** Phase 6.4 — Level-1 Module-Level Electrical Shading  
**Date:** 27 September 2026  
**Purpose:** objective checklist for deciding whether Phase 6.4 is merely implemented, validated, merged, or truly closed.


## 1. Status vocabulary


Use only these states:


| State | Meaning |
|---|---|
| NOT STARTED | No executable artifact exists. |
| IMPLEMENTED | Required code/schema/docs exist in the working baseline. |
| VALIDATED | Focused tests and required broader regression checks pass on one exact revision. |
| MERGED | The exact validated revision is integrated into the authoritative repository baseline. |
| CLOSED | All exit criteria and closure evidence below are satisfied and the Phase-6 anchor records closure. |


**Current milestone state: IMPLEMENTED / focused validation in progress.**  
Do not upgrade this line to `VALIDATED`, `MERGED`, or `CLOSED` without the corresponding evidence below.


## 2. Entry conditions


| ID | Entry condition | Current state | Required evidence |
|---|---|---:|---|
| E1 | Phase-6.1 fidelity/loss/authority contract frozen | SATISFIED | Level 0–3 fidelity and loss boundary remain unchanged. |
| E2 | Exact module-model capability is evidence-based | SATISFIED | `ResolvedComponentModel`, not raw capability booleans. |
| E3 | Project electrical-shading selection is exact-revision pinned | SATISFIED | Phase-6.2 project pins and selection hash. |
| E4 | Geometry-only module shading is deterministic | SATISFIED | Phase-5 compiled geometry + beam/sky/ground kernels. |
| E5 | Phase-6.3 regional irradiance exists as an optional upstream adapter | SATISFIED | `ElectricalRegionMap` + `LocalElectricalIrradianceState`; not mandatory for Level 1. |
| E6 | Validated whole-module SDM runtime already exists | SATISFIED | `module.pvsyst_singlediode.v6`. |


## 3. Required deliverables


| ID | Deliverable | Current state | Closure requirement |
|---|---|---:|---|
| D1 | Topology-independent Level-1 path | IMPLEMENTED | One module can execute Level 1 with no topology selected. |
| D2 | Explicit module-equivalent irradiance state | IMPLEMENTED | Beam/sky/ground preserved through geometry and optics before scalar collapse. |
| D3 | Exact module receiver binding | IMPLEMENTED | Receiver ID binds to the requested module instance; mixed receiver sets reject. |
| D4 | Trusted detailed-module-model gate | IMPLEMENTED | Invalid/missing `ResolvedComponentModel` blocks Level 1. |
| D5 | Whole-module SDM electrical state | IMPLEMENTED | Isc/Voc/Imp/Vmp/Pmp produced by existing validated SDM. |
| D6 | `ModuleLevelElectricalApproximationState v0.1` schema | IMPLEMENTED | Draft 2020-12 schema valid; produced state validates. |
| D7 | `ElectricalShadingResult` Level-1 envelope | IMPLEMENTED | Resolved fidelity and exact source/model identities recorded. |
| D8 | Geometry not double-counted | IMPLEMENTED | Geometry attribution is upstream/not re-booked. |
| D9 | No false mismatch/bypass/MPPT claim | IMPLEMENTED | All three attribution channels explicitly `not_modeled`. |
| D10 | Optional complete-region adapter | IMPLEMENTED | Physical-area-weighted collapse only at complete mapped coverage. |
| D11 | Incomplete regional coverage fails closed | IMPLEMENTED | No normalization over known regions that silently ignores missing module area. |
| D12 | Scientific vs execution identity separation | IMPLEMENTED | Material Level-1 approximation in scientific identity. |
| D13 | Deterministic output hashes | IMPLEMENTED | Identical inputs reproduce state and physical-result hashes. |
| D14 | Diagnostic project API endpoint | IMPLEMENTED | Non-persisted module snapshot endpoint; no Scene/ElectricalDesign mutation. |
| D15 | Focused Phase-6.4 unit tests | IMPLEMENTED | All named tests below pass. |
| D16 | Phase-6.4 engineering document | IMPLEMENTED | `docs/phase64-level1-module-electrical-shading.md`. |
| D17 | Phase-6.4 ADR | IMPLEMENTED | ADR 0059 accepted/recorded. |
| D18 | This measuring-stick document | IMPLEMENTED | Kept current through closure. |


## 4. Mandatory acceptance tests


These are the minimum focused tests. Renaming is permitted only if the milestone
mapping is updated at the same time.


| Test | Required outcome | Current evidence |
|---|---|---|
| `test_phase64_direct_module_equivalent_preserves_channel_order_without_topology` | PASS | Pending full focused run in repository context |
| `test_phase64_level1_executes_validated_whole_module_sdm_and_matches_direct_engine` | PASS | Pending full focused run in repository context |
| `test_phase64_raw_module_boolean_or_missing_resolved_evidence_cannot_execute_level1` | PASS | Pending full focused run in repository context |
| `test_phase64_optional_phase63_adapter_is_area_weighted_and_identity_bound` | PASS | Pending full focused run in repository context |
| `test_phase64_regional_adapter_fails_closed_on_incomplete_coverage` | PASS | Pending full focused run in repository context |
| `test_phase64_result_hashes_are_deterministic_for_same_inputs` | PASS | Pending full focused run in repository context |


## 5. Physics invariants that must remain true


### M1 — Level 1 does not require topology


```text
validated whole-module SDM
+ module geometry/irradiance state
→ Level 1 executable
```


Absence of `ModuleTopologyDefinition` must not block Level 1.


### M2 — Direct-channel arithmetic


For every channel `c`:


```text
post_geometry[c] = unshaded_poa[c] × visibility[c]
post_optical[c]  = post_geometry[c] × optical_modifier[c]
```


and:


```text
equivalent_incident_poa_global = Σ post_geometry[c]
equivalent_effective_irradiance = Σ post_optical[c]
```


### M3 — Complete regional collapse only


For mapped region areas `A_i` with `ΣA_i = A_module`:


```text
module_equivalent_channel = Σ(A_i × channel_i) / A_module
```


If `ΣA_i / A_module != 1` outside the frozen numerical tolerance, execution must
fail rather than renormalize the known subset.


### M4 — Whole-module model reuse


The Level-1 module MPP must equal the existing validated
`module.pvsyst_singlediode.v6` runtime evaluated at the same:


```text
equivalent effective irradiance
incident POA basis
module temperature
module definition revision
solver
```


within the existing numerical tolerance.


### M5 — No fabricated electrical loss


At Level 1:


```text
geometric irradiance = upstream
electrical mismatch = not modeled
bypass interaction = not modeled
MPPT operating point = not modeled
```


A Level-1 result must never be presented as bypass-aware partial-shading loss.


## 6. Regression gates before VALIDATED


All must be checked on the same exact repository revision:


- [ ] Phase-6.4 focused unit tests pass.
- [ ] Phase-6.3 region/local-irradiance tests still pass.
- [ ] Phase-6.2 project pinning/schema tests still pass.
- [ ] Phase-6.1 electrical-shading contract/adversarial tests still pass.
- [ ] existing module electrical-engine tests still pass.
- [ ] existing string/MPPT tests remain unchanged unless a real defect is found.
- [ ] all modified/new JSON schemas pass Draft 2020-12 validation.
- [ ] Python compile/import validation passes.
- [ ] TypeScript API/types compile in the normal web build.
- [ ] no Phase-5 geometry regression is introduced.


## 7. Reproducibility gate


On one fixed test case, save the exact evidence:


```text
module definition revision ID
resolved-component-model resolution ID
Scene revision/hash
ElectricalDesign revision/hash
source ShadingResult physical hash
optional region-map/local-state hashes
Level-1 aggregation method
ModuleLevelElectricalApproximationState hash
ElectricalShadingResult scientific-input hash
ElectricalShadingResult physical-result hash
```


Required result:


```text
same scientific inputs
→ byte/logically equivalent scientific payload
→ same module MPP
→ same state hash
→ same physical-result hash
```


## 8. Closure decision table


| Gate | Needed for IMPLEMENTED | VALIDATED | MERGED | CLOSED |
|---|:---:|:---:|:---:|:---:|
| D1–D18 artifacts present | ✓ | ✓ | ✓ | ✓ |
| focused tests green |  | ✓ | ✓ | ✓ |
| Phase-6.1/6.2/6.3 regression green |  | ✓ | ✓ | ✓ |
| module-engine regression green |  | ✓ | ✓ | ✓ |
| web/API build green |  | ✓ | ✓ | ✓ |
| exact revision recorded |  | ✓ | ✓ | ✓ |
| exact validated revision merged |  |  | ✓ | ✓ |
| main/authoritative anchor updated |  |  |  | ✓ |
| no unresolved Phase-6.4 blocking finding |  |  |  | ✓ |


## 9. Definition of Phase-6.4 CLOSED


Phase 6.4 is CLOSED only when all statements below are true:


```text
one module can execute Level 1 without topology
trusted SDM evidence is mandatory
channel ordering is explicit and reconciles numerically
whole-module MPP matches the existing validated SDM runtime
regional collapse is optional and requires complete coverage
geometry is not double counted
electrical mismatch/bypass/MPPT remain explicitly unmodeled
same inputs reproduce exact physical identities
focused + upstream regressions + normal build pass
exact validated revision is merged
closure state is recorded on the authoritative Phase-6 anchor
```


Until then, report the tranche as `IMPLEMENTED` or `VALIDATED`, not `CLOSED`.


## 10. Phase-6.5 entry gate


Phase 6.5 — Substring / Bypass Reference Kernel may start after the Phase-6.4
scientific boundary above is validated. Phase 6.5 must not modify the meaning of a
Level-1 result merely to simplify bypass implementation.