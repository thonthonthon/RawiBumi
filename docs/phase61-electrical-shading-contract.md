# RawiBumi — Phase 6.1 Electrical Shading Contract & Canonical Boundary v0.1


**Status:** CLOSED — Drive working baseline; GitHub synchronization pending  
**Date:** 25 September 2026  
**Baseline:** `main @ fefe5918b04634d9f8f89d4121471019ed8cbb24`  
**Parent:** Phase 6.0D Browser UAT Vertical Slice / Gate A  
**Scope:** Canonical electrical-shading contract only  
**Production mismatch/bypass solver:** Not included in Phase 6.1


## 1. Objective


Phase 6.1 freezes the interfaces and engineering semantics required before
production high-fidelity DC mismatch work begins.


The target future chain remains:


```text
geometric shadow
→ local module regions
→ electrical substrings / branches
→ local effective irradiance
→ submodule IV
→ bypass state
→ module IV
→ string IV
→ parallel strings
→ MPPT operating point
→ inverter
```


Phase 6.1 does not implement that numerical chain. It defines the authority,
identity, fidelity, provenance, loss, and fail-closed rules that later tranches
must obey.


## 1.1 Corrective hardening scope before closure


The pre-merge corrective pass is intentionally narrow. It exists to harden trust
boundaries already claimed by this contract; it does not reopen the Phase-6.1
architecture.


The following decisions are frozen and out of scope for corrective redesign:


```text
SceneRevision / ModuleInstance remains geometry authority
ElectricalDesignRevision remains connectivity authority
Phase-5 ShadingResult remains geometry-only authority
existing homogeneous string / MPPT fail-closed guards remain active
module_front_uv_normalized_width_height remains the intrinsic topology coordinate system
cell counts / bypass counts / layout codes never authorize inferred detailed topology
```


Corrective implementation is restricted to these five boundaries:


1. **Parameterization evidence boundary**
   - replace caller-asserted region/cell readiness booleans with revision-bound,
     provenance-bearing validation evidence;
   - a boolean may exist only as a derived result, never as authoritative evidence.


2. **Bypass-model evidence boundary**
   - distinguish source/verification-backed bypass-device models from explicit
     simulation assumptions;
   - structural presence of `forward_voltage_model` alone must not imply verified
     component truth.


3. **Topology execution-readiness boundary**
   - keep structural electrical-topology validity distinct from physical-region
     geometry readiness;
   - geometry-dependent Level-2 execution must not be unlocked by malformed,
     self-intersecting, or ambiguously overlapping region geometry.


4. **Detailed-SDM trust boundary**
   - the electrical-shading resolver must consume capability state produced by the
     trusted component-validation pipeline rather than trust an arbitrary stored
     `detailed_sdm_ready` boolean.


5. **IV-result verification semantics**
   - distinguish solver-declared MPP metadata from independently checked properties
     of the represented sampled curve;
   - do not imply continuous-curve proof from discrete samples unless the selected
     solver/model provides that guarantee.


No production mismatch solver, topology inference engine, new geometry authority,
or new electrical-connectivity authority is introduced by this hardening pass.


## 2. Existing authorities remain unchanged


```text
SceneRevision / ModuleInstance
= physical module placement and orientation


ModuleDefinition
= component identity, dimensions and electrical model data


ElectricalDesignRevision
= ordered module → string → MPPT → inverter connectivity


ShadingResult
= geometric beam / sky / ground visibility authority
```


Phase 6.1 adds no parallel editable geometry model.


## 3. ModuleTopologyDefinition


Detailed electrical shading needs internal physical-to-electrical module
construction.


The canonical topology object is separately revisioned:


```text
ModuleDefinition revision
        ↓ optional exact reference
ModuleTopologyDefinition revision
```


The module remains valid when no topology exists.


This follows the component-library rule that topology is optional and may be
added later without changing module identity.


