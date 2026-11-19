# OpenSIMPV — Phase 5.8 Annual Sampling / Cache / Measured Acceleration v0.1

**Status:** Phase-5.8 implementation anchor  
**Date:** 24 September 2026  
**Scope:** exact annual shading acceleration, static cache provenance, and measured reference-vs-accelerated performance  
**Physics change:** none  
**Angular approximation:** not enabled  
**Electrical mismatch:** not modeled

## 1. Objective

Phase 5.8 improves the execution cost of the geometry-aware beam, sky, and
ground kernels without changing their physical equations.

The frozen Phase-5.3 through Phase-5.7 reference solvers remain available as
the numerical oracle.

The governing distinction is:

    exact acceleration
    !=
    approximate sampling

Phase 5.8 implements the former and keeps the latter fail-closed.

## 2. Measured hotspot hypothesis

Inspection of the reference path identified direction-independent work repeated
for every directional query:

    receiver lookup
    receiver plane basis construction
    receiver polygon construction
    receiver area/planarity validation
    full occluder-list participation filtering
    receiver-front half-space clipping of every eligible face

Only projection from source direction onward is intrinsically direction-dependent.

Phase 5.8 prepares the direction-independent state once per receiver.

## 3. Reference path remains executable

Configuration:

    cache_policy.mode = none

uses the original reference path.

The reference implementations remain:

    calculate_direct_beam_shadow
    calculate_directional_receiver_visibility
    calculate_sky_visibility
    calculate_ground_visibility

without requiring prepared state.

This path is retained as the correctness oracle.

## 4. Exact prepared path

Configuration:

    cache_policy.mode = exact

activates derived prepared query state.

Implementation:

    geometry/shading/prepared.py

Engine:

    opensimpv.directional_visibility.prepared_exact
    version 0.1

Prepared state contains:

    receiver origin
    receiver normal
    receiver u/v basis
    receiver Shapely polygon
    receiver area
    receiver planarity result
    self-shading participation state
    eligible occluder count
    receiver-front-clipped occluder faces

No sun/source direction is stored in the prepared geometry.

## 5. Exactness boundary

Prepared execution reuses the frozen:

    projection equation
    polygon creation
    receiver intersection
    polygon union
    area tolerance
    horizon tolerance
    incidence tolerance
    factor convention

The Phase-5.3 direct-beam statuses remain:

    evaluated
    no_direct_beam_sun_below_horizon
    no_direct_beam_receiver_backside

The Phase-5.7 generic directional statuses remain:

    evaluated
    source_behind_receiver

## 6. Why receiver-front face clipping can be prepared

For a valid front-side source direction:

    receiver_normal dot source_direction > 0

Any shadow-casting occluder geometry must lie in the receiver-front half-space.

Clipping polygon faces against that fixed receiver plane therefore does not
depend on source azimuth/elevation.

Projection from the resulting clipped face does depend on source direction and
remains per-query.

## 7. Self-shading remains identity input

Prepared state is keyed/built with explicit:

    self_shading_enabled

because module-plane occluder participation changes with that flag.

The receiver itself is always excluded.

## 8. Beam acceleration

Beam snapshots may receive a prepared receiver map.

For normal scalar execution:

    prepared map present
    -> exact prepared beam query

    prepared map absent
    -> Phase-5.3 reference beam query

Beam diagnostics remain on the reference path so Phase-5.3 diagnostic geometry
is not silently redefined by acceleration.

## 9. Sky acceleration

Phase-5.6 weighted sky integration keeps the same:

    sky patches
    horizon patches
    patch weights
    receiver cosine response

Only the directional geometric visibility query may use prepared receiver state.

## 10. Ground acceleration

Phase-5.7 lower-hemisphere integration keeps the same:

    ground patches
    depression-band definition
    patch weights
    receiver cosine response
    uniform Lambertian ground-source assumption

Only the directional geometric visibility query may use prepared receiver state.

## 11. Static sky/ground cache

Implementation:

    geometry/shading/cache.py

Cache:

    opensimpv.shading_cache.process_local_exact
    version 0.1

