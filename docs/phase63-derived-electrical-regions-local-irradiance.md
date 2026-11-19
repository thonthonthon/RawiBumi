# RawiBumi — Phase 6.3 Derived Electrical Regions & Local Irradiance State


**Status:** IN PROGRESS — deterministic region geometry and three-channel local irradiance foundation implemented  
**Date:** 27 September 2026  
**Parent:** Phase 6.2 Canonical Module Topology & Capability Resolution  
**Scope:** project-pinned topology → derived electrical-region geometry → regional geometric visibility → local irradiance state; no mismatch/bypass IV solver


## 1. Objective


Phase 6.3 connects the existing geometry authority to the explicit module-topology
authority without creating a new editable design model.


The production boundary is:


```text
SceneRevision + pinned ModuleDefinition revision
+ explicit project-pinned ModuleTopologyDefinition revision
        ↓
CompiledShadingGeometry
        ↓
deterministic ElectricalRegionMap
        ↓
Phase-5 beam / sky / ground geometry evaluated per derived region
        ↓
regional ShadingResult (electrical_shading_scope = not_modeled)
        ↓
LocalElectricalIrradianceState
```


Electrical interaction remains outside this tranche.


## 2. Authority split


The following authorities remain frozen:


- `SceneRevision` owns module position/orientation and physical geometry;
- `ModuleDefinition` owns module dimensions and component data;
- `ModuleTopologyDefinition` owns physical-to-electrical internal topology;
- `ElectricalDesignRevision` owns module → string → MPPT → inverter connectivity;
- `CompiledShadingGeometry` remains the Phase-5 geometric visibility authority;
- `ElectricalRegionMap` is deterministic derived physics data only and is not editable;
- `LocalElectricalIrradianceState` is a derived scientific state and is not design authority.


No topology is inferred from cell count, half-cell flags, bypass count, PAN layout
codes or geometric proximity.


## 3. ElectricalRegionMap v0.1


`shading/electrical/region_map.py` derives one map for one exact module instance and
one exact selected topology revision.


The derivation binds and hashes:


```text
source Scene revision
module instance ID
module-definition revision
module-topology revision
source Phase-5 receiver ID
source CompiledShadingGeometry hash
module-front UV convention
placement orientation
mapper ID/version
region UV polygons
mapped 3D vertices and areas
```


A map cannot execute when:


- the module receiver is absent or disabled;
- the receiver is not a `module_plane`;
- receiver and topology module revisions disagree;
- topology geometry is structurally/execution invalid;
- the source compiled-geometry hash is missing/invalid;
- mapped electrical-region area exceeds the source receiver area beyond tolerance.


Gaps are permitted because the topology contract does not require physical regions
to cover the entire active module area. Positive-area overlap remains rejected by the
Phase-6.1 topology geometry gate.


## 4. Frozen portrait/landscape mapping


Topology polygons use intrinsic module-front normalized coordinates:


```text
U = intrinsic left → right
V = intrinsic bottom → top
viewed from module front
```


Scene placement currently stores `portrait` or `landscape`, but not landscape
handedness. Phase 6.3 therefore freezes the missing handedness explicitly:


```text
portrait:
    intrinsic UV is unrotated


landscape:
    intrinsic module is rotated 90° clockwise when viewed from module front
```


This convention is recorded in `mapper_manifest` and therefore participates in the
region-map identity. Changing it in a future contract version cannot silently reuse
an old map hash.


## 5. Regional geometric visibility


`shading/electrical/local_irradiance.py` creates an ephemeral regional query view of
the compiled geometry. It does **not** create Scene objects.


The view:


- replaces a module receiver query with its derived electrical regions;
- leaves the existing Phase-5 occluders unchanged;
- preserves the module source-entity identity so Phase-5 self-occluder exclusion
  semantics remain applicable;
- binds the query identity to the parent compiled-geometry hash and region-map hash.


The same established Phase-5 kernels are reused independently for each region:


```text
direct beam     → calculate_direct_beam_shadow
sky diffuse     → calculate_sky_visibility
ground/albedo   → calculate_ground_visibility
```


The result remains a canonical `ShadingResult`, with:


```text
receiver_granularity = electrical_region
electrical_shading_scope = not_modeled
```


Therefore this artifact is regional geometric information, not electrical mismatch
or bypass loss.


## 6. LocalElectricalIrradianceState v0.1


Phase 6.3 freezes this ordering for each electrical region and each irradiance
channel:


```text
unshaded POA component
× geometric visibility factor
= post-geometry POA component


post-geometry POA component
× explicit optical modifier
= electrically presented irradiance component
```


The three channels remain distinguishable:


```text
beam
sky diffuse
ground reflected
```


The scalar `effective_irradiance_w_m2` is the sum of the three post-optical
components. It is an irradiance input to later electrical physics; it is **not** an
electrical-loss result.


Optical modifiers are explicit values in `[0, 1]`; defaults are unity when the caller
has not supplied a separate optical correction. This avoids silently reapplying IAM
or other optical physics already included upstream.


Thermal state remains the frozen Phase-6.1 scope:


```text
single_module_temperature
```


One module temperature is attached to every region state for this contract version.


## 7. Scientific identity and fail-closed behavior


The local state binds:


- exact `ElectricalRegionMap` ID/hash;
- exact regional `ShadingResult` ID/hash;
- exact scene/module/topology identities inherited from the map;
- irradiance timestamp/interval;
- unshaded POA channels;
- regional visibility factors;
- optical modifiers;
- module temperature;
- mapper model IDs/versions.


The builder rejects:


- mixed region-map and ShadingResult identities;
- non-regional ShadingResult input;
- any input claiming electrical shading was already modeled;
- missing/extra regional receiver IDs;
- non-finite or negative irradiance;
- visibility/optical factors outside `[0, 1]`;
- invalid module temperature.


## 8. Project/API integration


The project service exposes derived maps through:


```text
GET /api/projects/{project_id}/electrical-shading/region-map
    ?module_instance_id=...
```


Execution requires a persisted Phase-6.2 selection for that module revision and a
project-pinned selected topology revision. The service deliberately does not fall
back to the current global catalog for this derivation.


This preserves project replay identity:


```text
saved project selection
+ saved pinned topology
+ current saved Scene revision
        ↓
derived region map
```


rather than:


```text
saved topology ID
+ whatever today's catalog happens to contain
```


## 9. Acceptance coverage implemented


`tests/unit/test_phase63_electrical_regions.py` currently proves:


1. portrait mapping is deterministic and area preserving;
2. the frozen landscape clockwise transform is deterministic;
3. stale topology/module revision binding fails closed;
4. region-specific direct-beam geometry can distinguish a blocked region from a
   clear region while electrical loss remains unmodeled;
5. local irradiance preserves beam/sky/ground channels and applies optical modifiers
   after geometry;
6. cross-map / cross-receiver identity mixing fails closed.


## 10. Non-goals


Phase 6.3 does **not** implement:


- region electrical parameter derivation;
- substring IV evaluation;
- bypass state solution;
- nonuniform module IV assembly;
- series string IV aggregation;
- parallel string aggregation;
- global MPPT operating-point solution;
- an electrical-loss percentage derived directly from shaded area.


Those remain later Phase-6 tranches.


## 11. Next handoff


The next electrical tranche can consume:


```text
ElectricalRegionMap
+ LocalElectricalIrradianceState
+ validated electrical parameterization evidence
```


without changing Scene geometry or reinterpretating module topology.