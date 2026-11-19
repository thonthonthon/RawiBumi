# OpenSIMPV — Phase 5.5 Beam-Only Vertical Simulation Slice v0.1

**Status:** Phase-5.5 implementation anchor  
**Date:** 24 September 2026  
**Scope:** direct-beam near-shading integrated into the existing homogeneous fixed-tilt SimulationRun chain  
**Diffuse obstruction:** not modeled  
**Ground obstruction:** not modeled  
**Electrical shading mismatch:** not modeled  
**Multi-group annual execution:** not modeled

## 1. Objective

Phase 5.5 connects the Phase-5 geometry stack to the existing numerical PV simulation chain.

The executable path is:

    canonical weather
    -> canonical temporal execution
    -> NREL SPA solar position
    -> irradiance completion
    -> unshaded POA transposition
    -> module receiver beam visibility
    -> execution-group area-weighted beam visibility
    -> beam-only POA modification
    -> IAM
    -> thermal/module coupling
    -> string / MPPT / inverter
    -> PCC

This is the first OpenSIMPV SimulationRun in which canonical physical scene geometry materially changes simulated energy.

## 2. Supported execution boundary

Phase 5.5 initially supports:

    one enabled inverter
    homogeneous_single_group execution plan
    module receiver granularity
    beam_method = opensimpv.beam_shadow.polygon_projection
    diffuse_method = none
    ground obstruction = none
    cache policy = none or exact
    full receiver polygons
    no electrical shading method

The existing multi-group and same-MPPT heterogeneous blockers remain in force.

## 3. Historical reference behavior

Historical Phase-4.9C R4 configuration uses:

    pvsyst_shd_reference

That configuration remains non-executable and continues to fail explicitly through the historical shading-scope blocker.

Phase 5.5 does not reinterpret an external oracle label as an internal solver.

A new explicit geometry-aware Phase-5 configuration is required for execution.

## 4. Common fixed-tilt worker

The existing Phase-3 fixed-tilt numerical chain was not duplicated.

engine/simulation/unshaded.py now has an internal common fixed-tilt path with one optional typed POA postprocessor inserted after POA transposition and before IAM.

Public unshaded execution continues to call this path with no POA postprocessor.

Phase-5.5 geometry-aware execution supplies the beam-only postprocessor.

## 5. Irradiance-stage insertion point

The binding order is:

    POA transposition
    -> near-shading beam modifier
    -> IAM

This order is deliberate.

The geometric visibility factor acts on physical direct irradiance before optical incidence-angle modification.

IAM is not double-applied and is not moved upstream into geometry.

## 6. Beam-only POA modifier

Implementation:

    engine/irradiance/shading.py

Model ID:

    opensimpv.poa_near_shading.beam_only
    version 0.1

For each timestep:

    POA_beam_shaded
    =
    POA_beam_unshaded
    ×
    execution_group_beam_visibility

Sky diffuse and ground-reflected POA are preserved unchanged.

## 7. Reconciled irradiance channels

The geometry-aware timeseries exposes:

    poa_beam_unshaded_w_m2
    beam_visibility_factor_group
    poa_beam_shaded_w_m2
    near_shading_beam_loss_w_m2
    poa_global_unshaded_w_m2
    poa_beam_w_m2
    poa_sky_diffuse_w_m2
    poa_ground_diffuse_w_m2
    poa_global_w_m2

The required identities are:

    poa_beam_unshaded
    =
    poa_beam_shaded
    +
    near_shading_beam_loss

and:

    poa_global_after_near_shading
    =
    poa_beam_shaded
    +
    poa_sky_diffuse
    +
    poa_ground_diffuse

## 8. Diffuse and ground preservation

Phase 5.5 never applies beam visibility to:

    poa_sky_diffuse_w_m2
    poa_ground_diffuse_w_m2

The beam-only modifier asserts these channels remain unchanged.

Diffuse sky obstruction and ground-view obstruction belong to later tranches.

## 9. Solar-direction source

