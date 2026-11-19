# RB-POST3D-08P2-E1 root-work engineering validation report

Task: `RB-POST3D-08P2-E1-FINAL-DOCUMENTATION`.
Branch: `ai/rb-post3d-08p2-e1-root-work-audit`.
Base: `3508f7f` (`3508f7f30342775ad7534833f3d759d576341b72`).
Formal E1 project status: **PENDING_MEASUREMENT**.
Measurement campaign: **completed**. Final independent E1 closure review: **pending**.

## A. Executive engineering summary

E1 measures observable root-solver work in the unchanged canonical one-interval
08P1 workload. It separates the physical producer, real serial attribution,
B2 numerical acceptance, persistence and verification so that follow-on
investigations can be ranked using measured work rather than aggregate timing.
The campaign comprises the original E1-R2 10-module smoke, eight independently
selected R3 measurements and four R3 comparison reports. All completed numerical
comparisons are **MATCH** for the physical and attribution fingerprints.

The scientific purpose is to identify expensive nested electrical solves while
preserving equations, root methods, tolerances, units, reference bases, topology,
provenance, callback order, cache policy and summation order. Identical fingerprints
establish exact recorded numerical parity for this fixture; they do not validate
new physics, representative field operation or the safety of an optimization.
The homogeneous daylight fixture leaves significant operating regimes unobserved.

Attribution is the first investigation priority: its warm `pvlib.i_from_v` calls
increase from **317,309** at 10 modules to **1,590,686** at 50, and its parallel
branch refinement evaluations increase from **431,722** to **2,158,579**.
Producer work also grows; B2 acceptance retains the same warm workload at both
sizes. Instrumented timings are diagnostic costs, **not production performance
estimates**. No production modification is authorized by this report.

This documentation pass changed only this document. It inspected existing JSON,
sidecars, diagnostic source, contracts and the 08P1 performance documentation;
it ran no simulation, benchmark, full regression or focused opcode trace, and
created no measurement evidence. Recorded suite/review dispositions are separated
below from checks performed during this documentation pass.

## B. Experiment configuration and provenance

All E1 measurement artifacts declare 10 or 50 modules, **one interval**, **one
worker**, a **900.0 s wall limit** and **4096 MiB sampled RSS ceiling**. R3 assigns
these limits independently to each isolated baseline/counts child, including
imports, fixture preparation, warm priming, checkpoints and selected work.
R2 used the preceding shared-budget orchestration. Parent metadata/final report
serialization are outside child budgets. The observed R3 children completed
within their limits; this is not a capacity guarantee for another workload.

The fixture is inherited through `rb_post3d_08p1.build_fixture`, using the retained
canonical module SDM, actual B2 evidence, three assumed series regions, Phase-6.6
solver and canonical dispatch/persistence. The 08P1 configuration documented in
`docs/validation/rb_post3d_08p1_performance.md` uses unique instances separated by
5 m in x, strings of at most ten modules on the existing MPPT: one string at 10
modules and five at 50. It retains inverter ratings and MPPT settings. This is a
controlled fixture, not the Huawei field string arrangement.

The inherited declared weather is `2026-03-21T10:00:00+07:00`, GHI/DHI 400 W/m²,
DNI 0 W/m². Assumption identity is `b2-equal-series`, revision
`b2-equal-series-r1`, source `b2-assumption`, retaining distinct `b2-original` /
`b2-retained` PAN provenance. Synthetic regions retain the fixture's explicit
opt-in and fail-closed policy. E1 checks positive unshaded POA and one replayed
interval. These descriptions come from the retained 08P1 documentation; E1 JSON
pins the complete inputs by digest rather than emitting their full payload.

Baseline installs no diagnostic observer. Counts uses selected Python profile
call/return/C-dispatch observation with source/bytecode classification, without
replacing scientific callables. No artifact contains a selected `trace` pass.
The defaults remain measurement mode `both` and cache selection `both`; campaign
R3 invocations deliberately select baseline and counts independently.

| Campaign | Modules / intervals / workers | Selected measured caches | Modes |
| --- | --- | --- | --- |
| E1-R2 smoke | 10 / 1 / 1 | cold then warm | baseline then counts in one report |
| R3 10 split, both | 10 / 1 / 1 | cold then warm | independent baseline and counts |
| R3 10 split, warm | 10 / 1 / 1 | warm only; separate cold priming | independent baseline and counts |
| R3 50 split, cold | 50 / 1 / 1 | cold only | independent baseline and counts |
| R3 50 split, warm | 50 / 1 / 1 | warm only; separate cold priming | independent baseline and counts |

Initial fixture setup clears the public physics caches once. A selected cold run
executes canonical dispatch, producer, attribution, B2 acceptance, persistence
with its nested verifier, physical/attribution replays and daylight/completeness
checks, then explicit package verification. Cold/warm run IDs remain
`cold_physics_cache` / `warm_physics_cache`. No cache clear occurs between them.
Warm-only performs this entire cold sequence uninstrumented before installing
an observer. Its priming record has null counters and `instrumented=false`;
priming is not measured cold coverage and is excluded from selected warm timings.
Warm `cache_before` equals priming/cold `cache_after_verification` exactly.

