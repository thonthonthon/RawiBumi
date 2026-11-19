# RB-POST3D-08P1 performance qualification

Baseline: accepted B3D2 commit `65b8001`, branch
`ai/rb-post3d-08b3-authenticated-execution`. This is a measurement harness,
not a production optimization. No production files or public contracts change.
The accepted compatibility baseline is 358 passed / 8 expected skips; this is
historical evidence, not verification of this harness.

## Configuration and authority

The harness extends `_fixture(_candidate())` from
`tests/unit/test_rb_post3d_08b3d2_activation.py`. It uses the retained canonical
module SDM, actual B2 evidence, three assumed series regions, the Phase-6.6
solver, real serial attribution, canonical downstream execution, actual
persistence and `verify_run_package`. Every completed cold and warm execution
has an independently verified persisted package. Temporary packages are removed
only after verification. Construction always uses `freeze_detailed_selection`.

Workloads are exactly 1, 10 and 50 unique module instances, one identical
fixture daylight interval, one selected module revision and one assumption.
Instances use the accepted first module's transform with 5 m increments in x;
field membership and string membership include each instance exactly once.
Strings contain at most ten modules: respectively 1, 1 and 5 strings on the
existing MPPT. Inverter ratings and accepted fixture MPPT settings are retained.
These are controlled workloads, not the Huawei string arrangement. There is
no 190-module or annual execution and no external weather acquisition.

Assumption identity: `b2-equal-series`, revision `b2-equal-series-r1`, source
`b2-assumption`, with distinct `b2-original` / `b2-retained` PAN provenance
records. The complete declaration, including source module revision, topology
revision, parameterization revision and digests, is emitted with each result.
The weather timestamp is `2026-03-21T10:00:00+07:00`, with GHI/DHI
400 W/m² and DNI 0 W/m², and is emitted from the selected weather. Successful
runs require positive unshaded POA for every module, preventing a dark fixture
from being accepted as a daylight measurement.

The accepted fixture supplies literal `scientific_options.allow_synthetic_regions=True`
and `fail_closed`. The harness changes only worker counts to one. It does not
create authority or introduce an authorization cache. Instrumentation calls
original functions with unchanged arguments and returns original results;
exceptions propagate. Independent acceptance retains `use_cache=False`.
SD1–SD4 in `.ai/TASK.RB08B_IMPLEMENTATION_FROZEN.md` and the solver identity
decision in `.ai/TASK.RB08B_B3_FULL_FROZEN.md` remain binding: current-verifier
scientific consistency is checked, not historical producer build attestation.
Level-3 denial, source bindings, witness rules, tolerances and v0.1 remain intact.

## Execution and measurement definitions

Run on Linux with the repository's existing test dependencies installed:

```sh
python scripts/benchmarks/rb_post3d_08p1.py > /tmp/rb_post3d_08p1.json
# Historical entrypoint only: do not rerun its 50-module stage for P2B1.
```

JSON goes to stdout; artifacts use temporary directories outside the repository.
The orchestrator must retain the JSON and return measurements for this document.
No benchmark or test was executed by Codex in this implementation round.

Each workload has a **single 600-second wall budget** for both subprocess passes,
including startup, construction, cold/warm execution and verification. The first
pass has no wrappers; the second instruments calls. Each fresh child sets
`RLIMIT_AS` to 4096 MiB before scientific-library imports. BLAS thread counts
are one. This is an address-space ceiling, stronger and different from an RSS
ceiling; allocation failures and nonzero exits are explicit `terminated` results.
Timeouts kill the whole process group and remain `timeout` results, never
completed measurements. Partial successful passes are retained as partial evidence.

Ten starts only after one completes safely. Fifty starts only after ten
completes safely. Both attempts rely on the enforced 600-second / 4096-MiB
case limits rather than multiplying fixed startup costs or lifetime RSS.
A preceding timeout, termination, invalid output or skip prevents the next
attempt; skipped JSON records include the preceding status. No projected
resource threshold is used. Worker-pool performance is unmeasured. Serial
worker initialization is expected to be zero and child RSS is expected to
be zero/not applicable; both remain unmeasured until confirmed by output.
No worker-pool scaling conclusion is permitted. Nonzero exits include their
actual diagnostics: fixture/authorization/design validation failures must be
reported as validation failures, not inferred to be resource failures.

Monotonic `perf_counter` supplies wall times; `process_time` supplies CPU times
separately for execution and verification. Setup/import/construction wall time
is reported separately. Parent case elapsed time includes child startup and
both passes. Process and child memory are Linux `ru_maxrss` / 1024 MiB, lifetime
high-water RSS; child RSS is the maximum individual child's peak, not a sum.
Per-module RSS therefore includes fixed interpreter/import/setup memory and is
not incremental module allocation. For completed larger cases the harness also
reports `(peak_N - peak_1)/(N - 1)` as a measured-difference derivation, including
run variability. This may be negative and is not an allocation measurement.

