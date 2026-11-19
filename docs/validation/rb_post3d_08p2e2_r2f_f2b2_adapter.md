# F2-B2 injected synthetic observation adapter, v1

This is an artificial input contract, not a production memory measurement. M0/M1
execution and production experiments remain on hold. All results, including
diagnostics and complete artificial cases, carry:

```json
{
  "production_memory_qualification": "INCONCLUSIVE",
  "production_chronological_peak": "NOT_OBSERVED",
  "input_kind": "FAKE_INPUT_ONLY"
}
```

The three existing files repaired in place provide a pure adapter, fake regression cases, and this
contract. The frozen F2-A observer and F2-B1 verifier remain unchanged. There is
no discovery, live provider, execution entry point, installation, instrumentation,
process creation, filesystem access, networking, or clock reading in the adapter.
It imports only F2-A, whose dependencies are standard library modules.

## Public interface and serialization

`adapt(provider_input: JSON object) -> sealed JSON object` is the sole public
operation. Import it from
`scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b2_adapter`. `SCHEMA` is
`rawibumi.fake-observation-adapter.f2b2.v1`; input declares this exact version and
output declares this version plus `.result`. This is a new fake-only contract;
it changes no production schema or observer/verifier contract.

Callers supply ordinary JSON types, with exact built-in types. Tuples, subclasses,
non-string object keys, nonfinite floats, cycles, invalid UTF-8 strings including
lone surrogates, and excessive input are rejected before reconciliation. All
integer fields consumed as integers reject booleans. Unknown JSON fields are
retained as evidence; they cannot override the output envelope. No input is
mutated. Canonical bytes are `observer.canonical_bytes(result)` (sorted JSON
object keys, indented, trailing newline, UTF-8); list order is preserved. The
same input gives identical bytes without a clock, random seed, or environment.

A mapped result contains `adapter_status=MAPPED_FAKE_INPUT`, `configuration`,
`evidence`, and the **unmodified** sealed F2-A `observer_report`. Its `outcome`
and `reasons` are exactly F2-A's. F2-A's `OBSERVATION_COMPLETE` describes only the
explicitly supplied artificial coverage under the supplied configuration.

An adapter failure has `adapter_status=ADAPTER_DIAGNOSTIC`, an invalid or
inconclusive `outcome`, fixed `reasons`, and null `configuration`, `evidence`,
and `observer_report`. A completely validated, bounded JSON copy is retained as
`provider_input` on schema failures. If copying fails, `provider_input` is null.
Unsafe payloads and arbitrary exception text are never echoed. All results are
sealed using F2-A `seal`; `observer.verify_integrity(result)` checks the seal.
Mapped records are deep copies independent of the retained provider event,
reading, and source-metadata objects; editing a mapped record cannot rewrite
the raw provider view. Any edit still invalidates the result's seal.

## Provider schema

All fields below are required unless identified as optional. A complete executable
fixture construction is in the companion regression file's `provider` helper;
it uses only injected text and events.

| Root field | Type and meaning |
| --- | --- |
| `schema` | Exact adapter `SCHEMA` above |
| `input_kind` | Literal `FAKE_INPUT_ONLY` |
| `clock` | `{kind: "monotonic", unit: "ns", domain_id: nonempty string}` |
| `sources` | List of explicitly declared source objects, described below |
| `configuration` | Explicit F2-A configuration, including the extra `execution_mode` topology field |
| `input_id`, `workload_id`, `independent_run_id` | F2-A nonempty artificial run/workload declarations |
| `conditions` | F2-A workload-conditions object; this is a comparability field |
| `events` | Ordered list of event objects, one per supplied chronological event |
| `holder_coverage` | Explicit F2-A `{identity, phase, events_complete}` declarations |
| `declared_record_count`, `declared_frame_count` | Nonnegative integer declarations, passed through without recounting or repair |
| `truncated` | Explicit boolean, passed through to F2-A |

Every source is an object with unique nonempty `source_id`, `kind` equal to
`fake_events`, `fake_proc`, or `fake_cgroup`, `clock_id` equal to the root
`clock.domain_id`, and a JSON object `metadata`. Multiple sources of each kind
are allowed. Source IDs and metadata are preserved verbatim. They assert injected
provenance; the adapter cannot authenticate them.

Configuration is the actual F2-A configuration:

```text
max_read_skew_ns: nonnegative integer
max_frame_gap_ns: positive integer
required_phases: nonempty, nonduplicated list of F2-A PHASES
topology:
  start_method: explicitly supplied "spawn"
  execution_mode: "inline" | "spawned"
  parents: [[pid, starttime_ticks], ...]
  workers: [{identity: [pid, starttime_ticks], parent: [pid, starttime_ticks], ...}, ...]
  max_concurrent_workers: nonnegative integer
```

F2-A validates the configuration without adapter repairs. Each worker's `parent`
is an explicit full identity reference. A ppid alone never establishes the
reference. Worker descriptors can include invariant `pool` labels. Pool capacity
does not define the observed roster: unobserved capacity slots receive neither
roster identities nor START events. Actual roster length and declared maximum
remain separate in output configuration; F2-A reports the observed lifetimes.

`start_method` is the caller-declared configured pool context, including for an
inline run. Frozen F2-A and F2-B1 require `spawn`; the adapter never supplies it
implicitly. Inline means no roster worker and no worker START. `execution_mode`
is retained in topology, so F2-B1 distinguishes inline from spawned behavior.
Spawned mode with an empty actual worker roster cannot establish worker coverage.
After reconciliation, unless F2-A already reports `INVALID_EVIDENCE`, it yields
the inconclusive adapter diagnostic `ADAPTER_SPAWNED_WORKERS_UNOBSERVED`, with
the original provider input retained and no observer report available to compare.
An unrostered worker START still retains F2-A's stricter invalid
`UNKNOWN_WORKER_TOPOLOGY`. Declared capacity never substitutes for a roster.

Each event requires `kind`, nonnegative integer `sequence`, nonnegative integer
monotonic `time_ns`, `source_id` for a `fake_events` source, matching `clock_id`,
and object `metadata` (for example an independently supplied event ID). Event
sequence starts at zero and is contiguous in complete evidence. Event times may
tie; supplied list order resolves ties. Events are never sorted or renumbered.

| Kind | Additional fields |
| --- | --- |
| START | `identity`, `ppid`, `role` (`parent` or `worker`), initial `phase` |
| PHASE | `identity`, explicit new `phase` |
| CREATE | `identity`, `phase`, nonempty `holder_id`, nonnegative integer `slots`, literal `initialization_succeeded=true` |
| RELEASE | `identity`, `phase`, `holder_id`, `slots`, optional `ownership_termination` evidence described below |
| FRAME | `expected_live`, `readings`, optional `cgroup`, paired `read_start_ns` / `read_end_ns` |
| EXIT | `identity`; F2-A requires the final aligned observation at this exact timestamp |

A proc reading has F2-A `identity`, `phase`, supplied raw `status` and `stat`
strings, optional `smaps_rollup` string or null, optional boolean `final`, paired
`read_start_ns` / `read_end_ns`, and adapter provenance:

```text
source_id: ID of a declared fake_proc source
clock_id: root domain_id
metadata: object
capture_sequence: nonnegative integer
file_read_bounds:
  status: {read_start_ns: integer, read_end_ns: integer}
  stat: {read_start_ns: integer, read_end_ns: integer}
  smaps_rollup: {read_start_ns: integer, read_end_ns: integer}  # when supplied
```

For every present string, file bounds are required and must fit within the proc
capture bounds, and end by FRAME time. The source,
clock, and capture sequence apply to the bundle; individual file intervals are
explicit rather than reconstructed from text. Extra file provenance can be
retained in these objects. A missing or non-string claimed-successful status/stat
is intentionally passed to F2-A's parser to obtain its canonical invalid reason.
`file_read_bounds` is still an object even when the required text is missing.

An explicit nonempty `read_failure`, such as `ENOENT:status` or `ESRCH`, describes
a failed proc capture. Before any frame/read-window or capture-sequence check
can return inconclusive, **every supplied proc capture**, successful or failed,
must have an explicit identity accepted by F2-A `identity_key`, unique among
all captures in its FRAME. Failed identities must also belong to the declared
roster and the enclosing FRAME's explicit `expected_live`; that list must have
valid, nonduplicated identities. These independent checks run across all frames
before mapping. Invalid metadata yields `INVALID_EVIDENCE`, with the original
bounded provider input and capture provenance retained in the diagnostic.
Successful-only expected-live and chronological lifecycle contradictions remain
with F2-A so its classifications are preserved.