The recorded environment is identical across R2 and R3: Linux (`platform=linux`),
Python `3.12.3 (main, Aug 31 2026, 10:18:26) [GCC 13.3.0]`, NumPy **2.5.3**,
SciPy **1.18.1**, pvlib **0.15.2**, pandas **3.0.6**. The inspected R3 launcher sets
`OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`. Hardware model,
OS/kernel version, system load and independent BLAS-runtime confirmation are not
recorded; no hardware-normalized or cross-machine inference is possible.

R3 harness version is `E1-R3-1`; harness SHA-256 is
`e0cf10a2952391a10efd24e3065f51646b0c4cd14886963b6f07ea26641fe2f4`.
R3 task SHA-256 is
`6321c54e4f5feb1ea6c3a6acfe73dce26a963f76f978a7775510c227cb25a7db`.
Both match the inspected current files. R2 task SHA-256 is
`7d84c88b17c2bc2b0c025e5a5e0a5e9b140045758c9e013c5b8249e3a3c3e355`;
its historical harness hash in `metadata.source_hashes` is
`2cbb8193875acf5e69e15a67262b7e10ce84fede8da4ccd6a22ea69e0fd8a3e2`.
R2 lacks the R3 harness-version/mode/priming identity contract and remains
historical evidence, not an R3 comparison input.

| Modules | Fixture / full workload-input SHA-256 |
| --- | --- |
| 10 | `db6b31d7df0f60db9ca2f4465cc3d1e1cee26ffcdbaf5762b25bcb28960c9cf8` |
| 50 | `dc16c54361304581a19ad5c726b0668c86ef26fc08e3ba2af6ef590488521236` |

Each R3 measurement pins the full base commit, source inventory, fixture/reference
assets, fixture/input files, and loaded repository imports before/after execution,
including indirect imports. Input identity covers all project/config/store/scene/
design/bundle fields plus weather index, values and dtypes. Task SHA is recorded
before and after execution. Recorded dirty state contains the three untracked E1
harness/test/report files; base commit alone therefore does not identify the harness.
The complete inventories are retained in JSON, not replaced by the abbreviated
identity table here.

## C. Numerical equivalence and diagnostic acceptance

Fingerprints hash sorted canonical payloads with exact finite binary64 `float.hex`
encoding, including signed zero, and no field filtering. They cover the entire
physical and attribution replays. Summary fingerprints are outside this comparison
scope. This pass verified equality of stored fingerprints; full replay payloads
are not present in the evidence, so their hashes were not recomputed from new runs.

| Modules | Physical fingerprint | Attribution fingerprint |
| --- | --- | --- |
| 10 | `c2b5c2984f375d6ff9dea2d68e351ef9ed4ef1494587849a892308a9fc0455b1` | `11cf264b3e5ffae9f3f54a00908649571612f1e49b467feac203cb488de18079` |
| 50 | `7c33361541cf044b2cc8769bcfe7e66c9c034d7730963544aa171aeb378b348b` | `00581ad93cdf35102f4e5afd0cf93d01a0b0f98ae08bcdcf4b90564f1ed94096` |

| Comparison artifact | Coverage | Result |
| --- | --- | --- |
| `smoke-r2.json` | 10-module internal baseline/counts; cold and warm | MATCH |
| `r3-10-compare-both.json` | 10-module independent baseline/counts; cold and warm | MATCH |
| `r3-10-compare-warm.json` | 10-module independent warm; cold priming identity checked | MATCH |
| `r3-50-compare-cold.json` | 50-module independent cold | MATCH |
| `r3-50-compare-warm.json` | 50-module independent warm; cold priming identity checked | MATCH |

For each module size the physical/attribution fingerprints are also identical
between cold, warm and uninstrumented cold priming. No equality between different
module sizes is claimed. All eight split measurement reports record
`diagnostic_status=completed`, but their own `fingerprint_comparison` is
`NOT_COMPARED_INDEPENDENT`: completion alone does not establish baseline/counts
parity. The separate reports establish **MATCH** after strict compatible coverage,
identity, cache, provenance, child-exit, overflow/hook and fingerprint checks.

This pass reproduced all four R3 comparisons in memory using the existing
read-only `compare_evidence` function, without writing a comparison artifact or
launching a workload. Input raw/canonical digests exactly match the saved comparison
records. Every measurement child has `status=completed`, `child_status=completed`,
exit code **0** and empty diagnostic log tail. All R3 children and the R2 counts
child explicitly record overflow **0** and null hook failure. The R2 baseline
has no observer and omits these hook/overflow fields; absence is not a zero counter.
All artifacts retain `regression_gates=NOT_RUN` and `status=PENDING_MEASUREMENT`.
Completed diagnostic, numerical parity and regression acceptance are distinct.

## D. Performance measurements

Durations are seconds, rounded to three decimals from JSON; RSS is sampled resident
bytes divided by 2²⁰, rounded to three decimals. These are recorded observations,
not synthetic values, averages or confidence intervals. Each row is one archived
measurement. The 10-module both/warm records provide separate observations, not
a statistically designed repeated campaign.

`timings.wall_seconds` spans the child's preparation, priming where applicable,
selected work and bookkeeping up to the timing record. Parent
`total_wall_seconds_before_serialization` also includes orchestration and child
collection, but excludes final parent serialization. Neither is an isolated solver
cost. RSS is for the measured child; no separate parent/descendant peak is supplied.

