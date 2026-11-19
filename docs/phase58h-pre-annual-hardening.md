# OpenSIMPV — Phase 5.8H Pre-Annual Hardening v0.1

**Status:** Phase-5.8H implementation anchor  
**Date:** 24 September 2026  
**Base:** Phase 5.8 merged main `ef24097ebaeb0228cfd07098a74b4aeaf369e5de`  
**Purpose:** close reproducibility, persistence, and annual-scale execution gaps before Phase 5.9  
**Shading physics change:** none  
**Electrical shading:** still not modeled

## 1. Why Phase 5.8H exists

The Phase-5.0 through Phase-5.8 audit found no reason to reopen the frozen beam,
sky, or ground equations.

It did find infrastructure behavior that was acceptable for short vertical-slice
tests but unsafe to freeze as an annual result compatibility surface:

- volatile cache telemetry was embedded in model/reproducibility provenance;
- exact static-cache identity used a shortened execution-plan ID rather than the
  complete execution-plan payload hash;
- cache payload validation was weaker than cache-key identity;
- receiver factors were accumulated as one Python list/DataFrame for the entire run;
- no full beam + sky + ground none-vs-exact canonical parity test existed;
- no real cold-cache vs warm-cache canonical parity test existed;
- below-horizon beam snapshots still queried every receiver;
- ShadingResult inline/reference storage modes were not mutually exclusive enough;
- model-resolution provenance depended on SimulationRun ID;
- result-frame assembly produced pandas fragmentation warnings;
- annual receiver-factor scale and module self-shading cost had not been measured.

Phase 5.8H resolves those boundaries before Phase 5.9.

## 2. Frozen physics boundary

No Phase-5.8H change is allowed to redefine:

    beam polygon projection
    source-direction projection
    receiver polygon clipping
    polygon union
    beam horizon semantics
    isotropic-sky weighting
    circumsolar = current beam-direction visibility
    horizon weighting
    lower-hemisphere ground weighting
    ground/albedo source model
    visibility factor convention

The Phase-5.3 through Phase-5.8 reference solvers remain the oracle.

## 3. Deterministic model provenance vs execution telemetry

The old exact-acceleration runtime exposed volatile fields inside
`near_shading_runtime`:

    prepared query build/hit counts
    static cache hit/miss counts
    process-local cache entry count

These can differ between cold and warm execution even for identical physical inputs.

Phase 5.8H separates:

### deterministic model/acceleration manifest

    acceleration_id
    acceleration_version
    cache_mode
    prepared engine ID/version
    static cache ID/version
    exact_physics
    angular_quantization

from:

### execution telemetry

    prepared_query_build_count
    prepared_query_hit_count
    prepared_receiver_count
    prepared_face_count
    static_cache_hit_count
    static_cache_miss_count
    static_cache_process_entry_count
    receiver-factor streaming metrics

Only the deterministic manifest belongs in reproducibility/model identity.

## 4. SimulationRun execution telemetry

`SimulationRun` gains an optional:

    execution_telemetry

object.

This field is operational evidence only.

It is intentionally not copied into `ReproducibilityManifest.model_manifest`.

Failed runs use an empty telemetry object and never reference a backend that did
not execute.

## 5. Content-derived model-resolution identity

Before 5.8H, canonical model resolution used:

    <simulation_run_id>:model-resolution

This made model provenance depend on the job/run identifier.

Phase 5.8H derives model-resolution identity from:

    module revision ID
    inverter revision ID
    requested module model
    requested inverter model

and emits:

    model-resolution:<content-hash-prefix>

Equivalent pinned model inputs can therefore have equivalent model manifests
across different SimulationRun IDs.

## 6. Full execution-plan hash in exact cache identity

The human-readable execution-plan ID remains:

    execution-plan:<16 hex>

but exact cache identity no longer relies on that shortened identifier.

Exact cache mode requires:

    source_execution_plan_payload_sha256

and binds the complete SHA-256 in the static cache key.

The shortened plan ID remains payload provenance only.

## 7. Static cache payload validation

Both cache writes and cache hits validate:

    ShadingResult storage consistency
    compiled_geometry_hash
    receiver_set_sha256
    source_scene_revision_id
    shading_configuration_hash
    source_execution_plan_id
    expected static channel set
    inline storage mode

Sky static results explicitly permit the companion channel:

    sky_visibility
    directional_diffuse_visibility