Only a failed capture that passes these checks is withheld from F2-A's
`readings`; all its original fields remain in `evidence.provider_input`.
Its `expected_live` entry is untouched, ensuring missing reads remain visible.
It cannot qualify as a process observation. **Any bundle-level `read_failure`
withholds the entire capture**, including a failure of optional smaps alone when
status/stat were supplied successfully. To express absent optional smaps while
retaining status/stat, omit `smaps_rollup` or set it to null, without a bundle-level
`read_failure`. Genuinely failed valid reads remain inconclusive unless F2-A
identifies stricter contradictions.

Cgroup objects have `source_id` for a `fake_cgroup` source, `clock_id`, `metadata`,
`capture_sequence`, monotonic `time_ns`, raw `memory_events` string or null, and
paired `read_start_ns` / `read_end_ns`. The interval must fit in FRAME
bounds and end no later than its `time_ns`, which must not be after
FRAME time. An explicit nonempty `read_failure` maps this cgroup capture to null;
the original remains in provider evidence. Missing/null cgroup information is
classified by F2-A. The same cgroup source ID must consistently identify the
same injected cumulative counter stream within a run.

`capture_sequence` is one global contiguous stream starting at zero, traversed
in supplied event order, each FRAME's proc readings in list order followed by
its cgroup capture. Failed captures occupy sequence positions too. No sequence
is assigned, filled, or repaired by the adapter. Capture sequence orders completed
capture envelopes: read-end timestamps cannot decrease. Equal endpoints and
overlapping bounded intervals do not establish atomicity.

## Mapping, clocks, and provenance

| Provider | F2-A destination |
| --- | --- |
| `configuration` | Verbatim reconcile config, including topology extras |
| Run IDs, workload, conditions, counts, truncation | Same-named evidence fields |
| `events` | `records` in original order, same sequences and timestamps |
| FRAME raw strings, bounds and metadata | Same reading/cgroup fields and extras |
| Explicit failed captures | Withheld from valid readings; raw provider object retained |
| Unjustified RELEASE | Withheld; original retained, `withheld_events` records sequence and reason |
| Supplied `holder_coverage` | Same entries; affected owner's declarations conservatively set false after a withheld RELEASE |
| Entire validated provider object | `evidence.provider_input` verbatim copy, covered by input hash |

Run-specific source IDs, boot/domain identifiers, metadata and capture sequences
belong in evidence, never in invariant configuration, topology descriptors, or
conditions. F2-B1 compares every config and topology setting other than roster
identity/reference labels; putting run IDs there legitimately prevents comparison.
Only workload, configuration and `conditions` define declared operating
comparability. Other root extras are raw evidence covered by hashes.

All times use **one explicitly declared artificial monotonic nanosecond domain**.
Every source, event and capture must refer to that exact domain. There is no
wall-time conversion, cross-boot offset inference, clock synchronization,
atomic-snapshot claim, or monotonic surrogate. A FRAME bounds its constituent
process/cgroup captures, and proc bundles bound their constituent file reads.
Missing process/frame/cgroup bounds remain missing: no timestamp is manufactured
from other intervals. They produce an inconclusive adapter diagnostic with
`ALIGNMENT_NOT_ESTABLISHED`. The provider contract requires explicit envelopes
for every capture, including cgroup reads which F2-A does not time-bound itself.
F2-A's process-window fallback therefore cannot conceal a missing envelope.

Structural inversion and containment contradictions fail before mapping. F2-A
retains ownership of live-phase windows, capture age and skew policy. Its
`capture_age_ns <= max_read_skew_ns` boundary is inclusive. A larger age is
inconclusive. Missing bounds give `ALIGNMENT_NOT_ESTABLISHED`. There is no new
memory budget, sampling policy, or comparability acceptance rule.

## Holder and phase semantics

CREATE is a successful initialization event with a supplied slot count. Failed
or unknown initialization cannot create a holder. RELEASE needs independent
explicit ownership-termination evidence:

```json
{
  "explicit": true,
  "basis": "explicit_owner_disposal",
  "evidence_id": "independently-injected-event-id"
}
```

The only v1 bases are `explicit_owner_disposal` and
`explicit_ownership_transfer`. Transfer terminates the recorded owner's ownership;
it does not imply deallocation or create a new owner's holder. These are fake
provider assertions; they do not establish that production constructors or
termination sites are observable. `evidence_id` is a nonempty provider assertion:
v1 does not resolve it to a declared source or a separately sequenced termination
event, so the asserted independence is not cross-checked. A missing/unknown/unjustified termination
object produces no RELEASE record. It retains raw evidence and conservatively
sets that owner's supplied holder coverage false. No missing coverage pair is
invented. Interval end, function return, FRAME, process EXIT, GC, and weakref are
never ownership-termination evidence. Missing events cannot be reconstructed from
counts or from the observation interval.

