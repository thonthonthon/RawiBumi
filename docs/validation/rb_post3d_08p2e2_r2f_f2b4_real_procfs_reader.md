# F2-B4-D2-B1: bounded injected byte reader and provenance envelope

D2-B1 supplies code and artificial-I/O regression tests. No live collection,
workload, benchmark, test execution, install, commit or push was performed by
the implementer. The orchestrator executes verification only after Claude review
PASS. D2-B2 live toy collection and D3 production experiments remain **HOLD**.

Scientific state remains `production_memory_qualification=INCONCLUSIVE` and
`production_chronological_peak=NOT_OBSERVED`. Holder release, simultaneous holder
occupancy and a memo-cap justification remain unestablished. The cache limit
remains 256.

## API boundary and provenance

The standalone module is
`scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_real_procfs_reader.py`.
Its request schema is `rawibumi.real-procfs-reader.f2b4.d2b1.v1`; its result
schema appends `.result`. It imports only `hashlib`, `json` and `re` and has no
module-level calls or default callback selection. Import and construction are
inert. It neither imports nor modifies D2-A, D1 or the observer/lifecycle stack.

`RealProcfsReader(read_proc=None, monotonic_ns=None, read_cgroup=None)` only stores
callbacks. `sample(request)` is the explicit callback entry point. All callbacks
in this gate must use artificial data. No native adapter exists. `REAL_PROCFS`
and `NATIVE` requests return `REAL_SOURCE_NOT_AUTHORIZED` before invoking any
callback or clock. Other source labels, including predecessor synthetic labels,
are rejected. The output always assigns `source_kind=TEST_INJECTED` and
`origin_attestation=UNVERIFIED`, including on rejected requests. A rejected
request produces no frames; its output label describes the available injected
mode, not an observation of the requested origin.

`REAL_PROCFS` and `LOCAL_COLLECTOR_RECORDED` are reserved for a future separately
authorized native adapter. The latter would mean local program attestation,
not cryptographic authenticity. They are never emitted by this implementation.
Attaching actual procfs callbacks to the injected mode is outside this contract;
Python cannot authenticate the external behavior of an arbitrary callable.
D2-A remains fake-only and must never receive actual data labeled `FAKE_FIXTURE`.

The distinct success outcome is `INJECTED_READS_CONSISTENT_NONQUALIFYING`. It means
only that supplied byte reads and caller assertions passed this envelope's
checks. It grants no process-sample, observation, workload, temporal-coverage or
production qualification. The envelope deliberately contains no cross-process
RSS sum. The predecessor validators reject its versioned schema.

## Closed request contract

Only exact JSON built-in types are allowed: dict, list, str, int, bool and null.
Floats (including NaN), subclasses, non-string keys, cycles and excessive inputs
fail before callbacks. The input is copied before any callback; later mutations
cannot change an in-flight request. Unknown or missing fields fail closed.

A minimal artificial parent-only request is:

```json
{
  "schema": "rawibumi.real-procfs-reader.f2b4.d2b1.v1",
  "source_kind": "TEST_INJECTED",
  "run_id": "fixture-run",
  "reader_source_sha256": null,
  "config": {
    "clock_ticks_per_second": 100,
    "boot_id": "11111111-2222-3333-4444-555555555555",
    "pid_namespace_id": "pidns:77",
    "max_read_skew_ns": 1000,
    "max_bytes": 4096,
    "max_total_bytes": 1048576,
    "max_read_attempts": 1000,
    "smaps_rollup_policy": "NOT_SAMPLED"
  },
  "roster": {
    "parent": {
      "pid": 100,
      "ppid": 1,
      "starttime_ticks": 10,
      "boot_id": "11111111-2222-3333-4444-555555555555",
      "pid_namespace_id": "pidns:77",
      "role": "parent"
    },
    "workers": [],
    "complete": true
  },
  "frame_rosters": [[100]],
  "cgroup": null
}
```

Every registered worker has the same six identity fields as the parent; its
`ppid` must equal the parent's registered PID and its role must be a label other
than `parent`. PIDs are positive integers through 2^31−1, PPIDs may be zero,
and no PID may be registered twice. Parent PPID cannot name a registered PID.
Starttime accepts the full unsigned 64-bit range [0, 2^64−1], in kernel clock
ticks since boot. It is not a wall-clock timestamp. Boot IDs use UUID syntax.
Every identity must match the configuration's separate boot and PID-namespace
provenance; mismatch prevents all reads.

