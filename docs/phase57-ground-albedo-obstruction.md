# OpenSIMPV — Phase 5.7 Ground / Albedo Obstruction v0.1

**Status:** Phase-5.7 implementation anchor  
**Date:** 24 September 2026  
**Scope:** receiver-side obstruction of the existing uniform ground/albedo-reflected POA channel  
**Beam shading:** inherited unchanged from Phase 5.5  
**Sky diffuse shading:** inherited unchanged from Phase 5.6  
**Ground illumination maps:** not modeled  
**Bifacial rear irradiance:** not modeled  
**Electrical mismatch:** not modeled

## 1. Objective

Phase 5.7 completes the three geometry-aware front-side irradiance channels available in the current fixed-tilt transposition model:

    direct beam
    sky diffuse
    ground/albedo reflected

The new ground model changes only receiver-side visibility of the existing scalar-albedo ground-reflected POA term.

It does not model spatial variation of irradiance incident on the ground.

## 2. Two ground problems remain distinct

Receiver-side obstruction:

    uniform reflected ground source
    -> receiver lower-hemisphere visibility
    -> ground-reflected POA modifier

Ground-illumination shadowing:

    sun/sky
    -> spatial ground irradiance
    -> scene shadow map
    -> reflected radiance field
    -> receiver

Only the first is Phase 5.7.

## 3. Generic directional visibility kernel

Implementation:

    geometry/shading/directional.py

Solver:

    opensimpv.directional_visibility.polygon_projection
    version 0.1

This kernel uses the same frozen receiver-plane, face clipping, projection, receiver clipping, polygon union, and self-shading semantics as the Phase-5.3 beam kernel.

It intentionally contains no global sun-above-horizon rule.

## 4. Beam API remains frozen

The existing public beam solver remains unchanged:

    calculate_direct_beam_shadow(...)

It still returns:

    no_direct_beam_sun_below_horizon

for solar vectors at/below the global horizon.

Ground directions are not passed through that solar wrapper.

This preserves Phase-5.3 semantics while enabling valid lower-hemisphere source directions.

## 5. Ground reference solver

Implementation:

    geometry/shading/ground.py

Solver:

    opensimpv.ground_visibility.weighted_dome
    version 0.1

Result contract:

    geometry/shading/ground-visibility-query-result.schema.json

## 6. Lower-hemisphere discretization

The global lower hemisphere is discretized by:

    azimuth sectors
    depression bands

with bands uniform in:

    mu = sin(depression)

For a patch:

    dOmega
    =
    delta_azimuth
    *
    (mu_high - mu_low)

Patch elevation is negative:

    elevation = -depression

## 7. Ground weighting

For one receiver and one lower-hemisphere patch:

    ground_patch_weight
    =
    patch_solid_angle
    *
    max(0, receiver_normal dot ground_direction)

Then:

    ground_visibility
    =
    sum(weight * directional_visibility)
    /
    sum(weight)

for receivers with nonzero front-side ground view.

## 8. Analytical unobstructed view factor

For an unobstructed front surface tilted by beta from horizontal, the continuous projected lower-hemisphere integral is:

    denominator
    =
    pi * (1 - cos(beta)) / 2

Equivalent normalized isotropic ground view factor:

    F_ground
    =
    (1 - cos(beta)) / 2

This is used as an analytical convergence reference.

## 9. Zero projected ground view

For a horizontal upward-facing front surface:

    beta = 0
    projected ground denominator = 0

The geometric visibility factor is returned as neutral:

    ground_visibility = 1

with:

    has_front_ground_view = false

This avoids division by zero and is physically harmless because the conventional front-side ground-reflected POA term is zero at zero tilt.

## 10. Occluder semantics

Ground directional queries preserve existing engineering rules:

    shading_enabled controls physics
    UI visible does not

    receiver never self-occludes

    module occluders obey self_shading_enabled

    disabled occluders do not participate

No support Surface is silently promoted to a ground occluder.

## 11. Ground source is not canonical geometry

The lower dome represents the directional support of the existing uniform Lambertian scalar-albedo ground-reflected POA model.

It does not create editable ground geometry or a second scene authority.

Canonical Scene remains authoritative.

