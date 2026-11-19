# F2-A passive memory observer core

This is an isolated, standard-library-only reconciliation core for **fake,
in-memory evidence**. It performs no file reads, instrumentation, process
creation, production import, callback installation or simulation. There is no
CLI. M0/M1 execution and production experiments remain on hold. The production
256-entry cache and model-owned `_BranchEndpointHolder` remain unchanged.

The only additions are the observer module, its fake-input unit tests and this
document. No production memory qualification or policy C qualification follows
from completing this task.

## Frozen scientific context

S3 observed 239 cumulative holder lifetimes and 717 cumulative slot lifetimes
in a 50-module, one-interval, one-worker warm workflow. These were not
simultaneous residents. S3 reached producer, attribution and
b2_numerical_acceptance; other phases were not reached. Its chronological peak
was not observed and its outcome was `MEMORY_SCREEN_INCONCLUSIVE`. The 256 MiB
target remains provisional and is not an acceptance PASS.

R2F-E `M1_ALLOCATOR_CALIBRATED` is synthetic only. Actual production memory
qualification remains INCONCLUSIVE. Spawn parents and workers require separate
accounting. Summing worker lifetime high-water marks cannot establish a
simultaneous system-memory peak.

## API and input contract

Import `scripts.benchmarks.rb_post3d_08p2e2_r2f_f2a_observer`. Its public pure
helpers are `parse_status`, `parse_stat`, `parse_smaps_rollup`,
`parse_memory_events`, `reconcile`, `canonical_bytes`, `digest`, `seal`,
`verify_integrity`, `signed_difference` and `compare_reports`.

`reconcile(configuration, evidence)` returns a JSON-safe report. Both arguments
are detached from caller-owned objects. Malformed JSON-safe evidence produces
structured report reasons. Inputs that cannot be faithfully preserved as JSON
(non-string object keys, non-finite numbers or arbitrary Python objects) raise
`EvidenceError(MALFORMED_INPUT)` before reporting. Standalone parsers also raise
`EvidenceError` with `code`, `detail` and `outcome` attributes.

All times are nonnegative **integer monotonic nanoseconds on one caller-declared
clock**. No wall clock or clock instrument is consulted. Booleans are rejected
as integers. Identity is `[positive_pid, nonnegative_starttime_ticks]`; the key
in report maps is `pid:starttime`. Starttime remains in kernel clock ticks,
without a guessed clock-frequency conversion.

Configuration has no threshold defaults:

```json
{
  "max_read_skew_ns": 5,
  "max_frame_gap_ns": 100,
  "required_phases": ["producer"],
  "topology": {
    "start_method": "spawn",
    "parents": [[100, 10]],
    "workers": [{"identity": [200, 20], "parent": [100, 10]}],
    "max_concurrent_workers": 1
  }
}
```

Numbers above are artificial example values, not proposed measurement policy.
The complete process roster includes replacement lifetimes. Multiple parents
are permitted. Worker concurrency is a global upper bound, not an inferred
expected worker count. A declared process that never starts is missing
evidence. A reading or start for an undeclared helper fails closed. Parents
must start before their workers and exit after them. A reused PID must have a
strictly larger starttime, after the previous lifetime exits. The roster and
lifecycle records are caller assertions, not discovered operating-system facts.

The phase vocabulary, copied without importing production code, is `setup`,
`producer`, `attribution`, `persistence`, `verification`, `dispatch`,
`b2_numerical_acceptance`, `compatibility_controls`. Required phases are an
explicit nonempty unique subset. Conservatively, each declared process lifetime
requires a complete aligned observation in each required phase. Callers must
choose required phases appropriate to the artificial workload; the observer
never infers that an unreached phase was covered.

Evidence contains these fields:

- `input_id`, `workload_id`, `independent_run_id`: nonempty strings. Independence
  is declared by the caller, not certified by the observer.
- `conditions`: a JSON object describing the declared workload conditions.
- `records`: ordered event objects, described below.
- `declared_record_count`, `declared_frame_count`: nonnegative integer manifest
  counts, including all supplied records and frames.
