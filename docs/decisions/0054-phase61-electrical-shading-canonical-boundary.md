# ADR 0054 — Phase-6.1 Electrical-Shading Canonical Boundary

**Status:** Accepted  
**Date:** 25 September 2026

## Context

Gate A is closed at the Phase-6.0D baseline. OpenSIMPV can now execute a
browser-authored fixed-tilt project through the existing Phase-5 geometry-aware
simulation chain.

The next maturity objective is electrical shading and high-fidelity DC physics.
The current geometry side is already authoritative and deterministic, while the
current electrical worker is intentionally homogeneous and fail-closed for
mismatched strings and MPPT states.

Detailed electrical shading requires an explicit physical-to-electrical module
topology. Existing module metadata such as cell count, row/column count,
half-cell flag, and bypass-diode count is useful but is not sufficient to infer
substring wiring for all module architectures.

The Open Component Library specification already defines ModuleTopology as an
optional object tied to a module revision and requires that topology may be
added later without changing module identity.

## Decision

1. Keep canonical Scene/ModuleInstance as physical placement authority.
2. Keep ElectricalDesignRevision as module → ordered string → MPPT → inverter
   connectivity authority.
3. Introduce ModuleTopologyDefinition as a **separately revisioned optional
   object** tied to one exact ModuleDefinition revision.
4. A ModuleDefinition may reference a topology revision, but missing topology
   never invalidates normal module use.
5. Do not infer detailed topology from cell count, bypass-diode count,
   half-cell flag, or source layout code alone.
6. Freeze intrinsic module coordinates as:

   ```text
   module_front_uv_normalized_width_height

   viewed from module front:
   U = 0..1 left → right across mechanical.width_m
   V = 0..1 bottom → top across mechanical.height_m
   ```

   Portrait/landscape/site placement is a Scene transform; it does not alter
   intrinsic topology coordinates.
7. Freeze four fidelity levels:
   - level_0_geometric_only;
   - level_1_module_approximation;
   - level_2_bypass_substring;
   - level_3_cell_submodule_iv.
8. Detailed-SDM readiness is not authorized by a raw
   `ModuleDefinition.capability_flags.detailed_sdm_ready` boolean. Phase-6
   electrical shading consumes the existing module `ResolvedComponentModel`
   produced by component/model resolution. It must be bound to the exact module
   revision and resolve `module.pvsyst_singlediode.v6` with
   `implementation_status = validated_contract` and
   `validation_status = passed`. The capability snapshot must agree, but it is
   not sufficient by itself. The shading resolver consumes this evidence and
   does not re-run SDM validation.
9. Missing or untrusted topology reduces available fidelity. It does not trigger
   silent topology synthesis. Trusted topology alone is still insufficient for
   Level 2: revision-bound validated region/sub-string parameterization evidence
   is also required. The authoritative capability input is an
   `ElectricalParameterizationEvidence` object bound to the exact module and
   topology revisions, model/version, validation record, provenance, source IDs,
   and parameterization payload hash. Caller-asserted availability booleans are
   not authoritative inputs. Whole-module SDM parameters are never silently
   divided or scaled into substring parameters. Automated topology consistency
   validation alone is not semantic authorization for Level 2; topology must be
   reviewed or manufacturer-verified.
10. Freeze the first executable topology class as protected substrings in series,
   each substring containing one or more explicit parallel branches with ordered
   physical regions.
11. Do not coerce cross-tied or unusual wiring into that common topology class.
    Unsupported topology stays unsupported until an explicit future topology
    class exists.
12. Keep electrical-topology structural validity distinct from physical-region
    geometry execution readiness. A topology may remain structurally valid stored
    component data while geometry-dependent detailed execution is blocked.
    Execution-ready region geometry requires simple/non-self-intersecting polygons
    and no positive-area overlap between distinct physical regions. Shared edges
    and point contacts are allowed.
13. Freeze ElectricalRegionMap as deterministic **derived physics state**, not
    editable engineering authority.
14. Preserve beam, sky-diffuse, and ground-reflected channels through the
    geometry-to-electrical handoff.
15. Freeze the local ordering as:

    ```text
    unshaded POA by channel
    → geometry visibility by channel
    → optical/IAM treatment
    → local effective irradiance
    ```

16. Preserve one module temperature per module for the initial Phase-6
    electrical-shading chain. Spatial thermal heterogeneity requires a future
    explicit model.
17. Freeze bypass model taxonomy as:
    - ideal;
    - constant_forward_drop;
    - parameterized_iv.

    Separately freeze bypass-model authority semantics:
    - `component_model`;
    - `explicit_simulation_assumption`.

    Structural presence of a forward-voltage model is not enough for Level 2.
    A component model requires sufficient verification state, trusted provenance,
    an explicit validation record, source IDs, and immutable model-payload
    identity. An explicit simulation assumption may execute only when it is
    deliberately identified and records its assumption rationale; it must remain
    distinguishable from source-validated component truth.
