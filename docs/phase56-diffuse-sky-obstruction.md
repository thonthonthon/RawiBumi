# OpenSIMPV — Phase 5.6 Diffuse Sky Obstruction v0.1

**Status:** Phase-5.6 implementation anchor  
**Date:** 24 September 2026  
**Scope:** geometry-aware isotropic/circumsolar/horizon sky-diffuse obstruction integrated into the existing homogeneous fixed-tilt SimulationRun  
**Beam shading:** inherited unchanged from Phase 5.5  
**Ground obstruction:** not modeled; Phase 5.7  
**Electrical mismatch:** not modeled; Phase 6  
**Multi-group annual execution:** not modeled

## 1. Objective

Phase 5.6 extends the first geometry-aware energy vertical slice from direct beam to sky diffuse while preserving the component decomposition already produced by the transposition engine.

The executable path becomes:

    canonical weather
    -> canonical solar position
    -> irradiance completion
    -> unshaded POA transposition with diffuse subcomponents
    -> direct-beam geometry
    -> isotropic-sky geometry
    -> circumsolar directional geometry
    -> horizon-band geometry
    -> component-level POA reconstruction
    -> IAM
    -> thermal / module / string / MPPT / inverter
    -> PCC

Ground-reflected POA remains geometrically unobstructed.

## 2. Why Phase 5.6 is component-aware

OpenSIMPV POA transposition already exposes:

    poa_isotropic_w_m2
    poa_circumsolar_w_m2
    poa_horizon_w_m2

These reconcile to:

    poa_sky_diffuse_w_m2

The optical layer also treats these differently:

    circumsolar -> direct-beam IAM at solar AOI
    isotropic -> sky diffuse IAM
    horizon -> horizon diffuse IAM

Therefore one generic scalar sky factor would discard physically relevant information and would be especially inappropriate for Perez-family transposition.

## 3. Sky solver identity

Reference solver:

    opensimpv.sky_visibility.weighted_dome
    version 0.1

Implementation:

    geometry/shading/sky.py

The result contract is:

    geometry/shading/sky-visibility-query-result.schema.json

## 4. Global sky dome

The isotropic diffuse solver discretizes the global upper hemisphere:

    elevation 0..90 deg
    azimuth 0..360 deg

The receiver is not assigned a receiver-local hemisphere. The global sky hemisphere is used, and receiver incidence enters through projected solid-angle weighting.

## 5. Equal-solid-angle elevation bands

Bands are uniform in:

    mu = sin(elevation)

For one patch:

    dOmega
    =
    delta_azimuth
    *
    (mu_high - mu_low)

This gives exactly equal solid angle for patches within a fixed dome resolution.

Patch center elevation is evaluated at the midpoint in mu.

## 6. Isotropic weighting

For one receiver and one sky patch:

    patch_weight
    =
    patch_solid_angle
    *
    max(0, receiver_normal dot patch_direction)

Only receiver-front-facing sky contributes.

The isotropic visibility factor is:

    sky_visibility
    =
    sum(patch_weight * directional_visibility)
    /
    sum(patch_weight)

This reproduces the geometric projected-solid-angle response of an isotropic sky.

For an unobstructed horizontal receiver:

    denominator = pi

For a tilted receiver the denominator corresponds to the unobstructed isotropic view factor of the global sky.

## 7. Directional visibility kernel reuse

Each front-facing sky patch uses the existing Phase-5.3 polygon-projection kernel:

    calculate_direct_beam_shadow(...)

The returned beam visibility is interpreted only as directional geometric visibility along the supplied direction.

This deliberately avoids introducing a second independent occlusion/ray engine.

All existing engineering semantics therefore continue to apply:

    shading_enabled controls physics
    UI visible does not
    receiver never self-occludes
    module occlusion obeys self_shading_enabled
    disabled occluders do not participate

## 8. Finite receiver semantics

Directional visibility is calculated over the full receiver polygon.

It is not a single center-point ray.

Therefore the sky visibility integral is area-aware at every sampled direction before the receiver factors are later aggregated to the homogeneous electrical group.

## 9. Horizon visibility

Perez-family transposition exposes a separate horizon component.

Phase 5.6 therefore uses a separately configured low-elevation dome:

    elevation 0..horizon_band_elevation_deg

with its own:

    horizon_azimuth_sectors
    horizon_elevation_bands

The same projected-solid-angle weighting is used within that band.

The resulting factor is:

    horizon_visibility_factor

It is not derived from the full-sky scalar.

## 10. Circumsolar visibility

Circumsolar diffuse is concentrated around the solar direction and the existing optical layer already applies direct-beam IAM to it.

Phase 5.6 therefore uses:

    circumsolar_visibility
    =
    current sun-direction receiver beam visibility