A topology revision is tied to exactly one ModuleDefinition revision.


## 4. No topology inference from counts


The following fields are useful metadata but are not sufficient to establish
detailed electrical wiring:


```text
physical cell count
cell rows / columns
half-cell flag
cells in series / parallel
bypass diode count
source layout code
```


RawiBumi shall not infer protected substring membership or parallel branch
wiring from those values alone.


Detailed fidelity requires explicit topology provenance.


## 5. Intrinsic module coordinate convention


The frozen coordinate convention is:


```text
module_front_uv_normalized_width_height
```


Viewed from the module front:


```text
U = 0 → 1
left → right across mechanical.width_m


V = 0 → 1
bottom → top across mechanical.height_m
```


These are intrinsic component coordinates.


Portrait/landscape placement, azimuth, tilt and scene position are external Scene
transforms. They never rewrite the topology coordinates.


## 6. Physical region taxonomy


A physical electrical region may represent:


```text
cell
half_cell
grouped_cells
submodule
```


Every region has:


```text
region_id
region_type
polygon_normalized
equivalent_element_count
```


The polygon is defined in normalized intrinsic module UV.


Two validation layers are intentionally distinct:


```text
topology_structurally_valid
= electrical references/membership/order are coherent and region polygons are
  bounded non-zero records


region_geometry_execution_ready
= every physical-region polygon is simple/non-self-intersecting
  + distinct physical regions do not overlap with positive area
```


Shared edges and point contacts between adjacent regions are allowed. Positive-area
overlap is not, because it would make later area-based irradiance mapping
ambiguous/double-counted.


A structurally valid topology with geometry that is not execution-ready remains
valid stored component data, but it cannot unlock geometry-dependent Level 2.


Region geometry is component-internal physics metadata, not editable site CAD.


## 7. Initial topology class


The first frozen common topology class for later executable detailed physics is:


```text
series_substrings_parallel_branches
```


Semantics:


```text
module
  ↓
protected substring 0
  ├─ parallel branch A
  │    region → region → region ...
  └─ parallel branch B
       region → region → region ...


  ↓ series


protected substring 1
  ...
```


Each branch contains an explicit ordered `series_region_ids` list.


Each physical region appears in exactly one branch for this topology class.


This contract class is intended to represent common protected-substring modules,
including common layouts with parallel half-cell branches.


Cross-ties or unusual interconnects shall not be coerced into this class.


A later topology class may add a general graph when justified.


## 8. Bypass devices


Bypass devices are explicit topology objects.


Each device identifies the protected substring IDs and one explicit model.


Frozen model taxonomy:


```text
ideal
constant_forward_drop
parameterized_iv
```


Every model carries:


```text
model_id
model_version
model_authority
verification_state
model_provenance
validation_record_id
assumption_id
assumption_rationale
parameters
source_ids
model_payload_sha256
```


The authority classes are:


```text
component_model
explicit_simulation_assumption
```


A `component_model` may be stored before it is trusted, but Level 2 requires
sufficient verification state, trusted provenance, an explicit validation record,
at least one source ID, and immutable model-payload identity.


An `explicit_simulation_assumption` may be executable when it is deliberately
selected and records an assumption ID and rationale. It must use
`verification_state = not_applicable` and
`model_provenance = simulation_assumption`; it cannot claim a component-model
validation record.


The resolver therefore distinguishes:


```text
validated_component_models
explicit_simulation_assumptions
mixed_validated_and_assumed
```


and returns explicit assumption IDs/findings when assumptions are active.


Structural presence of `forward_voltage_model` alone does not establish bypass
execution readiness or verified component truth.


A bypass model is never hidden inside the module solver.


## 9. Fidelity semantics


The frozen levels are:


### Level 0 — geometric only


```text
level_0_geometric_only
```


Existing Phase-5 geometric shading only.


No electrical mismatch claim.


### Level 1 — module approximation


