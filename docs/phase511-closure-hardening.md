# OpenSIMPV — Phase 5.11 Closure Hardening

**Status:** Phase-5 closure implementation anchor  
**Date:** 25 September 2026  
**Base:** Phase 5.10 merged main `e0287ae5cc1803c60eae11ebb177bba045a1004c`  
**New shading physics:** none

## 1. Objective

Freeze the Phase-5 maturity boundary.

Phase 5.11 does not add another solver. It converts the Phase-5 exit criteria into executable regression, reproducibility and performance-evidence gates.

## 2. Frozen regression family

The closure matrix includes:

| Family | Reference |
|---|---|
| simple unobstructed rooftop | R1 |
| multi-roof | R2 |
| ground-mounted fixed tilt | R3 |
| rooftop / obstacle-rich shading | R4 |
| multiple orientation | R5 |
| external shaded family | PVsyst VC0–VC5 |
| analytical geometry truth | Phase-5.3 microcases |

R5 remains an explicit electrical-boundary case. Its canonical geometry may compile and persist even where Phase-6 electrical interaction is not yet supported.

## 3. Save/reload geometry reproducibility

For R1–R5 the closure regression now checks:

    canonical Scene
    -> save
    -> reload
    -> compile shading geometry

and requires exact equality of:

    Scene canonical SHA-256
    compiled geometry payload SHA-256
    compiled geometry content

This proves compiled shading geometry remains derived deterministically from canonical design state.

## 4. Short full-chain R4 reproducibility

A nontrivial obstacle-rich R4 test executes:

    save Scene/design package
    -> reload
    -> compile geometry
    -> run beam + sky + ground geometry
    -> run SimulationRun

and preserves:

    Scene hash
    compiled geometry hash
    configuration canonical identity
    SimulationRun input hash
    standard result logical SHA-256
    ShadingResult physical SHA-256
    ShadingResult identity

This test is intentionally short enough for ordinary PR CI.

## 5. Full annual closure evidence

The dedicated Phase-5.11 workflow executes two full-year closure references.

### R1

R1 is the annual save/reload reproducibility reference.

It executes a complete annual exact geometry-aware run before save/reload and again after reload.

Required invariants:

    Scene hash identical
    compiled geometry hash identical
    configuration identity identical
    SimulationRun input hash identical
    standard annual logical SHA-256 identical
    receiver-factor physical SHA-256 identical
    ShadingResult identity identical
    ShadingResult physical SHA-256 identical
    |annual energy delta| <= 1e-6 Wh

### R4

R4 remains the annual nontrivial shaded reference.

The closure benchmark records:

    annual runtime
    receiver-factor row count
    annual PCC energy
    geometric near-shading loss
    scientific identities
    process maximum-resident-set evidence

The 216 × 8760 receiver-factor scale remains:

    1,892,160 rows

## 6. Performance evidence

`tools/benchmark_phase511.py` records:

- Scene → compiled shading geometry time;
- direct beam query count, elapsed time and time/query;
- sky-view receiver query count and elapsed time;
- Python traced peak memory for the geometry benchmark;
- cold/warm exact cache behavior and runtime;
- full R1 annual reproducibility runtimes;
- full R4 annual geometry-aware runtime;
- process high-water RSS evidence for the full annual R4 run.

No timing or memory value is a universal CI threshold.

Correctness/identity gates remain hard failures.

Performance values are interpreted only relative to defined benchmark environments.

Each benchmark payload records Python/runtime platform, machine architecture,
logical CPU count, GitHub Actions/runner metadata, timing clock, and the memory
measurement mechanisms used.  Full-workflow output is retained as a CI artifact
so later performance reviews can compare like-for-like evidence rather than
treating runner-dependent numbers as universal limits.

## 7. Cache closure rule

A short exact R4 cache benchmark must show:

    cold run:
        static cache miss count > 0

    warm run:
        static cache hit count > 0

while preserving:

    standard logical result identity
    shading physical result identity

Cache warmth therefore remains execution telemetry rather than scientific identity.

## 8. External validation closure

Phase 5.10 remains the external-validation authority.

Phase 5.11 carries forward:

    VC0–VC5 source decomposition
    directional asymmetry
    combined-case non-additivity
    fail-closed matched-input comparison contract

It does not invent a new OpenSIMPV/PVsyst equality score.

## 9. Phase-5 exit gate

The closure matrix freezes the following as satisfied for current scope:

### Geometry

- deterministic Scene → compiled shading geometry;
- analytical shadow truth;
- preserved module receiver identity;
- distinct beam/sky/ground effects.

### Simulation

- geometry modifies annual irradiance and PCC energy;
- unobstructed references remain stable;
- shading channels enter explicit loss stages;
- numerical reconciliation remains closed.

### Execution architecture

- shading/irradiance geometry is not globally limited to one project orientation;
- unsupported electrical heterogeneity remains explicit;
- Phase-6 mismatch physics is not falsely claimed.

### Reproducibility

- Scene/config/model identity is deterministic;
- cache invalidation is deterministic;
- shading and run manifests preserve physical identity;
- save/reload annual execution is reproducible.

