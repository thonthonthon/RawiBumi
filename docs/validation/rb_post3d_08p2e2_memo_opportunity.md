# RB-POST3D-08P2-E2-R2B-S1 minimal diagnostic redesign

Authorization: bounded diagnostic implementation and synthetic tests only.
Baseline HEAD: `8ad1cfcd6165d8cdbb3104fc236c76f694dee955`.
Branch: `ai/rb-post3d-08p2-e2-r2a-memo-observe`.
Implementation status: S1 bounded implementation for independent Claude review.
The separately authorized, operator-executed E2-R2A 10-module pilot is complete
and immutable. S1 has **NOT_EXECUTED** a real workload or requalification.
**50_MODULE_NOT_EXECUTED**. Further execution requires separate authorization.
Review and implementation do not authorize a capacity change.

Only these three existing E2 files are authorized for S1 changes:

- `scripts/benchmarks/rb_post3d_08p2e2_memo_opportunity.py`
- `tests/unit/test_rb_post3d_08p2e2_memo_opportunity.py`
- `docs/validation/rb_post3d_08p2e2_memo_opportunity.md`

Production code, E1 harness/tests/report/evidence, dependencies and Git history
are unchanged. E1 remains `CLOSED_WITH_REGRESSION_WAIVER` under the active task;
this diagnostic does not reopen its regression disposition.

## Inspected implementation and ownership

Source inspection preceded implementation. The production implementation is
`shading/electrical/substring_reference.py`:

- `_BranchEndpointHolder.__init__` registers a fixed set of branch bindings.
  Each `_BranchBinding` owns its endpoint values and `currents` dictionary.
  Strong production references prevent object ID reuse during a holder's life.
- `bind` requires the same region-state mapping, branch object, series-region
  sequence and individual state objects. Changed bindings are uncached.
- `_branch_current_at_voltage` permits current memoization only for the **exact**
  frozen `AnalyticalRegionReferenceState` and `PVSystRegionElectricalState`
  types. Subclasses and arbitrary region implementations are ineligible.
- Its key is `(target.hex(), voltage_tolerance_v, current_tolerance_a,
  max_iterations)`. Voltage signed zeros differ. Tolerance/iteration equality
  follows Python's existing tuple semantics, including numeric type equivalence
  and equality of tolerance signed zeros. No rounding or normalization is added.
- The first 256 successful distinct keys are admitted, without eviction. Misses
  after saturation are evaluated again. Exceptions never admit current entries.
  Endpoint reuse remains a separate production mechanism, including on some
  current-memo-ineligible paths.
- The uncached function retains its existing single-region inverse and generic
  series bisection, including the value returned at iteration exhaustion.

`module_series_adapter.build_phase66_series_module_operating_model` creates a
holder captured by the model's voltage callback. The attribution bypass-off
builder in `dc_attribution.py` independently creates its own holder and imports
the memo function as a separate global binding. These are distinct ownership
domains, even when numerical inputs are identical. The reference solver's
parallel branch and branch-state functions resolve the memo through its global
binding. The only repository import alias found by the source search is the
attribution binding; installation also discovers other loaded standard-module
global aliases by function identity.

## Instrumentation and reconciliation

One wrapper is installed on the canonical memo binding and its discovered
aliases. It delegates to the captured original exactly once with unchanged
arguments, returns the original result object, and re-raises the original
exception object. It never calls `bind`, a region callback, a solver or pvlib
to obtain telemetry. It never writes a production memo or endpoint value.

A focused line tracer reads **original-frame locals** after key construction.
It observes the actual cache-hit return path and admission assignment path.
Successful admission also requires the original call to finish successfully
and the original dictionary size to grow by exactly one. Actual failures and
bypasses have separate counters. A profile hook independently counts calls to
the original memo and uncached functions. Eligible misses must each have one
uncached call; eligible hits must have none. The profile counts must reconcile
with completed wrapper events, including bypass dispatch and standalone
uncached invocations.

Every eligible event must also match the independently replayed 256-entry
policy's hit/miss and admission decision. The aggregate 256 miss count must
match the directly observed eligible misses. Any discrepancy invalidates all
counterfactual results. A successful-key replay that later fails also fails
closed rather than claiming that a hypothesis would hide the failure.