```text
level_1_module_approximation
```


One electrical state per module.


Detailed internal bypass topology is not solved.


Requires a validated detailed module electrical model but does not require
ModuleTopologyDefinition.


Detailed-SDM readiness is not read from
`ModuleDefinition.capability_flags.detailed_sdm_ready`. The authoritative
handoff is the module `ResolvedComponentModel` produced by the component/model
resolution pipeline for the exact selected ModuleDefinition revision.


### Level 2 — bypass substring


```text
level_2_bypass_substring
```


Requires:


```text
validated detailed module electrical model
+ exact module topology revision
+ trusted topology provenance
+ trusted topology verification state
+ region geometry execution readiness
+ complete explicit bypass coverage
+ every bypass device has either a validated component model or an explicit simulation assumption
+ revision-bound ElectricalParameterizationEvidence for region/sub-string physics
```


The whole-module SDM is not silently divided or scaled into substring parameters.
Topology establishes connectivity; a separate validated parameterization establishes
the electrical model of those regions/substrings.


### Level 3 — cell/submodule IV


```text
level_3_cell_submodule_iv
```


Requires Level 2 plus:


```text
cell or half-cell region resolution
+ revision-bound ElectricalParameterizationEvidence for cell-level physics
```


Phase 6.1 implements neither region/sub-string nor cell-level parameter derivation;
it only freezes the capability gates.


## 10. Capability resolution


The contract-level resolver is:


```text
resolve_electrical_shading_capability(...)
```


It is a **pure derivation layer**. It does not inspect raw ModuleDefinition,
ModuleTopologyDefinition, bypass-model dictionaries, source provenance, or raw
parameterization evidence.


The upstream validation boundary produces immutable-style result objects:


```text
ResolvedComponentModel
    ↓ resolve_module_capability_snapshot(...)
ResolvedModuleCapabilitySnapshot


ModuleTopologyDefinition
    ↓ validate_topology_for_electrical_shading(...)
TopologyValidationResult


topology bypass models + TopologyValidationResult
    ↓ resolve_bypass_model_evidence(...)
BypassModelEvidence


ElectricalParameterizationEvidence
    ↓ validate_parameterization_for_electrical_shading(...)
ValidatedParameterizationEvidence
```


Only then is fidelity derived:


```text
ResolvedModuleCapabilitySnapshot
+ TopologyValidationResult
+ BypassModelEvidence
+ ValidatedParameterizationEvidence(region_substring)
+ ValidatedParameterizationEvidence(cell)
        ↓
resolve_electrical_shading_capability(...)
        ↓
available / maximum fidelity
```


This prevents the capability resolver from becoming a second validation authority.


The pure resolver still checks **cross-result identity consistency**: module,
topology, bypass, and parameterization results must refer to the same validated
module/topology revisions. This is a deterministic binding check between already
validated results, not re-validation of their raw sources.


The pure resolver returns:


```text
available_fidelity_levels
maximum_fidelity_level
detailed_sdm_ready
module_capability_resolution_id
topology_present
topology_valid                         # compatibility alias
topology_structurally_valid
region_geometry_execution_ready
topology_trusted
bypass_models_ready
bypass_model_readiness_mode
bypass_assumption_ids
region_parameterization_ready
cell_parameterization_ready
findings
```


Important rule:


```text
missing topology
→ lower maximum fidelity


NOT


missing topology
→ invalid module
```


Detailed topology with inferred or unresolved wiring does not unlock Level 2.


### 10.1 Detailed-SDM validation boundary


Raw module/model-resolution evidence is processed upstream by:


```text
resolve_module_capability_snapshot(...)
```


That boundary accepts the module `ResolvedComponentModel` and requires:


```text
component_type = module
status = resolved
exact selected ModuleDefinition revision
selected model = module.pvsyst_singlediode.v6
model_family = single_diode
implementation_status = validated_contract
validation_status = passed
explicit parameter_source_path
source_ids
capability_snapshot.detailed_sdm_ready = true
```


