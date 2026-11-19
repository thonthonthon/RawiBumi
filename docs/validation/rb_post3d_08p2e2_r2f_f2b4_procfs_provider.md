# F2-B4-D2-A procfs provider — code-only contract

D2-A implements a provider API and artificial regression fixtures. No real reader,
process discovery, workload launcher, simulation integration or experiment is
included. D2-B live reads and D3 production measurement remain on hold.

The input schema is `rawibumi.real-procfs-provider.f2b4.d2a.v1`; the output schema
adds `.result`. The module neither imports nor calls the D1 sampler. D1's schema
and acceptance rules are unchanged. The only accepted `source_kind` is
`FAKE_FIXTURE`; `REAL_PROCFS` fails with `REAL_SOURCE_NOT_AUTHORIZED`.
Caller-supplied attestation or qualification fields are unknown fields and fail
validation. A label does not authenticate the origin of arbitrary callbacks: the
trusted caller must supply artificial fixtures during D2-A. This library cannot
authenticate a callback or confer real-source attestation on its return value.

## API and exact request

`ProcfsProvider(read_proc=None, monotonic_ns=None, read_cgroup=None)` only stores
callbacks. Import and construction call no callback and perform no I/O. There is
no concrete Linux backend, default clock, environment lookup or live fallback.
`sample(request)` validates and snapshots the entire request before callbacks,
then returns a detached JSON-compatible dictionary. `canonical_json(result)`
serializes that dictionary deterministically. No file is written.

The request and every nested object are closed objects: all listed fields are
required, and additional fields fail validation. Floats, non-string dictionary
keys, custom Python objects, cycles and JSON container subclasses are rejected.

| Request field | Contract |
| --- | --- |
| `schema` | Exact input schema above |
| `source_kind` | `FAKE_FIXTURE` |
| `config` | Object described below |
| `roster` | Exactly `{parent, workers}` |
| `frame_count` | Integer 1–32; sequential frames in a single call |
| `cgroup` | `null`, or the optional diagnostic registration below |

`config` contains exactly:

| Field | Contract |
| --- | --- |
| `clock_ticks_per_second` | Fixed caller-supplied positive integer ≤1,000,000 |
| `boot_id` | UUID-shaped string; equality comparisons are exact and case-sensitive |
| `pid_namespace_id`, `host_id` | 1–96 ASCII label characters, starting with alphanumeric, then alphanumeric or `_ . : -`; `..` prohibited |
| `max_read_skew_ns` | Nonnegative integer <2^63, inclusive per-frame skew bound |
| `smaps_rollup_policy` | `NOT_SAMPLED` or `OPTIONAL_DIAGNOSTIC` |

The single parent is `{pid, starttime_ticks, boot_id, ppid}`. Each worker is
`{pid, starttime_ticks, boot_id, parent_pid, role}`. PIDs are integers 1–2^31−1;
parent PPid can also be zero. Starttimes are nonnegative integers <2^63. All
boot IDs must equal the configuration. Worker roles follow the label rule.
Workers must point to the registered parent; duplicate PIDs, a self-parent or a
parent whose PPid is one of its registered children are rejected. At most 64
processes, including the parent, can be registered. The roster is a trusted
caller assertion, with no completeness inferred from process names or CPU data.

No supplied field is resolved as a filesystem path. `read_proc(kind, pid,
max_bytes)` receives only a validated integer PID and `stat`, `status` or
`smaps_rollup`. `read_cgroup(kind, token, max_bytes)` receives a validated opaque
registration token and `memory.current`, `memory.peak` or `memory.events`.
Callbacks must return an **exact** `str`, terminated by newline, within the byte
limit; bytes and string subclasses are rejected. `max_bytes` is 65,536.
Callbacks must not silently truncate source text to this limit. A future D2-B
reader must read up to `max_bytes + 1` bytes and return an over-limit result when
overflow occurs, so the provider can report `OVERSIZED`. A newline at the limit
does not establish that a silently clipped source is complete; D2-A cannot detect
such reader contract violations. This requirement specifies future reader
behavior and does not authorize any real reads in this milestone.