## 12. Ground resolution contract

When:

    albedo_method
    =
    opensimpv.ground_visibility.weighted_dome

ShadingConfiguration must include:

    ground_dome_resolution:
        azimuth_sectors
        depression_bands

No fidelity-level default silently selects these values.

## 13. Albedo remains separate from visibility

Numerical albedo remains resolved by the execution group from canonical support-surface / numerical-option semantics.

Phase 5.7 does not replace it with the ground solver ID and does not fit:

    albedo * visibility

as one combined coefficient.

The separate concepts are:

    albedo = source reflectance/input
    ground_visibility = geometric transfer factor

## 14. Static ground snapshot

Implementation:

    geometry/shading/ground_snapshot.py

Orchestrator:

    opensimpv.ground_shading_snapshot
    version 0.1

Ground receiver visibility is static for fixed geometry and ground-dome resolution.

It is evaluated once per receiver set per run.

## 15. Ground ShadingResult

The existing Phase-5 contract is used with:

    channels = ["ground_visibility"]

Per receiver:

    ground_visibility_factor

is populated.

Beam and sky factors are null in the static ground-only snapshot.

## 16. Ground approximation manifest

Ground snapshots record:

    phase57_uniform_lambertian_ground_view

This explicitly states that:

    existing scalar-albedo ground-reflected POA
    is modified only by receiver-side visibility

while:

    spatial ground irradiance
    bifacial rear irradiance

are not modeled.

## 17. Ground POA modifier

Implementation:

    engine/irradiance/shading.py

Model:

    opensimpv.poa_near_shading.ground_visibility
    version 0.1

Operation:

    poa_ground_diffuse_shaded
    =
    poa_ground_diffuse_unshaded
    *
    ground_visibility_factor

## 18. Preserved channels

The ground modifier asserts that it does not change:

    poa_beam_w_m2
    poa_sky_diffuse_w_m2
    poa_isotropic_w_m2
    poa_circumsolar_w_m2
    poa_horizon_w_m2

Thus beam, sky, circumsolar, and horizon results remain frozen from earlier phases.

## 19. Ground output channels

Geometry-aware results may expose:

    poa_ground_diffuse_unshaded_w_m2
    ground_visibility_factor_group
    poa_ground_diffuse_shaded_w_m2
    near_shading_ground_diffuse_loss_w_m2

The canonical ground component column:

    poa_ground_diffuse_w_m2

becomes the post-obstruction value before IAM.

## 20. POA reconciliation

After Phase 5.7:

    poa_global_w_m2
    =
    poa_beam_w_m2
    +
    poa_sky_diffuse_w_m2
    +
    poa_ground_diffuse_w_m2

and:

    poa_diffuse_w_m2
    =
    poa_sky_diffuse_w_m2
    +
    poa_ground_diffuse_w_m2

## 21. Homogeneous electrical aggregation

Receiver ground factors are reduced using:

    group_ground_visibility
    =
    sum(receiver_area * receiver_ground_visibility)
    /
    sum(receiver_area)

Method:

    ground_visibility.execution_group_area_weighted_mean.v0.1

This remains an explicit approximation of the current homogeneous electrical worker.

## 22. Receiver factor preservation

The existing receiver-factor dataset is extended with:

    ground_visibility_factor
    ground_shading_result_id

Receiver-level geometry therefore remains available for later higher-fidelity electrical models.

## 23. Canonical execution mode

New state:

    beam_sky_ground_geometry

Execution scope:

    fixed_tilt_beam_sky_ground_shaded_homogeneous_single_inverter.v0.1

It requires the full prior Phase-5.6 path:

    beam geometry
    +
    sky geometry
    +
    ground geometry

Phase-5.5 and Phase-5.6 modes remain separate and unchanged.

## 24. Current executable ground configuration

Required:

    beam_method
    =
    opensimpv.beam_shadow.polygon_projection

    diffuse_method
    =
    opensimpv.sky_visibility.weighted_dome

    albedo_method
    =
    opensimpv.ground_visibility.weighted_dome

    receiver_granularity
    =
    module

    cache_policy
    =
    none or exact

    receiver subdivision
    =
    1 x 1

    model_options
    =
    {}

    sky_dome_resolution
    =
    explicit

    ground_dome_resolution
    =
    explicit

    topology
    =
    homogeneous_single_group