This means beam and circumsolar use the same geometric line of sight at a given solar state while remaining separate irradiance channels.

## 11. Signed Perez horizon policy

Perez horizon terms are empirical directional corrections and may be negative.

Phase 5.6 does not relabel them as strictly positive physical radiance.

Policy:

    linear_scale_signed_perez_horizon_component

Therefore:

    horizon_shaded
    =
    horizon_unshaded
    *
    horizon_visibility

and:

    horizon_delta
    =
    horizon_unshaded
    -
    horizon_shaded

The delta may be negative when reducing obstruction makes a negative empirical correction less negative.

The engine must not clamp this signed term merely to force a conventional positive loss label.

## 12. Explicit sky resolution contract

When:

    diffuse_method = opensimpv.sky_visibility.weighted_dome

SimulationConfiguration must include:

    sky_dome_resolution:
        azimuth_sectors
        elevation_bands
        horizon_azimuth_sectors
        horizon_elevation_bands
        horizon_band_elevation_deg

No fidelity-level default silently chooses these values.

Resolution participates in the simulation configuration hash and reproducibility record.

## 13. Static sky snapshot

Isotropic and horizon geometry do not depend on weather or current sun position for a fixed scene.

Phase 5.6 computes them once per receiver set per run using:

    evaluate_sky_shading_snapshot(...)

Implementation:

    geometry/shading/sky_snapshot.py

The static ShadingResult channels are:

    sky_visibility
    directional_diffuse_visibility

with:

    directional_diffuse_visibility.horizon

Circumsolar remains time-dependent and is supplied by the beam snapshot sequence.

## 14. Sky ShadingResult provenance

The sky ShadingResult records:

    source Scene revision
    compiled geometry hash
    shading configuration hash
    receiver-set hash
    execution-plan ID
    solver ID/version
    sky/horizon resolution
    weighting method
    directional visibility kernel ID/version
    directional evaluation count
    approximation manifest

The finite dome is explicitly identified as an approximation:

    phase56_discrete_weighted_sky_dome

## 15. Exact clear-sky fast path

When a receiver has no eligible occluders after applying engineering participation rules:

    sky_visibility = 1
    horizon_visibility = 1

without calling the directional beam kernel for each patch.

This is an exact geometry result, not a reduced-quality approximation.

## 16. POA diffuse modifier

Implementation:

    engine/irradiance/shading.py

Model ID:

    opensimpv.poa_near_shading.component_diffuse
    version 0.1

Inputs:

    sky_visibility_factor
    circumsolar_visibility_factor
    horizon_visibility_factor

Operation:

    isotropic_shaded
    =
    isotropic_unshaded * sky_visibility

    circumsolar_shaded
    =
    circumsolar_unshaded * circumsolar_visibility

    horizon_shaded
    =
    horizon_unshaded * horizon_visibility

Then:

    sky_diffuse_shaded
    =
    isotropic_shaded
    +
    circumsolar_shaded
    +
    horizon_shaded

## 17. Ground and beam preservation

The diffuse modifier asserts:

    direct beam before = direct beam after
    ground reflected before = ground reflected after

Phase 5.6 therefore cannot silently alter Phase-5.5 beam physics or Phase-5.7 ground physics.

## 18. New diffuse result channels

Geometry-aware standard time series can expose:

    poa_sky_diffuse_unshaded_w_m2
    sky_visibility_factor_group
    circumsolar_visibility_factor_group
    horizon_visibility_factor_group

    poa_isotropic_unshaded_w_m2
    poa_isotropic_shaded_w_m2
    near_shading_isotropic_loss_w_m2

    poa_circumsolar_unshaded_w_m2
    poa_circumsolar_shaded_w_m2
    near_shading_circumsolar_loss_w_m2

    poa_horizon_unshaded_w_m2
    poa_horizon_shaded_w_m2
    near_shading_horizon_delta_w_m2

    poa_sky_diffuse_shaded_w_m2
    near_shading_sky_diffuse_loss_w_m2

The existing Phase-5.5 beam channels remain.

## 19. Diffuse reconciliation

Required:

    isotropic_shaded
    +
    circumsolar_shaded
    +
    horizon_shaded
    =
    sky_diffuse_shaded

and:

    beam_shaded
    +
    sky_diffuse_shaded
    +
    ground_unobstructed
    =
    poa_global_after_near_shading

The signed horizon policy means total sky-diffuse delta is not asserted non-negative interval-by-interval.

## 20. Homogeneous electrical aggregation

Static module receiver sky and horizon factors are reduced to group factors using the same explicit receiver-area weighting pattern as Phase 5.5:

    group_component_visibility
    =
    sum(receiver_area * receiver_component_visibility)
    /
    sum(receiver_area)

Method ID:

    diffuse_visibility.execution_group_area_weighted_mean.v0.1

