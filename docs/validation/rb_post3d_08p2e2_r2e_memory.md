# R2E synthetic M0/M1 memory harness

Implementation only. No M0a, M0b, M1, benchmark, numerical workload or test was
executed by the implementer. Verification output belongs to the orchestrator.

**M0/M1 EXECUTION HOLD — M2/M3 HOLD — PRODUCTION IMPLEMENTATION HOLD —
PERFORMANCE CLAIM HOLD.**

The only deliverables are:

- `scripts/benchmarks/rb_post3d_08p2e2_r2e_memory.py`
- `tests/unit/test_rb_post3d_08p2e2_r2e_memory.py`
- this document

Production code is never imported or changed. The memo limit remains 256. The
builder inspected the frozen branch/HEAD and source bytes, and found the declared
baseline. This inspection was not an M0a run. The three preexisting E2 files were
identified by their declared hashes and left untouched. No measurement report or
default output directory was created.

## Frozen baseline and preflight

Defaults are branch `ai/rb-post3d-08p2-e2-r2a-memo-observe`, HEAD
`5a88b22eb3633d5b90282416bc8f87f4a96c9bb6`, and source SHA-256
`45157f6a93c9e066b54ddffe70875cf06bed4a17816ca8a0cd797d4120b1a3ba` for
`shading/electrical/substring_reference.py`.

The source guard compares the exact bytes, then checks the AST for exactly one
module-level memo-limit assignment to integer 256. Boolean, floating, missing,
duplicate and augmented assignments fail. The production file is read as data.

Future M0a runs in a fresh child with a ten-second parent watchdog. It records and
checks CPython 3.12.3, build/compiler and pymalloc/debug-build information, Linux
kernel and architecture, GC state/thresholds, existing tracemalloc or trace/profile
hooks, development mode, allocator environment, effective `PYTHONHASHSEED=0`
(including its interpreter flag), OS page size, CPU affinity, boot ID, git dirty
state, `/proc/self/status`, `smaps_rollup`, meminfo,
swap devices, THP enabled/defrag settings and cgroup v2 memory controls.
`clear_refs` is checked for existence and write access **without writing**.
Git inspection disables optional locks. Missing required fields, unknown units,
unknown cgroup layouts and incompatible interpreters/platforms fail closed.

CPU affinity from `sched_getaffinity` is required. The cgroup's
`cpuset.cpus.effective` is optional recorded data: a missing file is recorded as
`ABSENT_CONTROLLER_NOT_ENABLED`, since a cgroup v2 memory controller can operate
without an enabled cpuset controller. A present empty or malformed CPU set, a
literal sentinel in the file, or a permission/read error still fails closed.
The `memory.*` and `memory.events` requirements remain mandatory. Calibration
identity binds either the observed CPU set or its absence sentinel, so a change
in controller availability invalidates prior calibration.

Linux feature availability is necessary; it does not establish that a WSL2 kernel
has acceptable measurement behavior. The report records its actual release. The
R-NULL empirical reset check remains mandatory, and owner acceptance of the host
remains pending. Only the known cgroup v2 filesystem layout is implemented;
unsupported layouts require review rather than a fallback.

After the owner commits the harness, the frozen HEAD changes. Future operators
must explicitly supply the newly approved expected HEAD/branch. These arguments
never override the immutable production source hash or the limit of 256.

## Calibration and workload

M0b launches these fresh processes sequentially, once each, with 40 seconds each:

| Role | Measurement | Acceptance interval |
| --- | --- | --- |
| R-NULL | Untraced, no intentional payload in the measured window | VmHWM increase 0–4 MiB |
| R-KNOWN | Untraced 16 MiB page-touched bytearray | RSS increase 12–24 MiB |
| T-KNOWN | Traced 16 MiB bytearray | Traced-current increase 95–105% of 16 MiB |