- `truncated`: explicit boolean evidence-truncation marker.
- `holder_coverage`: declarations such as
  `{"identity":[100,10],"phase":"producer","events_complete":true}`. A unique
  declaration for every process and required phase is necessary even when no
  artificial holders were created. Observed phases also require declarations.
  Absent or false coverage is incomplete.

Every record has `sequence`, `time_ns`, `kind`. Sequences start at zero and
strictly increase by one. A gap is retained as incomplete evidence. Duplicate
or reversed sequences are invalid. Timestamps never decrease; frame capture
timestamps strictly increase. Equal event times are ordered by sequence; the
observer does not invent sub-timestamp ordering. The raw record list retains
this order. Counts and markers are assertions checked without repair.

Record kinds and their additional fields:

| Kind | Required fields and semantics |
| --- | --- |
| `START` | `identity`, `role` (`parent` or `worker` matching the roster), `ppid`, `phase`. Parent ppid is declared here; worker ppid must equal its declared parent's PID. |
| `PHASE` | `identity`, `phase`; must change the current live phase. |
| `EXIT` | `identity`; closes an existing live lifetime. |
| `CREATE`, `RELEASE` | `identity`, `holder_id` (nonempty string), `phase`, `slots` (nonnegative integer). Phase must match the process's current phase. |
| `FRAME` | `expected_live`, `readings`, optional frame `read_start_ns`/`read_end_ns`, optional `cgroup`. `time_ns` is capture completion. |

Optional `role` or `ppid` on live lifecycle/holder records must agree with START.
Each reading supplies `identity`, `phase`, `status` text, `stat` text, optional
`smaps_rollup` text, optional paired `read_start_ns`/`read_end_ns`, and optional
boolean `final` (default false). Pid and PPid must agree between status, stat
and START; stat field 22 must match the identity starttime. A reading before
START or after EXIT is invalid. Decreasing VmHWM within a lifetime is invalid.

`EXIT` has a complete final observation only if a valid, explicitly `final`
reading at the exit timestamp was in a complete aligned frame before EXIT in
sequence order. Otherwise exit is recorded with an incomplete-final-observation
reason. Open process and holder lifetimes are flagged at the end.

## Parsing supplied text

Status requires `Pid`, `PPid`, `VmRSS`, `VmHWM`, `VmSwap`. VmHWM must be at least
VmRSS. Smaps rollup requires `Rss` and `Swap`, and permits its address-range
`[rollup]` header. Other supplied smaps fields are also parsed as kB. Status
`Vm*`, `RssAnon`, `RssFile`, `RssShmem` and `HugetlbPages` are parsed as memory
fields. Their kB values become integer bytes using 1024. Other status fields
remain raw metadata even when their values end in `kB`; names such as
`worker 12 kB` and `proc_kB` are valid. Known memory keys still require kB units.
Other status metadata (for example Name and CPU masks) is not interpreted, but
must have colon-delimited unique field names. Missing required fields,
duplicates, wrong units, malformed integers and negative memory values fail.

Stat splits at the final closing parenthesis, preserving spaces and embedded
parentheses in comm. It requires at least 22 fields, checks numeric tokens and
extracts starttime from field 22. Linux signed fields, including tty_nr, tpgid,
cutime, cstime, priority, nice, itrealvalue, rss, exit_signal, processor,
cguest_time and exit_code, may be negative. Identity, ppid, starttime and other
unsigned fields may not. Parsing does not mistake negative nice for a corrupt
identity.

Supplied cgroup v2 memory.events requires `low`, `high`, `max`, `oom`, `oom_kill`.
Optional `oom_group_kill` and future lowercase/underscore counter names are
preserved if present. Values are counts, never kB. Missing optional fields stay
absent; a missing text/read remains null or absent, never an invented zero.

## Frames, memory and holder metrics

