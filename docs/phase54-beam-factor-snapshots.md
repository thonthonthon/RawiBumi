# OpenSIMPV — Phase 5.4 Module/Receiver Beam Factors & Diagnostic Shadow Artifact v0.1

**Status:** Phase-5.4 implementation anchor  
**Date:** 24 September 2026  
**Scope:** deterministic receiver-set beam-factor orchestration around the Phase-5.3 reference kernel  
**Annual SimulationRun integration:** not included  
**Diffuse / ground obstruction:** not included  
**Electrical mismatch:** not included

## 1. Objective

Phase 5.4 turns the Phase-5.3 single-receiver beam kernel into a deterministic receiver-set operation without changing the beam-shadow equations.

The implemented chain is:

    Canonical Scene
    -> CompiledShadingGeometry
    -> SimulationExecutionGroupPlan
    -> explicit receiver set
    -> Phase-5.3 beam kernel per receiver
    -> ShadingResult

Optional projected geometry is emitted separately as a non-authoritative diagnostic artifact.

## 2. Main API

Implementation:

    geometry/shading/snapshot.py

Primary API:

    evaluate_beam_shading_snapshot(...)

The function evaluates one explicit sun state across one explicit receiver set.

It returns:

    BeamShadingSnapshotResult
        shading_result
        diagnostic_artifact | null

## 3. Main result contract

Phase 5.4 reuses the existing Phase-5.0:

    ShadingResult

rather than creating a second factor-result model.

For Phase 5.4:

    channels = [beam_visibility]

and each inline record contains:

    receiver_id
    timestamp
    sun_vector_xyz
    beam_visibility_factor
    sky_visibility_factor = null
    ground_visibility_factor = null
    quality_flags

No diffuse or ground factor is fabricated.

## 4. Receiver selection is explicit

A snapshot must receive exactly one selection source:

    explicit receiver_ids

or:

    SimulationExecutionGroupPlan
    + optional execution_group_ids

The API does not silently evaluate every receiver in the compiled scene.

This preserves the Phase-5.2 electrical/execution grouping boundary.

## 5. Execution-group receiver selection

Helper:

    receiver_ids_from_execution_group_plan(...)

Selection rules:

- groups are selected explicitly or all groups are selected when no group subset is supplied;
- receiver IDs are deduplicated and sorted;
- unresolved module receiver IDs fail closed;
- an empty selected receiver set fails closed;
- unknown execution-group IDs fail closed.

When an execution plan is used, its:

    compiled_geometry_hash

must exactly match the supplied CompiledShadingGeometry hash.

## 6. Receiver granularity

The active shading configuration remains authoritative.

Current Phase-5.4 behavior:

    receiver_granularity = module
        -> only module_instance receivers

    receiver_granularity = surface
        -> only surface receivers

    receiver_granularity = mixed
        -> module_instance and/or surface receivers

    receiver_granularity = pv_field
        -> unsupported by the current compiled receiver contract

No receiver type is silently coerced.

## 7. Configuration gate

Before evaluation, Phase 5.4 calls the Phase-5.0 strict geometry-aware configuration gate.

It additionally requires:

    beam_method = opensimpv.beam_shadow.polygon_projection
    diffuse_method = none
    albedo_method = none or null
    electrical_shading_method = none / null / not_modeled

The beam snapshot therefore cannot silently ignore a requested diffuse or ground model.

## 8. Unsupported approximation modes

Phase 5.4 does not implement angular shadow caching.

Therefore:

    cache_policy.mode = angular_bins

fails explicitly.

Supported snapshot modes are:

    none
    exact

The calculation remains exact for the supplied sun vector within the Phase-5.3 reference-kernel tolerances.

## 9. Receiver subdivision

The Phase-5.3 reference kernel evaluates the complete receiver polygon.

Therefore Phase 5.4 currently accepts only:

    receiver_subdivision_u = 1
    receiver_subdivision_v = 1

when those fields are present.

No hidden receiver sampling grid is introduced.

occluder_chord_tolerance_m is also rejected because the current native compiled polygon-face geometry already defines the occluder shape and the beam kernel does not consume that option.

## 10. Model options

Phase 5.4 requires:

    model_options = {}

for the reference snapshot path.

This prevents unimplemented options from being accepted and silently ignored.

## 11. Deterministic receiver ordering

The orchestrator normalizes receiver selection to:

    receiver_id ascending

before calculation and serialization.