F2-A decides duplicate holder IDs, unmatched/cross-owner RELEASE, slot
contradictions and open holders for mapped, explicitly justified RELEASE events.
An unjustified RELEASE is withheld even if its holder was never created; the
adapter checks its owner's roster membership and field structure but does not
reconstruct holder matching before withholding. This limitation produces
inconclusive coverage findings rather than F2-A's `INVALID_RELEASE` for that
withheld event. Its original evidence and `ADAPTER_RELEASE_UNJUSTIFIED` in
`withheld_events` remain available for inspection. Concurrency and phase attribution follow F2-A:
the holder's phase is its CREATE phase, including a release after a phase
transition. Per-process HWM remains per lifetime and is never summed. Sample
RSS sums are kept separate from HWM and from cgroup counters.

START gives only its explicitly observed initial phase. PHASE records are kept
chronologically; missing phases are never inferred from subsequent phases or
EXIT. Distinct producer and attribution pools can have disjoint worker lifetimes
under the same parent with a concurrency limit smaller than total roster length.
Their mapping is valid, but frozen F2-A requires **each observed process** to have
an aligned observation in **every required phase**. With required producer and
attribution phases, these disjoint pools therefore report
`MISSING_PHASE_COVERAGE` and cannot compare. The adapter does not fabricate worker
phases or tune `required_phases` to force completeness.
The authoritative recovery task's priority 7 explicitly permits this frozen
F2-A inconclusive result: the distinct-pool positive case demonstrates correct
mapping and holder attribution, not complete observation coverage.

## Fail-closed matrix