Sky and ground factors are static for fixed:

    compiled geometry
    receiver set
    self-shading state
    solver versions
    dome resolution
    configuration

They can therefore be cached exactly.

## 12. Cache storage model

The current implementation is:

    bounded
    process-local
    thread-safe
    LRU
    derived-only

Default capacity:

    256 entries

Values are deep-copied on storage and retrieval.

The cache is not canonical engineering state and is never authoritative.

## 13. Static cache channels

Phase 5.8 caches complete static ShadingResult payloads for:

    sky_visibility
    ground_visibility

Direct beam is not naively result-cached per sun vector.

## 14. Why annual beam results are not blindly cached

Typical annual solar evaluation timestamps produce many distinct sun vectors.

A direction-result cache with low reuse can consume memory without reducing
geometry work materially.

Phase 5.8 therefore accelerates annual beam execution by reusing prepared
receiver geometry across every canonical sun state.

Further beam-result caching requires measured evidence.

## 15. Cache identity

Static cache key binds:

    cache contract version
    channel
    compiled_geometry_hash
    shading_configuration_hash
    solver_manifest_hash
    receiver_set_sha256
    source_execution_plan_id

The execution-plan ID is included because the cached object is the complete
ShadingResult and its provenance contains source_execution_plan_id.

## 16. Physical invalidation basis

The cache manifest records invalidation on:

    source_scene_revision
    compiled_geometry_hash
    shading_configuration_hash
    solver_manifest_hash
    fidelity_level
    sampling_resolution
    receiver_set

The full shading configuration hash already binds:

    self_shading_enabled
    sky_dome_resolution
    ground_dome_resolution
    cache policy
    temporal resolution request
    method selections

## 17. Solver-version invalidation

The cache solver-manifest hash binds:

    beam solver ID/version
    generic directional solver ID/version
    sky solver ID/version
    ground solver ID/version
    prepared exact engine ID/version
    acceleration ID/version
    static cache ID/version

A solver-version change therefore cannot warm-hit old exact static results.

## 18. Existing ShadingCacheManifest activated

Phase 5.8 uses:

    geometry/shading/shading-cache-manifest.schema.json

rather than introducing a second cache-provenance contract.

Each static cache entry records:

    cache_key_sha256
    channel
    receiver_set_sha256
    sun_state_sha256 = null
    result_sha256
    entry_uri = null

The null sun state is deliberate because sky and ground visibility are static.

## 19. Cache mode semantics

    none
    =
    reference calculation, no static result reuse

    exact
    =
    prepared exact geometry + exact static sky/ground cache

    angular_bins
    =
    reserved explicit approximation, not executable in Phase 5.8

No mode is selected implicitly from fidelity_level.

## 20. Angular bins remain deferred

The Phase-5.0 configuration contract still defines:

    sun_azimuth_bin_deg
    sun_altitude_bin_deg

for angular_bins.

Phase 5.8 does not activate this approximation.

The exact acceleration context rejects angular_bins explicitly and canonical
runtime continues to fail closed on that mode.

## 21. Annual sun sampling policy

The current exact annual policy is:

    canonical_simulation_solar_evaluation_timestamps

Every simulation interval uses its canonical solar-evaluation timestamp.

No additional shading-time coarsening is applied.

## 22. sun_position_resolution_seconds contract correction

Before Phase 5.8, a positive:

    sun_position_resolution_seconds

was schema/contract-valid but not actually consumed by geometry-aware annual
execution.

Phase 5.8 closes that false-provenance gap.

Current executable rule:

    sun_position_resolution_seconds = null

A non-null value now produces blocking rule:

    SIMULATION_SCOPE_SUN_POSITION_RESOLUTION_NOT_EXECUTABLE

until an explicit temporal shading-sampling model exists.

## 23. Runtime provenance

Geometry-aware runtime metadata records:

    sun_sampling_policy
    sun_position_resolution_seconds
    shading_acceleration
    shading_cache_manifest