Duplicate explicit receiver IDs are collapsed into one set member.

Caller collection order therefore does not change result identity.

## 12. Timestamp handling

Snapshot timestamps are optional.

When supplied, timestamps must:

- be valid ISO-8601;
- include an explicit timezone.

They are normalized to UTC with a trailing Z before hashing and serialization.

Equivalent timestamps therefore share one sun-state identity.

## 13. Sun-vector normalization

The snapshot normalizes the supplied sun vector before receiver evaluation.

Equivalent vectors such as:

    [0, 0, 1]
    [0, 0, 5]

produce the same normalized sun state and the same snapshot identity.

The Phase-5.3 kernel still performs its own defensive normalization.

## 14. Snapshot identity

Phase 5.4 adds deterministic snapshot provenance to ShadingResult:

    orchestrator_manifest
    receiver_set_sha256
    sun_state_sha256
    source_execution_plan_id
    result_payload_sha256

The result ID is derived from:

    result_payload_sha256

as:

    shading-result:<hash-prefix>

The payload hash excludes the result ID and the hash field itself, avoiding circular identity.

## 15. Configuration identity

shading_configuration_hash is the canonical SHA-256 of the complete active shading configuration.

Changing any explicit configuration value therefore changes snapshot identity even when the current scalar factor happens to remain numerically equal.

## 16. Receiver-set identity

receiver_set_sha256 hashes the sorted unique receiver-ID set.

This provides the receiver-set component required by later cache identity.

## 17. Sun-state identity

sun_state_sha256 hashes:

    normalized sun vector
    normalized timestamp

The shading configuration hash separately captures self-shading state and other solver choices.

## 18. Orchestrator provenance

The main result records:

    orchestrator_id = opensimpv.beam_shading_snapshot
    orchestrator_version = 0.1

Physics provenance remains separately recorded in solver_manifest.

This distinguishes:

    factor orchestration version

from:

    direct-beam solver version

## 19. Beam solver manifest

The ShadingResult beam solver manifest records:

    solver ID/version
    Phase-5.3 numerical tolerances
    Shapely/GEOS runtime versions
    receiver_evaluation = full_polygon
    receiver count

sky_diffuse and ground slots are populated by explicit:

    model_id = none

entries.

Unimplemented physics is therefore visible in provenance.

## 20. Quality flags

Per-receiver records expose deterministic quality/status flags.

Current flags are:

    sun_below_horizon
    receiver_backside
    receiver_clear
    receiver_partially_shaded
    receiver_fully_shaded
    self_shading_disabled

Unsupported geometry remains an error rather than a quality flag.

## 21. Single-query equivalence

Phase 5.4 does not redefine beam physics.

For each receiver:

    snapshot beam_visibility_factor
    ==
    calculate_direct_beam_shadow(...) beam_visibility_factor

under identical geometry, sun state, self-shading configuration, and reference tolerances.

This equality is regression-tested.

## 22. Optional diagnostics

Detailed projected geometry is optional.

Normal mode:

    scalar ShadingResult only

Diagnostic mode:

    identical scalar ShadingResult
    +
    BeamShadowDiagnosticArtifact

Diagnostics do not alter the scalar result ID or payload hash.

## 23. Diagnostic authority

The diagnostic artifact is explicitly:

    authority = derived_diagnostic_only
    editable = false

It is not engineering source state and is not required for normal simulation.

## 24. Diagnostic content

The diagnostic artifact binds:

    shading result ID
    compiled geometry hash
    shading configuration hash
    receiver-set hash
    sun-state hash
    execution-plan ID when present
    orchestrator ID/version
    beam solver ID/version
    sun vector
    timestamp
    self-shading state
    receiver count

Per receiver it stores:

    receiver-plane basis
    receiver polygon in local u/v coordinates
    projected occluder-face polygons
    receiver-clipped shadow polygons
    clipped areas
    final union polygon/multipolygon
    contributing occluder IDs
    scalar factor/status

## 25. Diagnostic geometry uses the same solver path

The Phase-5.3 beam implementation gained an internal optional diagnostic collector.

Public helper:

    calculate_direct_beam_shadow_with_diagnostics(...)

runs the same calculation path as:

    calculate_direct_beam_shadow(...)

It does not contain a second projection or clipping implementation.

This is required so debug geometry cannot disagree with the scalar answer by construction.

## 26. Canonical diagnostic polygon serialization

Diagnostic 2-D polygon rings are serialized deterministically:

- closing duplicate coordinates are removed;
- ring start is rotated to a deterministic lexicographic origin;
- polygons are normalized through the same planar geometry engine;
- multipolygon components are sorted canonically.

This makes the optional diagnostic artifact hashable and reproducible within the frozen solver/geometry-engine runtime.

## 27. Diagnostic artifact identity

The artifact records:

    diagnostic_payload_sha256
    diagnostic_artifact_id

with:

    beam-diagnostic:<hash-prefix>

The diagnostic payload hash is independent of the scalar result payload hash.

## 28. R4 / VC5 integration

Phase 5.4 uses the existing Phase-4.9C R4 scene, which reconstructs the frozen Phase-4.9B VC5 geometry:

    12 support surfaces
    12 PV fields
    216 modules
    12 strings
    1 inverter
    2 obstacles
    tilt 20°
    azimuth 0°

This is an integration test, not a solver-definition source.

## 29. R4 execution chain

The R4 test executes:

    canonical R4 Scene
    -> compile_shading_geometry()
    -> build_simulation_execution_plan()
    -> 216 execution-group receiver IDs
    -> evaluate_beam_shading_snapshot()

The execution plan remains:

    homogeneous_single_group

for this reference design.

## 30. R4 selected sun states

The integration test evaluates explicit north and south sun states selected to exercise the two-obstacle geometry.

Self-shading is disabled for this test so the observed spatial factor pattern isolates canonical obstacle geometry.

The test requires:

- 216 receiver records;
- deterministic repeat of the same snapshot;
- nonuniform beam factors;
- at least one clear and one shaded receiver;
- different shaded receiver sets for opposite directional sun states.

No PVsyst factor target is used.

## 31. R4 is not a calibration target

Phase 5.4 does not modify:

    solar position
    module geometry
    obstacle geometry
    projection equations
    numerical tolerances
    receiver dimensions

to improve PVsyst agreement.

PVsyst remains a later external oracle.

Analytical Phase-5.3 geometry remains primary truth for the beam kernel.

## 32. ShadingResult schema extension

The existing ShadingResult v0.1 schema is extended compatibly with optional snapshot provenance fields:

    orchestrator_manifest
    receiver_set_sha256
    sun_state_sha256
    source_execution_plan_id
    result_payload_sha256

Existing Phase-5.0 example artifacts remain valid.

## 33. Machine-readable diagnostic schema

New schema:

    geometry/shading/beam-shadow-diagnostic-artifact.schema.json

This schema is separate from ShadingResult by design.

## 34. Validation coverage

Phase-5.4 tests verify:

1. stable receiver ordering;
2. duplicate receiver normalization;
3. timestamp UTC normalization;
4. correct beam-only ShadingResult channel;
5. null diffuse and ground factors;
6. explicit electrical_shading_scope = not_modeled;
7. quality flags;
8. exact equivalence to Phase-5.3 single-query results;
9. diagnostic mode leaves scalar result unchanged;
10. diagnostic artifact schema validity;
11. execution-group receiver selection;
12. execution-plan/compiled-geometry hash binding;
13. receiver-order-independent result identity;
14. normalized-sun-vector identity;
15. fail-closed diffuse request;
16. fail-closed ground request;
17. fail-closed angular-bin cache request;
18. fail-closed hidden model options;
19. fail-closed unsupported receiver subdivision;
20. R4 216-receiver execution-group integration;
21. R4 directional nonuniformity;
22. R4 repeated snapshot identity.

## 35. Deliberate non-goals

Phase 5.4 does not implement:

    annual/timeseries shading execution
    POA/effective irradiance integration
    diffuse sky obstruction
    ground obstruction
    spatial acceleration
    shadow caching
    electrical mismatch
    bypass-diode physics
    frontend shadow animation

## 36. Exit gate

Phase 5.4 is complete when:

    CompiledShadingGeometry
    + explicit receiver set
    + explicit sun state
    + explicit geometry-aware shading configuration
        -> deterministic schema-valid ShadingResult

with:

    single-query equivalence proven
    execution-group receiver selection proven
    result identity stable
    diagnostics optional and separate
    R4 selected-sun factor vectors reproducible and spatially nonuniform

After closure:

    -------- PHASE 5.4 RECEIVER BEAM FACTOR ORCHESTRATION STABLE --------

The next tranche may integrate the beam factors into the numerical irradiance chain as a beam-only vertical slice without redefining the Phase-5.3 geometry equations.