18. Freeze a common sampled ElectricalIVCurve contract usable at submodule,
    module, string, and combined-MPPT scope. Voltage samples are strictly
    ascending. Voltage is positive from PV + to PV -, current is positive when
    delivered by the PV source, and P = V×I with positive power meaning
    generation. Multiple local P-V maxima are valid.

    `global_mpp` and `local_mpp_candidates[]` are solver-declared metadata,
    not conclusions inferred solely from the stored samples. The contract
    independently checks P≈VI, verifies that declared global MPP power is not
    below represented sampled maxima/local candidates beyond explicit tolerance,
    and requires declared local candidates to correspond to represented sampled
    local power extrema within explicit voltage/power tolerances.

    These checks establish sampled-representation consistency only. They do not
    prove continuous-curve optimality. A continuous-curve claim is valid only
    when `mpp_semantics.continuous_curve_guarantee = solver_guaranteed` and an
    explicit non-empty solver/model guarantee basis is recorded.
19. Keep existing homogeneous string/MPPT guardrails until a validated Phase-6
    full-IV aggregation path replaces them for supported fidelity levels.
20. Keep geometric irradiance, electrical mismatch, bypass interaction, and MPPT
    operating-point effects as separate staged counterfactuals. Freeze the delta
    sign as reference minus evaluated: positive is loss and negative is recovery.
    The bypass term is therefore signed because bypass activation may recover
    power relative to a forced-off counterfactual; it is not intrinsically a
    positive "loss".
21. No silent electrical-shading fallback is allowed. The default is
    `fail_closed`. A lower-fidelity run is allowed only through an explicit
    `explicit_lower_fidelity` policy and must record requested and resolved
    fidelity.
22. Separate scientific identity from execution identity. Cache, storage
    location, parallelization, and equivalent execution mechanics must not alter
    physical/scientific result identity.
23. Retain legacy ModuleDefinition `detailed_shading_ready` and
    `detailed_sdm_ready` capability flags only for schema/backward compatibility.
    They are non-authoritative under Phase 6.1. Detailed-SDM authorization comes
    from the exact-revision `ResolvedComponentModel`; higher fidelity additionally
    requires the separately revisioned topology and revision-bound
    parameterization evidence.
24. Freeze the v0.1 local region irradiance handoff as front-side only. Spatial
    bifacial rear-side electrical nonuniformity requires a future explicit
    extension rather than being implicitly folded into front-side channels.
25. Make electrical-shading capability resolution a pure derivation layer.
    Raw component/model-resolution data, topology, polygon geometry, bypass
    models, and parameterization evidence are validated/classified upstream into
    `ResolvedModuleCapabilitySnapshot`, `TopologyValidationResult`,
    `BypassModelEvidence`, and `ValidatedParameterizationEvidence`.
    `resolve_electrical_shading_capability(...)` consumes only those results and
    must not re-run source verification, SDM validation, topology validation,
    polygon geometry checks, bypass-model validation, or parameterization
    validation. It may enforce cross-result identity consistency so validated
    snapshots from different module/topology revisions cannot be mixed.
26. Phase 6.1 freezes contracts only. It does not activate a production
    electrical-shading solver.

## Consequences

### Positive

- Geometry, topology, and electrical connectivity remain separate authorities.
- Detailed-shading capability can be added to a module without changing module
  identity.
- Detailed-SDM capability is consumed from the same immutable model-resolution
  artifact already stored with simulation runs, avoiding a second validation
  authority inside electrical shading.
- Capability derivation is deterministic over prevalidated snapshots/results and
  cannot silently reinterpret raw evidence at the fidelity-selection boundary.
- Ordinary modules remain usable when topology is absent.
- Half-cell/common parallel-branch layouts can be represented explicitly
  without inferring them from counts.
- Unsupported unusual wiring fails closed rather than being approximated as a
  conventional module.
- Invalid/ambiguous physical-region geometry can be corrected without discarding
  an otherwise coherent electrical topology revision.
- Later acceleration can change execution mechanics without changing scientific
  identity.
- Loss accounting can distinguish reduced irradiance from electrical mismatch
  and MPPT interaction.
- Simplified bypass physics may be used transparently as an explicit simulation
  assumption without being promoted to manufacturer/component truth.

### Costs

- A module may need an additional separately managed topology revision.
- Detailed-shading readiness cannot be decided from nameplate/cell-count data
  alone.
- Some commercial module architectures will remain below Level 2 until both
  topology and a validated region/sub-string parameterization are available.
- High-volume region/IV artifacts require additional derived-state management in
  later tranches.

## Rejected alternatives

### Embed topology permanently inside ModuleDefinition

Rejected because the component-library architecture already treats topology as
optional and addable later without changing module identity. Separate revisioning
also gives topology its own provenance and verification lifecycle.

### Infer substrings from cell count and bypass-diode count

Rejected because multiple physical/electrical layouts can share those counts.

### Add cell polygons as editable Scene entities

Rejected because cell/submodule regions are derived physics regions inside a
placed module, not a new engineering geometry authority.

### Collapse geometric shading to one electrical loss factor

Rejected because geometric irradiance reduction and electrical mismatch/bypass
are physically distinct and must remain independently auditable.

### Automatically downgrade fidelity

Rejected because it can silently change the physical model used by a study.
Lower fidelity must be an explicit, recorded engineering decision.