The expected identity set must match the reconciled live set, and every
expected identity must have exactly one valid reading. Missing workers or
parents withhold that frame's aggregate while retaining valid per-process
status, HWM and optional smaps data. Unexpected or duplicate readings invalidate
the frame. A frame with no live processes does not establish an aggregate.
If `expected_live` itself is malformed, contains duplicate identities or names
an identity that is not live, validation aborts before processed readings or a
processed frame are recorded. All supplied readings remain in raw evidence;
the overall report is INVALID_EVIDENCE. This retained limitation differs from
a valid expected set with missing/unexpected readings, where valid per-process
readings are preserved separately.

Read bounds must lie within the current process lifetime and phase and end no
later than capture time. A frame envelope may bound readings whose individual
bounds are absent; supplied individual bounds must lie inside that envelope.
Without complete bounds alignment is `NOT_ESTABLISHED`. `read_skew_ns` is latest
read end minus earliest read start; `capture_age_ns` is capture time minus
earliest read start. Both must be bounded by `max_read_skew_ns` (checking age
also bounds the span). Excessive age/skew withholds the aggregate. An invalid
window also withholds it, without discarding parsed process values. Accepted
alignment is labelled `BOUNDED_SEQUENTIAL_READS`, never atomic.
Successive supplied read windows for one stable identity may touch but cannot
overlap or reverse; their order is checked independently of frame capture order.

Only complete, acceptably aligned frames sum status VmRSS across parents and
workers. The report's maximum is a **sampled RSS sum**, not a chronological peak
or system-memory measurement. Shared pages can be counted repeatedly. Smaps
Rss is summed separately only if every process in that eligible frame supplies
it. VmHWM is reported separately per stable identity as the maximum observed
reading: an observed lower bound on that lifetime's high-water mark. No sum of
VmHWM is computed or emitted.

Frame gaps, initial START-to-first-frame gaps and trailing records beyond the
last frame are checked against the supplied maximum gap. A clean sample cannot
repair a missing interval. Declared frame-count mismatch, zero frames and
missing process coverage fail closed. Valid samples remain visible when the
overall record set is incomplete or invalid; consumers must examine outcome.

Optional cgroup input is a frame object such as
`{"source_id":"fake-cgroup","time_ns":10,"memory_events":"low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n"}`.
It remains separate from process RSS with its own supplied timestamp and
hierarchical cumulative event-counter semantics. Timestamps strictly increase
per source and cannot be after capture. Previously seen counters must not
decrease or disappear. An absent reading is incomplete rather than zero.
Although cgroup input is optional to supply, `OBSERVATION_COMPLETE` requires a
valid cgroup `memory.events` reading in every frame; absence yields
`MISSING_CGROUP_DATA` and `INCONCLUSIVE`. No zero counters are synthesized. A
nonzero `oom`, `oom_kill` or `oom_group_kill` fails closed, as does nonzero `max`.
`low` and `high` are retained pressure diagnostics and do not independently
change outcome. No counter baseline subtraction hides prior OOM/limit events.
Nonzero status VmSwap or smaps Swap also fails closed. None of these event
counts is added to process RSS.

Holder IDs are scoped to stable process identity. Identical IDs in different
processes are allowed. Reuse within one identity, including after release, is
rejected. Release requires a matching live holder and the original slot count.
A release for an ID known only in another process is a cross-process release.
Lifecycle phase may change between creation and release; lifetime counts and
concurrency buckets remain attributed to CREATE phase.

Cumulative counts include every valid CREATE, including open lifetimes, without
inferring missed creates. Maxima are observed concurrent holder and slot counts
per identity (ALL and CREATE-phase buckets) and across all identities by phase.
Event sequence order resolves equal times. These counts are artificial
instrumentation evidence, never measured RSS or a production projection.
An exited process is excluded from later concurrency even if a RELEASE was
missing. Its unreleased lifetime remains open in the evidence, with no invented
release event or release timestamp.
Maxima maps are sparse when no events were supplied. Lifetime coverage and event
coverage have separate flags; invalid records and missing/truncated declared
coverage prevent a complete event-coverage flag. Overall `coverage_complete`
requires an entirely clean observation set.

## Reason-code contract

`INVALID_EVIDENCE` dominates `INCONCLUSIVE`. With neither class of reason,
outcome is the neutral `OBSERVATION_COMPLETE`. This describes observer evidence
only and is never a memory-budget acceptance result. `REASON_CLASSES` is the
canonical code-to-class mapping; reports retain details and sequence references.

