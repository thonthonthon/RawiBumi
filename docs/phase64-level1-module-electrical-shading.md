# RawiBumi — Phase 6.4 Level-1 Module-Level Electrical Shading


**Status:** IN PROGRESS — module-equivalent Level-1 reference path implemented  
**Date:** 27 September 2026  
**Parent:** Phase 6.3 Derived Electrical Regions & Local Irradiance  
**Scope:** one validated whole-module electrical state per module; no substring/bypass/string/MPPT interaction solver


## 1. Objective


Phase 6.4 exercises the first electrical stage of the Phase-6 chain without
pretending that detailed partial-shading physics already exists.


The Level-1 boundary is:


```text
geometry-only module shading
+ explicit unshaded beam / sky / ground POA
+ explicit optical modifiers
+ one module thermal state
+ validated whole-module electrical model
        ↓
module-equivalent effective irradiance
        ↓
one whole-module Isc / Voc / Imp / Vmp / Pmp state
        ↓
ElectricalShadingResult(level_1_module_approximation)
```


Level 1 is deliberately **not** bypass-aware and does not calculate electrical
mismatch interaction inside the module.


## 2. Frozen Level-1 semantics


1. One placed module receives one whole-module electrical operating state per
   evaluated interval.
2. The canonical Level-1 route is topology-independent. A
   `ModuleTopologyDefinition` is not required to execute Level 1.
3. Execution requires trusted exact-revision evidence for the validated
   `module.pvsyst_singlediode.v6` whole-module model.
4. A raw `detailed_sdm_ready` boolean is never sufficient authority.
5. Internal spatial nonuniformity is represented only through a documented uniform
   equivalent irradiance. It is not electrically solved.
6. Geometric irradiance reduction remains upstream and is never re-booked as
   electrical mismatch loss.
7. Substring IV, bypass state, nonuniform module-IV reconstruction, string-IV,
   parallel strings and MPPT interaction remain outside Phase 6.4.


## 3. Two equivalent-irradiance adapters


### 3.1 Canonical direct module-receiver route


`build_module_equivalent_irradiance_from_module_shading(...)` consumes one exact
module receiver from a geometry-only `ShadingResult`.


The ordering is frozen as:


```text
unshaded channel POA
× geometric visibility
= post-geometry POA


post-geometry POA
× optical modifier
= electrically presented POA


sum of electrically presented channels
= module-equivalent effective irradiance
```


Beam, sky diffuse and ground-reflected channels remain explicit through this
collapse.


The receiver ID must bind to the requested module instance as:


```text
receiver:module:<module_instance_id>
```


### 3.2 Optional Phase-6.3 regional adapter


`collapse_local_irradiance_to_module_equivalent(...)` may collapse an existing
`LocalElectricalIrradianceState` to the same Level-1 whole-module abstraction.


This does **not** make topology a Level-1 prerequisite. It is an optional adapter
for studies that already produced Phase-6.3 regional state.


The adapter is fail-closed:


- exact map ID/hash binding is required;
- Scene and module identities must agree;
- region sets must exactly match;
- every region must have positive physical area;
- mapped module-area coverage must equal 1 within explicit numerical tolerance;
- all regions must use one common unshaded POA basis and optical-modifier basis;
- each regional effective irradiance must reconcile with its channel state.


The whole-module equivalent is the physical-area-weighted mean of the regional
post-geometry and post-optical channel states.


## 4. Whole-module electrical model


`evaluate_level1_module_approximation(...)` reuses the existing validated PVsyst-v6
single-diode runtime. It does not introduce a second module model.


Required evidence:


```text
exact ModuleDefinition revision
+ ResolvedComponentModel for the exact revision
+ selected validated module.pvsyst_singlediode.v6 model
```


The evaluator produces:


```text
Isc
Voc
Imp
Vmp
Pmp
active state
```


for the explicit module-equivalent irradiance and one module temperature.


## 5. New derived state


Phase 6.4 adds:


```text
ModuleLevelElectricalApproximationState v0.1
```


It records:


- exact Scene / ElectricalDesign / module revision identities;
- source geometric `ShadingResult` identity;
- optional source regional state/map/topology identities;
- interval and evaluation time;
- aggregation method;
- three-channel unshaded, post-geometry and post-optical irradiance;
- one equivalent incident POA scalar;
- one equivalent effective-irradiance scalar;
- one module temperature;
- whole-module MPP state;
- exact model/solver manifest;
- `internal_nonuniformity_scope = collapsed_uniform_equivalent`;
- `bypass_scope = not_modeled`;
- deterministic payload SHA-256.


## 6. ElectricalShadingResult semantics at Level 1


The output uses the existing `ElectricalShadingResult` envelope with:


```text
resolved_fidelity = level_1_module_approximation
```


Attribution is intentionally conservative:


```text
geometric_irradiance   = upstream / not re-booked
electrical_mismatch    = not_modeled
bypass_interaction     = not_modeled
mppt_operating_point   = not_modeled
```


The result therefore means:


> this module has a validated whole-module electrical response to an explicit
> equivalent irradiance state.


It does **not** mean:


> the electrical consequence of the module's internal nonuniform shading has been
> solved.


That distinction is required for the Phase-6 loss ledger to remain reconcilable.


## 7. Product/API diagnostic surface


The project API adds a non-persisted engineering snapshot endpoint:


```text
POST /api/projects/{project_id}/electrical-shading/level1-module-snapshot
```


It consumes an exact saved module instance, the saved electrical-shading fidelity
selection, explicit sun/irradiance/optical/thermal snapshot inputs and explicit sky
and ground resolution.


It returns:


```text
source_shading_result
module_equivalent_irradiance_state
module_state
electrical_shading_result
```


The endpoint mutates neither `SceneRevision` nor `ElectricalDesignRevision`.


## 8. Determinism


Scientific identity includes the material physical approximation:


- whole-module SDM model;
- Level-1 aggregation method;
- channel/optical ordering;
- module-equivalent state hash;
- exact component-model resolution identity;
- exact source Scene/ElectricalDesign/shading identities.


Execution-only policy remains separate where it does not alter physics.


For identical inputs:


```text
same equivalent state
→ same ModuleLevelElectricalApproximationState hash
→ same module MPP
→ same ElectricalShadingResult physical-result hash
```


## 9. Focused validation added


`tests/unit/test_phase64_level1_module_approximation.py` covers:


1. topology-free direct module aggregation and channel ordering;
2. reuse/equivalence with the existing validated whole-module SDM runtime;
3. fail-closed behavior when trusted resolved-model evidence is absent;
4. area-weighted full-coverage regional collapse;
5. failure on incomplete regional coverage;
6. deterministic state/result hashes.


Full repository regression/CI remains required before this tranche can be marked
closed.


## 10. Non-goals


Phase 6.4 does not implement:


- region/submodule parameter derivation;
- substring IV curves;
- bypass diode switching;
- nonuniform module IV/PV curves;
- multiple local P-V maxima;
- non-identical modules in series;
- parallel string common-voltage aggregation;
- MPPT tracking behavior;
- annual high-fidelity detailed-shading integration.


## 11. Phase-6.5 handoff


Phase 6.5 may begin once the Phase-6.4 milestone gate is satisfied.


Its job is the first true internal electrical-interaction kernel:


```text
region/sub-string irradiance
→ substring IV
→ explicit bypass-device behavior
```


The slow transparent reference kernel must come before accelerated production
implementations.