The exact JSONL journal includes sequence, phase, B2 requesting context, slot
serial, lossless key, actual hit/miss/bypass, success/failure, actual admission,
uncached-call count and directly observed nested `i_from_v` count. Records are
streamed to disk, hashed and size bounded; there is no retained event list.
After hook cleanup and journal flush/fsync/close, the child serializes exactly
one observation to immutable canonical JSON bytes. This detaches all aggregate,
ownership and memory fields from mutable observer dictionaries. It clears the
online slot/rank tables and removes the observer's replay reference **before**
creating the independent offline replay. The final report uses that snapshot;
its SHA-256 is checked again by the parent. Neither success nor failure cleanup
recomputes a report from released state. Slot retirement and event semantics
are unchanged; there are no weak references or external replay databases.

The writer exclusively publishes `X.json.events.jsonl.sha256` from its final
stream digest after a complete observation and a closed journal. A short write,
overflow or incomplete observation cannot publish completed journal evidence.
`verify_journal` independently rereads the bounded stream, checks sequence,
recomputes every capacity scenario, and hashes the exact raw bytes against the
sidecar. It requires nonempty, newline-complete rows and unchanged, valid sidecar
contents. A completed child requires identical digest, event count, byte count
and counterfactual aggregates, then the existing independent E1 count/numerical
gates. The parent independently streams and hashes final journal bytes again,
compares the sidecar and child identity, and only then permits `COMPLETED`.
Missing, malformed, truncated, mismatched or redirected sidecars fail closed.
These checks detect incomplete evidence; they do not provide an atomic multi-file
transaction or a guarantee against later modification of archived files.

Future execution additionally compares original memo, uncached and `i_from_v`
counts **for every phase** against the digest-validated immutable E1 counts
artifact for the selected cache run. It validates the baseline/counts artifact
identities, source and fixture inventories, numerical environment, workload
identity, numerical fingerprints, public-cache snapshots and completed
operations. Missing coverage, missing child output, disagreement or a failed
gate cannot produce `COMPLETED` evidence.

One successful-key rank table per slot models first-N admission at 256, 512,
1024, 2048 and 4096. The same table models unlimited admission **within the
explicit global successful-key bound**. Exhaustion invalidates that scenario
and the whole observation; it does not become an eviction policy. A separate
`last_key` hypothesis retains only the most recently successful eligible key.

The explicit **`256_plus_last_key`** hypothesis retains the original first 256
successful distinct admitted keys without eviction **plus** an additional
last-successful-key slot. A modeled hit occurs exactly when the access key has
successful distinct rank <=256 **or** equals that slot's immediately preceding
successful access key. Last-key state uses the production tuple
`(target.hex(), voltage_tolerance_v, current_tolerance_a, max_iterations)` and
its exact Python equality through lossless journal encode/decode. Voltage
`+0.0` and `-0.0` remain distinct; solver-option equivalences remain those of
the production tuple. Every successful eligible access, including an actual
hit on an admitted key, updates the last key. Failures do not update ranks or
last-key state and never become cached successes. Each branch slot in each
holder lifetime owns independent state, preserved across phase transitions.

Before saturation the hybrid has the same hits as the actual 256-entry memo.
After saturation a repeated unadmitted key can become a modeled hit, whereas
a nonrepeated unadmitted key misses. Returning to an admitted key always hits
and makes that admitted key the last successful key. The original 256 entries
remain retained. `successful_admissions` counts successful modeled misses
retained by a policy once per access, even when both mechanisms retain a key;
it does not count last-key pointer updates on modeled hits. Hybrid modeled
additional uncached evaluations are zero because it preserves all actual hits.
This scenario is included in online replay, offline verification, serialized
phase aggregates and completed-report validation. Its results remain conditional
on the same exact stream and pure successful outcomes.

The standalone `last_key` hypothesis can lose admitted-key hits: it also counts
extra uncached evaluations when an actual
256-entry hit would become a last-key miss, and reports the net evaluation
delta. Their additional `i_from_v` cost is `NOT_OBSERVED`: an actual cache hit
provides no kernel-cost measurement. Gross potential avoided calls therefore
must not be interpreted as net kernel savings for standalone `last_key` retention.

## Hook and lifetime coverage

The profiler establishes phases using original function code identities:

| Original frame | Phase |
| --- | --- |
| `detailed_backend._evaluate_interval` | producer |
| `detailed_attribution._evaluate_attribution_interval` | attribution |
| `parameterization._evaluate_numerical_candidate_physics` | B2 numerical acceptance |
| `artifacts.persist_run_package` | persistence |
| `artifacts.verify_run_package` | verification |

B2 takes precedence over enclosing phases; nested B2 preserves its original
requesting context. B2 parent-context counts duplicate B2 totals and must never
be added to them. Setup/dispatch/compatibility phases retain their own counters.
No phase transition resets a production holder's counterfactual state. Counts
belong to the phase of each access, while admission belongs to its slot lifetime.

Original holder-constructor returns register monotonically numbered holder and
slot lifetimes, creation phase, B2 context, creator source location and branch
order. New constructors overwrite object-ID lookup entries. Numerically equal
models, recreated holders and separate branch slots never share replay state.
The observer retains no holder, branch or state object. An active wrapper only
temporarily references its original memo dictionary. Synthetic weak-reference
checks establish that model-state lifetime is not extended after a call.

Installation requires fresh exclusive profile/trace hooks. Binding/code identity
checks cover memo aliases, uncached evaluation, holder initialization/binding,
pvlib and phase entry points at memo boundaries and cleanup. Changed bindings,
changed live capacity, unwrapped original calls, foreign threads and replaced
hooks invalidate telemetry. Cleanup restores aliases still owned by the observer,
including standard-module aliases imported during observation, and clears active
frame state. It preserves a foreign replacement instead of overwriting it.

## Numerical and behavioral safety

Telemetry callbacks catch and latch their own exceptions, including sink errors
and overflow. They stop collecting after a fault but allow the original solver
to finish with its own result or exception and its original cache admission.
Counterfactuals are then `NOT_OBSERVED`; partial direct counts are labeled
`PARTIAL_OR_NOT_OBSERVED`. Observer exceptions are never stringified or read
through custom exception attribute hooks inside a scientific call.

Exact option capture supports built-in finite float, int and bool key components,
with integers restricted to 64 bits for retention. Unsupported option objects,
nonfinite options and unknown key shapes invalidate coverage without extra
conversion, hashing or comparison of those objects. This restriction affects
diagnostic acceptance only; the original function still receives the arguments.

Actual `i_from_v` calls are profile events for the pinned original function.
The observer attaches descendant calls to their nearest original memo frame
only while its uncached evaluation is active. A hypothetical larger cache hit
can therefore be associated with that actual evaluation's observed call count.
`potential_avoided_observed_i_from_v` is a **conditional derived count**, not
invented kernel-call savings. It assumes the same exact stream, successful pure
outcomes and unchanged downstream dependencies. These observations do not prove
what a modified cache would do to the future access stream, endpoint state,
runtime or whole-run behavior. Instrumented timings establish no speedup.

## Bounds, watchdog and evidence

Proposed maximum controls are enforced before execution:

| Resource | Limit |
| --- | --- |
| selected telemetry events | 150,000,000 (default and maximum) |
| registered slot lifetimes | 4,096 |
| distinct successful slot keys, all lifetimes combined | 3,145,728 (default and maximum) |
| simultaneous wrapper/phase/uncached frames and kernel ancestry | 256 per category |
| loaded memo alias registry | 256 |
| scanned individual module namespace | 16,384 names |
| journal | 2,048 MiB; at most 4,096 bytes per row |
| child JSON read by parent | 32 MiB |
| child wall time, including imports, priming and independent replay | 900 seconds default; explicitly configurable up to 2,400 |
| child sampled resident memory | 4,096 MiB |

Using a conservative planning allowance of 1,024 bytes per retained key and
8,192 bytes per registered slot, the configured maxima give:

- Diagnostic key retention: `3,145,728 * 1,024 = 3,072 MiB`.
- Diagnostic slot retention: `4,096 * 8,192 = 32 MiB`.
- Online replay allowance: **3,104 MiB**; offline allowance: **3,104 MiB**.
- Sequential verification allowance, including 32 MiB for reporting:
  `max(3,104, 3,104) + 32 = 3,136 MiB`, not the sum of two live rank tables.