| Campaign | Baseline child wall (s) | Counts child wall (s) | Baseline / counts parent wall (s) | Baseline / counts sampled peak RSS (MiB) | Counts observation events |
| --- | --- | --- | --- | --- | --- |
| R2 10 both | 95.525 | 396.057 | 492.111 combined | 212.918 / 216.168 | 53,943,811 |
| R3 10 both | 95.938 | 395.383 | 96.243 / 395.625 | 213.137 / 215.500 | 53,943,811 |
| R3 10 warm | 94.523 | 234.340 | 94.803 / 234.603 | 211.734 / 213.590 | 25,374,620 |
| R3 50 cold | 162.806 | 690.229 | 163.178 / 690.568 | 241.352 / 244.895 | 91,835,632 |
| R3 50 warm | 323.051 | 815.265 | 323.358 / 815.525 | 242.855 / 246.266 | 88,641,061 |

| Campaign | Cache | Baseline execution (s) | Counts execution (s) | Baseline explicit verifier (s) | Counts explicit verifier (s) |
| --- | --- | --- | --- | --- | --- |
| R2 10 both | cold | 43.169 | 180.174 | 5.810 | 26.498 |
| R2 10 both | warm | 37.870 | 158.950 | 5.814 | 26.237 |
| R3 10 both | cold | 43.684 | 182.522 | 5.823 | 25.503 |
| R3 10 both | warm | 38.148 | 157.304 | 5.794 | 25.760 |
| R3 10 warm | warm | 38.138 | 155.272 | 5.819 | 25.201 |
| R3 50 cold | cold | 152.612 | 639.167 | 6.905 | 40.639 |
| R3 50 warm | warm | 151.634 | 608.620 | 7.323 | 39.336 |

Execution time is canonical dispatch, which includes persistence and its embedded
verification. The explicit verifier column is the subsequent independent
`verify_run_package` invocation. Replay/daylight/fingerprint bookkeeping is outside
the execution timer; priming total includes that bookkeeping. The two verifier
contexts must not be confused with the single explicit verifier duration.

| Warm-only artifact | Uninstrumented cold execution (s) | Explicit verifier (s) | Total priming (s) |
| --- | --- | --- | --- |
| `r3-10-baseline-warm.json` | 43.261 | 5.907 | 49.265 |
| `r3-10-counts-warm.json` | 44.981 | 5.831 | 50.905 |
| `r3-50-baseline-warm.json` | 154.521 | 7.016 | 162.091 |
| `r3-50-counts-warm.json` | 151.569 | 6.793 | 158.902 |

Observed instrumentation overhead is reported as `counts / baseline`, elapsed
difference and `(counts / baseline - 1) × 100%` for matched execution coverage.
These ratios include run variability and observer work. They are not production
speedups and cannot subtract or distribute uniform overhead across functions.
Warm-only child wall ratios also include uninstrumented priming, so the execution
ratios are the relevant selected-work comparison.

| Campaign | Cache | Execution counts / baseline | Added execution (s) | Added execution % | Explicit verifier counts / baseline |
| --- | --- | --- | --- | --- | --- |
| R2 10 both | cold | 4.1737 | 137.006 | 317.37% | 4.5612 |
| R2 10 both | warm | 4.1973 | 121.081 | 319.73% | 4.5130 |
| R3 10 both | cold | 4.1782 | 138.837 | 317.82% | 4.3796 |
| R3 10 both | warm | 4.1235 | 119.156 | 312.35% | 4.4461 |
| R3 10 warm | warm | 4.0714 | 117.134 | 307.14% | 4.3309 |
| R3 50 cold | cold | 4.1882 | 486.555 | 318.82% | 5.8854 |
| R3 50 warm | warm | 4.0137 | 456.986 | 301.37% | 5.3716 |

**Instrumented timings are not production performance estimates.** Baseline rows
are uninstrumented observations for this fixture and environment only; neither
mode establishes field performance, annual runtime or an optimization benefit.
Historical 08P1 timings used a different harness/resource policy and earlier B2
work; they provide workload context, not a controlled E1 before/after comparison.

## E. Root-solver attribution

Tables use per-cache `passes[].runs[].counters`, not aggregate child counters that
mix cold/warm work. Counts include execution plus explicit verification. The
root-family evaluation table also uses the corresponding single-run child
`root_observations` records, preserving their explicitly recorded zero values.
`N/O` means not observed / absent; missing keys are never silently converted to zero.
Producer and attribution integer counts are identical in cold and warm for each
size, and the two R3 10-module warm selections agree. R2 smoke and R3 10-module
both integer phase counters also agree for each cache state.

B2 descendants are charged to `b2_numerical_acceptance`, with their original parent
context recorded separately. Root work is therefore not lost when persistence/
verification direct phase views contain no root-family calls.

| Modules | Cache | Phase | pvlib i_from_v | pvlib v_from_i | Module Isc calls | String Isc calls | Parallel solve calls | Uncached branch-current calls |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | cold & warm | producer | 110,723 | 3,822 | N/O | 1 | 4,200 | 122,835 |
| 10 | cold & warm | attribution | 317,309 | 10,622 | N/O | 30 | 12,516 | 364,326 |
| 50 | cold & warm | producer | 545,723 | 17,982 | N/O | 5 | 20,880 | 621,195 |
| 50 | cold & warm | attribution | 1,590,686 | 53,222 | N/O | 150 | 62,556 | 1,818,303 |
| 10 & 50 | cold | B2 acceptance | 284,640 | 133,632 | 24 | N/O | 11,904 | 337,116 |
| 10 & 50 | warm | B2 acceptance | 213,480 | 100,224 | 18 | N/O | 8,928 | 252,837 |