The shading sun vector is derived from the canonical solar-position result at every simulation evaluation time.

Inputs:

    solar_azimuth_deg
    solar_apparent_elevation_deg

Conversion:

    sun_vector_from_azimuth_elevation(...)

The apparent elevation is used so the geometric direction is aligned with the solar state used by the existing POA incidence calculation.

No hand-picked sun vector is injected into SimulationRun.

## 10. Receiver-level geometry

For every simulation interval, Phase 5.5 evaluates the Phase-5.4 receiver-set snapshot using:

    CompiledShadingGeometry
    SimulationExecutionGroupPlan receiver IDs
    canonical sun vector
    active self_shading_enabled state

Module-level geometric factors remain the source data.

## 11. Electrical approximation boundary

The current electrical backend remains homogeneous.

Therefore module-level beam factors are reduced to one execution-group factor by:

    group_visibility
    =
    sum(receiver_area × receiver_visibility)
    /
    sum(receiver_area)

Method ID:

    beam_visibility.execution_group_area_weighted_mean.v0.1

This is an explicit electrical-execution approximation, not detailed electrical shading physics.

## 12. Why area weighting

Compiled receiver area is used rather than a plain arithmetic mean so the aggregation remains correct if module receiver areas are not all identical.

For equal module areas the result equals the arithmetic module mean.

## 13. Approximation disclosure

Every geometry-aware canonical run records a warning-level SimulationAssumption:

    phase55_beam_visibility_area_weighted_electrical_approximation

It states that module-level geometric visibility is collapsed to one homogeneous execution-group beam modifier and electrical mismatch is not modeled.

## 14. Module-level factor preservation

The group factor does not replace the underlying receiver vector.

The full long-form receiver factor dataset is persisted separately as:

    shading-receiver-factors.parquet

with columns including:

    interval_start
    evaluation_time
    receiver_id
    receiver_area_m2
    beam_visibility_factor
    quality_flags_json
    shading_result_id

The SimulationRun and ReproducibilityManifest both reference this dataset.

## 15. Receiver-factor provenance

The factor dataset reference records:

    file SHA-256
    logical-content SHA-256
    row count
    columns
    Parquet engine/version

The run model manifest also records the receiver-factor logical hash.

## 16. Snapshot provenance compaction

Per-timestep Phase-5.4 snapshot objects are not copied wholesale into the annual model manifest.

Instead the geometry-aware runtime records:

    snapshot_count
    snapshot_manifest_sha256

while the full receiver-factor values remain in the separate dataset.

This avoids an unnecessarily large JSON manifest.

## 17. Geometry and execution provenance

The geometry-aware runtime records:

    compiled geometry hash
    execution plan ID
    execution plan payload SHA-256
    execution group ID
    receiver set SHA-256
    receiver count
    total receiver area
    aggregation method ID
    solar-direction source
    electrical_shading_scope = not_modeled

## 18. Performance-ratio denominator

For geometry-aware runs, IEC-style performance ratio continues to use the incident unshaded POA reference irradiation.

Therefore the KPI denominator uses:

    poa_global_unshaded_kwh_m2

when available.

This ensures geometric near-shading remains a performance loss rather than disappearing from the PR denominator.

Legacy unshaded runs continue to use:

    poa_global_kwh_m2

which is numerically the same as the unshaded incident POA.

## 19. Shading electrical-energy summary

SummaryResult already allows:

    shading_energy_loss_wh = null

Phase 5.5 uses null for geometry-aware runs because a separate electrical-energy shading loss requires a counterfactual no-shading electrical simulation.

The engine does not fabricate an electrical Wh loss from irradiance loss.

Unshaded runs retain:

    shading_energy_loss_wh = 0

## 20. Standard timeseries

The standard result surface now passes through the new beam-shading irradiance channels when present.

Legacy unshaded runs do not gain synthetic zero-valued shading columns.

This preserves prior numerical/result behavior for R1-R3 legacy configurations.

## 21. Canonical shading execution modes

