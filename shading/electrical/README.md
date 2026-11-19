# Electrical shading boundary

Development Phase 6.1 freezes the canonical electrical-shading contracts in
this package. It deliberately does **not** implement production mismatch,
bypass, module-IV, string-IV, or MPPT operating-point physics.

Authority remains split as follows:

```text
Scene / ModuleInstance
= physical placement and orientation

ModuleDefinition
= commercial/electrical module definition

ModuleTopologyDefinition
= optional separately revisioned internal physical-to-electrical topology

ElectricalRegionMap
= deterministic derived mapping of topology regions onto one placed module

ElectricalDesignRevision
= module → ordered string → MPPT → inverter connectivity
```

The geometry-to-electrical handoff preserves beam, sky-diffuse, and
ground-reflected irradiance channels. Geometric irradiance reduction is
upstream of electrical mismatch/bypass and must not be booked a second time as
an electrical loss.

Electrical-shading fidelity is explicit:

```text
Level 0  geometry only
Level 1  module-level electrical approximation
Level 2  bypass-substring-aware
Level 3  cell/submodule IV
```

No detailed topology is inferred from cell count, bypass-diode count, or a
marketing layout code. Missing topology reduces available fidelity; it does not
invalidate ordinary module use.


Detailed module-model readiness is evidence-based. The resolver consumes the
module `ResolvedComponentModel` produced by the existing component/model
resolution pipeline for the exact selected module revision. A raw
`ModuleDefinition.capability_flags.detailed_sdm_ready` value is not
authoritative; the resolved artifact must select the validated
`module.pvsyst_singlediode.v6` contract and its capability snapshot must agree.

Level-2/3 parameterization readiness is also evidence-based. The resolver consumes
`ElectricalParameterizationEvidence` bound to the exact module and topology
revisions, model/version, validation record, provenance, source IDs, and payload
hash. Caller-supplied availability booleans are not authoritative capability
inputs.

Bypass-model readiness follows the same trust rule. A stored forward-voltage
model is classified as either `component_model` or
`explicit_simulation_assumption`. Component models require validation/provenance
evidence before Level 2; assumptions may execute only when explicitly identified
and surfaced as assumptions rather than component truth.

Topology structure and region geometry readiness are separate. Electrical
membership/order can remain structurally valid even when a region polygon is not
safe for execution. Geometry-dependent Level 2 additionally requires simple
(non-self-intersecting) region polygons with no positive-area overlap between
distinct regions; shared edges and point contacts are allowed.

Capability resolution itself is pure derivation. Raw module/model evidence,
topology geometry, bypass models, and parameterization records are first converted
into `ResolvedModuleCapabilitySnapshot`, `TopologyValidationResult`,
`BypassModelEvidence`, and `ValidatedParameterizationEvidence`. The final
resolver only combines those validated results and checks their revision bindings;
it does not re-run source/model/geometry validation.

`ElectricalIVCurve.global_mpp` and `local_mpp_candidates[]` are
solver-declared metadata. Contract validation separately checks consistency with
the represented samples: P≈VI, global power not below represented sampled maxima,
and local candidates matching represented sampled local extrema within explicit
tolerances. These checks do not claim continuous-curve optimality unless the
solver explicitly records a continuous-curve guarantee and basis.

See:

- `docs/phase61-electrical-shading-contract.md`
- `docs/decisions/0054-phase61-electrical-shading-canonical-boundary.md`
- `shading/electrical/contract.py`

## Phase 6.3 derived electrical regions

Phase 6.3 adds a deterministic, non-editable bridge from one exact module-plane
receiver and one exact selected `ModuleTopologyDefinition` revision to physical
electrical regions:

```text
Scene / CompiledShadingGeometry
+ explicit project-pinned ModuleTopologyDefinition
        ↓
ElectricalRegionMap
        ↓
regional beam / sky / ground visibility
        ↓
LocalElectricalIrradianceState
```

`ElectricalRegionMap` is derived physics data, not Scene geometry. Portrait uses the
intrinsic module-front UV convention unchanged; landscape is frozen as 90° clockwise
when viewed from the module front and the transform convention participates in the
map identity.

Regional visibility reuses the existing Phase-5 kernels. Its `ShadingResult` declares
`receiver_granularity = electrical_region` and
`electrical_shading_scope = not_modeled`: regional shading remains geometry, not
bypass/mismatch loss.

Local irradiance preserves beam, sky-diffuse and ground-reflected components and
applies explicit optical modifiers only after geometric visibility. Phase 6.3 does
not derive substring/cell electrical parameters and does not implement bypass,
module-IV, string-IV or MPPT solving.

## Phase 6.4 Level-1 module approximation

Phase 6.4 adds the first electrical response after the geometry/irradiance handoff.
Level 1 produces one validated whole-module SDM state per module and does **not**
require a `ModuleTopologyDefinition`. The canonical path consumes one exact module
receiver, preserves beam/sky/ground through geometry and optical treatment, and then
collapses them to one explicit uniform-equivalent module irradiance.

When a Phase-6.3 `LocalElectricalIrradianceState` already exists, it may be collapsed
to the same Level-1 state only when the mapped regions cover the complete module area;
the collapse is physical-area weighted and incomplete coverage fails closed.

Execution requires trusted exact-revision `ResolvedComponentModel` evidence selecting
`module.pvsyst_singlediode.v6`. The output records one Isc/Voc/Imp/Vmp/Pmp state.
Electrical mismatch, bypass interaction, string-IV and MPPT behavior remain explicitly
`not_modeled`; geometric irradiance reduction remains upstream and is not re-booked.

See:

- `docs/phase64-level1-module-electrical-shading.md`
- `docs/phase64-milestone-measuring-stick.md`
- `docs/decisions/0059-phase64-level1-module-equivalent-electrical-state.md`


### Opt-in anisotropic component handoff

Detailed execution with the new optics settings preserves five incident components per region: beam, isotropic,
circumsolar, signed horizon correction and ground. Existing geometry queries supply beam, sky, horizon and ground
visibility; circumsolar follows the solar direction. IAM follows geometry per component, then soiling is applied
once. The mapper records all source, geometric and optical component values in an additive `component_state`.

Only the new branch exposes the already-computed horizon visibility through the existing directional-diffuse
record field. Legacy visibility records and hashes remain unchanged. The component collapse validates binding,
state hashes, full area coverage and reconstruction before area-weighting the module thermal input. It does not
use the legacy three-channel uniform-optics approximation for anisotropic sky. Signed isotropic and horizon terms are scaled,
not clamped; a negative combined sky or effective irradiance is refused. The IV solver, geometry, quadrature and
single-module-temperature approximation remain unchanged.

For component-bearing S18b states, optical factors may exceed one: cubic module IAM tables can overshoot. Factors must remain finite and non-negative; no clipping is applied. Legacy states without component evidence retain the original [0, 1] optical-factor contract. All geometric visibility factors remain bounded to [0, 1].
