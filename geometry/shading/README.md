# Geometry-Aware Shading

This package begins Development Phase 5.

Phase 5.0 contains **contracts and conventions only**. It intentionally does not
implement a production shadow, sky-view, ground-view, acceleration, cache, or
annual shading solver.

Frozen conventions:

- canonical engineering geometry remains the Phase-4 `Scene`;
- shading geometry is derived numerical state;
- local axes are X East, Y North, Z Up, metres;
- `sun_vector` points from receiver toward the sun;
- visibility factor 1 = clear and 0 = blocked;
- beam, sky-diffuse, and ground visibility remain separate channels;
- Phase 5 does not claim electrical mismatch physics.

See `docs/phase50-geometry-aware-shading-contract.md`.


## Phase 5.1 compiler

Phase 5.1 adds deterministic:

```text
Scene
→ existing Phase-4 GeneratedScene3D semantics
→ CompiledShadingGeometry
```

Current native compilation includes:

- resolved module planes as module receivers;
- resolved module planes as self-shading-capable occluder records;
- surfaces explicitly marked `shading_receiver=true` as aggregate receivers when
  their polygon has no holes;
- native obstacle footprints as vertical polygon-face occluders.

It deliberately does not infer surface-occluder participation because canonical
`Surface` currently has no `shading_enabled` engineering field. It also does
not substitute footprint extrusion for `imported_mesh` geometry.

See `docs/phase51-compiled-shading-geometry.md`.

## Phase 5.3 direct-beam reference kernel

Phase 5.3 adds deterministic single-receiver direct-beam visibility.

Flow:

    CompiledShadingGeometry
    + receiver_id
    + receiver-to-sun vector
    -> projected and unioned receiver shadow
    -> beam_visibility_factor

The reference kernel uses polygon projection and pinned Shapely/GEOS planar topology. It intentionally performs no diffuse, ground, annual, or electrical shading physics.

See docs/phase53-direct-beam-shadow-kernel.md.

## Phase 5.4 receiver beam-factor snapshots

Phase 5.4 orchestrates the Phase-5.3 reference kernel across an explicit receiver set or Phase-5.2 execution-group receiver IDs.

Normal output uses the existing ShadingResult contract with beam_visibility as the only modeled channel. Optional projected polygons are emitted separately as a derived_diagnostic_only BeamShadowDiagnosticArtifact.

See docs/phase54-beam-factor-snapshots.md.

## Phase 5.6 weighted sky-diffuse obstruction

Phase 5.6 adds deterministic static isotropic-sky and horizon visibility against
`CompiledShadingGeometry`.

The reference sky solver uses equal-solid-angle global upper-hemisphere patches
and weights each patch by solid angle times positive receiver cosine response.
Directional patch visibility reuses the Phase-5.3 full-polygon projection
kernel.

Circumsolar diffuse remains time-dependent and uses the current sun-direction
beam visibility. Horizon diffuse uses a separate low-elevation weighted dome.
Ground visibility remains unmodeled until Phase 5.7.

See `docs/phase56-diffuse-sky-obstruction.md`.

## Phase 5.7 ground/albedo obstruction

Phase 5.7 adds a generic source-direction finite-receiver visibility kernel and a
deterministic weighted lower-hemisphere ground solver.

The public Phase-5.3 direct-beam wrapper remains unchanged and keeps its
sun-below-horizon semantics. Ground directions use the generic kernel instead.

The ground model modifies receiver-side visibility of the existing uniform
Lambertian scalar-albedo ground-reflected POA channel only. Spatial ground
illumination, spatial albedo, and bifacial rear irradiance remain outside this
tranche.

See `docs/phase57-ground-albedo-obstruction.md`.

## Phase 5.8 exact acceleration and cache

Phase 5.8 keeps the Phase-5.3 through Phase-5.7 reference solvers as correctness
oracles while adding an exact prepared-query path for annual execution.

`cache_policy.mode="none"` uses the reference path. `"exact"` prepares
direction-independent receiver geometry and receiver-front-clipped eligible
occluder faces once per receiver, then reuses them for beam, sky, and ground
queries.

Static sky and ground ShadingResult payloads may be reused through a bounded
process-local exact cache whose provenance is emitted using the existing
`ShadingCacheManifest` contract. Angular-bin approximation remains fail-closed.

See `docs/phase58-annual-cache-measured-acceleration.md`.

## Phase 5.8H pre-annual hardening

Phase 5.8H keeps all Phase-5.3–5.8 shading equations unchanged while hardening
execution and artifact boundaries before annual SimulationRun work.

Exact static-cache identity now binds the full execution-plan payload SHA-256,
cache hits and writes validate the complete static ShadingResult provenance
surface, and volatile hit/miss/build counters are execution telemetry rather than
model/reproducibility identity.

Scalar direct-beam snapshots also use an exact global below-horizon shortcut:
one receiver query establishes the frozen no-direct-beam state and the remaining
receiver records reuse that state. Diagnostic mode retains the complete reference
path.

ShadingResult persistence is now explicitly exclusive between inline and
dataset-reference modes, with runtime record-count reconciliation.

See `docs/phase58h-pre-annual-hardening.md`.


## Exact receiver-pool memory admission (PERF3)

Native compiled scenes use sourceward face and vertex allocation upper counts for
the unchanged receiver preparation. Admission reserves 1.25 times that prepared
allocation, a 1.5 GiB allowance for later parent allocations, and per-worker
compiled-state, base and scratch budgets. Unsupported metadata retains the
original conservative estimate. The allowance means a smaller machine selects
serial execution sooner.

The reservation remains the smaller of 6 GiB and half available memory. The
nonblocking machine lease, 12-worker cap and fatal summed-RSS runtime guard are
unchanged; this accounting never changes a shading factor or retries a failure.