| Class | Reason codes |
| --- | --- |
| INVALID_EVIDENCE: fields/parsers | `MALFORMED_INPUT`, `MISSING_FIELD`, `DUPLICATE_FIELD`, `NEGATIVE_FIELD`, `INVALID_UNIT`, `INCONSISTENT_COUNTER` |
| INVALID_EVIDENCE: identity/lifecycle | `INVALID_IDENTITY`, `PID_REUSE_ANOMALY`, `DUPLICATE_RECORD`, `OUT_OF_ORDER`, `UNKNOWN_WORKER_TOPOLOGY`, `IDENTITY_CONTRADICTION`, `INVALID_PHASE`, `INVALID_LIFECYCLE`, `UNEXPECTED_PROCESS`, `INVALID_READ_WINDOW` |
| INVALID_EVIDENCE: holders | `DUPLICATE_HOLDER`, `INVALID_RELEASE`, `CROSS_PROCESS_RELEASE`, `SLOT_COUNT_MISMATCH` |
| INCONCLUSIVE: missing/truncated evidence | `SAMPLE_GAP`, `MISSING_PROCESS`, `INCOMPLETE_FRAME_SET`, `EVIDENCE_TRUNCATED`, `SEQUENCE_GAP`, `DECLARED_COUNT_MISMATCH` |
| INCONCLUSIVE: coverage/lifetimes | `MISSING_PHASE_COVERAGE`, `MISSING_ROLE_COVERAGE`, `OPEN_PROCESS_LIFETIME`, `EXIT_WITHOUT_FINAL_OBSERVATION`, `OPEN_HOLDER_LIFETIME`, `INCOMPLETE_HOLDER_COVERAGE` |
| INCONCLUSIVE: alignment/contamination | `ALIGNMENT_NOT_ESTABLISHED`, `EXCESSIVE_READ_SKEW`, `SWAP_OBSERVED`, `OOM_OBSERVED`, `CGROUP_LIMIT_EVENT`, `MISSING_CGROUP_DATA` |

## Reports, integrity and comparisons

Schema is `rawibumi.passive-memory-observer.f2a.v1`. Reports include configuration,
input/workload/run IDs, the complete raw supplied evidence, its SHA-256,
identities, lifecycle and role/phase coverage, per-process observations/HWM,
sampled aggregate frames, separate cgroup readings, holder metrics, reasons,
completeness and caveats. Raw malformed JSON-safe records remain raw; valid
per-process data remains separately accessible. Evidence is never repaired or
extrapolated. No observation is read from the machine.

Report shape retains a known limitation: configuration-invalid reports omit
the top-level input/workload/run IDs and derived metric/coverage sections;
supplied IDs remain in raw evidence when present. Consumers must permit these
sections to be absent. Frames include `capture_age_ns` only when complete read
bounds establish its value. An absent key does not mean zero. Comparison
validation refuses malformed or incomplete reports without assuming those
sections exist.

Canonical serialization uses sorted object keys, two-space JSON indentation,
UTF-8, one trailing newline, and `allow_nan=False`. Ordered input lists retain
their order; derived identity maps and reading lists have deterministic order.
SHA-256 covers canonical report bytes **excluding `integrity`**. The integrity
object declares algorithm, scope and digest. `verify_integrity` checks it;
this detects accidental modification, not authenticity or truth of declarations.

`compare_reports(baseline, candidate)` returns `COMPARABLE_FAKE_OBSERVATIONS`
only for two integrity-verified reports of this schema with outcome
`OBSERVATION_COMPLETE`, empty reasons, `coverage_complete: true`, the pinned
production envelope and `FAKE_INPUT_ONLY` input kind. Configuration (including
topology), workload and declared conditions must match. Both sampled maximum
RSS metrics must be nonnegative integer bytes. Callers must declare distinct
independent run IDs and input IDs; input hashes and raw record lists must
differ. Relabelled identical observations are refused conservatively. The
function cannot certify physical independence.

