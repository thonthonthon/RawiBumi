# OpenSIMPV — Phase 5.9 Full Geometry-Aware Annual SimulationRun v0.1

**Status:** Phase 5.9 implementation and acceptance anchor  
**Date:** 24 September 2026  
**Base:** Phase 5.8H merged main `6aa0bd353b898b480e60602ca5e39ea6140d1d1d`  
**Pull request:** #66 — Phase 5.9: full geometry-aware annual SimulationRun integration  
**Shading physics change:** none to the frozen Phase-5.3–5.8H beam / sky / ground equations  
**Electrical shading:** detailed mismatch / bypass behavior remains not modeled

## 1. Closure statement

Phase 5.9 closes the annual product/artifact integration boundary for the
Phase-5 geometry-aware engine.

The production path can now execute the complete supported chain:

    weather
    -> solar position
    -> unshaded POA
    -> direct-beam geometric visibility
    -> sky-diffuse obstruction
    -> ground/albedo obstruction
    -> IAM / effective irradiance
    -> temperature
    -> supported homogeneous electrical aggregation
    -> inverter
    -> PCC energy
    -> annual summary + explicit geometric shading counterfactual

The phase deliberately does not reopen the reference shading equations and does
not introduce Phase-6 electrical mismatch.

## 2. Annual ShadingResult is now the authoritative shading artifact

Geometry-aware SimulationRuns now publish one annual/long-run
`ShadingResult` in dataset-reference mode.

The receiver-factor Parquet dataset belongs to:

    ShadingResult.dataset_reference

The pre-existing:

    SimulationRun.shading_receiver_factor_reference

is retained only as a compatibility reference and is required to equal the
same dataset-reference object exactly.

This prevents one logical receiver-factor dataset from acquiring two ambiguous
artifact identities.

The annual ShadingResult records:

- source Scene revision;
- compiled geometry hash;
- full execution-plan payload SHA-256;
- receiver-set SHA-256;
- exact solver/model manifests;
- active beam / sky / directional diffuse / ground channels;
- fidelity and receiver granularity;
- approximation manifest;
- dataset row count and dataset reference;
- full artifact payload identity;
- separate physical/scientific result identity.

## 3. Execution identity and scientific result identity are separate

The canonical SimulationConfiguration/input identity still includes the full
shading configuration, including `cache_policy`.

Therefore:

    cache_policy.mode = none

and:

    cache_policy.mode = exact

remain intentionally different execution/configuration identities.

Phase 5.9 adds a separate scientific shading identity for exact-physics
comparison. Only the already-proven exact execution alternatives `none` and
`exact` are normalized to common exact-physics semantics.

Approximate angular or temporal policies are not normalized.

This preserves auditability without falsely treating an execution policy as a
physical difference.

## 4. Receiver-factor logical identity and physical-content identity are separate

Receiver-factor rows retain snapshot provenance IDs such as:

    shading_result_id
    sky_shading_result_id
    ground_shading_result_id

Those IDs legitimately differ when the canonical execution configuration differs.

Consequently, the complete receiver-factor logical-content SHA-256 remains the
storage/reproducibility identity, while Phase 5.9 adds:

    physical_content_sha256

which excludes only those execution/configuration-derived snapshot-ID columns.

The physical hash retains timestamps, receiver identity, receiver area, all
visibility factors, and quality flags.

This makes none-vs-exact physical comparison explicit rather than pretending the
complete persisted rows are byte/logically identical.

## 5. Annual geometric near-shading energy counterfactual

For complete 8760-hour or 8784-hour geometry-aware runs,
`SummaryResult.shading_energy_loss_wh` is now quantified by an explicit second
PCC-energy calculation.

Counterfactual definition:

    same weather
    same design
    same IAM / optical models
    same thermal model
    same electrical model
    same non-shading losses
    geometric beam / sky / ground visibility forced clear

Then:

    shading_energy_loss_wh
    =
    counterfactual_clear_geometry_PCC_energy_wh
    -
    geometry_aware_PCC_energy_wh