The branch-current column records observable Python call boundaries. Its root
observation reports zero *classified direct Python objective evaluations* in these
fixtures, while iterations and scientific termination are `not_observed`. That
zero does not establish zero native-kernel work or absence of endpoint helpers.
pvlib calls similarly do not expose native solver iteration counts.

| Modules | Cache | Phase | Family | Objective evals | Bracket evals | Bisection refinement evals | Post-solve evals | Golden-section evals |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | cold & warm | producer | string Isc | 38 | 2 | 36 | 0 | 0 |
| 10 | cold & warm | producer | parallel branch | 149,200 | 4,110 | 145,090 | 4,110 | 0 |
| 10 | cold & warm | attribution | string Isc | 1,102 | 60 | 1,042 | 0 | 0 |
| 10 | cold & warm | attribution | parallel branch | 443,968 | 12,246 | 431,722 | 12,246 | 0 |
| 50 | cold & warm | producer | string Isc | 186 | 10 | 176 | 0 | 0 |
| 50 | cold & warm | producer | parallel branch | 753,760 | 20,430 | 733,330 | 20,430 | 0 |
| 50 | cold & warm | attribution | string Isc | 5,502 | 300 | 5,202 | 0 | 0 |
| 50 | cold & warm | attribution | parallel branch | 2,219,785 | 61,206 | 2,158,579 | 61,206 | 0 |
| 10 & 50 | cold | B2 acceptance | module Isc | 988 | 48 | 940 | 0 | 0 |
| 10 & 50 | cold | B2 acceptance | parallel branch | 421,116 | 11,604 | 409,512 | 11,604 | 0 |
| 10 & 50 | cold | B2 acceptance | uniform MPP | 2,616 | N/O | 0 | 48 | 2,664 |
| 10 & 50 | warm | B2 acceptance | module Isc | 741 | 36 | 705 | 0 | 0 |
| 10 & 50 | warm | B2 acceptance | parallel branch | 315,837 | 8,703 | 307,134 | 8,703 | 0 |
| 10 & 50 | warm | B2 acceptance | uniform MPP | 1,962 | N/O | 0 | 36 | 1,998 |

Refinement columns count classified objective calls at bisection call sites;
they are **not solver iteration counts**. Module Isc and string Isc objective
totals are bracket plus refinement evaluations. Parallel totals exclude post-solve
reconstruction; bracket plus refinement equals objective evaluations.

Uniform MPP direct bracket evaluations are `N/O`: golden initial points are not
reported as root bracket probes. Cold B2 has **192 initial**, **2,424 golden
refinement** and **48 post-solve** point calls: **2,616 objective** and **2,664
recorded golden-section** calls. Warm has **144 initial**, **1,818 refinement**,
**36 post-solve**, **1,962 objective** and **1,998 golden-section** calls.
The harness's golden-section counter includes reconstruction; it must not be
silently relabeled as iterations or the objective-only total. These are measured
B2 values at both module sizes. Uniform MPP solve calls are **48 cold / 36 warm**.

Persistence has one direct `persist_run_package` call per selected execution;
verification has two direct `verify_run_package` calls, one embedded during
persistence and one explicit afterward. Producer and attribution each have one
interval call. B2 has four cold / three warm
`_evaluate_numerical_candidate_physics` calls per execution-plus-verify run.

| B2 parent (10 & 50) | Coverage | Physics calls | i_from_v | v_from_i | Module Isc calls | Module Isc objective evals | Parallel calls | Parallel refinement evals | Golden-section evals |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dispatch | cold only | 1 | 71,160 | 33,408 | 6 | 247 | 2,976 | 102,378 | 666 |
| persistence | cold & warm | 1 | 71,160 | 33,408 | 6 | 247 | 2,976 | 102,378 | 666 |
| verification | cold & warm | 2 | 142,320 | 66,816 | 12 | 494 | 5,952 | 204,756 | 1,332 |

The verification parent view combines embedded and explicit verification; it is
not two extra explicit verifiers. Warm B2 dispatch work is absent from warm-only
observation; in a cold/warm delta its previously registered keys can be explicit
zero deltas. These representations are compatible without inventing counters.
Other B2 parent contexts are empty here.

Additional observable counts describe selected Python boundaries and selected-frame
C dispatch, not total interpreter or native kernel activity.

| Modules | Cache | Phase | Branch-current wrapper calls | Module-state calls | String-state calls | String _evaluate_module calls | Selected Python-to-C events |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | cold & warm | producer | 157,510 | 1,400 | 140 | 1,400 | 2,095,878 |
| 10 | cold & warm | attribution | 464,530 | 2,762 | 4,162 | 4,162 | 6,116,725 |
| 50 | cold & warm | producer | 795,070 | 6,960 | 696 | 6,960 | 10,566,106 |
| 50 | cold & warm | attribution | 2,322,547 | 13,802 | 20,802 | 20,802 | 30,553,580 |
| 10 & 50 | cold | B2 acceptance | 444,624 | 3,856 | N/O | N/O | 6,255,604 |
| 10 & 50 | warm | B2 acceptance | 333,468 | 2,892 | N/O | N/O | 4,691,703 |