Every RSS child first allocates and releases an 8 MiB page-touched reset probe,
then collects GC, **before** the measured window. There is one reset attempt. The
only permitted write is the ASCII value `5` to that child's own
`/proc/self/clear_refs`, after fresh TASK authorization and an active RSS-child
check. Verification requires an independently observed VmHWM above VmRSS before
reset, a lower VmHWM afterward, and exact equality of VmHWM and VmRSS afterward.
This conservative equality rule fails closed if instrumentation/allocator noise
prevents proving the reset. A successful write by itself is insufficient. These
probe bytes are not part of R-NULL's measured window.

After this verified reset, successive Linux/WSL VmHWM observations are not
required to be monotonically nondecreasing. The parent no longer requires
`post_release.VmHWM >= retained.VmHWM >= before.VmHWM`, and applies no replacement
tolerance or corrected readings. This shared RSS-payload validation change applies
to both M0b and M1. Strict parsing, required fields, nonnegative raw integer
readings, per-snapshot `VmHWM >= VmRSS >= RssAnon` and smaps
`Rss >= AnonHugePages` remain mandatory. Reset verification semantics and all
calibration intervals in the table above remain unchanged. In particular, a
negative R-NULL retained-minus-before VmHWM still fails its 0–4 MiB bound.

The harness prevents its own in-window resets by construction: there is one
`clear_refs` write site, guarded by fresh authorization and active RSS-child
identity, and each RSS measurement calls it exactly once before the `before`
snapshot. A VmHWM difference alone cannot establish whether an external actor
reset the counter during the window; the harness does not detect such external
resets from these readings. No hidden reset or retry was added.

The owner-provided historical R-KNOWN observation had retained VmHWM 41,664,512
bytes and post-release VmHWM 41,549,824 bytes: a signed difference of −114,688
bytes (−112 KiB). A synthetic regression uses those exact readings and shows that
this difference alone does not invalidate an otherwise correct calibration. This
is historical evidence, not a new measurement. The original failed M0b report
remains `INVALID_EXPERIMENT` and is preserved unchanged; it is not reclassified,
regenerated or reusable as a passing calibration. Binding still requires a stored
passing outcome and matching harness/TASK/provenance, including the harness hash
changed by this correction.

The pre-window spike can still affect later allocator behavior. Under typical
glibc defaults the 8 MiB bytearray can be mmap-allocated; freeing that mapping can
raise the dynamic mmap threshold to about 8 MiB and the trim threshold to about
16 MiB. This can change heap-versus-mmap placement and heap trimming for later
allocations, potentially affecting post-release VmRSS. The child environment
strips `MALLOC_*` and `GLIBC_TUNABLES` overrides, but the harness does not record
the glibc version. This is a possible mechanism, not a measured effect or a
guarantee of allocation placement or threshold values. Being outside the reset
window does not remove its possible influence on allocator state.

M1 is blocked by any calibration failure. Standalone M1 additionally requires an
existing M0b report's explicit SHA-256 and matching sidecar. It recomputes the
calibration decision and binds the TASK, harness and source hashes, expected Git
baseline and measurement identity (host boot/kernel/build, allocator, GC, affinity,
cgroup configuration and THP settings). Combined execution binds the exact
canonical calibration payload by SHA-256 in the consolidated report.
Binding also requires the stored VmHWM diagnostic evidence to match its
recomputation exactly, including signed integer types and the informational label.

M1 uses exactly 512 independent plain dictionaries. G256 retains 131,072 entries;
G1024 retains 524,288, an additional 393,216 entries. The six fresh children, with
120 seconds each, are:

1. T-BASE
2. T-CAND
3. R-BASE
4. R-CAND
5. R-CAND
6. R-BASE

Each slot sees the same capacity-independent deterministic stream: 1,024 unique
voltages including both signed zeros, repeat hits, and two final overflow keys.
The G256 retained contents are the prefix of G1024. Keys use
`(float.hex(voltage), voltage_tol, current_tol, max_iterations)`; the tolerance
floats are shared across keys and slots, hex strings are constructed per request,
and retained value floats are distinct runtime objects. `max_iterations=200`
matches the production default. Admission is one
`d[key] = value` at a time, retaining the first N keys, without pre-sizing, bulk
update, eviction or global capacity. Occupancy is measured per slot and in total.
Values are synthetic; there is no physical model or electrical calculation.