### Validation

- analytical cases pass;
- controlled OpenSIMPV cases pass;
- VC0–VC5 are decomposed;
- combined obstacles are not treated as additive;
- unsupported external parity is stated rather than hidden.

At closure:

    -------- GEOMETRY-AWARE PV SIMULATION STABLE --------

## 10. Measured closure evidence

Final pre-merge validation on PR #68:

    normal validation workflow
    run #233
    result = PASS

    pytest
    587 passed in 218.38 s

    benchmark_phase58.py --quick
    PASS

    benchmark_phase58h.py --quick
    PASS

    benchmark_phase59.py --quick
    PASS

    validate_phase510.py
    PASS

    benchmark_phase511.py --quick
    PASS

Dedicated full closure workflow:

    workflow = phase511-closure-validation
    run #8
    workflow run ID = 36074578227
    result = PASS

Retained artifact:

    name = phase511-closure-benchmark
    artifact ID = 10840460187
    artifact SHA-256 digest =
    f486e73a88a96b197cc923703b105fab8a4209cf6fb53307fa185f6e717828f9

### Benchmark environment

    Python = CPython 3.12.14
    OS = Linux
    runner architecture = X64
    logical CPU count = 2
    CPU = AMD EPYC 7763 64-Core Processor
    platform = Linux-6.17.0-1022-azure-x86_64-with-glibc2.39

These values identify this benchmark environment only.

### R1 annual save/reload reproducibility

Observed:

    before-save annual runtime
    = 41.152964238 s

    after-reload annual runtime
    = 40.720936269 s

    annual PCC energy
    = 20,564,278.602868505 Wh

    annual energy delta after save/reload
    = 0.0 Wh

Identity remained exact:

    SimulationRun input SHA-256
    ccb34b19e4c21e0933878895ed8f747aaab55d7ff81452566e9ab48c6cb40a97

    standard result logical SHA-256
    7eb370f6c3a782eb2e28aa6d497ec1f0cec15cccf3c4723a476cf912c668d386

    receiver-factor physical SHA-256
    73008f8f019250b236fb1c2c18e5e5a08ead12427a678ef10f87383f3b255126

    ShadingResult physical SHA-256
    7bd520578b2f442ec4e85ce3e930280a08d62bc5abb068afcf74c5863d5143c7

    Scene SHA-256
    a745383d533849eaf6e0c443ec2e6520e29ae8f6227c2e025d88c237357195e6

    compiled geometry SHA-256
    afde57a040235280ed60435b15ec349ea3293627151eb1ad803f98b9a825b3dd

    SimulationConfiguration SHA-256
    0f78b9f557d36696c8dfd47f8911d360f00da36144eb4fb88fdd41b7f9cb35c7

The 1e-6 Wh deterministic tolerance was therefore satisfied with zero observed drift.

### R4 full annual shaded reference

Observed:

    annual geometry-aware runtime
    = 986.488600264 s

    receiver-factor rows
    = 1,892,160

    annual PCC energy
    = 222,213,163.04400626 Wh

    geometric near-shading energy loss
    = 28,625,177.898560107 Wh

Identity:

    receiver-factor physical SHA-256
    75281f2d68a4c210c76871d453b57fde5d1634c27fd73bbec7e4296e80c63f03

    ShadingResult physical SHA-256
    a26bbcfb6b64a3dc750285a4e6086bc2feb8b8bb0a0f928a97570709f32833e1

    standard result logical SHA-256
    0d213f2376fa45131453cd35db9467a0c06f728b618611bde3530635a5f1dd99

Process high-water RSS after the R4 run was:

    530,165,760 bytes

R4 did not raise the process high-water mark beyond the preceding annual R1
runs in this workflow, so the recorded R4-stage high-water growth was zero.
This is process-level evidence, not a claim that R4 itself allocates zero memory.

### Geometry/cache performance evidence

For the same runner:

    R4 Scene -> compiled geometry
    = 0.334784215 s

    direct beam
    = 48 queries
    = 0.058918349 s/query

    sky view
    = 12 receiver queries
    = 4.811215238 s/receiver

    geometry benchmark traced Python peak
    = 2,346,173 bytes

Short R4 exact-cache evidence:

    cold runtime = 15.306983515 s
    cold cache = 0 hits / 2 misses

    warm runtime = 1.358549854 s
    warm cache = 2 hits / 0 misses

    standard-result identity = unchanged
    shading physical identity = unchanged

Timing and memory values remain non-gating evidence and shall only be compared
against suitably matched benchmark environments.

---

## 11. Phase-6 boundary

Phase 5 hands forward:

    per-module / per-receiver geometric irradiance state
    + canonical electrical topology
    + explicit receiver identity
    + reproducible geometric shading artifacts

Phase 6 may now introduce:

    local irradiance
    -> substring state
    -> bypass state
    -> module IV
    -> string IV
    -> parallel strings
    -> MPPT operating point
    -> inverter

without redefining the canonical Scene or the Phase-5 geometric shading system.