Direct persistence and verification selected Python-to-C dispatch counts are **2**
and **146**, respectively, at either size/cache selection; dispatch has **240** at
10 modules and **1,200** at 50. Setup and compatibility-control counters are empty
because preparation precedes hooks and separate negative controls do not run as
representative fixture work. Root-family iteration counts and scientific
termination reasons remain **not_observed** throughout; no focused opcode tracing
was selected. Module Isc calls absent in producer/attribution and string Isc calls
absent in B2 remain N/O, not fabricated zeroes.

## F. Scaling analysis: 10 versus 50 modules, warm

The comparison uses warm-only baseline/counts pairs, excluding cold priming.
Ratios are calculations from recorded values, not extra measurements. Fivefold
module growth also changes string count from one to five; it does not isolate
module count from topology size.

| Warm metric | 10 modules | 50 modules | 50 / 10 |
| --- | --- | --- | --- |
| Attribution i_from_v calls | 317,309 | 1,590,686 | 5.0131 |
| Attribution v_from_i calls | 10,622 | 53,222 | 5.0105 |
| Attribution string Isc calls | 30 | 150 | 5.0000 |
| Attribution parallel solve calls | 12,516 | 62,556 | 4.9981 |
| Attribution parallel refinement evals | 431,722 | 2,158,579 | 4.9999 |
| Producer i_from_v calls | 110,723 | 545,723 | 4.9287 |
| Producer parallel refinement evals | 145,090 | 733,330 | 5.0543 |
| B2 i_from_v calls | 213,480 | 213,480 | 1.0000 |
| B2 parallel refinement evals | 307,134 | 307,134 | 1.0000 |
| Baseline warm execution (s) | 38.138 | 151.634 | 3.9760 |
| Counts warm execution (s) | 155.272 | 608.620 | 3.9197 |
| Baseline explicit verifier (s) | 5.819 | 7.323 | 1.2585 |

Attribution pvlib calls, string solves, branch solves and refinement evaluations
are approximately fivefold in these fixtures. Producer work also grows approximately
with module/string count. B2 acceptance counts remain constant in these
fixtures; that observation is specific to their retained acceptance configuration,
not a claim about every possible B2 candidate set. One producer interval, one attribution
interval, one persistence and two verifier calls remain constant, while their
durations and non-root costs need not be constant.

Fixed preparation, package construction/replay/checks and verification contribute
to per-execution cost; they must be separated from module-related root work.
JSON does not isolate a pure setup duration, so child-wall residuals are not
presented as a measured setup counter. Explicit baseline verification rises from
5.819 to 7.323 s despite constant B2 root counts; constant root counts alone do
not establish constant verifier duration.

Warm-cache effects are specific: candidate physics holds one entry (maxsize 64,
misses 1, hits 0) after cold and warm work; producer physics holds one entry
(maxsize 16, misses 1). Producer cache hits move **164 → 329** at 10 modules and
**804 → 1,609** at 50. Initial cold caches are empty. Explicit verification leaves
these snapshots unchanged. Warm removes one B2 dispatch-context physics evaluation;
producer and attribution root counts remain unchanged. Fresh acceptance work in
persistence/verification still occurs. Warm priming costs 49.265/50.905 s at 10
modules and 162.091/158.902 s at 50 (baseline/counts), which must not be hidden in
a warm-only campaign cost.

These two fixture sizes support bounded workload comparisons only. They do not
establish universal asymptotic complexity, interval/annual scaling, heterogeneous
state scaling, larger-plant capacity or arbitrary topology behavior.

## G. Counter integrity and timing interpretation

B2 parent-context counters are a contextual view of the same events in B2 phase
totals. For every R3 selected cache run, this pass checked that every B2 integer
counter equals its sum across parent contexts. Do not add contextual views to B2
totals. Direct phases identify ownership; parent views identify who requested
acceptance work. Neither authorizes removing a scientific check.

Inclusive timers span nested calls. Producer/attribution interval timers include
descendant branch/pvlib work. Persistence includes its embedded verifier and nested
B2 work; verification's aggregate timer includes embedded and explicit calls.
B2's physics timer includes its root/pvlib descendants. **Inclusive timings must
not be summed**, within or across these categories; sums would count the same
execution repeatedly. The following overlapping views are not a partition or
production time budget.

| Warm-only counts inclusive view (s; overlapping) | 10 modules | 50 modules |
| --- | --- | --- |
| Producer interval | 25.060 | 125.686 |
| Attribution interval | 71.468 | 367.771 |
| Attribution parallel solves | 65.403 | 335.900 |
| Attribution pvlib i_from_v | 27.327 | 140.985 |
| B2 physics total | 64.523 | 64.382 |
| Persistence | 49.338 | 70.462 |
| Verification, embedded + explicit | 50.406 | 78.517 |

The observer retains bounded selected-code/counter/live-frame state; completion
is invalidated on overflow or hook failure. Counts mode has no production event
cap. Event totals are selected profile observations, not root iterations.
`returns_or_unwinds` identifies an observable exit, not convergence or a scientific
termination reason. Missing counters and unreached families remain limitations.
Native kernel loops, C-internal calls and some allocations are outside these Python
boundaries; selected C-dispatch counts do not measure the whole interpreter or
native libraries.

## H. Scientific and measurement limitations

- **Active bypass:** not observed as a representative active-bypass workload.
  Calling protection/clamp helpers does not establish active bypass operation.
- **Nonuniform electrical states:** homogeneous daylight does not establish
  heterogeneous irradiance/temperature or mismatch behavior/performance.