The full unshared-tolerance sensitivity workload is deferred. Only tiny identity
tests exercise unshared objects. Tests inspect CPython dictionary growth at 171,
342 and 683 using at most 684 integer-key entries, without extra measurement
children. Policy C (Producer=256, Attribution=512, B2=1,024) is not implemented.

## Instruments, outcomes and limits

Traced children report Python traced baseline/current/peak and post-release
current/peak. RSS children report VmRSS, measured VmHWM, RssAnon, VmSwap,
smaps-rollup RSS/AnonHugePages/Swap and post-release readings. A traced child never
takes RSS measurement snapshots; an RSS child never starts tracemalloc. The parent
samples RSS solely to enforce its resource ceiling, including for traced children.
Those samples are explicitly not a measured peak and may miss brief spikes.

M0b adds `calibration.vmhwm_signed_differences` within the existing v1 report
schema. It contains `interpretation: "informational_only"` and an object for each
of `R-NULL` and `R-KNOWN`, with these signed integer byte differences:

- `retained_minus_before_bytes`: retained VmHWM minus before VmHWM.
- `post_release_minus_retained_bytes`: post-release VmHWM minus retained VmHWM.

These are raw differences without clamping, absolute values or invented corrected
VmHWM readings. They add no PASS/FAIL gate. The existing R-NULL bound still uses
its retained-minus-before VmHWM value, as before. Diagnostic evidence is present
for both passing and out-of-bounds/swapping calibration outcomes after child
validation; malformed or incomplete measurements fail closed without partial
diagnostics. The embedded/bound calibration object carries this diagnostic field;
the prospective M1 classification rule is described below.

Three kinds of evidence must be interpreted separately:

- Active-window memory evidence: before-to-retained readings, VmHWM within the
  verified reset window, window increments and retained smaps-rollup Rss describe
  the synthetic allocation window.
- Post-release residual memory evidence: post-release VmRSS reflects resident
  memory after payload release and GC, including allocator retention and trimming.
  It does not directly measure retained payload size; the preparatory spike can
  influence it through the allocator mechanism described above.
- AnonHugePages evidence: before, retained and post-release readings test
  comparability of huge-page backing between the paired processes. They do not
  establish that huge-page behavior was identical throughout the window.

Reports preserve raw signed candidate-minus-baseline traced current/peak/increment,
each A1–B1 and A2–B2 RSS comparison, RSS means, and within-child window-increment
comparisons. Separate signed pairwise comparisons and means cover retained
smaps-rollup RSS/AnonHugePages/Swap and post-release VmRSS. Incremental bytes/entry
divides by 393,216. Negative traced current/peak/increment, retained RSS pairs and
means, before-normalized RSS window pairs, and retained smaps pairs and means
make M1 `INCONCLUSIVE`. Post-release VmRSS pairs and means remain signed diagnostics;
their negativity alone does not block prospective M1 qualification. Any difference
in AnonHugePages between paired baseline/candidate readings at the before,
retained or post-release point also makes M1
`INCONCLUSIVE`, with signed evidence identifying each point. This is an instrument
comparability check, without an additional numeric threshold. Observed swapping
also prevents a successful calibration/qualification of the synthetic allocator
experiment.

The v1 schema identifier and all existing comparison tables remain unchanged.
`unexplained_negative_metrics` remains the exact names-only list of **all** negative
metrics, including post-release VmRSS, in its original traversal order. This legacy
field is descriptive; it is no longer itself the acceptance gate. Two additive
lists identify the prospective decision explicitly:

- `acceptance_blocking_negative_metrics`: negative traced and retained comparisons.
- `post_release_negative_diagnostics`: negative released-RSS `pair_1`, `pair_2`
  and `mean` comparisons, in that order, omitting nonnegative comparisons.