Acceleration metrics include:

    acceleration ID/version
    cache mode
    prepared query build count
    prepared receiver count
    prepared face count
    static cache hit count
    static cache miss count
    process-local cache entry count
    exact_physics = true
    angular_quantization = false

## 24. Reference-vs-exact oracle tests

Phase 5.8 adds exact equality tests for:

    direct beam
    generic directional visibility
    weighted sky visibility
    weighted ground visibility

The prepared result must equal the reference result, not merely fall within a
new looser physical tolerance.

## 25. Status-boundary tests

Beam parity covers:

    clear/front source
    oblique front source
    low front source
    global below-horizon sun
    receiver backside

Generic directional parity covers:

    upper hemisphere
    lower hemisphere
    receiver backside

Thus the exact acceleration cannot erase the Phase-5.3/5.7 semantic distinction.

## 26. Determinism tests

Prepared execution retains deterministic occluder ordering.

Reordering the input occluder collection must not change the exact result.

## 27. Static cache warm/cold test

The cache tests exercise:

    cold lookup -> miss
    compute/store
    identical context lookup -> hit

The returned ShadingResult logical payload is unchanged.

The resulting ShadingCacheManifest must validate against the existing schema.

## 28. Cache invalidation tests

Phase 5.8 explicitly tests misses after changes to:

    compiled geometry hash
    self_shading_enabled
    sky resolution
    source execution plan
    solver version

Receiver-set identity is independently hash-bound in the cache key/manifest.

## 29. cache_policy=none test

The none path must produce:

    no prepared receiver state
    no static cache lookup/storage
    empty cache manifest entries
    exact reference solver execution

This preserves a permanently available oracle path.

## 30. R4 runtime parity

The exact Phase-4.9B/4.9C R4 geometry is run twice through the canonical
Phase-5 beam vertical path:

    cache_policy.mode = none
    cache_policy.mode = exact

Acceptance:

    identical standard time-series columns
    identical numerical values
    identical receiver beam factors
    identical total PCC energy

Only acceleration/cache provenance and configuration identity may differ.

## 31. Measured benchmark harness

Implementation:

    tools/benchmark_phase58.py

The harness measures:

    synthetic high-irrelevant-module-count geometry
    R1
    R4

For every case it reports:

    receiver count
    direction count
    query count
    compiled occluder count
    reference seconds
    exact preparation seconds
    exact query seconds
    exact first-run total seconds
    query-only speedup
    first-run total speedup
    physics parity

## 32. Benchmark is not a flaky performance gate

CI acceptance is:

    physics parity = required

Timing thresholds are:

    not required for pass/fail

because shared CI hardware is noisy.

Measured timing remains engineering evidence and is captured from the validation
job output.

## 33. Synthetic benchmark purpose

The synthetic case contains many enabled module occluders while:

    self_shading_enabled = false

The reference solver must scan and reject them on every directional query.

The prepared exact path performs that participation filtering once.

This isolates a known source of annual-query overhead.

## 34. R1 benchmark purpose

R1 provides the canonical clear reference project.

It detects acceleration overhead on simple geometry and ensures the optimization
does not depend on obstruction being present.

## 35. R4 benchmark purpose

R4 provides the exact 216-module, two-obstacle VC5 geometry.

It measures the acceleration on a realistic canonical near-shading reference
scene rather than only on synthetic microbenchmarks.

## 36. CI integration

The validation workflow runs:

    python -m pytest -q

followed by:

    python tools/benchmark_phase58.py --quick

The benchmark fails CI only if exact and reference physics diverge.

## 37. DataFrame fragmentation warning boundary

The existing pandas fragmented-frame warnings remain outside the primary Phase-5.8
geometry optimization.

They may be addressed separately only with result-schema/hash invariance tests.

Phase 5.8 does not remove engineering channels to suppress warnings.

## 38. Non-goals

Phase 5.8 does not implement:

    angular-bin sun approximation
    temporal shading interpolation
    spatial ground irradiance
    bifacial rear irradiance
    electrical mismatch
    multi-group annual electrical execution
    GPU acceleration
    approximate BVH culling
    PVsyst fitting