The selected model and validation state are authoritative; the capability
snapshot is a consistency check, not a standalone authorization boolean.


A raw `ModuleDefinition.capability_flags.detailed_sdm_ready = true` therefore
cannot unlock Level 1 or higher.


The electrical-shading capability resolver itself does not re-run SDM validation.


### 10.2 Topology / geometry validation boundary


Raw topology is processed upstream by:


```text
validate_topology_for_electrical_shading(...)
```


It produces `TopologyValidationResult`, including:


```text
topology_present
topology_revision_id
module_revision_id
topology_structurally_valid
topology_trusted
region_geometry_execution_ready
bypass_coverage_complete
region_resolution
findings
```


Polygon computation, self-intersection checks, overlap checks, revision binding,
verification-state checks, and topology provenance checks occur here — not in
the pure capability resolver.


### 10.3 Bypass-model validation boundary


Bypass model classification is processed upstream by:


```text
resolve_bypass_model_evidence(...)
```


It returns `BypassModelEvidence` with:


```text
topology_revision_id
bypass_models_ready
readiness_mode
assumption_ids
findings
```


Component-model validation and explicit-assumption classification therefore occur
before capability derivation.


### 10.4 Parameterization validation boundary


Raw `ElectricalParameterizationEvidence` is processed upstream by:


```text
validate_parameterization_for_electrical_shading(...)
```


It produces `ValidatedParameterizationEvidence` bound to an expected scope and
the exact selected module/topology revisions.


Caller-asserted availability booleans remain prohibited.


Only a validation result with `ready = true` can contribute to Level 2/3
capability derivation.




## 11. Fidelity selection and fallback


Default behavior:


```text
fallback_policy = fail_closed
```


If the requested fidelity is unavailable, simulation must stop before the
unsupported solver path.


An explicit alternative is:


```text
fallback_policy = explicit_lower_fidelity
```


This is allowed only when the caller deliberately requests it and the run
records:


```text
requested fidelity
resolved fidelity
fallback applied
fallback reason
```


There is no silent fidelity downgrade.


## 12. ElectricalRegionMap


The geometry/topology bridge is:


```text
ModuleInstance
+ placed module receiver
+ ModuleTopologyDefinition
        ↓
ElectricalRegionMap
```


This artifact is:


```text
authority = derived_physics_only
editable = false
```


It binds each topology region to the placed module geometry and retains exact
source identities.


It is reproducible and hashable.


Phase 6.2 will implement production derivation.


## 13. Geometry-to-electrical irradiance handoff


The local ordering is frozen as:


```text
unshaded POA by channel
→ geometric visibility by channel
→ post-geometry POA by channel
→ optical / IAM treatment
→ local effective irradiance
```


The channels remain explicit:


```text
beam
sky diffuse
ground reflected
```


Do not collapse them into one unexplained shading multiplier.


Do not apply Phase-5 geometry twice.


### 13.1 Irradiance side scope


The v0.1 local electrical region state is explicitly:


```text
irradiance_side_scope = front_side_only_v0.1
```


It covers the existing front-side Phase-5 geometry-to-electrical handoff only.
Spatially resolved bifacial rear-side electrical nonuniformity is not implicitly
folded into this state and requires a future explicit contract extension.


## 14. Thermal boundary


Initial Phase-6 electrical shading preserves:


```text
thermal_state_scope = single_module_temperature
```


All electrical regions inside one module initially consume one module
temperature.


A spatial electrothermal/hotspot model is deferred and requires a future
explicit contract.


## 15. Electrical IV contract


The common IV artifact is:


```text
ElectricalIVCurve
```


Scopes:


```text
submodule
module
string
mppt_combined
```


Initial representation:


```text
sampled_voltage_grid
sample_order = ascending_voltage
sign_convention = pv_delivery_current_positive_power_equals_v_times_i
```