Circumsolar group visibility uses the corresponding current-sun area-weighted beam visibility.

## 21. Receiver-factor persistence

The Phase-5.5 receiver factor dataset is extended rather than replaced.

For sky-aware runs it additionally retains:

    sky_visibility_factor
    circumsolar_visibility_factor
    horizon_visibility_factor
    sky_shading_result_id

This preserves the spatial geometric state required for later Phase-6 electrical mismatch modeling.

## 22. Canonical execution mode

New execution state:

    beam_sky_geometry

Execution scope:

    fixed_tilt_beam_sky_shaded_homogeneous_single_inverter.v0.1

Beam-only Phase-5.5 execution remains:

    beam_only_geometry
    fixed_tilt_beam_shaded_homogeneous_single_inverter.v0.1

The old route is not redefined.

## 23. Canonical support boundary

Phase 5.6 requires:

    beam_method = opensimpv.beam_shadow.polygon_projection
    diffuse_method = opensimpv.sky_visibility.weighted_dome
    albedo_method = null or none
    receiver_granularity = module
    cache mode = none or exact
    receiver subdivision = 1 x 1
    no chord-tolerance approximation
    model_options = {}
    explicit sky_dome_resolution
    homogeneous_single_group
    all active module receivers resolved

Unsupported requests fail before numerical execution.

## 24. Historical references

The historical:

    pvsyst_shd_reference

configuration remains an external reference label and remains blocked.

Phase 5.6 does not reinterpret it as the OpenSIMPV sky solver.

## 25. Electrical approximation disclosure

Sky-aware runs retain the Phase-5.5 beam aggregation limitation and add:

    phase56_component_diffuse_geometry_approximation

The assumption discloses:

    finite explicit sky-dome integration
    receiver-to-group area weighting
    circumsolar reuse of sun-direction visibility
    signed horizon scaling
    no ground obstruction
    no electrical mismatch

## 26. Analytical validation

Phase-5.6 reference tests include:

    full sky solid angle = 2*pi
    horizon dome solid angle = 2*pi*sin(horizon_limit)
    open horizontal receiver projected sky weight = pi
    open sky visibility = 1
    fully blocked discrete dome visibility = 0
    disabled occluder has no effect
    receiver cannot self-occlude
    module occluder follows self_shading_enabled
    symmetric half-azimuth mask visibility = 0.5
    occluder input reorder is deterministic
    ShadingResult validates

The half-sky mask uses an exact symmetric weighting oracle rather than an external program.

## 27. POA component validation

A dedicated test includes a negative horizon correction and proves:

    component factors applied independently
    beam unchanged
    ground unchanged
    sky subcomponents reconcile
    global POA reconciles
    signed horizon delta is retained

## 28. R1 clear-scene regression

R1 is executed as:

    Phase-5.5 beam-only
    Phase-5.6 beam + sky

with the same beam-bearing test weather.

With no eligible sky obstruction:

    sky factor = 1
    horizon factor = 1
    circumsolar factor = 1
    diffuse geometry loss = 0

Phase-5.6 must reproduce Phase-5.5:

    beam channels
    ground POA
    effective irradiance
    PCC power

within explicit tolerances.

## 29. R4 integration

Exact R4 canonical geometry is executed in:

    Phase-5.5 beam-only mode
    Phase-5.6 beam + sky mode

Acceptance requires:

    Phase-5.5 beam channels unchanged
    ground-reflected POA unchanged
    sky/horizon visibility within [0,1]
    at least one actual sky/horizon obstruction
    circumsolar visibility exactly follows beam visibility
    diffuse subcomponents reconcile
    at least one positive isotropic or circumsolar obstruction loss
    receiver sky factors retained
    PCC energy does not exceed beam-only counterfactual

A signed horizon correction is allowed to create a signed local delta.

## 30. Non-goals

Phase 5.6 does not implement:

    ground-view obstruction
    bifacial rear irradiance
    electrical substring/bypass physics
    per-module IV under spatial shading
    multi-group annual numerical execution
    angular-bin acceleration
    mesh/BVH optimization
    PVsyst result fitting

## 31. Exit gate

Phase 5.6 is complete when:

    CompiledShadingGeometry
    -> deterministic weighted sky/horizon receiver visibility
    -> current-sun circumsolar directional visibility
    -> explicit area-weighted execution-group component factors
    -> component-level diffuse POA modification
    -> unchanged direct-beam and ground channels
    -> existing IAM/thermal/electrical chain
    -> PCC

with analytical tests, R1 no-loss equivalence, R4 independent diffuse obstruction, complete provenance, and full repository CI green.

After closure:

    -------- PHASE 5.6 DIFFUSE SKY OBSTRUCTION STABLE --------

The next planned tranche is Phase 5.7 — Ground / Albedo Obstruction.