The canonical runtime now distinguishes:

    unshaded
    beam_only_geometry

Beam-only geometry execution is accepted only when the complete Phase-5 geometry-aware contract is explicit and executable.

Unsupported requested shading physics fails before numerical execution.

## 22. Explicit unsupported cases

The beam-only canonical path blocks:

    diffuse_method other than none
    ground/albedo obstruction method
    receiver granularity other than module
    angular-bin cache mode
    receiver subdivision other than 1×1
    occluder chord-tolerance approximation
    hidden/non-empty model_options
    unresolved module receivers
    multiple execution groups
    same-MPPT heterogeneous execution groups

## 23. No hidden ground-shading semantics

albedo_method = none in the Phase-5 shading configuration means:

    no geometric ground obstruction model

It does not remove ordinary ground-reflected irradiance from POA transposition.

The existing numerical albedo still produces ground-reflected POA.

That contribution is simply left unshaded in Phase 5.5.

## 24. Test-only beam-bearing weather

The historical Phase-4.9C weather has DNI = 0 and therefore cannot test beam-energy propagation.

Phase 5.5 creates a separate synthetic test-only weather revision with:

    nonzero DNI
    physically reconciled GHI/DHI/DNI
    existing R4 site coordinates
    opensimpv_derived provenance
    synthetic upstream_generation metadata

The frozen Phase-4.9C weather is not modified.

## 25. Clear-scene regression

R1 is rerun with the beam-bearing test weather in two modes:

    legacy unshaded
    geometry-aware beam-only

Because the scene has no eligible obstacle shading and module self-shading is disabled:

    group visibility = 1
    beam shading loss = 0

The two paths must reproduce the same:

    POA beam
    effective irradiance
    PCC power

within explicit numerical tolerance.

## 26. R4 vertical integration

The exact canonical R4/VC5 geometry is rerun with the beam-bearing test weather.

Acceptance requires:

    module receiver factor rows = 216 × timestep count
    at least one group visibility < 1
    positive near_shading_beam_loss
    sky diffuse unchanged
    ground diffuse unchanged
    beam algebra reconciled
    group factor equals area-weighted receiver vector
    PCC energy lower than the unshaded counterfactual

This is the first end-to-end energy-path use of near-shading geometry.

## 27. Historical R4 remains external-oracle-only

The original R4 SimulationConfiguration with pvsyst_shd_reference must still fail.

This verifies that Phase 5.5 added a new explicit solver path rather than changing historical reference semantics.

## 28. R5 boundary

R5 remains outside current annual numerical scope because it resolves to multiple execution groups.

Phase 5.5 does not combine multi-group annual execution with beam integration.

The Phase-5.2 blocker remains authoritative.

## 29. Electrical physics not claimed

Phase 5.5 does not model:

    per-module IV under spatial shading
    per-string irradiance heterogeneity
    bypass diode conduction
    substring shading
    parallel string mismatch
    same-MPPT heterogeneous operating point
    shaded module IV reconstruction

These remain Phase 6.

## 30. External PVsyst comparison

Phase 5.5 does not use final R4 energy as a PVsyst acceptance target.

The model still lacks:

    diffuse obstruction
    ground obstruction
    circumsolar-specific geometric treatment
    electrical mismatch

PVsyst remains a later decomposed external validation oracle.

## 31. Exit gate

Phase 5.5 is complete when:

    canonical solar state
    -> module geometric beam factors
    -> explicit area-weighted execution-group factor
    -> beam-only POA modification
    -> existing IAM/thermal/electrical chain
    -> PCC energy

with:

    R1 clear case equal to unshaded
    R4 positive beam loss and lower energy
    diffuse/ground unchanged
    POA ledger reconciled
    receiver vector persisted separately
    approximation/provenance explicit
    historical R4 reference still blocked
    prior regressions green

After closure:

    -------- PHASE 5.5 BEAM-ONLY VERTICAL SIMULATION STABLE --------

The next planned tranche is Phase 5.6 — Diffuse Sky Obstruction.