Labels are opaque strings of at most 96 characters matching
`[A-Za-z0-9][A-Za-z0-9_.:-]*`, excluding `..`. Namespace labels such as `pidns:77`
are caller-assigned identifiers, not raw nsfs links. Raw `pid:[...]`, systemd
paths and escaped unit names are not accepted as labels. Any future native
adapter must explicitly map verified OS identities to immutable opaque tokens
without accepting user paths or weakening traversal restrictions.

`frame_rosters` is one list of caller-asserted present PIDs per requested frame.
It does not discover processes. An unknown PID is never read, and a registered
but absent identity remains in the frame with unsuccessful read placeholders.
Missing, late, extra and vanished workers or `roster.complete=false` demote the
capture. Even matching complete assertions cannot prove unregistered workers
absent: `worker_absence_proven=false` and `unregistered_worker_coverage` remains
`NOT_ESTABLISHED`. No lifecycle events, holder release or owner termination are
fabricated. Phase and lifecycle evidence required for a future qualification
path is not established by this API.

`reader_source_sha256` is null or 64 lowercase hexadecimal characters. The
result binds it as `CALLER_ASSERTED_ONLY`, or reports `NOT_RECORDED` for null.
The module never reads its own source. The exact reader version, run ID,
configuration, registered identities and canonical request SHA-256 are bound
into the result. An external orchestrator must record the actual new-file
hashes; this field cannot substitute for that verification.

## Callback and bounds contract

`read_proc(path, limit)` returns **exact bytes**. The module constructs only
`/proc/<registered-pid>/stat`, `/proc/<registered-pid>/status`, and, when enabled,
`/proc/<registered-pid>/smaps_rollup` string arguments. In B1 these strings are
pure lookup keys for fake path resolvers. It never opens them. There is no path
input, discovery, directory enumeration, process-name scan, background task,
subprocess, network, OS clock or filesystem adapter.

| Bound | Limit |
| --- | --- |
| Registered identities, including parent | 64 |
| Requested frames | 32 |
| Configured file byte cap | 1–65,536 |
| Configured total byte budget | 1–4,194,304 |
| Configured attempted reads | 1–8,288 |
| Input depth / visited nodes | 16 / 20,000 |
| Single / total UTF-8 input string bytes | 65,536 / 4,194,304 |
| Monotonic ns timestamps and skew limit | 0–2^63−1 |
| Stat unsigned / signed fields | u64 / i64 |
| Consecutive whitespace / digits | 64 / 20 |
| Stat fields through the final supported field | 52 |

Each read receives `min(max_bytes, remaining_total_budget) + 1` as its maximum
return length. A conforming future native adapter must perform at most that
bounded read. Exactly the extra detection byte yields `OVERSIZED` (or
`TOTAL_BYTES_CAP_EXCEEDED` when the total budget reduced the cap); it is never
parsed or silently truncated. Returning more is
`READER_CONTRACT_VIOLATION` and stops capture. Non-exact bytes, including str,
bytearray, memoryview and bytes subclasses, also stop capture. With conforming
callbacks total returned bytes are bounded by the configured budget plus one
detection byte. Hostile callbacks can allocate/return more or block forever;
this pure injected library cannot preempt them. Their excessive buffers are
not decoded or hashed. Callback bounds are obligations, not OS isolation.

Bounded byte results retain byte length and SHA-256 even when decoding or the
end clock fails. Oversized results within the callback limit retain their hash.
Callback violations retain the observed length where available, without
hashing an arbitrarily oversized object. Each attempted read records its order,
kind, registered target, monotonic start/end window, status, reasons and a safe
exception class. Known built-in exception classes are preserved; custom
classes are normalized to the relevant built-in family. No exception message,
raw stat command, raw status text or unrelated command line is exported.

UTF-8 decoding is strict. Missing final newline, NUL/C0/C1 controls other than
horizontal tab and LF, Unicode line separators, overlong digit or whitespace
runs and malformed/duplicate fields fail closed. Unknown status fields must
still have valid field syntax but are not interpreted or exported. Known memory
fields require integer `kB`, converted using 1024 bytes per kB, with overflow
rejection. VmHWM must be at least VmRSS for that status read. smaps fields require
the same units and its Rss and Swap fields are mandatory. The optional rollup
header supports normal padding. Full hand-written Linux-shaped status, stat
and smaps fixtures guard format compatibility without reading a host.