Each entry includes `source` (the existing report field name), `comparison`
(`pair_1`, `pair_2`, `mean`, or `candidate_minus_baseline` for traced), `metric`,
and the four original comparison values: `baseline_bytes`, `candidate_bytes`,
`candidate_minus_baseline_bytes` and `incremental_bytes_per_entry`. Values and
integer/float types are copied without recomputation, clamping or absolute values.
Pair 1 compares A1/B1; pair 2 compares A2/B2, despite the B2-before-A2 child order.
The blocking list traverses traced current/peak/increment, RSS pairs, RSS means,
window pairs, smaps pairs and smaps means, preserving metric order in each table.
Only blocking negatives, observed swap and huge-page differences drive the
prospective `INCONCLUSIVE` decision after validation. Failed M0a/M0b qualification,
hash/provenance binding, role/mode validation, exact occupancy/capacity/admission,
source guards, parsing and reset verification retain their independent failure
paths. Invalid inputs return no partial negative diagnostics. No magnitude
tolerance or traced/RSS agreement threshold is introduced.

This policy is prospective only. The historical R2F-B report
`.ai/validation/rb_post3d_08p2e2_r2e/r2fb_m1_all_20261016T122043Z_601151.json`
remains immutable and `INCONCLUSIVE`, pinned by SHA-256
`292f407c3fb935b00932468c844f084bdefce25e43fe1762f3afc29bf0963cbe`.
Its literal readings in a mocked counterfactual qualify as
`M1_ALLOCATOR_CALIBRATED` while preserving the release differences −1,712,128,
−2,248,704 and −1,980,416.0 bytes. This does not reclassify or replace the report
on disk. The harness edit changes `harness_sha256`; existing M0b reports therefore
cannot bind to a standalone M1 using the edited harness. The execution hold remains
in force; no rerun, retry or new calibration is authorized.

THP enabled mode `always` can confound M1. Preflight still accepts it, but paired
AnonHugePages readings are very likely to differ and force `INCONCLUSIVE` under
the existing rule. Equal readings at the three sample points do not rule out
asynchronous khugepaged activity between samples. THP mode and its suitability
for a meaningful M1 are pending host-acceptance decisions, without a preflight or
M1 rule change here.

No `ru_maxrss` value is used or subtracted across processes.

`M1_ALLOCATOR_CALIBRATED` means instrument validity, exact occupancy, completed
children, mode separation, comparable huge-page readings, no observed swapping
and no acceptance-blocking negative deltas. It qualifies only synthetic allocator
and instrument behavior. It does not approve candidate-cache deployment, establish
a production chronological memory peak or qualify a 717-slot projection. There is
no invented numeric threshold for replicate agreement or traced/RSS agreement. Any such
future criterion requires owner approval. The outcome vocabulary distinguishes
`PREFLIGHT_PASS`, `CALIBRATION_PASS`, `M1_ALLOCATOR_CALIBRATED`,
`INFRASTRUCTURE_FAILURE`, `INVALID_EXPERIMENT`, `INCONCLUSIVE`, and `RESOURCE_LIMIT`.
Transport envelopes with `outcome=null` merely identify completed child IPC.

The optional 717-slot projection is deferred and reports `NOT_EVALUABLE`, labeled
as a projection. M1 cannot exactly model C's 512-capacity slots. There is no
production memory-screen pass claim. Every consolidated report fixes:

```text
production_chronological_peak=NOT_OBSERVED
production_memory_qualification=INCONCLUSIVE
```

The overall stage ceiling is interpreted as a combined 900 seconds, including a
50-second parent/report reserve: 10 + 3×40 + 6×120 + 50. The parent launches no
child after its 850-second measurement budget and uses a Linux real-time alarm
for the 900-second ceiling including reporting. Every child has a separate process
group. Deadline, sampled RSS over 1,024 MiB or excessive IPC leads to
`RESOURCE_LIMIT` and group termination. Spawn/proc failures yield
`INFRASTRUCTURE_FAILURE`, except for a narrowly recognized child-exit race:
missing process files (`FileNotFoundError`/`ProcessLookupError`) or status text
with all four required memory fields absent permit exit confirmation. The parent
checks exit immediately, then polls for at most 0.5 seconds, capped by the child's
remaining deadline and a finite poll count. It never retries the RSS read. Exit
confirmed within that grace does not itself constitute an infrastructure failure;
the existing deadline, IPC and final exit-code/JSON checks still apply. A child
still alive fails closed; reaching its deadline yields `RESOURCE_LIMIT`.
Permission errors, other read errors, partial/duplicate fields, invalid units or
values, inconsistent status and invalid injected RSS values fail immediately as
`INFRASTRUCTURE_FAILURE`, even if exit has become visible. The maximum guard RSS
remains the maximum of successful samples; its existing zero initial value when
none succeeded is not a fabricated exit sample. No children run concurrently;
no retries, relaxed limits or automatic reruns exist. Interrupted parent
supervision terminates a live child.

