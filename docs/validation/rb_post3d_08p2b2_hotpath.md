# RB-POST3D-08P2-B2 electrical hot path

## Selected operation

Only `substring_reference.py` changes production behavior. The existing
`_branch_current_at_voltage` algorithm is retained as
`_branch_current_at_voltage_uncached`; its wrapper reuses successful exact I(V)
results in the existing model-owned `_BranchEndpointHolder`.

Call graph inspected: module_series_adapter voltage_at_current → protected
substring evaluation → parallel branch solve → currents_at → branch I(V) →
PVSystRegionElectricalState.current_at_voltage → pvlib i_from_v. The bypass-off
DC attribution model already passes its own holder through the same solver.
Protected substring construction also evaluates I(V) at the bypass clamp.
Module-IV short-circuit solving and B2 acceptance use the no-holder path and
remain fresh; no changes were made to module_iv or parameterization.

Each branch solve starts at identical branch-domain endpoints. The low endpoint,
bypass clamp, and shared prefixes of the midpoint tree repeat exactly across
requested currents. The final converged midpoint can also repeat within one
solve. These are redundant evaluations of the same pure region laws, rather
than merely high function counts. Distinct voltages and currents remain
necessary. Independent B2 acceptance and attribution counterfactuals are not
removed or shared with the producer.

## Equality and bounds

Reuse requires the same mapping, branch object, ordered region IDs, and exact
region-state objects. Only the existing frozen AnalyticalRegionReferenceState
and PVSystRegionElectricalState types qualify. Their fields bind parameterization,
irradiance, temperature, reverse domain and solver choice. Module revision and
topology remain bound through model ownership and the unchanged provenance gate.
The key includes exact voltage float.hex (including signed zero), both numerical
tolerances and iteration limit. No rounding is performed. Bypass clamp voltage
is part of the same exact key; bypass state is still calculated afresh.

Each registered branch admits at most 256 results. Once full, existing entries
remain readable and new points execute normally without storage. No new branch
slots, global result cache, permission cache, or worker-shared cache is created.
Failures are never stored. Unknown or replaced bindings execute the reference
path. Arithmetic, bisection order, iteration exhaustion, conservation checks and
all existing tolerances remain unchanged.

Before: one real branch inversion for every invocation, including repeats.
After: one real inversion per admitted unique exact key; a repeated admitted key
requires zero further inversions. Unadmitted keys still require one inversion.
The independent review observed a real 101-point uneven-irradiance sweep:
21,726 actual regional I(V) evaluations before exact-match memoization and
18,848 after, a reduction of 2,878 evaluations (approximately 13.2%). The
reviewed sweep reported bit-identical numerical results with reuse enabled and
disabled. This is a review-observed sweep, not an annual benchmark or a claim
of 13.2% wall-time improvement. These counts are not from the timing JSON files,
which label their operation counts as unmeasured.

The previous benchmark `branch_current_inversion` counter now includes calls
returning reused results. After memoization it is therefore not equivalent to
the count of actual regional I(V) evaluations.
Historical profile counts (pre-B1) are
72,165 branch solves and 2,690,938 branch-current calls; not all are redundant.

## Verification status

No tests, builds or benchmarks executed by Codex, per workflow instructions.
The new test file compares real protected substring states and canonical hashes
against the unchanged uncached algorithm across uniform/nonuniform/dark states,
temperatures, open circuit, near short circuit, MPP neighborhood, reverse bias
and both sides of bypass transition. It includes bounded-storage and real
nonlinear call-count assertions, exact-voltage isolation, changed-condition
isolation, iteration exhaustion, exception parity, strict opt-in and Level-3
rejection. A real canonical run comparison checks attribution intervals, source
identity and numerical fingerprint and independently verifies both packages.
The reference execution scopes both the kernel and directly imported attribution
branch-current bindings to the uncached algorithm, then restores both. Both runs
use one worker and construct separate model-owned holders. Exact comparisons
and scientific tolerances are preserved.
Corrected-test regression results are **pending orchestrator execution**;
Codex executed **0 tests** for this cleanup. Historical logs are not fresh evidence.

The orchestrator must also run the existing Phase-6.5/6.6 electrical suites,
B2 acceptance, B3D1/B3D2 worker and package verification, B1 transaction tests,
and Phase-6.9/6.10 regressions, including historical v0.1 hash fixtures.
Authorization code, public schemas, source identities and hash algorithms were
not edited. This is source evidence, not a claim of passing verification.

## Recorded ten-module timing

Human-operated, uninstrumented measurements for the existing ten-module fixture
are recorded in `.ai/validation/rb_post3d_08p2b1_final/after_10module.json`
(before B2) and `.ai/validation/rb_post3d_08p2b2_final/after_10module.json`
(after B2). Both specify `instrumented: false`. The values below agree with
those original JSON measurements after rounding; improvements use unrounded
wall times and `(before - after) / before`.

| Physics cache | Measurement | Before (s) | After (s) | Improvement |
| --- | --- | ---: | ---: | ---: |
| Cold | Execution | 50.68 | 41.72 | 17.7% |
| Cold | Independent verification | 7.11 | 5.79 | 18.6% |
| Cold | Total | 57.80 | 47.51 | 17.8% |
| Warm | Execution | 44.495 | 37.997 | 14.6% |
| Warm | Independent verification | 7.05 | 5.65 | 19.9% |
| Warm | Total | 51.55 | 43.65 | 15.3% |

The measured warm execution improvement meets the 10% engineering target for
this fixture. This evidence cleanup does not qualify the 190-module Huawei
pilot. Regression and historical hash parity for the corrected test remain
pending the orchestrator's fresh execution and Claude's independent review.