The stat parser locates the final command `)`, so embedded spaces and parentheses
do not shift field 22. It validates all numeric fields present using Linux i64
or u64 bounds, including a u64-max rsslim, negative tpgid, priority and nice.
At least fields 1–22 must exist. Embedded LF in command text, invalid UTF-8 comm,
unknown future fields beyond 52 and other unsupported text deliberately fail
closed; B2 compatibility still needs its own approval and review.

For each present identity the normal sequence is `stat_before`, `status`,
optional `smaps_rollup`, then `stat_after`. Both stat identities must match the
registration's PID, PPID and starttime; status PID/PPID must agree as well.
A failed pre-read identity prevents status/smaps reads (`PRIOR_IDENTITY_UNVERIFIED`)
while retaining an attempted stat-after check unless capture has stopped.
Zombies/dead processes, PID reuse, reparenting, disappearing processes and a
live status lacking Vm fields all remain nonqualifying. Status/stat contradictions
are invalid; ordinary lifecycle gaps are incomplete. State changes between
live R/S/D states are allowed and are not identity changes.

The injected monotonic-ns clock is called before and after each callback,
including failed reads. Ties are allowed. Invalid values, exceptions or
regressions stop capture; no replacement timestamp is invented. Each frame
and capture records first start, last successful end and their observed span;
`read_window_complete=false` exposes missing windows. A partial span is not a
substitute for a missing end time. Per-frame excess skew demotes the frame.
Clock-tick identity and monotonic ns domains are never aligned or inferred:
`starttime_alignment=NOT_CALIBRATED`. No inter-frame cadence or continuous
coverage claim is made.

## Separate gated cgroup diagnostics

Cgroups default to null/off and require a separate callback
`read_cgroup(token, kind, limit)` plus this closed object:

```text
enabled: true
token: opaque label (not a path)
controller_id: opaque caller-asserted cgroup-v2 controller label
membership: exactly the unique registered PIDs
membership_provenance: opaque caller assertion label
boot_id, pid_namespace_id: exactly the configuration domains
baseline:
  memory_current_bytes, memory_peak_bytes: u64 integers
  events: named u64 counters, requiring low/high/max/oom/oom_kill
  observed_ns: nonnegative i64 monotonic timestamp
  provenance: opaque caller assertion label
```

Only `memory.current`, `memory.peak` and `memory.events` are requested, in that
order, under the same byte and clock bounds as process reads. No cgroup path is
resolved, no membership is discovered, and there are no writes or resets.
Membership and baseline remain `CALLER_ASSERTED_ONLY` under TEST_INJECTED.
Baseline chronology must precede the cgroup read start. Peak and event counters
cannot decrease from the baseline or a previous successfully parsed cgroup
section. An event name previously present cannot disappear. The diagnostic
reference advances even if an unrelated process/skew failure subsequently
invalidates the frame: this conservatively detects later resets and does not
promote the failed frame. The test suite pins this behavior.

Current can decrease and is not compared to peak in either the baseline or the
sequential reads: there is no atomic correspondence assumption. Increasing event
counters are retained as diagnostics, with no workload acceptance implied.
Cgroup accounting is distinct from process RSS, can include descendants and is
never added to VmRSS or VmHWM. Missing callback, namespace mismatch, malformed
counters, missing events, permissions, unavailable files, resets or bad baseline
chronology cannot yield a consistent frame.

## Failure handling and fixed nonclaims

Any frame reason clears **all** process VmRSS/VmHWM/smaps values and **all**
cgroup current/peak/events values. Registered identities and successful/failed
read provenance remain visible; no partial success survives. Failed cgroup
sections retain the caller's explicitly labeled baseline, not observed values.
Optional smaps/cgroup failures conservatively demote the entire frame. Earlier
consistent frames may retain their values but never promote a failed capture.

If the clock, attempt budget, total budget or callback contract stops capture,
all identities in the current partial frame remain present with unsuccessful
placeholders as needed. Later frames are not fabricated: `frames_requested`
and `CAPTURE_STOPPED` make missing temporal coverage explicit.