Electrical signs are frozen:


```text
voltage > 0
= PV positive terminal above PV negative terminal


current > 0
= current delivered by the PV source


power = voltage × current
power > 0
= generated power
```


Negative voltage/power remains representable where reverse-biased submodule
states require it. Sample voltages must be strictly increasing.


Each point retains:


```text
voltage
current
power
```


The contract explicitly supports multiple local P–V maxima.


It therefore records solver-declared metadata:


```text
global_mpp
local_mpp_candidates[]
```


and explicit verification semantics:


```text
mpp_semantics.declaration_authority = solver_declared
mpp_semantics.sample_verification_scope = represented_samples_only
mpp_semantics.voltage_tolerance_v
mpp_semantics.power_tolerance_w
mpp_semantics.continuous_curve_guarantee
mpp_semantics.continuous_curve_guarantee_basis
```


The declarations and the independent sampled-curve checks are distinct.


The contract validator independently verifies only what the stored representation
supports:


```text
every sampled point: power ≈ voltage × current
declared global MPP voltage lies within the represented sampled voltage domain
declared global MPP power is not below any represented sampled power maximum
declared global MPP power is not below any declared local-MPP candidate
every declared local-MPP candidate corresponds to a represented sampled local
power extremum within the declared voltage/power tolerances
```


These checks establish consistency with the **represented sampled curve**. They
do not prove that the declared global MPP is the mathematical maximum of an
unrepresented continuous IV curve.


Continuous-curve optimality may be claimed only when:


```text
continuous_curve_guarantee = solver_guaranteed
continuous_curve_guarantee_basis = explicit non-empty solver/model basis
```


Otherwise:


```text
continuous_curve_guarantee = none
continuous_curve_guarantee_basis = null
```


No production global-MPP search or interpolation solver is introduced by this
contract validation.


This prevents a future shaded module/string/MPPT implementation from assuming a
single smooth maximum or overstating what discrete IV samples prove.


## 16. Existing string and MPPT guardrails stay active


Current models:


```text
string.identical_series_mpp.v0.1
mppt.identical_parallel_mpp.v0.1
```


remain valid for their present homogeneous scope.


Phase 6.1 does not weaken their mismatch guards.


A full-IV aggregation path replaces those restrictions only in later tranches
and only for supported fidelity levels.


## 17. ElectricalShadingConfiguration


The new optional nested configuration separates Phase-6 model selection from
the legacy `electrical_shading_method` compatibility field.


It records:


```text
requested_fidelity
fallback_policy
thermal_state_scope
loss_accounting_boundary
model_selections
scientific_options
execution_options
```


The existing Phase-5 geometry worker continues to reject this Phase-6
configuration.


Contract availability does not imply solver availability.


## 18. Scientific identity versus execution identity


Scientific identity contains material physical/model choices:


```text
contract version
requested fidelity
fallback policy
thermal scope
loss-accounting boundary
model selections
scientific options
```


Execution identity additionally includes:


```text
cache choices
storage mechanics
parallelization
execution-specific numerical mechanics
```


Rules:


```text
change scientific option
→ scientific hash changes


change only cache/storage/parallelization
→ scientific hash unchanged
→ execution hash may change
```


This is required before annual acceleration/caching work.


## 19. ElectricalShadingResult


The result contract binds:


```text
source Scene revision
source ElectricalDesignRevision
source ShadingResult physical identity
requested fidelity
resolved fidelity
fallback state
topology revision IDs
region-map hashes
scientific model manifest
execution manifest
loss-accounting boundary
scientific input hash
physical result hash
execution payload hash
approximations
findings
```


High-volume local-state and IV data may later use bounded dataset references.


## 20. Loss-accounting boundary


The frozen ordering is:


```text
geometry
→ electrical mismatch / bypass interaction
→ MPPT operating point
→ inverter
```