Cold means **cold physics caches after fixture construction**, with both
`_validated_producer_physics` and `_cached_numerical_candidate` cleared. It does
not mean cold imports, OS caches, or structural validation caches: construction
already exercises these. Warm means a second run on identical immutable inputs
in that child **after the cold package verification**. No warmed run is labeled
cold. Cache hit/miss counters are reported before execution, after execution,
and after independent verification. Cache hits are never physical evaluations.

The instrumented pass counts actual `_evaluate_numerical_candidate_physics`
entries separately from acceptance requests, including fresh `use_cache=False`
requests, witness validations, transport validations, worker initializations,
actual backend module model builds, attribution module counterfactual calls,
and explicit package verifier invocations. Execution and independent verification
counts are separate. These are call-site observations, not estimates of solver
inner iterations. Wrappers also measure inclusive backend interval, attribution
interval, persistence and verifier times. Inclusive times overlap and must not
be summed. `backend_interval_inclusive_seconds_per_module` includes transport/witness
validation, string/MPPT assembly and wrapper overhead; it is not pure solver
time. `module_model_inclusive_seconds_per_module` separately measures model
construction, also including its validation and wrapper overhead. Attribution
interval time includes counterfactual evaluations and aggregation. Persistence
time covers `persist_run_package`, including its `verify_detailed_context`
check and embedded post-persist `verify_run_package` call
(`engine/simulation/artifacts.py:1256,1344`), rather than all upstream
diagnostic/parquet writes. Execution-phase `package_verifier` and
`fresh_b2_requests` counts include this nested independent verification.
The execution-phase inclusive `package_verifier` seconds/count explicitly
report the nested package verification; subtracting those seconds from
inclusive persistence yields persistence excluding that nested call, still
including the earlier context verification. The separately timed explicit
post-run verifier and its counts are additional independent verification.
These categories must not be described as serialization-only costs.

Uninstrumented wall timing is the primary end-to-end result. The ratio of
instrumented to uninstrumented cold execution wall time reports observed
profiling overhead plus run-to-run variability; no causal overhead precision
is claimed from one pair. Missing counts/times in the timing pass are JSON null
(unmeasured), rather than zero. Instrumented counts are measured, and derived
per-module metrics are calculations from those measurements.

## Saved staged measurement results

Evidence: `.ai/validation/rb_post3d_08p1_measurements/staged_benchmark.json`.
The 1- and 10-module cases completed both uninstrumented and instrumented
cold/warm passes. The 50-module case completed its uninstrumented cold/warm
pass, then the full case timed out at 600.012 s. It is **not** a completed
instrumented 50-module workload. No 190-module workload ran.

| Modules | Uninstrumented cold execution wall / CPU (s) | Warm execution wall / CPU (s) | Cold / warm verifier wall (s) | Parent / child lifetime peak RSS (MiB) |
| --- | --- | --- | --- | --- |
| 1 | 34.682 / 34.644 | 28.184 / 28.135 | 12.446 / 12.440 | 203.648 / 159.688 |
| 10 | 59.609 / 59.563 | 53.345 / 53.348 | 12.632 / 12.667 | 211.008 / 160.086 |
| 50 (timing pass only) | 172.390 / 172.319 | 166.264 / 166.212 | 13.687 / 13.623 | 249.277 / 160.117 |

RSS is Linux process lifetime high-water RSS, not incremental allocation.
Instrumented parent/child peaks were 203.199/160.223 MiB (1 module) and
211.555/160.098 MiB (10). The uninstrumented parent peak difference between
1 and 10 modules is 7.359 MiB, or 0.818 MiB per added module; this includes
run variability and is not a heap-allocation measurement.

| Modules | Instrumented cold / warm execution wall (s) | Cold / warm verifier wall (s) | Cold / warm full physics during execution | Witness / transport calls |
| --- | --- | --- | --- | --- |
| 1 | 33.954 / 27.809 | 12.464 / 12.541 | 5 / 4 | 21 / 2 |
| 10 | 59.468 / 53.467 | 12.751 / 12.677 | 5 / 4 | 165 / 2 |