Ground static results require:

    ground_visibility

A malformed or stale process-local cache entry therefore fails closed instead
of being trusted solely because a key was found.

## 8. Cache manifest hardening

`ShadingCacheManifest` now requires:

    source_execution_plan_payload_sha256

and its invalidation basis can include:

    execution_plan

The declared invalidation basis therefore matches actual cache-key behavior.

## 9. Bounded-memory receiver-factor pipeline

The geometry-aware worker no longer requires all receiver-factor records to stay
in one Python list until simulation completion.

It can now flush deterministic receiver-factor chunks.

Worker controls:

    receiver_factor_chunk_consumer
    retain_receiver_factors
    receiver_factor_chunk_rows

Default chunk target:

    8192 rows

Short tests/runs can retain the DataFrame in memory for debugging and regression.

Large canonical runs can stream chunks and return no in-memory receiver-factor
DataFrame.

## 10. ReceiverFactorParquetSink

New artifact helper:

    ReceiverFactorParquetSink

Properties:

    bounded-memory chunk input
    deterministic interval_start + receiver_id ordering
    fixed column contract
    fixed Arrow schema after first chunk
    zstd Parquet
    same logical-content SHA-256 convention as in-memory persistence
    content-addressed ResultDatasetReference
    temp-file staging before immutable run output
    telemetry for row/chunk/max-buffered-row counts

## 11. Canonical streaming threshold

Canonical execution predicts receiver-factor rows from:

    working simulation interval count
    ×
    execution-group receiver count

Threshold:

    250,000 rows

At or below threshold:

    retain in memory
    then persist to Parquet

Above threshold:

    stream to Parquet during geometry-aware execution
    do not retain full receiver-factor DataFrame

R4 annual scale is:

    216 × 8760
    =
    1,892,160 rows

so it is decisively on the streaming path.

## 12. Streaming identity requirement

For identical logical receiver-factor rows:

    in-memory persistence logical_content_sha256
    =
    streaming persistence logical_content_sha256

Physical Parquet file bytes are not required to match because row-group
boundaries may differ.

Logical content is the compatibility identity.

## 13. Exact below-horizon beam short circuit

For scalar direct-beam snapshots:

    normalized sun z <= frozen horizon tolerance

the solver evaluates one receiver to establish the frozen no-direct-beam result
and solver manifest, then reuses that exact global condition across the remaining
receiver set.

This is exact because global below-horizon status is independent of receiver
geometry.

For N receivers:

    old scalar receiver queries = N
    Phase-5.8H scalar receiver queries = 1

Output still contains N receiver records.

Diagnostic mode remains on the full reference path.

## 14. ShadingResult persistence contract

Production ShadingResult now requires:

    orchestrator_manifest
    receiver_set_sha256
    source_execution_plan_id
    result_payload_sha256
    approximation_manifest

Storage modes are hardened:

### inline

    inline_records required
    dataset_reference absent or null

### dataset_reference

    valid dataset_reference required
    inline_records forbidden

Runtime storage consistency additionally requires:

    inline record_count == len(inline_records)

or:

    referenced record_count == dataset_reference.row_count

This is preparation for annual dataset-reference use in Phase 5.9.

## 15. Standard result DataFrame assembly

`build_standard_timeseries()` now builds the ordered result column mapping
first and constructs the DataFrame once.

It no longer repeatedly inserts dozens of columns.

Requirements:

    same column order
    same values
    same logical-content hashes
    same downstream schemas

The purpose is to remove avoidable pandas fragmentation overhead without changing
the result surface.

## 16. Full-channel none-vs-exact parity

Phase 5.8H adds an end-to-end R4 comparison using:

    beam
    +
    sky diffuse
    +
    ground/albedo

for:

    cache_policy.mode = none

versus:

    cache_policy.mode = exact

Acceptance is exact physical equality of:

    standard time series
    receiver beam/sky/horizon/ground factors
    total PCC energy

Identity fields that legitimately include execution policy are excluded from the
physical-factor comparison.

## 17. Cold-vs-warm canonical parity

The same R4 beam+sky+ground exact configuration is executed:

    cold process-local static cache

then:

    warm process-local static cache

Acceptance:

    identical deterministic model_manifest
    identical ReproducibilityManifest.model_manifest
    identical canonical input_hash
    identical standard-result logical content hash
    identical receiver-factor logical content hash