## Identity, parsing and timing

Per process, the order is `stat_before`, `status`, optional `smaps_rollup`, then
`stat_after`. A clock call immediately precedes and follows each attempted read,
including a reader that raises an ordinary exception. Failure before a read
leaves its window explicitly missing. A clock failure stops further callbacks;
remaining entries in that frame are failed with `CAPTURE_STOPPED` and subsequent
requested frames are not fabricated.

Both stat reads independently check PID, PPid and field-22 starttime against the
registration. The final `)` delimits stat's command, including embedded spaces
and parentheses. Missing field 22, malformed integers and invalid states fail.
Z/X/x states fail as `PROCESS_NOT_LIVE`. Normal R/S changes across sources are
permitted. Status requires Pid, PPid and State, rejects duplicate fields
(including unselected metadata), and requires kB units for present memory fields.
A dead status can omit all Vm* fields: its PID/PPid are still checked and it gives
`PROCESS_NOT_LIVE` (`INCOMPLETE`), without fabricated counters. Live status also
requires VmRSS and VmHWM; their absence remains `MISSING_FIELD` (`INVALID`),
including for a registered kernel thread with no mm and a live State.
VmSwap is optional. VmHWM below VmRSS is rejected consistently with the existing
pure parser's counter rule. VmRSS ×1024 is `vmrss_bytes`; VmHWM remains separate.
Optional smaps requires Rss and Swap, supports a rollup header and returns only
its parsed memory fields. None of these counters represents unique physical
memory; Linux RSS/HWM counters are approximate.

The injected clock must return exact integers in [0, 2^63). Ties are retained;
decreases or exceptions make the frame invalid. Clock provenance consists of
`INJECTED_MONOTONIC_NS` and the caller-supplied host, boot and namespace labels.
These assertions are never independently authenticated using host metadata.
Starttime ticks are never converted to or compared with nanoseconds:
`starttime_alignment=NOT_CALIBRATED`. In particular, no shared time origin or
suspend behavior is inferred from a tick rate.

Every read records status, reason codes, start/end nanoseconds and, when a
bounded string can be encoded, its UTF-8 byte length and SHA-256. Raw source text,
process command names and exception messages are omitted. Frames record first
start, last end, skew and `read_window_complete`; missing windows stay missing.
Top-level first/last/skew fields span the attempted capture. The configured skew
limit applies per frame, rather than to the whole series. Skew above the bound is
`INCOMPLETE`. A failed read or identity check makes every process in that frame
non-successful and clears all its RSS/HWM/smaps values; failed records are kept.
Earlier independent frames can retain their values, while the overall capture
still fails. Read statuses distinguish a valid individual read from frame
eligibility. Frame reason codes explain ineligibility of otherwise valid reads.

## Optional cgroup corroboration

A cgroup registration has exactly `token`, `controller_id`, `membership`,
`membership_provenance`, and `baseline`. Tokens are plain labels or normalized
relative components separated by `/`, at most 192 characters total. Each
component starts with alphanumeric or `_`, contains only alphanumeric, `_`, `.`
or `-`, and is at most 64 characters. Empty, `.`, `..`, double-slash, absolute,
backslash, NUL and traversal forms are rejected. No token is opened or joined to
a path by this module. Controller and provenance fields use the label rule.

`membership` is a duplicate-free list of integer PIDs equal to the registered
roster. This is explicitly `CALLER_ASSERTED_ONLY`; membership is not independently
verified by reading cgroup.procs. It is not a claim of isolation, completeness or
ownership. Each capture registers one fixed cgroup identity; no comparisons
cross different identities or separate calls.