## 25. Why albedo_method names the geometry worker

The compatibility-preserving Phase-5 shading block already owns beam, diffuse, and albedo/ground method selectors.

Phase 5.7 uses the existing:

    albedo_method

selector to activate ground-visibility geometry.

This does not redefine the numerical albedo value; numerical albedo remains a separate runtime input and provenance field.

## 26. Analytical tests

Phase-5.7 tests cover:

    lower hemisphere solid angle = 2*pi

    horizontal upward receiver
    -> zero projected front ground view

    vertical receiver
    -> projected ground integral converges to pi/2

    below-global-horizon direction
    -> valid generic directional visibility

    same direction through beam API
    -> no_direct_beam_sun_below_horizon

    fully blocked discrete front ground view
    -> visibility = 0

    disabled occluder
    -> no effect

    receiver
    -> no self-occlusion

    other module
    -> obeys self_shading_enabled

    symmetric half-ground mask
    -> visibility = 0.5

    occluder reorder
    -> deterministic

    ShadingResult schema
    -> valid

## 27. Direct-beam regression boundary

All pre-existing Phase-5.3 beam tests remain part of the full repository suite.

No parameter or status in:

    calculate_direct_beam_shadow(...)

is modified by Phase 5.7.

## 28. Ground POA unit test

A dedicated POA test verifies:

    only ground component changes
    beam is unchanged
    sky diffuse is unchanged
    isotropic is unchanged
    circumsolar is unchanged
    horizon is unchanged
    diffuse sum reconciles
    global POA reconciles

## 29. R1 regression

R1 is executed in:

    Phase 5.6 beam + sky
    Phase 5.7 beam + sky + ground

With no eligible ground-view obstruction:

    ground visibility = 1
    ground obstruction loss = 0

Phase 5.7 must reproduce Phase 5.6:

    beam channels
    sky channels
    ground POA
    global POA
    effective irradiance
    PCC power

within explicit tolerances.

## 30. R4 integration

R4 is executed in:

    Phase 5.6 beam + sky
    Phase 5.7 beam + sky + ground

Acceptance requires:

    beam channels unchanged
    sky channels unchanged
    ground factors within [0,1]
    unshaded ground reference preserved
    shaded ground <= unshaded ground
    total POA reconciliation
    receiver ground factors persisted
    PCC energy <= Phase-5.6 counterfactual

R4 is not forced to have a nonzero ground obstruction if its actual canonical geometry does not produce one at the configured resolution.

Controlled analytical scenes prove nonzero ground obstruction independently.

## 31. Runtime assumption

Ground-aware runs add:

    phase57_uniform_ground_view_geometry_approximation

The assumption discloses:

    receiver-side lower-hemisphere geometry
    uniform Lambertian scalar-albedo source
    receiver-area group aggregation
    no ground irradiance shadow map
    no bifacial rear irradiance
    no electrical mismatch

## 32. Non-goals

Phase 5.7 does not implement:

    spatial ground irradiance maps
    ground-source sun/sky shadowing
    spatial albedo maps
    bifacial rear irradiance
    rear-side module view factors
    electrical substring/bypass physics
    per-module shaded IV
    multi-group annual numerical execution
    hidden angular acceleration
    PVsyst energy fitting

## 33. Exit gate

Phase 5.7 is complete when:

    lower-hemisphere source directions
    -> generic finite-receiver visibility
    -> weighted receiver ground factor
    -> explicit area-weighted group factor
    -> ground-reflected POA modifier
    -> unchanged beam and sky channels
    -> IAM
    -> thermal/electrical chain
    -> PCC

with analytical lower-hemisphere tests, preserved Phase-5.3 beam semantics, R1 no-loss regression, R4 truthful integration, receiver-factor persistence, explicit approximation/provenance, and full repository CI green.

After closure:

    -------- PHASE 5.7 GROUND / ALBEDO OBSTRUCTION STABLE --------

The next planned tranche is Phase 5.8 — Annual Sampling / Cache / Measured Acceleration.