- **Reverse-domain operation:** not observed; no conclusion about reverse roots,
  branch behavior, limits or stability.
- **Dark operation:** not observed; positive daylight checks exclude it.
- **Arbitrary stateful callables:** compatibility/order controls are synthetic;
  they do not establish representative performance or scientific coverage.
- **Native solver iterations:** not observed. pvlib and selected Python calls are
  observable boundaries, not internal iterations. Bisection evaluations cannot
  be relabeled as iteration counters.
- **Scientific termination reasons:** not observed. Returns/unwinds do not identify
  convergence criteria, tolerance satisfaction or root-selection rationale.
- **Nested endpoint probes:** cached branch endpoints and golden initial points
  are not direct bracket counters; missing counters do not imply no work.
- **Sampled RSS:** Linux child RSS is sampled every 20 ms. Transient peaks,
  descendants, parent memory and some native allocation details are excluded;
  this is not a continuous hard cap, heap measurement or incremental memory cost.
- **Statistical/external validity:** hardware/load metadata and confidence bounds
  are unavailable; only one interval and these two fixture sizes are covered.
- **Persistence after interruption:** completed runs have checkpoints, but work
  since the last checkpoint can be lost. JSON/sidecar replacements are individually
  atomic, not an atomic pair; interruption can yield a rejected digest mismatch.
- **Regression/review:** full regression is NOT_RUN; final independent closure
  review is pending. Numerical parity is not a substitute for either gate.

## I. Evidence inventory and verified SHA-256 digests

All campaign artifacts are beneath `.ai/validation/rb_post3d_08p2e1/`.
Each JSON has schema `RawiBumiRootWorkAudit`, version 2. This pass verified all
**13** embedded canonical digests and all **13** adjacent raw-file sidecars.
Canonical evidence digest is SHA-256 of sorted compact JSON with
`evidence.sha256=null`; raw digest is SHA-256 of exact archived bytes. They are
different identities. Sidecars contain the raw JSON digest, not the canonical
digest. The separate sidecar table hashes the sidecar's own bytes. Embedded child
records are inside parent JSON, not separately archived JSON paths with standalone
sidecars in this inventory.

| JSON path | Verified canonical evidence SHA-256 | Verified raw-file SHA-256 |
| --- | --- | --- |
| `.ai/validation/rb_post3d_08p2e1/r3-10-baseline-both.json` | `0499c9f7fb367bab64dbf4385e2e71aa52e7386fd4f94bda71a0c2bc8384a56e` | `9059ce527faab6fed7546fe32cab373fde7cfab5c0f8061466c0ba8b2bc4a13e` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-baseline-warm.json` | `9ac7a179eb3e5f5a190e2cd6d0dc7b70f3f6c11d080f53ad512c19d15d09c041` | `cb739bf7c15155b9e47c3ea04ddae01b1cdb5a0ab35a1768b091db39bddf7dbe` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-compare-both.json` | `cd49f18b2bb2e980133314a015dc68ae6b48fa215b1b4a990f5cc740b74e3021` | `d0925a507cbffb5fe767b3486455d34226a244d745097bb48f54c8e453a6c3dc` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-compare-warm.json` | `e9593320064f48c685e9feaa92388281dc8ec5a714bf0814fe730fafc751961d` | `1083d69845bf0f30b49ebed2ee9bdb38dc6b9f0bb11496ae893333c17ff90487` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-counts-both.json` | `b5c55096f26f65cbd0e5df06c2f8a576e907e1cfbdc245c9dd9022a4fdb10349` | `8a578e6bef85fbff9b89e7f75199f318487fc5fa72e30e881351bea23ecf8c2d` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-counts-warm.json` | `dc9aabb8807fd6c6ef2e2b1948f0d735dbbe601717f46ae3ebd4c892b7d61fb4` | `e9aff28a2219493116a64edf98e171c206edb09d8d241e2508d11e1047179571` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-baseline-cold.json` | `a27920a2149520c47a27c9c932313e4ecda06048b45f2b9db29bfeb781db3ba9` | `2ce0f12ff76e4274be30fe9437094b8e2f236352fc24c615bf6ffbe21ff62332` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-baseline-warm.json` | `48d3d8376a90153576966a9c5c317fe6da36eb09700462c10bd25597bc516fd0` | `7a2e7a6fce69ec2e2554dc2174d86fcba3c3d31ce5a8aedd502850ab83eca4ce` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-compare-cold.json` | `4c0952f1a99ed084eaf3fa5478773c54e6173f40ef5f547f50b21aaae7028129` | `1d99e7765fae1e21413cf7954447a01251c3a5ba0a5fed02f3297f4a9dce8232` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-compare-warm.json` | `2559f625b8765d0a10ce3a5bb249997fe41b9d19d5f862f8ab5f118a2091b0f7` | `1fe9844ac5e7f7d2fcc15f33625e251ee1d18b03d6e6457b45c18bbe7ef597b6` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-counts-cold.json` | `b688b31a6cf1bf0a88a9ee56a0e418ad485dc6b1f3d3b1917b7a898e9eb2914b` | `822567c7fd019b301a27515d26d67f32010dfa0b73ccee34cd88ecd43ec3f3ed` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-counts-warm.json` | `e4d648c3b28cd2d27d502dbce6bf0095336160426f49cfb40702e61d77d16c34` | `ab641dc5c71242dd55457cf3857579e696fefdbfc0cda5855c63e70409ff1561` |
| `.ai/validation/rb_post3d_08p2e1/smoke-r2.json` | `f40a5e40c90ce314bf50313ad580650b3bbd149242d6f540c537817a9c3baf6f` | `84912614c41acbb921c2ae681c27d10018a817c60bd3521e2c9eb3854e8d0021` |

| Sidecar path | Verified raw sidecar-file SHA-256 |
| --- | --- |
| `.ai/validation/rb_post3d_08p2e1/r3-10-baseline-both.json.sha256` | `01814323d5d5943bc47174a550f0b15e251e7c291eca058b42c4d12520e8fb3a` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-baseline-warm.json.sha256` | `356ba8391392ac5ca9c3f7b57bd2f62fafe80f734ba5116c37ce8fc74fe07323` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-compare-both.json.sha256` | `8a5936e5810630cebb0417a377eff56a1c447048c0da7a88960b2a4d33b31037` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-compare-warm.json.sha256` | `3860486c553265aaa9a9aa1876e86f13c8c9fdd1ffff26e657df5f458ec14dd8` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-counts-both.json.sha256` | `5621d1901e61af028493063d19d95befde58ea3fdc1de82884c142e5f50347b0` |
| `.ai/validation/rb_post3d_08p2e1/r3-10-counts-warm.json.sha256` | `3fd06c074061276ee07a2616c19dbe0637485053e91751c098bf394f5fd833bc` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-baseline-cold.json.sha256` | `9b558e447cd1e1a2698fcd7f540c45c8a5e44405a9a4fea6e15875c18638f54b` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-baseline-warm.json.sha256` | `18a3587c1aca227e0f76727888fd3a73e1d5bf7057253065db12806453bb7359` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-compare-cold.json.sha256` | `669374a4b86373699b559e7261aaa005ef3409d1152216fb18e369023767023c` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-compare-warm.json.sha256` | `c2df07740cab1cbe141ac7bcae969a5c1bfd9f92e1d54b470eddab848bcfe14f` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-counts-cold.json.sha256` | `3a998f95408953ce1b6ee1c9bb259df8b2ca85e19930bde5d7720df45c5d1786` |
| `.ai/validation/rb_post3d_08p2e1/r3-50-counts-warm.json.sha256` | `3e228be9c8db3c33f3557136d2bb3b1ab068118f64ac9e30193330a6d9d18083` |
| `.ai/validation/rb_post3d_08p2e1/smoke-r2.json.sha256` | `42f55264a6eb3dd5632b210ed13ec459dd0803777eac52d81052b33366e47445` |