Children use `.venv/bin/python -P -s -B` with a minimal environment and a fixed
hash seed, stripping allocator, tracing, development, loader and Python path
overrides. `-I` is deliberately avoided because it ignores `PYTHONHASHSEED`.
The immutable hash-seed check also rejects `ignore_environment` mode.
Internal child mode also requires a bounded inherited-pipe permit bound to its
actual parent PID, role and TASK. Calibration children require preflight evidence;
M1 children require both preflight and successful calibration payload hashes. The
parent supplies these only after their gates pass. Calling the hidden child flag
alone cannot launch an unsupervised measurement. This is an accidental-execution
guard in a trusted Python process, not a security boundary against Python code
that deliberately forges its own handoff.

Future reports are confined to `.ai/validation/rb_post3d_08p2e2_r2e/`. CLI output
names must be simple `.json` filenames; arbitrary roots are not a CLI option.
The library root parameter exists for temporary-directory tests. Directory-descriptor
walks reject symlinks at every ancestor; leaf files use `O_EXCL|O_NOFOLLOW` and mode
0600. Both JSON and SHA-256 sidecar creation must succeed, with cleanup of only
newly created files on failure. Existing evidence is never overwritten. Reports
over 1 MiB are refused before creating the output directory. Sidecars hash the
exact UTF-8 report bytes. Future calibration reads enforce the same confinement,
regular-file requirement, size bound and no-follow policy.

Provenance includes TASK/harness/source hashes, expected and observed baseline,
dirty state, UTC timestamp, parent argv, child command templates and pipe permits, sanitized environment,
platform/build/host facts, instrument readings, limits, calibration lineage and
measured occupancy. Child IPC uses temporary files to avoid pipe deadlocks.
Each child's embedded stderr is capped at a 4 KiB byte preview, with the complete
byte count, SHA-256 and an explicit truncation flag. These diagnostics accompany
successful children, child failures and IPC-limit failures. The full stderr is
hashed incrementally rather than embedded, preserving report space for all
children and their instrument evidence. Nonzero-exit error text is also bounded.

## Future operator commands — NOT EXECUTED

These commands require separate owner approval, independent harness review and an
explicit authoritative TASK scope update. The CLI refuses all measurement stages
under the current TASK, even if its correct digest is supplied.

The future TASK must remove its `M0/M1 EXECUTION HOLD` and contain exactly one
affirmative line specifying the approved stages, for example:

```text
R2E_MEMORY_EXECUTION_AUTHORIZED: M0a,M0b,M1
```

The operator must supply that exact TASK's SHA-256. Each stage/child revalidates
the TASK bytes and stage membership. M0b requires M0a; standalone M1 requires M0a
and an already bound M0b report. `all` requires all three stage authorizations.
Merely adding a command-line flag does not release the current HOLD.

```bash
# NOT EXECUTED; replace every placeholder with reviewed values.
.venv/bin/python -P -s -B scripts/benchmarks/rb_post3d_08p2e2_r2e_memory.py --stage M0a --task-sha256 <approved-task-sha256> --expected-head <approved-head> --output preflight-unique.json
.venv/bin/python -P -s -B scripts/benchmarks/rb_post3d_08p2e2_r2e_memory.py --stage M0b --task-sha256 <approved-task-sha256> --expected-head <approved-head> --output calibration-unique.json
.venv/bin/python -P -s -B scripts/benchmarks/rb_post3d_08p2e2_r2e_memory.py --stage M1 --task-sha256 <same-approved-task-sha256> --expected-head <approved-head> --calibration-report <absolute-fixed-root>/calibration-unique.json --calibration-sha256 <exact-report-sha256> --output allocator-unique.json
# Alternative combined authorized run, without an external calibration report:
.venv/bin/python -P -s -B scripts/benchmarks/rb_post3d_08p2e2_r2e_memory.py --stage all --task-sha256 <approved-task-sha256> --expected-head <approved-head> --output combined-unique.json
```