`diagnostic_key_retention_allowance_bytes`, `online_replay_allowance_bytes`,
`offline_replay_allowance_bytes` and `sequential_verification_peak_allowance_bytes`
report these separate planning quantities. Releasing Python rank graphs does not
promise immediate RSS reduction: allocator arenas/native libraries may retain
pages. Remaining nominal headroom under 4,096 MiB is 960 MiB, not a demonstrated
bound for the rest of the process. Neither the observed pilot bytes-per-key ratio
nor this allowance proves that 50 modules will fit.

These are planning estimates, **not measured RSS** or allocator guarantees;
production/native/import allocations are additional. The exact journal may
consume 2 GiB disk separately. Report, sidecars and temporary run artifacts
consume additional disk; production run-package size has not been measured here.

Modeled production incremental memory uses 1,024 bytes for each additional
entry beyond the first 256 **per slot**. Summing all observed slot lifetimes
is a conservative upper bound on simultaneous peak; no destructor observation
or assumed lifetime overlap reduces it. Last-key retained memory is reported
separately for standalone `last_key`. For `256_plus_last_key`, the incremental
allowance is one additional 1,024-byte entry per observed slot lifetime, at most
**4 MiB** at 4,096 slots. This conservative allowance also covers slots whose
last key already belongs to the first 256 or that have no successful access.
It does not increase the actual production memo's 256-entry capacity.
The diagnostic planning allowances are separate from the unchanged **256 MiB**
modeled incremental production-cache screening target and the unchanged
**4,096 MiB** sampled RSS cap. Incomplete
observations suppress whole-run modeled memory figures.

The parent owns a new child process group, samples Linux leader RSS every 20 ms,
enforces its wall deadline, kills the owned group and reaps the leader. E1's
unchanged OS SIGALRM child backstop also covers a missing parent and native
calls holding the GIL. RSS sampling is not a continuous hard ceiling and excludes
descendants/transient peaks. Missing RSS prevents a completed report. Abrupt
termination can leave a partial journal and no child JSON; the parent emits a
capped/failed status, never admissible opportunity counts. Parent report parsing,
raw-byte hashing and serialization are bounded separately and outside the child's
wall budget.

Future output is confined to `.ai/validation/rb_post3d_08p2e2/`. Existing output,
symlink redirects and occupied companion paths are rejected. For output `X.json`,
the retained files are `X.json`, `X.json.sha256`, `X.json.events.jsonl`,
`X.json.events.jsonl.sha256`, `X.json.child.json`, and `X.json.child.json.sha256`.
All sidecars hash exact file bytes. The new diagnostic report is schema version 2;
the qualified JSONL event representation is unchanged. The historical schema-1
pilot has no journal sidecar and remains immutable under its original contract;
S1 does not regenerate its files or retroactively certify it with the new verifier.
Failed artifacts are kept for diagnosis and must not be reused as completed
evidence. Temporary workload
directories are cleaned on normal exit; watchdog death may leave them in E2.
No E1 artifact is written, deleted, relocated or assigned a new fingerprint.

E2 records current HEAD/dirty state/environment/task digest, immutable E1
baseline/counts paths and raw digests, unchanged E1 source/fixture inventories,
workload identity, hook bindings and ownership, E2 harness digest, and loaded
source inventories before/after execution. Source, task and harness mutation
invalidates completion. The E1 harness fingerprint remains
`e0cf10a2952391a10efd24e3065f51646b0c4cd14886963b6f07ea26641fe2f4`.
Archiving ignored evidence and sidecars externally remains an operator step.

## Preregistered future screen

At **50 modules, warm**, the 1024-entry counterfactual must potentially avoid
at least **5% of the original whole-run 2,349,889 `i_from_v` calls** to prioritize
a capacity prototype: at least **117,495 observed-call equivalents**.
The denominator includes producer 545,723, attribution 1,590,686 and B2 213,480;
it is not the attribution-only denominator. Sum disjoint phase totals once.