The complete counterfactual basis is exposed as:

    SummaryResult.shading_energy_loss_basis

This is geometric near-shading energy effect at the current Phase-5 electrical
fidelity.

It is not:

- a sum of geometric percentages;
- bypass-diode loss;
- substring mismatch loss;
- shaded module-IV loss;
- same-MPPT heterogeneous IV interaction.

Those remain Phase 6.

Short/nonannual geometry-aware runs retain a null shading-energy-loss KPI rather
than publishing a counterfactual with a different period semantic.

## 6. Run-package completion and recovery semantics

Phase 5.9 introduces:

    run-package-manifest.json

The completion manifest is written last after all run artifacts.

It inventories each package file with:

- relative path;
- artifact role;
- byte size;
- file SHA-256.

The manifest itself has a canonical payload SHA-256.

A package is consumable only when:

- the completion manifest exists;
- the manifest payload hash validates;
- every declared artifact exists;
- every declared artifact size and hash validate;
- no undeclared files exist in the package.

A missing or invalid completion manifest means the package is incomplete and
must be rebuilt.

Completed SimulationRun IDs are immutable.

For design-launched runs, the exact `design-validation-report.json` is staged
before numerical execution and is allowed only when its canonical hash matches
the validation evidence passed to the canonical runner. It is therefore covered
by the final completion manifest without weakening the run-directory
immutability guard.

## 7. Bounded annual receiver-factor persistence retained

The Phase-5.8H streaming boundary remains unchanged:

    predicted receiver rows <= 250,000
        -> retained/in-memory persistence path

    predicted receiver rows > 250,000
        -> bounded streaming Parquet path

The annual R4 acceptance case uses the streaming path.

No large annual receiver-factor JSON array is introduced.

## 8. Phase 5.9 regression coverage

Added canonical regressions for:

1. one authoritative annual shading dataset;
2. ShadingResult/reference equality;
3. persisted annual ShadingResult;
4. run-package completion verification;
5. package tamper detection;
6. none-vs-exact distinct execution identities;
7. none-vs-exact equal receiver physical content;
8. none-vs-exact equal scientific shading physical identity;
9. cold-vs-warm exact result equivalence;
10. streaming and retained physical-content hash compatibility.

Existing Phase-5.8H streaming parity tests were extended to require
`physical_content_sha256` parity as well as full logical-content parity.

## 9. CI evidence

Latest normal PR validation on the closure branch:

    workflow: validation
    run: #222
    result: PASS

The gate includes:

    python -m pytest -q
    python tools/benchmark_phase58.py --quick
    python tools/benchmark_phase58h.py --quick
    python tools/benchmark_phase59.py --quick

The earlier current-product-code normal validation run #221 also passed.

## 10. Full annual acceptance evidence

Dedicated benchmark:

    benchmark_id:
    opensimpv.phase59.full_geometry_aware_annual.v0.1

Independent successful workflow executions:

    phase59-annual-validation run #1
    workflow run ID 36025601062
    PASS

    phase59-annual-validation run #2
    workflow run ID 36025669152
    PASS

Timing is evidence only and is not a correctness threshold.

### R1 — full-year clear/no-loss regression

Synthetic deterministic annual clear-sky integration fixture:

    intervals = 8760

Observed:

    annual PCC energy
    = 20,564,278.602868505 Wh

    shading_energy_loss_wh
    = 0.0

Exact-physics comparison:

    cache none
    exact cold
    exact warm

all produced the same:

    standard logical SHA-256
    7eb370f6c3a782eb2e28aa6d497ec1f0cec15cccf3c4723a476cf912c668d386

    receiver physical SHA-256
    73008f8f019250b236fb1c2c18e5e5a08ead12427a678ef10f87383f3b255126

    shading physical-result SHA-256
    7bd520578b2f442ec4e85ce3e930280a08d62bc5abb068afcf74c5863d5143c7

while the canonical input hashes remain different between cache-none and
cache-exact, as designed.