Output names must be new. These examples are future alternatives, not an automatic
rerun sequence. Any change in bound TASK/harness/platform identity invalidates an
earlier calibration. M2/M3 have no implementation or operator commands.

## Orchestrator verification and pending decisions

The sole authorized test command, **not executed by the implementer**, is:

```bash
.venv/bin/python -m pytest -q tests/unit/test_rb_post3d_08p2e2_r2e_memory.py
```

Tests use tiny synthetic dictionaries, fake facts/clocks/processes/reset callbacks,
fabricated occupancy metadata and `tmp_path` report roots. Real collectors,
allocation probes, process spawning and real tracer startup are forbidden by a
test fixture, which also forbids the default watchdog proc reader, real process
group signals and real sleeps. Child-function tests replace probes with
eight-byte allocations, build only two tiny slots and use fabricated RSS/tracer
readings. They exercise
all calibration/M1 child roles, JSON serialization and parent payload validation.
Real anonymous pipes cover successful permit reading without starting processes;
successful CLI branches use fake stages/children, fake alarms and temporary report
roots. No full-size workload, real M0a, proc reset, default report-root creation or
measurement run occurs. Incompatible-platform assertions fail; no tests skip.
The real production source is read only for its byte/AST guard. Tests exercise
threshold boundaries, signed deltas, mode/occupancy rejection, report integrity,
calibration binding, no-retry failure paths and authorization refusal. Regression
coverage includes absent versus malformed cpuset data, mandatory memory controls,
distinct A1/B1/B2/A2 readings and window increments, signed huge-page/post-release
deltas, bounded noisy-child evidence and forbidden production claims/instruments.
Mocked watchdog regressions cover ordinary, already-visible and in-progress exit,
prior-sample maxima, continued live processes, malformed status and instrument
values, permission failures, bounded grace with a frozen clock, deadline expiry,
nonzero exit validation, interruption cleanup, permit-descriptor closure and
process-group cleanup. Isolated negative post-release comparisons now pin the
prospective diagnostic-only rule while retaining the legacy names and signed
values. Source-safety checks pin the experiment constants,
role order, report schema and single clear_refs write site. These are coverage
descriptions; test results must come from the orchestrator's targeted command.
VmHWM correction regressions cover the exact historical −114,688-byte difference,
monotonic observations, negative retained-minus-before evidence, unchanged R-NULL,
R-KNOWN and T-KNOWN bounds, reset verification failures, strict parsers and
per-snapshot relationships, malformed/incomplete/reordered payloads, one reset
before the window, and diagnostic integrity through report serialization/binding.
Prospective M1 regressions embed the historical R2F-B readings without depending
on gitignored artifacts. They pin all three release negatives, original comparison
tables and numeric types, nonnegative release cases, each traced blocker, retained
RSS/smaps pairs and means, before-normalized window negatives, swap and signed
huge-page differences at every snapshot, invalid resets/readings/roles/modes and
occupancy, failed calibration, legacy traversal compatibility, deterministic
labels, and temporary report round-trip/SHA-256 integrity. The historical report
and its sidecar remain unchanged; on-disk evidence integrity is checked separately
from these portable fake-instrument tests.

Pending owner decisions are host acceptance (including WSL2 and whether THP
`always` is acceptable), any additional M1 agreement criterion, and confirmation
of the combined 900-second interpretation.
The harness conservatively uses feature/reset validity, no agreement threshold
and the combined ceiling, as directed by the READY plan. These choices authorize
no execution. Production chronological peak, production memory qualification,
policy C, full unshared sensitivity, M2/M3 and speedup claims remain outside scope.