The modeled incremental peak-memory target is **at most 256 MiB**.
`memory.modeled_incremental_bytes` is the cumulative across-all-slots hypothetical
production allowance, separate from diagnostic retention. Chronological peak
production memory is explicitly `NOT_OBSERVED`; there is no destruction timeline.
A cumulative modeled upper bound at or below the threshold establishes the
conservative modeled target (`MEMORY_SCREEN_MET`). Above it, no chronological
peak bound within the threshold is established: report **MEMORY_SCREEN_INCONCLUSIVE**
and `estimated_memory_target_established=false`, never a memory pass.
The overall decision is `SCREEN_MET` only when both call and modeled-memory
screens pass; otherwise it is `CALL_SCREEN_NOT_MET`, or `MEMORY_SCREEN_INCONCLUSIVE`
when the call criterion passes but memory remains inconclusive. The separate
`memory_screen` remains inconclusive even if the call criterion also fails.
Sampled process RSS is a fifth, independent quantity at parent-report level;
it includes diagnostic and production allocations and cannot establish this
incremental production-memory target. A different observed original
denominator, incomplete evidence or a 10-module run produces `NOT_OBSERVED`
for this screen. This is a prioritization screen, **not a production speedup gate**.

## Proposed CLI — NOT EXECUTED

After independent Claude review and separate execution authorization, from the
repository root, the proposed 10-module S1 requalification command (not authorized
here) is:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B scripts/benchmarks/rb_post3d_08p2e2_memo_opportunity.py \
  --modules 10 --intervals 1 --workers 1 --cache-state warm \
  --wall-cap-seconds 900 --memory-limit-mib 4096 \
  --max-events 150000000 --max-slots 4096 --max-keys 3145728 --journal-limit-mib 2048 \
  --reference-e1 .ai/validation/rb_post3d_08p2e1/r3-10-baseline-warm.json \
  --reference-e1-counts .ai/validation/rb_post3d_08p2e1/r3-10-counts-warm.json \
  --output .ai/validation/rb_post3d_08p2e2/s1-10-warm-memo.json
```

Only after acceptable requalification evidence and separate 50-module authorization
would the following explicitly enlarged wall cap be available:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -B scripts/benchmarks/rb_post3d_08p2e2_memo_opportunity.py \
  --modules 50 --intervals 1 --workers 1 --cache-state warm \
  --wall-cap-seconds 2400 --memory-limit-mib 4096 \
  --max-events 150000000 --max-slots 4096 --max-keys 3145728 --journal-limit-mib 2048 \
  --reference-e1 .ai/validation/rb_post3d_08p2e1/r3-50-baseline-warm.json \
  --reference-e1-counts .ai/validation/rb_post3d_08p2e1/r3-50-counts-warm.json \
  --output .ai/validation/rb_post3d_08p2e2/s1-50-warm-memo.json
```

E1 `prepare_workload` and `execute_cache_run` are reused without modification.
Warm priming is the entire original cold dispatch/replay/daylight-check/verifier
sequence, uninstrumented, with its original run ID. Initial clearing happens
once, and there is no intervening cache clear. The measured warm run uses the
original warm run ID. E2 supports one measured cold or warm selection per child;
it does not aggregate cold and warm for the 5% screen. Cold selection requires
immutable E1 artifacts covering that selection. A fresh observer is installed
after warm priming; preexisting holders are rejected rather than seeded by guess.

Standalone offline verification, after authorized journal creation:

```python
from scripts.benchmarks.rb_post3d_08p2e2_memo_opportunity import verify_journal
verified = verify_journal('.ai/validation/rb_post3d_08p2e2/s1-10-warm-memo.json.events.jsonl')
```

Match its digest/count/bytes and aggregates against the child observation;
offline replay alone cannot certify missing phase coverage, E1 parity or RSS.

## Synthetic validation and findings

The authorized test command is:

```bash
.venv/bin/python -B -m pytest -q -p no:cacheprovider \
  tests/unit/test_rb_post3d_08p2e2_memo_opportunity.py
```

Tests cover replay/admission/saturation through 4096, bounded no-cap exhaustion,
standalone `last_key` and `256_plus_last_key` behavior, unsuccessful evaluations,
signed zero and raw option equality,
distinct models, one-iteration generic solver exhaustion, stateful unknown laws,
changed bindings, original exception/result identity, sink faults, hostile
exception attributes, exclusive hooks, dynamic alias cleanup, missing coverage,
foreign threads, event/key/slot/journal/frame bounds, mocked watchdog outcomes,
immutable E1 call-count mismatch rejection and the preregistered screening edges.
Watchdog tests use a synthetic process stand-in; no workload subprocess executes.
CLI tests parse arguments and validate archived E1 artifacts read-only.
Ceiling tests cover the new default, permitted maximum, rejection above maximum in
CLI controls and configuration constructors, inclusive key-budget boundaries,
failure/repeat access at a full budget and rejection without replay-state
mutation. The maximum-boundary test seeds the global counter and retains just
one real key; it allocates no million-object table. A two-event journal tests
the reduced global budget across independent slots. Hybrid tests cover before
and after saturation, repeated/nonrepeated unadmitted keys, returning to an
admitted key, successful-hit last-key updates, failures, signed zero, option
equality, independent branch slots, online/offline agreement and JSON report
serialization/completion gates.