Expected telemetry differs:

    cold -> static misses
    warm -> static hits

That difference is intentionally outside model/reproducibility identity.

## 18. Forced streaming parity

A canonical R4 short run is executed once with streaming disabled by threshold
and once with streaming forced.

Acceptance:

    same receiver-factor logical-content SHA-256
    same row count
    streaming backend retains no full receiver-factor DataFrame
    max buffered rows remain chunk bounded

This validates the persistence path independently of annual runtime duration.

## 19. Annual-scale persistence benchmark

The Phase-5.8H benchmark writes a complete R4-equivalent annual receiver-factor
dataset:

    216 receivers
    ×
    8760 hourly intervals
    =
    1,892,160 rows

through `ReceiverFactorParquetSink`.

The benchmark verifies:

    exact expected row count
    bounded per-chunk row count
    successful Parquet finalization
    logical-content hash production

Elapsed time/file size are evidence, not correctness thresholds.

## 20. R4 self-shading benchmark

The Phase-5.8H benchmark also enables:

    self_shading_enabled = true

on the exact R4 compiled geometry.

It compares the frozen reference beam solver against the prepared exact solver
for every module receiver and multiple sun directions.

Acceptance:

    complete query result equality

Timing and speedup are evidence only.

This closes the Phase-5.8 benchmark gap where module-plane occluders were excluded.

## 21. CI policy

The validation workflow runs:

    python -m pytest -q
    python tools/benchmark_phase58.py --quick
    python tools/benchmark_phase58h.py --quick

No wall-time speedup threshold is used.

Hard gates are:

    numerical/reference parity
    storage identity
    bounded annual row scale
    schema validity

## 22. shading_energy_loss_wh remains unresolved intentionally

Phase 5.8H does not overload:

    SummaryResult.shading_energy_loss_wh

The field remains null for geometry-aware Phase-5 runs because a rigorous
near-shading energy counterfactual has not yet been frozen.

Phase 5.9 must define whether the metric is:

    geometric near-shading energy loss
    electrical mismatch shading loss
    or a separately named pair of metrics

before publishing a non-null annual value.

## 23. Intentional deferrals remain

Phase 5.8H does not implement:

    general Surface occluder semantics
    imported mesh adapter
    polygon-hole triangulation
    spatial ground-irradiance maps
    bifacial rear irradiance
    substring / bypass-diode shading
    shaded module IV mismatch
    heterogeneous same-MPPT interaction
    multi-group annual electrical aggregation
    angular-bin approximation
    temporal shading interpolation
    PVsyst result fitting

## 24. Exit gate

Phase 5.8H closes when:

    Phase-5.3–5.8 physics regressions remain green

    cold/warm model provenance is deterministic

    volatile cache telemetry is outside reproducibility identity

    exact cache key binds full execution-plan SHA-256

    stale/malformed static cache payloads fail closed

    ShadingResult storage contract is strict

    full beam+sky+ground none/exact parity passes

    full beam+sky+ground cold/warm parity passes

    streaming/in-memory receiver factor logical identity passes

    below-horizon receiver-set shortcut is exact

    annual 1,892,160-row persistence benchmark is bounded and green

    R4 self-shading reference/exact benchmark is green

    full repository CI is green

After closure:

    -------- PHASE 5.8H PRE-ANNUAL HARDENING STABLE --------

Only then start Phase 5.9.


## 25. Successful measured gate — workflow run #205

The first complete Phase-5.8H gate to pass all three CI stages was:

    workflow run = 36008597530
    run number = 205
    job = schema-and-reference-tests

Repository tests:

    569 passed
    167.55 s

No pandas fragmentation warning summary was emitted. The previous repeated
fragmentation warnings were removed by batch-assembling both the detailed engine
time series and the standard result projection.

The longer pytest wall time relative to Phase 5.8 is expected because Phase
5.8H deliberately adds:

    full beam + sky + ground none-vs-exact R4 execution
    cold + warm exact R4 execution
    retained + forced-streaming R4 execution

CI wall time is not used as a production-performance benchmark.

## 26. Phase-5.8 reference benchmark remains green

Run #205 retained exact parity in the existing Phase-5.8 benchmark.

Synthetic high-irrelevant-module case:

    reference_seconds = 0.012855
    exact_total_seconds = 0.003635
    first_run_total_speedup = 3.54x
    query_only_speedup = 3.87x
    physics_parity = true