## 39. Exit gate

Phase 5.8 is complete when:

    reference solvers remain executable

    cache_policy=exact uses prepared exact receiver geometry

    beam/sky/ground exact parity tests pass

    static sky/ground result cache is identity-safe

    ShadingCacheManifest is populated and schema-valid

    non-null unimplemented sun temporal coarsening fails closed

    R4 none-vs-exact canonical execution is numerically identical

    R1/R4/synthetic benchmark records measured timing with physics parity

    all Phase-5.3 through Phase-5.7 regressions remain green

    full repository CI is green

After closure:

    -------- PHASE 5.8 ANNUAL SAMPLING / CACHE / MEASURED ACCELERATION STABLE --------

The next planned tranche is Phase 5.9 — Full Geometry-Aware Annual SimulationRun.


## 40. Measured CI evidence — run #197

The first successful benchmark evidence was recorded by pull-request workflow:

    workflow run = 35998652768
    run number = 197
    job = schema-and-reference-tests

Repository correctness before the benchmark:

    558 passed
    155 warnings
    86.38 s

The suite includes an intentional canonical R4 reference-path run and exact-path
run, so total pytest wall time is not itself a production speedup benchmark.

## 41. Synthetic measured result

Case:

    synthetic_high_irrelevant_module_count

Configuration:

    receiver_count = 1
    compiled_occluder_count = 601
    direction_count = 48
    query_count = 48

Measured:

    reference = 0.012966 s
    exact preparation = 0.000299 s
    exact directional queries = 0.003391 s
    exact first-run total = 0.003689 s

Observed on this CI runner:

    query-only speedup = 3.82x
    first-run total speedup = 3.51x

Physics parity:

    true

This case isolates repeated rejection of module occluders when module
self-shading is disabled.

## 42. R1 measured result

Configuration:

    receiver_count = 18
    compiled_occluder_count = 18
    direction_count = 6
    query_count = 108

Measured:

    reference = 0.013808 s
    exact preparation = 0.001912 s
    exact directional queries = 0.001672 s
    exact first-run total = 0.003584 s

Observed on this CI runner:

    query-only speedup = 8.26x
    first-run total speedup = 3.85x

Physics parity:

    true

R1 demonstrates that exact preparation is beneficial even on the canonical clear
reference project.

## 43. R4 measured result

Configuration:

    receiver_count = 216
    compiled_occluder_count = 218
    direction_count = 6
    query_count = 1296

Measured:

    reference = 1.299797 s
    exact preparation = 0.070809 s
    exact directional queries = 0.862852 s
    exact first-run total = 0.933661 s

Observed on this CI runner:

    query-only speedup = 1.51x
    first-run total speedup = 1.39x

Physics parity:

    true

R4 is the most relevant benchmark because it uses the exact 216-module VC5
canonical reference geometry with the north/south obstacle pair.

The measured gain is meaningful but not exaggerated: the prepared path removes
repeated direction-independent work, while polygon projection/intersection/union
remain real per-direction costs.

## 44. Interpretation of measured speedups

These numbers are evidence for this runner and workload, not universal constants.

The strongest conclusion is:

    exact preparation improved all three measured cases
    while producing bit-for-bit-equivalent query result dictionaries

The R4 result also shows that Phase 5.8 has not exhausted the optimization space.

Future exact acceleration may investigate:

    exact spatial candidate indexes
    receiver/occluder relationship classes
    vectorized projection
    batched polygon processing

but each must remain oracle-checked.

## 45. First benchmark CI correction

Initial PR workflow:

    run #196
    workflow 35998399055

had:

    pytest = 558 passed, 155 warnings in 71.68 s

but the new benchmark command failed before physics execution because invoking:

    python tools/benchmark_phase58.py --quick

placed the tools directory rather than repository root on Python's import path.

Failure:

    ModuleNotFoundError: No module named 'geometry'

The benchmark was corrected to insert the repository root before project imports.

No physics code, numerical tolerance, acceptance rule, or benchmark threshold was
changed.

Run #197 then passed both pytest and the benchmark.