`baseline` has exactly `memory_current_bytes`, `memory_peak_bytes`, `events`,
`provenance`, `boot_id`, `pid_namespace_id`, `observed_ns`. Numeric values are
nonnegative integers <2^63; baseline peak must be ≥ baseline current. Boot and
namespace match config. Provenance follows the label rule. `events` is an object
of lowercase/underscore counter names (≤64 characters), requiring low, high,
max, oom and oom_kill. Baseline time must precede or tie the first cgroup read.
It is compared only within the caller-asserted injected monotonic domain.
The peak/current inequality is a deliberately stricter registration precondition
for the caller's artificial baseline, rather than a rule for sequential observed
reads or evidence of atomicity. A caller baseline assembled from sequential
readings with current above peak is outside this baseline contract and is rejected
before collection. Sequential provider reads allow that ordering. Supporting such
baselines would require a separately reviewed baseline contract change.

Cgroup current and peak are byte counters; events are counts. Unknown event
counters are retained as counts. Peak and events must not decrease relative to
the supplied baseline and preceding successful cgroup observation for this fixed
identity. Disappearing known event counters also fail. Current and peak are read
sequentially and are not compared as if atomic. Counter resets are unsupported
and fail closed. OOM/limit event counts are diagnostic data, never qualification.

A requested diagnostic with missing reader/data, malformed text, invalid baseline
chronology or decreasing counters is reason-coded and makes the frame
non-successful. Process records remain present. Omit `cgroup` or select
`NOT_SAMPLED` to omit optional collection. All cgroup data and baselines remain in
their own section; they are never added to, subtracted from or substituted for
process RSS. There is no cross-process RSS sum in D2-A.

This is an intentional conservative limitation: optional means collection can
be omitted by configuration. Once requested, a cgroup or smaps failure clears
RSS/HWM/smaps values for every process in the frame, even when its mandatory stat
and status reads succeeded. Malformed diagnostics, inconsistent counters and
invalid baseline chronology can make the entire capture `INVALID`; missing data
can make it `INCOMPLETE`. Records and individual read statuses remain available,
and independent successful frames retain their values. Optional diagnostics do
not provide an independently successful RSS result when the frame fails.

## Fail-closed results, bounds and limitations

Success is `FAKE_PROVIDER_SAMPLE_CONSISTENT`: consistency of artificial supplied
readings only. `INVALID` takes precedence over `INCOMPLETE`, then success. Invalid
reasons are explicitly enumerated in `INVALID_CODES`; other generated failures
are incomplete. Sorted reason entries carry a code and deterministic location;
per-class reason-code lists are sorted and deduplicated. Input validation stops
at the first invalid condition before calling a reader or clock.

| Condition | Reason |
| --- | --- |
| PermissionError | `PERMISSION_DENIED` |
| FileNotFoundError or ProcessLookupError | `PROCESS_VANISHED` |
| Other OSError | `READ_FAILED` |
| Other Exception | `READER_EXCEPTION` |
| Non-exact-string return | `READER_CONTRACT_VIOLATION` |
| Oversized UTF-8 text / missing newline | `OVERSIZED` / `TRUNCATED` |
| Bad clock value/exception / decrease | `CLOCK_FAILURE` / `CLOCK_NON_MONOTONIC` |
| Missing required callbacks | `READER_NOT_CONFIGURED`, `CLOCK_NOT_CONFIGURED`, `CGROUP_READER_NOT_CONFIGURED` |
| Identity mismatch / starttime race | `IDENTITY_CONTRADICTION` / `PID_REUSE_OR_IDENTITY_RACE` |
| Parsing, duplicate or missing field | `RAW_TEXT_MALFORMED`, `DUPLICATE_FIELD`, `MISSING_FIELD` |
| Skew / aggregate source budget | `READ_SKEW_EXCEEDED` / `TOTAL_TEXT_CAP_EXCEEDED` |

Only Exception subclasses are mapped. KeyboardInterrupt/SystemExit propagate.
If the reader and closing clock both fail, both reason codes are retained.
Missing or failed readings never become zero.