R1:

    reference_seconds = 0.013138
    exact_total_seconds = 0.003490
    first_run_total_speedup = 3.76x
    query_only_speedup = 8.06x
    physics_parity = true

R4, self_shading_enabled = false:

    receivers = 216
    occluders = 218
    directions = 6
    queries = 1296

    reference_seconds = 1.272115
    exact_prepare_seconds = 0.070017
    exact_query_seconds = 0.848719
    exact_total_seconds = 0.918737

    first_run_total_speedup = 1.38x
    query_only_speedup = 1.50x
    physics_parity = true

## 27. R4 module self-shading evidence

Phase-5.8H adds a measured case with:

    self_shading_enabled = true

Run #205 quick benchmark:

    receivers = 216
    compiled occluders = 218
    directions = 2
    queries = 432

    reference_seconds = 4.003299
    exact_prepare_seconds = 0.520205
    exact_query_seconds = 2.824179
    exact_total_seconds = 3.344384

    first_run_total_speedup = 1.20x
    query_only_speedup = 1.42x
    physics_parity = true

Interpretation:

    prepared exact execution remains beneficial when module-plane occluders
    participate, but the gain is materially smaller than in the clear/excluded-
    module cases because real per-direction module-to-module polygon work remains.

This is evidence for future exact spatial candidate indexing; it is not evidence
for weakening the self-shading model.

## 28. Annual receiver-factor persistence evidence

Run #205 exercised the complete R4-equivalent annual factor scale:

    receivers = 216
    hourly intervals = 8760
    expected rows = 1,892,160
    actual rows = 1,892,160

Streaming structure:

    chunk_count = 365
    max_chunk_rows = 5,184
    bounded_chunk_rows = true

Measured fixture persistence:

    elapsed_seconds = 131.395
    file_byte_size = 1,285,975
    logical_content_sha256 =
    1545741646239f7e5b27074a4d4f49b8fcc24969ee04bf20b8a32cef30cc7029

The byte size is **not** a production storage-size estimate. The benchmark uses
deliberately repeated constant visibility values and therefore compresses unusually
well. The acceptance evidence is the correct 1,892,160-row scale, bounded chunk
size, successful finalization, and deterministic logical-content hash.

## 29. Intermediate CI corrections

Several intermediate PR heads failed for hardening-integration reasons rather
than physics divergence.

Runs #200–#202:

    old Phase-5.8 regression still expected prepared receiver/build counts
    inside model_manifest.near_shading_runtime

Correction:

    deterministic acceleration identity remains in model_manifest
    volatile prepared/cache counts moved to SimulationRun.execution_telemetry
    the historical regression was migrated accordingly

No physical output changed.

Run #203 / #204:

    pytest passed
    existing Phase-5.8 benchmark passed
    Phase-5.8H annual benchmark failed before persistence because a timezone-aware
    DatetimeIndex was converted to NumPy object timestamps and then added to a
    numpy.timedelta64

Correction:

    benchmark timestamps are now generated from UTC nanosecond integers

No production shading or persistence equation changed.

## 30. Streaming failure cleanup

Large geometry-aware execution stages receiver-factor Parquet data in a temporary
file before finalization.

Phase 5.8H guards geometry backend dispatch so that if simulation raises before
completion:

    ReceiverFactorParquetSink.abort()

is invoked and the staged temp file is removed.

This prevents failed large simulations from leaving an orphaned partial receiver-
factor stream.

The broader run-package transactional boundary remains a Phase-5.9 artifact-
orchestration concern: once canonical result artifacts have been finalized,
run-package immutability and failure/recovery semantics should be considered as
one annual product boundary.

## 31. Remaining questions intentionally carried into Phase 5.9

Phase 5.8H closes the infrastructure blockers identified by the pre-annual audit,
but does not pre-decide every annual product-semantic issue.

Phase 5.9 must still define:

    annual ShadingResult dataset-reference identity

    relation between ShadingResult dataset_reference and
    SimulationRun.shading_receiver_factor_reference

    annual beam snapshot/result identity without large inline JSON arrays

    cold/warm cache execution telemetry retention policy in persisted packages

    near-shading annual energy-loss counterfactual semantics

    whether execution-only cache_policy should remain part of scientific input
    identity or receive a separate physics-result identity layer

    transactional persistence/failure semantics for the complete annual run package

These are annual result-product questions, not unresolved Phase-5.3–5.8 shading
physics.