| Defect | Outcome / reason owner |
| --- | --- |
| Non-JSON, coercion, surrogate, cycle, nonfinite value | Adapter invalid `ADAPTER_NON_JSON`; no unsafe payload retained |
| Invalid/missing schema field | Adapter invalid `ADAPTER_SCHEMA_INVALID` |
| Unsupported or inconsistent clock/domain/time | Adapter invalid `ADAPTER_CLOCK_INVALID` / `ADAPTER_TIME_INVALID` |
| Missing/wrong-kind source reference | Adapter invalid `ADAPTER_SOURCE_INVALID` |
| Inline worker or unconfirmed CREATE | Adapter invalid `ADAPTER_INLINE_WORKER` / `ADAPTER_CREATE_UNCONFIRMED` |
| CREATE slots not a nonnegative integer | Adapter invalid `ADAPTER_CREATE_SLOTS_INVALID`; distinct from F2-A's CREATE/RELEASE count mismatch |
| Unjustified RELEASE owner outside roster | Adapter invalid `ADAPTER_RELEASE_OWNER_UNKNOWN` |
| Size/depth/integer/event/read/source cap exceeded | Adapter invalid `ADAPTER_CAP_EXCEEDED`; never silently trim |
| Impossible read interval or constituent containment | Adapter invalid `INVALID_READ_WINDOW` |
| Missing frame/proc/cgroup envelope | Adapter inconclusive `ALIGNMENT_NOT_ESTABLISHED` |
| Timestamp inversion or nonincreasing sequence | Adapter invalid `OUT_OF_ORDER` |
| Capture sequence gap | Adapter inconclusive `SEQUENCE_GAP`, with raw provider retained |
| Record sequence gap, truncation, count mismatch | F2-A inconclusive `SEQUENCE_GAP`, `EVIDENCE_TRUNCATED`, `DECLARED_COUNT_MISMATCH` |
| Missing status/stat or malformed claimed-successful raw string | F2-A invalid parser reason; no normalization |
| Missing/malformed identity on any proc capture | Adapter invalid `ADAPTER_CAPTURE_IDENTITY_INVALID`, before withholding or window/sequence diagnostics |
| Duplicate identity across successful/failed captures in a FRAME | Adapter invalid `ADAPTER_DUPLICATE_CAPTURE_IDENTITY` |
| Failed capture identity outside roster / outside expected_live | Adapter invalid `ADAPTER_FAILED_CAPTURE_NOT_ROSTERED` / `ADAPTER_FAILED_CAPTURE_NOT_EXPECTED` |
| Failed capture with missing/malformed/duplicated expected_live | Adapter invalid `ADAPTER_EXPECTED_LIVE_INVALID` (wrong list type: `ADAPTER_SCHEMA_INVALID`) |
| Explicit failed proc bundle with valid, unique, rostered, expected identity | F2-A inconclusive `MISSING_PROCESS`, `INCOMPLETE_FRAME_SET` (additional coverage or stricter invalid reasons possible); whole bundle withheld even for optional-smaps-only failure |
| Optional smaps absent | No invalidity implied; sampled smaps aggregate remains null |
| Missing/failed cgroup | F2-A inconclusive `MISSING_CGROUP_DATA` |
| Spawned mode, empty actual roster | Adapter inconclusive `ADAPTER_SPAWNED_WORKERS_UNOBSERVED`, unless F2-A already reports stricter invalid evidence |
| Roster worker never STARTed, with no worker events, expected_live entries or readings | F2-A inconclusive `MISSING_PROCESS`, `MISSING_ROLE_COVERAGE` when the worker role is entirely unobserved |
| Late START after first FRAME; worker remains in that FRAME's expected_live and readings | F2-A invalid `UNEXPECTED_PROCESS`: FRAME expects an identity not yet live |
| Late START after first FRAME; worker omitted from expected_live but successful reading still supplied | F2-A invalid `INVALID_LIFECYCLE`: reading identity is not yet live |
| Consistent late START; worker absent from first FRAME's expected_live and readings | F2-A inconclusive `MISSING_PHASE_COVERAGE` when its initial phase was never observed; no START moved or synthesized |
| START outside roster / incompatible topology | F2-A invalid `UNKNOWN_WORKER_TOPOLOGY` |
| PID reused while live, older replacement starttime, stat mismatch | F2-A invalid `PID_REUSE_ANOMALY` |
| Duplicate identity with equal pid/starttime in roster | F2-A invalid `UNKNOWN_WORKER_TOPOLOGY` (not two lifetimes) |
| Disappearance without EXIT | Missing reads/open lifetime; parent EXIT with live child additionally invalid `INVALID_LIFECYCLE` |
| Duplicate CREATE / unmatched RELEASE / cross-owner / slots | F2-A invalid `DUPLICATE_HOLDER`, `INVALID_RELEASE`, `CROSS_PROCESS_RELEASE`, `SLOT_COUNT_MISMATCH` |
| Unknown/unobserved holder termination | F2-A inconclusive `OPEN_HOLDER_LIFETIME`, `INCOMPLETE_HOLDER_COVERAGE`; filtering can also expose sequence/count gaps |
| Unjustified RELEASE referencing a never-created holder | Withheld with `ADAPTER_RELEASE_UNJUSTIFIED`; F2-A inconclusive coverage findings, not `INVALID_RELEASE` for the withheld event |
| Uncovered phases / missing final / open processes | F2-A inconclusive `MISSING_PHASE_COVERAGE`, `EXIT_WITHOUT_FINAL_OBSERVATION`, `OPEN_PROCESS_LIFETIME` |
| Swap, increasing oom/oom_kill, nonzero cgroup max | F2-A inconclusive `SWAP_OBSERVED`, `OOM_OBSERVED`, `CGROUP_LIMIT_EVENT` |
| Decreasing cumulative counters | F2-A invalid `INCONSISTENT_COUNTER` |

Within a mapped report, F2-A's invalid reasons take precedence over its
inconclusive reasons, and reasons may coexist. Capture identity validation across
all frames precedes adapter-level inconclusive window/capture-sequence checks,
so such gaps cannot conceal invalid capture identities. Adapter diagnostics
report the first failing check, not an exhaustive defect inventory.
Unexpected reconciliation exceptions yield a fixed invalid
`ADAPTER_RECONCILIATION_FAILED` diagnostic rather than a partial report or
exception payload.

Reason ownership is explicit in `adapter_status`. For `MAPPED_FAKE_INPUT`, all
top-level reasons come directly from the embedded F2-A report. For
`ADAPTER_DIAGNOSTIC`, they arise before a report can be returned. `ADAPTER_*`
codes name adapter checks, including `ADAPTER_CREATE_SLOTS_INVALID` and
`ADAPTER_RELEASE_OWNER_UNKNOWN`; they are not F2-A holder/topology results.
The remaining adapter checks deliberately reuse these unprefixed F2-A names:

| Adapter diagnostic code | Adapter-level meaning |
| --- | --- |
| `INVALID_READ_WINDOW` | Inverted or uncontained supplied frame/proc/file/cgroup envelope, or file/cgroup completion after its allowed timestamp |
| `ALIGNMENT_NOT_ESTABLISHED` | Both bounds absent from an explicit frame, proc or cgroup envelope; no F2-A fallback used |
| `OUT_OF_ORDER` | Decreasing event time, nonincreasing event/capture sequence, or decreasing capture completion time |
| `SEQUENCE_GAP` | Noncontiguous global capture sequence (event gaps remain F2-A's responsibility) |
| `INVALID_IDENTITY`, `MALFORMED_INPUT`, `NEGATIVE_FIELD`, `INVALID_PHASE` | Propagated F2-A helper errors while validating roster/coverage identities or fields of a withheld RELEASE; no reconciliation report exists |

`ADAPTER_RELEASE_UNJUSTIFIED` is metadata in `withheld_events`, not a top-level
F2-A reason. The resulting coverage/sequence/count findings are F2-A's.

Bounds are fake-input resource limits, not measurement policy: 4,096 events,
256 proc captures per FRAME, 512 sources, depth 32 (root depth zero), 200,000
visited JSON values, 262,144 UTF-8 bytes per string/key, 8,388,608 total string/key
bytes, and 256-bit integer magnitude. Objects/lists are checked before traversal;
the value limit also bounds container width. Counts are not silently rewritten
to match these limits. Accepted input is serialized without lossy normalization.

## Independent verification and limitations

Use `verifier.verify_report(result["observer_report"])` to reconstruct a mapped
report. Use **only** F2-B1
`compare_verified_reports(baseline_report, candidate_report)` for comparison.
Neither the adapter envelope nor its hash establishes comparability. Adapter
diagnostics have no report; supplying null to F2-B1 remains fail-closed.

Two separately supplied complete artificial runs with different PIDs can compare
through F2-B1's topology-shape semantics. Workload, conditions, execution mode,
worker descriptors and per-parent topology distribution remain comparison gates.
Signed candidate-minus-baseline sampled RSS differences, including negative
values, are available only when F2-B1 deems both complete runs comparable.
Partial events never qualify, even if an observed sampled value is smaller.

Hashes establish serialization integrity and reconstruction consistency, not
live authenticity, true independence, real worker coverage, a chronological
production peak, memory qualification, timing improvement, or numerical claims.
Arbitrary regenerated fake evidence can be internally consistent. Observed
VmHWM is a per-process counter; shared pages may be counted repeatedly in sampled
RSS sums. Optional smaps, sequential read bounds and cgroup counters do not
remove those limitations.

Any future live work requires separate owner authorization: independently
established successful constructor/ownership-termination sites for both pools,
actual spawn roster and parent identities, monotonic clock provenance, source
permissions and read-failure handling, complete phase/final/holder coverage,
separate production authenticity and experimental-independence controls, and
review of the live observation design. This contract authorizes none of those
executions, M0/M1, policy C, numerical work, or runtime experiments.

## Verification handoff

The companion tests cover inline, one/multiple spawned workers, all F2-A phases,
distinct pools, PID lifetime reuse and anomalies, roster absence and late START,
read boundaries and skew, failed/malformed/optional reads, disappearing workers,
holder lifecycle contradictions and forbidden release inferences, phase gaps,
swap/OOM/counters, truncation/count/final failures, malformed JSON and Unicode,
caps, deterministic bytes, mutation immunity, F2-B1 reconstruction and semantic
comparison, and adapter execution with live I/O and clocks patched to raise.
Recovery regressions also cover failed-capture malformed/missing/off-roster/not-expected
identities, successful/failed duplicate combinations in either order, invalid
identities combined with earlier or same-frame window/sequence gaps, all three
late-START classifications, consistent absent-worker coverage, empty spawned
rosters, optional-smaps bundle failure versus omitted/null optional text, and
independent mapped/raw event objects. Noncomparability helpers use a separately
supplied complete baseline with distinct run IDs and PIDs and assert candidate
ineligibility and a null metric delta; shared run IDs cannot mask a fail-open case.

The implementer did **not** run pytest, builds, benchmarks, or production code.
Targeted execution and the positive pinned pass count with zero skips remain an
orchestrator gate, as does Claude review with zero blockers and majors:

```text
.venv/bin/python -m pytest -q tests/unit/test_rb_post3d_08p2e2_r2f_f2b2_adapter.py
```

No passing count is asserted before the orchestrator runs that command.