The following nine archived console logs were read and are all **empty (0 bytes)**.
Their verified raw SHA-256 is
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Logs have no canonical evidence digest or adjacent sidecar.

- `.ai/validation/rb_post3d_08p2e1/r3-10-baseline-both-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-10-baseline-warm-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-10-counts-both-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-10-counts-warm-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-50-baseline-cold-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-50-baseline-warm-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-50-counts-cold-console.log`
- `.ai/validation/rb_post3d_08p2e1/r3-50-counts-warm-console.log`
- `.ai/validation/rb_post3d_08p2e1/smoke-r2-console.log`

Supporting read-only inputs, hashed during this pass (raw bytes; no canonical
evidence digest):

| Read-only input path | Verified raw SHA-256 |
| --- | --- |
| `AGENTS.md` | `db09ab4a699089b465d4a53d609f20a52f28383c376f74a769b365f03df16828` |
| `.ai/TASK.md` | `6321c54e4f5feb1ea6c3a6acfe73dce26a963f76f978a7775510c227cb25a7db` |
| `scripts/benchmarks/rb_post3d_08p2e1_root_work.py` | `e0cf10a2952391a10efd24e3065f51646b0c4cd14886963b6f07ea26641fe2f4` |
| `tests/unit/test_rb_post3d_08p2e1_contract.py` | `28576d8f33fdece7ffc6931dc472d12aa837531de918e4c5186270cd2803a9e2` |
| `docs/validation/rb_post3d_08p1_performance.md` | `9a27266b0b81e8c15a29f4144746ce52e2078f100d231dbc95f0d8d9840c5b17` |

The R3 independent review and F1 validation are campaign dispositions supplied
for this task; no standalone review JSON or pytest transcript is present in the
authorized evidence directory. No path/digest for those records is invented.
The prior report records 203 passing targeted contracts; current contract source
corroborates the F1 lifecycle controls below, but does not itself prove a test run.
Retain external review/test records with the campaign for closure review. External
archival of the ignored JSON/sidecars remains an operator responsibility and was
not verified here.

## J. Engineering interpretation and ranked follow-on investigations

1. **Attribution nested electrical work.** Investigate real serial counterfactual
   curves, string current solving and parallel branch refinement. This is the
   measured concentration: at 50 modules attribution has 1,590,686 i_from_v calls,
   62,556 parallel solves and 2,158,579 refinement evaluations. It represents
   67.69% of warm i_from_v calls and 67.48% of parallel refinement evaluations
   across distinct producer/attribution/B2 phase views (49.46% / 48.84% at 10).
   These shares describe counts, not exclusive CPU time. Its overlapping interval/
   parallel-solve observations, 367.771 / 335.900 s at 50, support investigating
   this path first without treating them as production estimates or summable costs.
   Identify repeated state construction, endpoint work and dependency/callback
   relationships before considering a change. Nonuniform, bypass, reverse, dark
   and stateful cases remain scientific acceptance boundaries.