For both measured instrumented sizes, execution includes four fresh B2 requests
in persistence (two pre-write checks and two in its embedded disk verifier).
The separately invoked verifier adds two fresh B2 requests and two actual
physics evaluations: six fresh requests per complete execution-plus-verify run.
The cold producer adds one cached-path physics evaluation; warm producer adds
none. These counts describe the historical baseline before P2B1 optimization.
Worker initializations were zero (serial); each execution had one solver interval,
one attribution interval, one persistence and one embedded package verifier.
Module model and attribution module calls were 1 and 10 respectively.

Cold inclusive attribution was 1.909 s (1 module) and 19.600 s (10), with
module counterfactual slices 1.908 and 19.589 s. Warm attribution was 1.879
and 19.583 s. This is approximately linear in these two one-interval cases;
interval scaling and larger instrumented attribution scaling are unmeasured.
Cold inclusive persistence was 24.777/25.195 s, including embedded verification
12.291/12.675 s. Fresh B2 inclusive slices were 24.594/24.621 s. These nested
categories overlap; summing them double-counts work.

Instrumented/uninstrumented cold execution ratios were 0.9790 and 0.9976;
these are observed ratios including variability, not proof of negative overhead.

## Observed bottlenecks and bounded follow-up

The P2A cProfile evidence in `hotspot_summary.txt` and `caller_relationships.txt`
traced twelve `verify_detailed_context` calls across two runs: four from
`verify_run_package`, two from `persist_run_package`, six from attribution
source verification. Actual `_evaluate_numerical_candidate_physics` callers
were twelve fresh evaluator calls and one cached producer miss. The fresh
physics cumulative time was 113.834 s under profiling; do not substitute this
instrumented result for the uninstrumented timing table.

The source-level transaction analysis in the P2B1 document establishes which
checks are duplicates. Independent verifier boundaries still require fresh
physics. P2B1 changes only those transaction-local duplicates; updated wall
measurements and counts await the orchestrator.

Remaining per-module bottlenecks include real attribution counterfactual curves,
module IV assembly and nested branch/current solving. cProfile observed
2,627,173 `_branch_current_at_voltage` calls from `currents_at`, 63,705 parallel
branch solves from protected substring evaluation, and 17,660 module state calls
from the series adapter. Lambert-W current evaluation dominates the profiled
self-time ranking (41.701 s in `_lambertw_i_from_v`). These inclusive call
relationships are evidence of kernel work, not permission to approximate physics.
Witness calls grow from 21 to 165 while warm inclusive witness validation is
only 0.001/0.008 s; raw call counts alone do not establish the largest cost.
No numerical kernel, attribution algorithm or historical harness is modified.

## Verification handoff and readiness

Regression commands selected for the orchestrator (current outcomes **not run** by Codex):

```sh
pytest tests/unit/test_rb_post3d_08p1_benchmark_contract.py
pytest tests/unit/test_rb_post3d_08b3d2_activation.py
pytest tests/unit/test_rb_post3d_08b3d1_verification.py tests/unit/test_rb_post3d_08b3c_context_propagation.py tests/unit/test_rb_post3d_08b3b_snapshot_witness.py tests/unit/test_rb_post3d_08b2_region_physics.py
python scripts/benchmarks/rb_post3d_08p1.py > /tmp/rb_post3d_08p1.json
# Historical entrypoint only: do not rerun its 50-module stage for P2B1.
git status --short
git diff --stat
```

The orchestrator should also run the exact accepted Phase-6.9/6.10 compatibility
selection; its previous 358/8 result is not a current harness result. Contract
tests check staged limits, valid frozen fixture membership, missing opt-in denial,
forwarding identity/exception preservation, restricted patch construction and
explicit timeout/termination results without running the benchmark.

Prior `.ai/reports/claude_review_3.json` refers to B3D1 test diagnostics, not
P1: those existing tests are outside this task's allowlist. The accepted B3D2
baseline supersedes that historical review for baseline selection; no old test
or production file is edited here. Current regression outcomes must be supplied
by the orchestrator rather than inferred from that review.

**Pilot recommendation: qualification pending.** Saved baseline measurements do
not establish Huawei 190-module readiness, physical yield validation or
manufacturer approval. Current regression results and P2B1 before/after timing
remain the orchestrator's responsibility.

## Review round 1 response

Historical F1 staging gates and hard caps, F3–F5/F7 nested accounting and
measurement definitions, F6 validation/resource distinction, and F8 stderr
capture remain implemented in the unchanged harness.

The historical review's missing-measurement issue is resolved by the saved
staged JSON above. No new tests or benchmarks were executed by Codex. Earlier
B3D1 diagnostic findings concern a superseded task: current assertions already
use explicit-boolean witness errors, unpinned-source diagnostics, stale topology
binding and parameterization payload hash mismatch. No out-of-scope tests were
edited to address historical findings.