Every comparison includes `baseline_outcome`, `candidate_outcome`,
`baseline_reason_codes` and `candidate_reason_codes`. Codes are sorted unique
strings, retaining each side's evidence status inside the sealed comparison.
An unreadable outcome or malformed reason list becomes null, never an invented
status or an empty list. Source-report SHA-256 fields cover the complete sealed
input report; an unreadable or non-JSON report has a null source digest.

Every other case returns sealed `NOT_COMPARABLE` with
`candidate_minus_baseline_sampled_max_rss_bytes: null`. In particular,
truncation, OOM, swap and absent-worker evidence cannot produce a numerical
comparison even if some sampled metrics remain available. Comparison-specific
reasons are `INTEGRITY_MISMATCH`, `SCHEMA_MISMATCH`, `INVALID_EVIDENCE`,
`INVALID_ENVELOPE`, `CONDITIONS_MISMATCH`, `INPUTS_NOT_INDEPENDENT`,
`MISSING_SAMPLED_METRIC`, `INPUT_NOT_OBSERVATION_COMPLETE` and `MALFORMED_REPORT`.
`INPUT_NOT_OBSERVATION_COMPLETE` also rejects a complete label contradicted by
nonempty reasons or a false/missing coverage flag. `MALFORMED_REPORT` covers
invalid report/container types, malformed outcome/reason metadata, missing
required comparison fields and non-JSON values, without raising AttributeError
or copying unsafe values into the result.

For complete comparable inputs, the only metric is candidate minus baseline
sampled maximum RSS. Negative integer differences are retained, never clamped
or converted to absolute values. The standalone `signed_difference` helper
also preserves integer/float arithmetic types. No comparison upgrades
qualification or grants acceptance.

F2-B limitation: configuration equality currently includes the literal
`(pid, starttime_ticks)` roster. Fake inputs can deliberately reuse those
numbers without asserting shared real lifetimes, but independent real runs
with different identities cannot compare. Future F2-B comparability should
use declared thresholds, phases, start method and topology shape rather than
literal PIDs. This fake-only repair does not change that contract.

Every report and comparison pins:

```text
production_memory_qualification = INCONCLUSIVE
production_chronological_peak = NOT_OBSERVED
```

No estimates are generated. Any future hypothetical estimate would require
`MODEL_ONLY` semantics and new authorization. There is no actual memory-budget
decision, runtime speedup claim, numerical parity claim or 717-slot production
projection.

## Prior review disposition

F1 and F3 are repaired with fail-closed comparison and malformed-structure
guards; F4 is repaired by selecting status memory keys. Regressions cover
incomplete inputs on either side, malformed raw reports, unusual Name values
and signed complete comparisons. F9 now exercises a genuinely live worker
whose reading is supplied despite omission from `expected_live`, including
withheld aggregates and retained parent data.

The optional F2 and F6 repairs are deferred; their processed-frame retention
and variable report-shape limitations are documented above. F5 remains the
documented F2-B cross-run limitation. F8's per-frame cgroup requirement is now
explicit. F7 is an operator path-inventory concern: the planner reports no
stray untracked files at this repair's start. The implementer has not removed
or modified files outside the three authorized F2-A paths.

## Verification ownership

The new test module supplies fake text and records entirely in memory. It
covers parsers and units, unusual comm strings, signed stat fields, PID reuse,
multiple parents/workers, overlapping/replacement lifetimes, exits, incomplete
frames, skew/gaps, independent HWM versus sampled totals, cgroups, swap/OOM,
holder misuse/concurrency/coverage, truncation, integrity and signed comparisons.
It also inspects the observer AST and re-executes its source with mocked file
access and restricted imports to check import safety. No tests are skipped.

The implementer must not execute tests, builds, benchmarks, simulations or live
instruments. The orchestrator alone owns this targeted verification:

```text
.venv/bin/python -m pytest -q tests/unit/test_rb_post3d_08p2e2_r2f_f2a_observer.py
```

Test execution and Claude reviewer acceptance remain pending after implementation.
Observer-core completion does not lift the production experiment hold.