2. **Physical producer work, separately.** Producer has 545,723 i_from_v calls,
   20,880 parallel solves and 733,330 refinement evaluations at 50 modules, with
   125.686 s overlapping interval observation. It remains present in warm work;
   the warm physics cache does not eliminate this root workload. Investigate
   module/string IV assembly and nested branch evaluation independently of
   attribution. Similar call shapes do not prove that sharing results, batching
   or changing numerical methods would preserve canonical semantics.
3. **B2 acceptance and requesting contexts, separately.** Warm B2 has three physics
   evaluations, 213,480 i_from_v calls, 100,224 v_from_i calls, 307,134 parallel
   refinement evaluations and 1,998 recorded golden-section evaluations at either
   size. Its fixed work matters especially at 10 modules; cold adds one dispatch
   evaluation. Investigate context ownership and uniform-MPP/module-Isc work while
   preserving fresh independent acceptance and verifier boundaries. A duplicated
   counter view does not identify a removable duplicate scientific computation.
4. **Persistence, verification and fixture coverage.** Investigate non-root package/
   replay/validation costs after separating nested B2 work, then expand authorized
   diagnostic coverage to unobserved electrical regimes if required for a later
   proposal. Constant verifier call/B2 counts do not account for all verifier
   duration or module-related package work.

These are investigations, not approved optimizations. E1 does not establish that
caching, batching, callable substitution, altered roots/tolerances, changed
summation or any approximation is scientifically safe. A follow-on production
proposal requires its own authorization, exact scientific equivalence criteria,
representative fixtures, provenance review and regression evidence. This report
authorizes no production modification.

## K. Closure disposition and independent review readiness

E1-R2 smoke is completed with internal MATCH, 53,943,811 selected observation
events, no overflow and its protected archive intact. R3 supplies independent
baseline/counts selection, complete cold priming for warm-only, fresh per-child
limits, strict read-only comparisons and partial checkpoints. All four 10-module
and four 50-module measurements completed, and all four R3 comparisons are MATCH.

**Independent E1-R3 review: PASS_WITH_NOTES**, recorded as the supplied campaign
verdict. The existing task also preserves an earlier E1-R2 PASS_WITH_NOTES
precondition; those two review stages must not be conflated.

**F1 flaky-test repair and validation:** current bounded contracts tolerate
`/proc/<pid>/stat` disappearance via `OSError` (including exit races), exercise
`ProcessLookupError` and generic unavailable-proc negative cases, synchronize the
synthetic descendant's readiness, allow a 10 s synthetic leader budget and poll
for descendant exit up to 5 s before cleanup. The descendant sleeps 30 s, so
completion-plus-cleanup budgets remain below that lifetime. These controls address
lifecycle-test races and change no electrical calculation.

The supplied campaign result is **203 passed, 0 failed** for
`tests/unit/test_rb_post3d_08p2e1_contract.py`. The prior report's targeted invocation
is `.venv/bin/python -B -m pytest -q -p no:cacheprovider tests/unit/test_rb_post3d_08p2e1_contract.py`.
It was not rerun in this documentation pass; retry counts and additional F1
validation transcripts are not invented.

| Gate / disposition | Recorded state | Meaning |
| --- | --- | --- |
| E1 measurement campaign | COMPLETED | R2 smoke + eight R3 measurements retained |
| Numerical comparisons | MATCH | Physical/attribution cold and warm parity for measured fixtures |
| Targeted E1 contract suite | 203 passed, 0 failed | Supplied campaign result; no fresh pytest run here |
| Independent R3 implementation review | PASS_WITH_NOTES | Supplied campaign verdict; notes/coverage limits retained |
| Full regression / artifact regression gates | NOT_RUN | No regression acceptance inferred |
| Final independent E1 closure review | PENDING | Must review this report and evidence |
| Formal E1 project status | PENDING_MEASUREMENT | Unchanged; no final closure declared |

Documentation validation performed here: canonical/raw digest checks for all
13 JSON/sidecar pairs; in-memory reproduction of the four R3 comparisons; recorded
fingerprint/cache/child-status checks; B2 integer parent-context partition checks;
10-module R2/R3 and R3 warm integer counter consistency; report/source scope and
whitespace checks. No scientific workload or pytest suite was executed here.

**Critical issues:** none identified in this documentation/evidence consistency
check. **Major issues:** none identified in consolidated figures or stored
comparison validity; missing full regression and final closure review remain open
acceptance gates, not passes. This is not a new independent code-review verdict.
**Minor notes/limitations:** unobserved electrical regimes and native iterations/
termination, overlapping timing/counter views, sampled RSS, incomplete hardware/
statistical metadata, checkpoint durability limits, and unavailable standalone
R3/F1 review/test records in the authorized inventory. These remain explicit rather
than becoming zero counters or scientific acceptance.

The report is ready for final independent E1 closure review within these evidence
limits. The reviewer should confirm digest-linked inputs, F1 and R3 source identity
and external review/test records, unchanged scientific/cache/callback semantics,
contextual counter integrity, instrumented-timing interpretation and open regression/
coverage gates. No simulations, benchmarks, full regression, focused opcode tracing,
staging, commits, merges, pushes or rebases were performed in this pass. Only this
report is the authorized changed file. Final closure is not declared; E1 remains
**PENDING_MEASUREMENT**.