Geometric irradiance loss is upstream authority.


ElectricalShadingResult therefore records explicit staged counterfactuals with:


```text
attribution_delta_convention
= reference_minus_evaluated_positive_is_loss
```


So every modeled stage uses:


```text
delta = reference - evaluated
positive delta = loss
negative delta = recovery / gain
```


The result records:


```text
geometric irradiance
    upstream_not_rebooked


electrical mismatch
    uniform same-area-weighted effective irradiance
    → nonuniform irradiance with bypass forced off


bypass interaction
    nonuniform irradiance with bypass forced off
    → nonuniform irradiance with bypass enabled
    signed delta


MPPT operating point
    ideal global MPP
    → selected tracker operating point
```


The bypass term is an **interaction delta**, not intrinsically a positive loss:
activating a bypass diode may recover power relative to the forced-off
counterfactual. Later numerical implementations may report signed energy/power
deltas, but must preserve these non-overlapping stage definitions.


## 21. Provenance and trust


Topology provenance states are:


```text
direct_source
manual_verified
derived_validated
inferred
unresolved
```


Only the first three provenance states may participate in detailed topology
fidelity. In addition, the topology verification state must be `reviewed` or
`manufacturer_verified`; automated consistency validation alone does not prove
that the source wiring semantics were mapped correctly.


This separates:


```text
data exists
from
data is trusted for high-fidelity physics
```


## 22. Machine-readable artifacts


Phase 6.1 introduces:


```text
components/schema/module-topology-definition.schema.json
shading/electrical/electrical-parameterization-evidence.schema.json
shading/electrical/electrical-shading-configuration.schema.json
shading/electrical/electrical-region-map.schema.json
shading/electrical/local-electrical-irradiance-state.schema.json
shading/electrical/electrical-iv-curve.schema.json
shading/electrical/electrical-shading-result.schema.json
shading/electrical/contract.py
```


ModuleDefinition gains an optional:


```text
module_topology_revision_id
```


reference.


The legacy `ModuleDefinition.capability_flags.detailed_shading_ready` and
`detailed_sdm_ready` keys may remain for backward/schema compatibility, but
neither is an authoritative Phase-6 electrical-shading capability input. The
trusted detailed-SDM handoff is a `ResolvedComponentModel` from the existing
component/model-resolution pipeline. A ModuleDefinition alone cannot prove
validated model selection, topology trust, or region/cell parameterization
readiness.


## 23. Deliberate Phase-6.1 non-goals


Not implemented:


```text
automatic topology extraction
PAN topology mapping
electrical region derivation
local region irradiance calculation
region/sub-string and cell parameter derivation
bypass state solver
nonuniform module IV solver
general series string IV
parallel string IV
MPPT operating-point solver
electrical mismatch energy accounting
annual detailed-shading acceleration
browser fidelity selector
spatial bifacial rear-side electrical mismatch
```


These belong to later Phase-6 tranches.


## 24. Validation requirements


Phase 6.1 tests must prove:


The corrective adversarial cases are cross-referenced in
`docs/phase61-corrective-adversarial-test-matrix.md`.