Cold and warm exact runs also retain identical complete receiver logical hashes.

### R4 — full-year nontrivial geometry-aware case

Synthetic deterministic annual clear-sky integration fixture:

    intervals = 8760
    module receivers = 216

Observed:

    receiver-factor rows
    = 1,892,160

    annual geometry-aware PCC energy
    = 222,213,163.04400626 Wh

    explicit geometric near-shading energy counterfactual loss
    = 28,625,177.898560107 Wh

    corresponding clear-geometry counterfactual PCC energy
    = 250,838,340.94256637 Wh

Receiver-factor persistence:

    mode = streaming_parquet
    predicted rows = 1,892,160
    actual rows = 1,892,160
    chunk count = 231
    target chunk rows = 8192
    maximum observed chunk rows = 8208

Identity:

    receiver physical SHA-256
    75281f2d68a4c210c76871d453b57fde5d1634c27fd73bbec7e4296e80c63f03

    shading physical-result SHA-256
    a26bbcfb6b64a3dc750285a4e6086bc2feb8b8bb0a0f928a97570709f32833e1

    standard-result logical SHA-256
    0d213f2376fa45131453cd35db9467a0c06f728b618611bde3530635a5f1dd99

The approximately 11.41% geometric near-shading PCC-energy reduction in this
synthetic acceptance fixture is benchmark behavior only. It is not a calibrated
project yield, a PVsyst match, or an external validation result.

## 11. Acceptance-gate disposition

Phase-5.9 required boundary:

    explicit shading channels
    PASS

    annual geometry-aware time series
    PASS

    annual SummaryResult
    PASS

    annual dataset-reference ShadingResult
    PASS

    one authoritative receiver-factor dataset identity
    PASS

    reproducibility manifest attachment
    PASS

    none-vs-exact physical equivalence
    PASS

    cold-vs-warm exact equivalence
    PASS

    R1 full-year clear/no-loss
    PASS

    R4 full-year nontrivial shaded execution
    PASS

    bounded annual receiver-factor persistence
    PASS

    explicit geometric shading-energy counterfactual
    PASS

    run-package completion/recovery semantics
    PASS

    existing numerical/loss reconciliation
    PASS

## 12. Intentional boundaries after Phase 5.9

Phase 5.9 does not implement:

- detailed substring or bypass-diode shading;
- shaded module IV reconstruction;
- series string IV under nonuniform module irradiance;
- heterogeneous same-MPPT IV interaction;
- general multi-group annual electrical aggregation;
- R5 execution;
- angular-bin approximation;
- temporal shading interpolation;
- imported arbitrary mesh adapter;
- general Surface occluder semantics;
- spatial albedo/ground irradiance maps;
- bifacial rear irradiance;
- PVsyst result fitting.

R5 remains explicitly blocked unless a later phase deliberately implements the
required separable multi-group numerical/electrical execution.

## 13. Phase-5.10 handoff

Phase 5.10 should now focus on analytical and external validation decomposition.

Do not reopen Phase-5.3–5.8H equations because of final annual-energy differences.

Validation order should remain:

    analytical geometry truth
    -> controlled OpenSIMPV synthetic cases
    -> independent/open implementation where appropriate
    -> PVsyst VC0–VC5 cross-software comparison
    -> final energy comparison only after upstream differences are understood

Use the existing VC0–VC5 family to decompose:

- solar-angle alignment;
- beam directionality and beam loss;
- circumsolar treatment where comparable;
- diffuse obstruction;
- albedo obstruction;
- monthly shading;
- annual shading;
- combined-obstacle behavior;
- downstream energy after upstream attribution.

Preserve the observed directional asymmetries rather than normalizing them away.

## 14. Binding implementation decisions

ADR:

    docs/decisions/0050-phase59-annual-artifact-semantics.md

Key rule:

    execution/configuration identity
    !=
    physical/scientific shading result identity

and:

    geometric near-shading energy effect
    !=
    Phase-6 electrical mismatch loss