| Class | Exact reason codes |
| --- | --- |
| Invalid input / schema | INPUT_NOT_JSON, INPUT_CAP_EXCEEDED, SCHEMA_INVALID, UNKNOWN_FIELD, SCHEMA_VERSION_MISMATCH |
| Invalid source / configuration | SOURCE_KIND_NOT_ACCEPTED, REAL_SOURCE_NOT_AUTHORIZED, CONFIGURATION_INVALID, IDENTITY_INVALID, DUPLICATE_IDENTITY, BOOT_ID_MISMATCH, PID_NAMESPACE_MISMATCH, CGROUP_CONFIGURATION_INVALID |
| Invalid byte/text/identity contract | READER_CONTRACT_VIOLATION, RAW_TEXT_MALFORMED, INVALID_UTF8, DUPLICATE_FIELD, MISSING_FIELD, STATUS_STAT_CONTRADICTION |
| Invalid clock/counter provenance | CLOCK_FAILURE, CLOCK_NON_MONOTONIC, COUNTER_INCONSISTENT, BASELINE_CHRONOLOGY_INVALID |
| Incomplete lifecycle / roster | PID_REUSE_OR_IDENTITY_RACE, PROCESS_REPARENTED, PROCESS_NOT_LIVE, PROCESS_MEMORY_UNAVAILABLE, PROCESS_VANISHED, REGISTERED_PROCESS_MISSING, UNKNOWN_PROCESS, ROSTER_INCOMPLETE, PRIOR_IDENTITY_UNVERIFIED |
| Incomplete I/O / windows / budgets | PERMISSION_DENIED, READ_FAILED, READER_EXCEPTION, CGROUP_UNAVAILABLE, READER_NOT_CONFIGURED, CGROUP_READER_NOT_CONFIGURED, CLOCK_NOT_CONFIGURED, OVERSIZED, TRUNCATED, TOTAL_BYTES_CAP_EXCEEDED, READ_ATTEMPT_CAP_EXCEEDED, CAPTURE_STOPPED, READ_SKEW_EXCEEDED |

Reasons preserve code and location, deduplicated deterministically; read sequence
is retained in ordered frame/process/read arrays and numbered actual attempts.
INVALID takes precedence over INCOMPLETE, which takes precedence over the
nonqualifying consistency outcome. A canonical SHA-256 integrity seal covers
the complete result excluding its integrity object. It detects accidental
changes relative to the seal, not forgery; anyone can recompute it.

VmRSS and VmHWM remain approximate process counters. Per-process HWM is not a
simultaneous-worker peak. Sequential multi-PID reads are not atomic, and their
sum is neither an established lower bound nor the exact instantaneous peak.
A sampled maximum would not prove a continuous peak. This implementation does
not compute either aggregate or maximum. Logical owner end-of-use, physical
holder release, simultaneous holders and cache policy cannot be inferred.

## Verification handoff

The new unit suite uses deterministic bytes, fake path lookup and fake clocks.
It covers normal parent/worker reads, format and u64/i64 boundaries, identity
reuse/contradictions, domain mismatches, disappearance/permissions, late/missing/
extra workers, source laundering, schema/cycle/cap failures, clock regression/
skew, byte limits and hashes, partial frames, cgroup failures/baselines/resets,
inert import/constructor and detached snapshots. Guards forbid live procfs or
cgroup opens, discovery at those paths, process spawning and sockets. A stricter
inertness test blocks filesystem, time and process operations and restricts
imports before executing the precompiled module source; it never selects a
native collector. No skips or expected failures are added.

No tests were run by the implementer. AST parsing is static syntax inspection,
not execution of the module or tests. After final Claude PASS with zero
BLOCKER/MAJOR findings, the orchestrator must run the exact seven-suite argv in
`.ai/TASK.md`, require more than 1,142 passes and zero skips, and preserve the
review round, test argv/results, before/after Git state, actual file hashes,
work order and contract in a verified SHA-256-manifest ZIP outside the repository.
Independent audit and a separately authorized commit remain later gates.

Existing D2-A review findings informed this separate implementation: full u64
stat formats are covered; stale cgroup observed values are cleared; lifecycle
races remain incomplete; realistic status/smaps fixtures are supplied; and
namespace/cgroup path mapping remains explicit and opaque. No predecessor
source or contract was changed.