Bounds are 32 frames, 64 processes, 65,536 UTF-8 bytes per text, 4,194,304 total
returned bounded source bytes, JSON input depth 16 and 20,000 nodes, and a separate
4,194,304-byte input-string budget. Container and character lengths are checked
before copying/encoding. Text has a 64-character whitespace-run guard before
parsing and rejects runs of 21 or more consecutive ASCII digits before integer
conversion. Unsigned stat fields accept [0, 2^64−1], including field-25 rsslim's
20-digit `18446744073709551615`; signed stat fields accept [−2^63, 2^63−1].
Consumed PID, PPid and starttime values retain their narrower nonnegative <2^63
parsing bound, and roster PIDs retain the 2^31−1 cap. Other integers and
byte-normalized counters must fit below 2^63. Control line separators other than
LF and tab are rejected. Stat has at most 256 tail fields. These explicit bounds
admit current 52-field Linux stat fixtures, without promising acceptance of every
possible future kernel text. Global reason sets are not recopied per read/frame;
frame reasons use a linear slice of newly appended entries.

Callbacks are trusted to return promptly and respect their requested bound. A
synchronous injected API cannot preempt an uncooperative callback or prevent it
from allocating memory or touching the OS. This milestone contains no timer,
thread or subprocess to enforce callback wall time. A future authorized runner
must independently bound callback execution; the provider bounds its own read
count/parsing/allocation and rejects excessive observed skew. No new production
dependency or architecture change is introduced here.

The input is copied before any callback; a callback mutating the caller's request
cannot change this capture. Returned structures are detached from the input,
provider state, other captures and shared metadata in other frames. The integrity
seal is SHA-256 of UTF-8 canonical JSON excluding `integrity`: sorted keys,
indent=2, ensure_ascii=true, allow_nan=false, trailing newline. It provides
integrity, not origin authentication. The validated request has a separate hash;
source strings have separate hashes and are never serialized into the result.

All paths fix `production_memory_qualification=INCONCLUSIVE`,
`production_chronological_peak=NOT_OBSERVED`, `production_workload_measured=false`,
`origin_attestation=UNVERIFIED`, `holder_release=NOT_ESTABLISHED`,
`atomic_snapshot=false`, and
`bound_claim=NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK`. There is no holder release,
owner termination, concurrent memo occupancy, production qualification, measured
workload, aggregate RSS, sampled maximum or true continuous peak assertion.

`worker_absence_proven` is always false. Empty rosters have coverage
`NOT_ESTABLISHED`. A successfully read registered worker roster is
`REGISTERED_ROSTER_OBSERVED`; failed capture coverage is `UNCERTAIN`.
`unregistered_worker_coverage` always remains `NOT_ESTABLISHED`. Workers born and
exited between observations can remain invisible. No roster establishes worker
absence, and no sequential collection establishes atomicity or a peak bound.

## Regression coverage and execution status

The new suite uses only inline artificial source strings, fixed boot/namespace
identities, deterministic clocks and fake reader exceptions. It covers valid
parent/worker samples and callback order; parentheses, PID reuse, parent mismatch,
full 52-field stat with unsigned RSS limits and signed scheduling fields, i64/u64
endpoints and overflow, dead states without Vm* fields, bad/duplicate/missing
status fields; oversized/truncated text and numeric guards; error mappings;
clock ties/failures/decreases/skew; registered worker departure and late arrival
across frames, successful frame preservation and worker coverage uncertainty;
separate cgroup counters/baselines and optional failures; nested
schema/type/path/cap attacks; source immutability, deterministic seals and detached
results. Import/construction/sampling run under patched live APIs and a restricted
import allowlist. D1 is checked read-only for its unchanged schema and rejection
of real-source labels and the new envelope.

**No tests, builds, benchmarks, experiments or provider calls were executed by the
implementer.** Test results are pending independent review and orchestrator
verification; this document claims no passing count or acceptance. The authorized
orchestrator command is the six-suite targeted pytest argv in `.ai/TASK.md`,
including this new suite and the five unchanged predecessors. Acceptance requires
more than 846 passing tests, zero skipped, zero BLOCKER/MAJOR findings, scope and
immutable-source checks, followed by the independent audit. No commit, staging,
branch change, installation or push is part of this implementation.