S1 additionally tests the inclusive key/event ceilings by seeding counters while
retaining tiny dictionaries, wall-cap boundaries, and unchanged resource caps.
Child orchestration tests replace fixture preparation and workload dispatch with
six analytical memo accesses, preserving real observer, snapshot, journal and
independent replay code. They assert online state is released before verification,
exactly one report is generated, snapshot digest/contents survive cleanup or
verification failure, and journal/sidecar disagreement prevents completion.
Parent tests use process stand-ins and independently reject missing/corrupt
sidecars, truncated journal bytes and modified snapshots. Short writes,
interrupted replay and telemetry overflow remain failed/incomplete evidence.
No real workload subprocess or fixture execution is used.

Validation result: **102 passed in 3.57 seconds**, using the command above with
`PYTHONDONTWRITEBYTECODE=1`. Both Python files passed in-memory AST/syntax
compilation and all three files passed whitespace checks. AST comparison against
the pre-S1 script confirmed unchanged journal rows, policy/event replay, and
observer hook/callback methods. Only constructor limits, final reporting/release,
verification orchestration, integrity and memory assessment changed.

Scope verification covered 795 inventoried paths: only the three authorized E2
files changed, with no added/removed paths, staging or Git history/branch changes.
All 792 protected paths remained unchanged. Protected file SHA-256 values were
compared except for the large pilot journal, whose size, nanosecond mtime and
inode were unchanged; it was not reread or rewritten. No real workload, benchmark,
profile, full regression, E1/pilot artifact edit or dependency change was performed.

## Historical pilot and remaining limitations

The immutable operator pilot at
`.ai/validation/rb_post3d_08p2e2/r2a-10-warm-memo.json` reports `COMPLETED` under
schema 1: 455,662 successful slot keys, 237 slots, 79 holders, 19,632,479 selected
telemetry events, 955,508 memo journal events, 253,385,238 journal bytes and
471,367,680 sampled peak RSS bytes (449.53 MiB). Its instrumented warm execution
was 395.080 seconds with 60.268 seconds explicit package verification. These
are archived diagnostic observations, not S1 measurements or speedup evidence.
They do not prove 50-module resource bounds, event volume or timing. The archived
pilot and E1 inventories are preserved; no sidecar has been backfilled.

S1 eliminates simultaneous live full replay tables. Python allocator retention,
other live objects, native allocations, transient RSS peaks, disk flush overhead,
sequential verification time and 2 GiB journal exhaustion remain risks. The
ceilings are limits, not a promise that either workload will complete. Parent
integrity hashing adds a bounded second raw-byte read outside the child deadline.
Multi-file output is not atomic; a killed process may leave exclusive partial
artifacts that must not be reused as completed evidence.

Preexisting holders, missing hooks/aliases, unsupported options, changed bindings,
foreign threads and reentrant memo streams invalidate observation. Bypass detail,
interrupt classification, and local/closure aliases remain existing limitations.
Unwrapped original calls are detected by profiling, but transient foreign binding
changes wholly between checked boundaries are not adversarially detectable.
Callbacks inspecting tracing, stacks or thread timing are outside the synthetic
behavioral-equivalence evidence. Nonuniform, active bypass, reverse-domain, dark
and representative stateful-callable workloads remain unqualified by S1. Existing
numerical/E1/B2 gates remain mandatory for any future authorized measurement.

Independent Claude review should focus on snapshot lifetime and exception paths,
release-before-replay ordering, sidecar finalization and child/parent completion
gates, boundary arithmetic, cumulative-versus-peak memory screening, unchanged
256/hybrid replay and observer callback order, source/fixture/E1 parity gates,
and preservation of pilot evidence. This implementation does not claim that
independent review, requalification or a production performance gate has passed.

**50_MODULE_NOT_EXECUTED**.