1. all new schemas are valid Draft 2020-12;
2. a representative common module topology validates;
3. malformed topology references fail;
4. region coordinates stay inside normalized intrinsic UV;
5. duplicate/unmapped region wiring fails closed;
6. cell/bypass counts alone do not unlock detailed fidelity;
7. no topology still permits Level 0/Level 1 where module electrical capability exists;
8. trusted complete topology alone does not unlock Level 2 without validated region/sub-string parameterization;
9. Level 2 unlocks only with topology plus revision-bound validated region/sub-string parameterization evidence;
10. stale, wrong-revision, failed-validation, or source-less parameterization evidence cannot unlock detailed fidelity;
11. the legacy caller-asserted parameterization availability booleans are rejected;
12. bypass-model object presence alone does not unlock Level 2;
13. a component bypass model requires verification/provenance/validation evidence before execution;
14. an explicit bypass simulation assumption is executable only when its assumption identity and rationale are recorded and surfaced;
15. topology structural validity remains distinct from region-geometry execution readiness;
16. self-intersecting region polygons do not unlock geometry-dependent Level 2;
17. positive-area overlap between distinct physical regions does not unlock geometry-dependent Level 2;
18. shared region edges/points remain allowed and do not count as overlap;
19. a raw ModuleDefinition detailed_sdm_ready boolean cannot unlock Level 1+;
20. detailed SDM readiness requires an exact-revision ResolvedComponentModel selecting the validated PVsyst single-diode model;
21. stale, blocked, lower-fidelity, or failed-validation module-resolution evidence fails closed;
22. the existing module-model resolver output is accepted by the Phase-6.1 capability snapshot producer;
23. capability derivation consumes only prevalidated snapshot/result objects;
24. mutating raw module/topology/parameterization objects after snapshot creation cannot change the pure resolver result;
25. source/model/topology/geometry/parameterization validation is not re-run inside the pure resolver;
26. otherwise-valid snapshots/results from mismatched module/topology revisions fail closed;
27. Level 3 remains blocked without separately validated cell-level parameterization evidence;
28. requested unsupported fidelity fails by default;
29. explicit lower-fidelity fallback is deterministic and visible;
30. execution-only option changes do not change scientific identity;
31. the Phase-5 geometry worker still rejects active Phase-6 electrical configuration;
32. solver-declared global MPP cannot be below the maximum represented sampled power beyond declared tolerance;
33. solver-declared local-MPP candidates must correspond to represented sampled local power extrema within declared tolerances;
34. sampled-curve checks do not imply continuous-curve optimality unless an explicit solver guarantee and basis are recorded;
35. existing Phase-5 regression and benchmark gates remain green.


## 25. Exit criterion


Phase 6.1 is closed for the **Google Drive working baseline** when:


```text
canonical boundary documented
+ ADR accepted
+ schemas valid
+ focused Phase-6.1 contract suite green
+ changed Phase-5 shading-boundary compatibility suite green
+ Python contract modules compile
+ Drive source matched the recorded GitHub Phase-6.1 head before closure-only edits
+ closure decision and handover recorded
```


The Drive working baseline satisfies those conditions on 25 September 2026.
Closure evidence executed from files materialized directly from the Drive repository:


```text
Phase-6.1 focused contract suite       23 passed
Phase-5 shading-boundary compatibility  6 passed
Python compileall                       PASS
Draft 2020-12 closure-critical schemas  9 PASS
```


Before these closure-only documentation edits, all 22 files changed by GitHub PR #74
matched the recorded GitHub head exactly at content/byte level:


```text
b8d17de8e5973cf93fc892d6865edd4065b525d9
```


The GitHub transport remains a separate synchronization gate. PR #74 is still
draft/open/unmerged, and the hosted `validation` and
`phase511-closure-validation` workflows have not produced a new executable pass on
the final synchronized head because the affected GitHub Actions jobs terminate
before repository steps execute. That infrastructure condition is neither a green
validation result nor a code-test failure.


When GitHub Actions is available again, synchronize these closure-only Drive changes
to the Phase-6.1 branch, execute both required workflows successfully on the exact
synchronized head, then mark the PR ready and merge that exact head. No Phase-6.1
architecture change is required merely for synchronization.


Working-state split after this closure:


```text
Google Drive working repository
6.1  Electrical Shading Contract & Canonical Boundary   CLOSED
6.2  Canonical Module Topology & Capability Resolution  NEXT


GitHub transport
PR #74                                                DRAFT / OPEN / UNMERGED
CI + merge synchronization                            PENDING
```


Phase 6.2 may now proceed in the Drive working repository against this frozen
contract without inventing a second geometry or electrical authority.