# F2-B4-D2-B2-B0: bounded native procfs adapter hardening, artificial I/O only

This gate hardens the existing D2-B2-A native Linux capture **capability**, its
artificial filesystem regression suite, and this document. No native capture, measured process, workload,
benchmark, test run, or production memory observation was performed by the
implementer. The numerical engine and the 256-entry memo policy are unchanged.

`production_memory_qualification=INCONCLUSIVE` and
`production_chronological_peak=NOT_OBSERVED` in every result.

## Trust boundary and API

The module is self-contained and uses only the standard library. Its bounded
parsers validate stat numeric tails and status fields while treating stat comm
and status Name values as opaque bytes. It does not import or modify any
predecessor. D2-B1 continues to reject real
sources. D2-A, D2-B1, D1 and their accepted schemas are unchanged. The new envelope
cannot be passed to those consumers as a qualifying observation.

`NativeProcfsAdapter(filesystem=None, monotonic_ns=None)` only stores its
arguments. `sample(request=None, *, native_opt_in=None)` is the sole public
capture entry point. Import, construction, missing/default configuration and
request-validation failures perform zero filesystem reads or clock calls.

Artificial captures require both an injected filesystem facade and a clock:

- `filesystem.open(name, *, directory, dir_fd) -> fd`: exact nonnegative integer.
- `filesystem.read(fd, limit) -> bytes`: exact built-in bytes; empty means EOF.
- `filesystem.close(fd)`: close once, with no retry.
- `monotonic_ns() -> int`: exact integer in `[0, 2**63-1]`, nondecreasing.

These are trusted, artificial, nonblocking test doubles. The adapter checks
returned sizes/types and stops on violations; Python cannot preempt a callback
that hangs, prevent its own external I/O, or undo its allocations. Injecting a
facade that itself performs native I/O is outside the artificial-I/O contract and
does not confer native provenance.

Native selection requires all of the following **at call time**, after complete
bounded request validation:

1. `capture_mode="NATIVE"` and `source_kind="NATIVE_REQUEST"`.
2. The exact built-in string `NATIVE_OPT_IN` supplied through the `native_opt_in`
   keyword. No constructor flag, request field or environment variable opts in.
3. Neither a filesystem nor a clock was injected.
4. Linux and the required `O_NOFOLLOW`, `O_DIRECTORY`, `O_CLOEXEC`, `O_RDONLY`
   flags are available.

Only then does the adapter bind its minimal `os` facade and
`time.monotonic_ns`. Combining any injection with a native request or call-time
opt-in fails before calling the injection. Default execution never falls back to
native I/O. The tests replace the native-facade constructor with a
rejecting guard and block all `os.open/read/close`, including relative `openat`
paths. A positive control satisfies every native gate with a blocking fake
facade and stops at its first root-open attempt using a `BaseException` sentinel,
before any native I/O or clock call. A second fake root-open failure returns an
unverified native envelope and checks its nonqualifying source/clock labels;
existing OS flag constants are preserved. Direct checks of the real facade use only
disallowed paths, which must fail before `os.open`. No native bytes are produced.

The opt-in is a technical interlock, not permission to run a live capture.
D2-B2-B1 requires separate explicit user authorization and an independent safety
preflight. B0 authorizes only the blocked artificial positive control, with no
real `/proc` or cgroup reads, child creation, live smoke or production run.

## Versioned schemas

Request: `rawibumi.native-procfs-adapter.f2b4.d2b2a.v1`.
Result: the same identifier with `.result` appended. This is a separate,
nonqualifying capture envelope, with no backward-compatibility conversion.

All object keys below are exact: missing or extra fields fail. Inputs are bounded,
deep-copied JSON values; custom objects, cycles and invalid Unicode fail before
callbacks. JSON depth is at most 16, node count 20,000, individual string size
65,536 UTF-8 bytes, total string bytes 4,194,304, and integers fit i64/u64 bounds.

The request root contains exactly:

| Field | Contract |
| --- | --- |
| `schema` | Request schema above |
| `capture_mode` | `INJECTED` or `NATIVE` |
| `source_kind` | `TEST_INJECTED` for injected; `NATIVE_REQUEST` for native requests |
| `run_id` | Caller label, up to 96 ASCII characters |
| `config` | Exact configuration described below |
| `roster` | `parent`, `workers`, `complete` |
| `frame_rosters` | 1–32 caller-asserted lists of observed positive PIDs |
| `cgroup` | `null` or exactly `{"enabled": false}`; no cgroup reader exists |

Labels use `[A-Za-z0-9][A-Za-z0-9_.:-]*` and exclude `..`. PID namespace IDs are
opaque caller labels such as `pidns:77`, not filesystem paths or raw nsfs strings.
Boot IDs use the UUID-shaped hexadecimal representation. Neither is read from
the host. The supplied clock-tick rate is caller-asserted, with no `sysconf` or
starttime-to-wall-clock calibration.

Each registered identity has exactly `pid`, `ppid`, `starttime_ticks`, `boot_id`,
`pid_namespace_id`, `role`. PIDs are exact integers in `[1, 2**31-1]`; PPID allows
zero. Starttime accepts the complete unsigned 64-bit range. The parent has role
`parent` and an external PPID. Workers have another label and the registered
parent's PID as PPID. Duplicate PIDs fail; boot and namespace values must match
config. Up to 64 identities, including the parent, are allowed.

Configuration has exactly these fields:

| Field | Accepted bounds or values |
| --- | --- |
| `clock_ticks_per_second` | 1–1,000,000 |
| `boot_id`, `pid_namespace_id` | Caller-asserted provenance as above |
| `max_read_skew_ns` | 0–`2**63-1` |
| `max_bytes` | 1–65,536 per leaf stream |
| `max_total_bytes` | 1–4,194,304 across the capture |
| `max_read_attempts` | 1–16,384 read calls, including EOF reads |
| `max_read_iterations` | 1–128 calls per leaf stream, including EOF reads |
| `smaps_rollup_policy` | `NOT_SAMPLED` or `OPTIONAL_DIAGNOSTIC` |

Frame lists have at most 64 distinct PIDs. They are assertions, not discoveries.
Unknown PIDs are flagged and never read. A missing asserted registered PID flags
the frame but does not suppress registered reads. `complete=false` is incomplete.
Even a consistent complete roster never proves absence of unknown workers.

## Provenance and fixed nonclaims

Every rejected/default or injected result has `source_kind=TEST_INJECTED`,
`origin_attestation=UNVERIFIED`, `qualification=NONQUALIFYING`. No injected result
emits `REAL_PROCFS`, `LOCAL_COLLECTOR_RECORDED`, `FAKE_FIXTURE`,
`PROCESS_RSS_SAMPLE_COMPLETE`, `OBSERVATION_COMPLETE` or production qualification.
User-supplied origin, qualification and outcome fields are rejected.

A later authorized native call uses `source_kind=NATIVE_PROCFS_UNVERIFIED` and
`origin_attestation=UNVERIFIED_NATIVE_CAPTURE`, selected only after the native
gates pass. This deliberately stops at the work order's separate, nonqualifying
native envelope: no attested real-source route or independent verifier is added.
All results have `independent_verification=REQUIRED_NOT_PERFORMED`.

Neither branch establishes holder release, owner termination, concurrent cache
occupancy, a chronological production peak, worker absence or coverage of unknown
workers. `atomic_snapshot=false` and
`bound_claim=NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK` are fixed. `VmRSS` and `VmHWM`
are per-process kernel approximations in bytes (`kB * 1024`), reported separately.
Optional rollup fields remain diagnostics. There is no RSS sum, aggregate,
maximum, cgroup accounting, or purported simultaneous lower bound.

Local hashes are integrity checks, not authentication. Python callers can change
module globals or code; the technical gates are not a security boundary against
a caller who controls the interpreter. The blocked positive control tests gate
reachability only; it cannot establish native provenance or qualifying evidence.

## Paths, read budgets and frame lifecycle

Native glue opens only constant `/proc`, then validated decimal registered PID
directories relative to that descriptor, and `stat`, `status`, optional
`smaps_rollup` relative to the held PID descriptor. Every open uses `O_NOFOLLOW`
and `O_CLOEXEC` with `O_RDONLY`; directories additionally use `O_DIRECTORY`.
The facade itself rechecks the root/PID/leaf allowlist before calling `os.open`,
which always receives `dir_fd=dir_fd`. No caller path,
filename, enumeration, automatic registration or process discovery is supported.

The root is opened once per capture. Each frame opens its PID directories once,
then reads every `stat_before`, every `status`, optional rollups, and every
`stat_after`. PID descriptors are held through both identity barriers. There is
no reopen retry. Directory descriptors are not pidfds and do not prove process
liveness. `/proc` is not independently verified as a procfs mount; `hidepid` may
make a live process look missing. No boot file, namespace link, task tree,
command line or unrelated host metadata is read.

For each stream, `cap=min(max_bytes, remaining_total_bytes)`. The first read asks
for `cap+1`; each subsequent short-read request asks for `cap+1 - bytes_returned`.
EOF is required. One extra returned byte is an overlimit failure, never a silent
truncation. With a compliant facade the capture may consume one sentinel byte
beyond its total-byte budget, then stops; the hard maximum is therefore
`max_total_bytes+1`. A larger-than-requested chunk or non-exact bytes stops capture
as a contract violation without hashing/copying the oversized result.

Open attempts have the independent finite cap
`1 + frame_count * MAX_PROCESSES * 5`, covering root plus one PID directory and
at most four leaf opens per registered process/frame. Short reads are bounded
by both per-stream iteration and capture-wide read-call budgets. No read retry,
background loop, scheduling, sleep, spawn, networking or cgroup operation exists.
Frames are bounded back-to-back operations; later frames are not fabricated once
capture stops. A `CAPTURE_STOPPED` reason records omitted requested frames.

Every read records its label, PID, requested limits, read-call count, monotonic
start/end, exact returned byte length, SHA-256, status and reasons. On an I/O
failure the digest covers the bounded prefix actually returned (empty if none),
not an asserted complete source. `byte_provenance_complete` means all returned
bytes could be accounted for; it does not mean EOF or a valid source. Contract
violations have no digest. Reasons preserve simultaneous read and clock failures.
Exception messages and arbitrary exception class names are never serialized.

Pre/post observations retain only PID, PPID, starttime and state. No comm, Name,
raw source text or command line enters evidence. Stat uses a strict ASCII PID
prefix without leading zeros and the final `) ` separator; only its state/numeric tail is ASCII-decoded
and validated. Comm is fully opaque, including embedded parentheses, newlines,
controls (even NUL), invalid or truncated UTF-8, digit runs and empty names. Its
only length bound is the existing per-stream byte budget; no 15-byte assumption
is imposed. Status is split on byte newlines, discards Name values before text
validation, and still detects duplicate Name keys. Other status fields and all
smaps text retain strict UTF-8, control, digit-run and structural checks.

Per-frame first/last read times use the minimum actual start and maximum actual
end across processes; the capture window uses the same extrema across frames.
This includes failed reads when later reads are `NOT_READ`. Skew and window
completeness are recorded. Times can tie; regression, invalid
clock values or clock exceptions stop capture. Skew over the configured limit
fails the frame. The envelope has capture-wide windows and byte/open/read counts.

## Failure classification

`INVALID` takes precedence over `INCOMPLETE`; a reason-free frame/result is
`CAPTURE_CONSISTENT_NONQUALIFYING`. All results remain explicitly nonqualifying.
Within stat/status parsing, a missing final newline yields `TRUNCATED` before
UTF-8 or control-character validation, including when both defects are present.

- `INCOMPLETE`: disappearance (ENOENT/ESRCH), permission denial, generic I/O or
  callback exceptions, PID reuse/starttime drift, PPID drift at **either** status
  or stat, zombie/dead state, live state without memory fields, incomplete/missing/
  unknown roster members, truncated streams, overlimit input, exhausted I/O
  budgets, excessive skew, or stopped capture.
- `INVALID`: malformed text/UTF-8 outside opaque comm/Name values,
  duplicate/missing required structural fields,
  integer overflow, PID contradictions, non-leader `Tgid != Pid`, inconsistent
  VmHWM/VmRSS, traversal/symlink errors (ELOOP/ENOTDIR), read contract violations,
  invalid/regressing clocks, schema/configuration/provenance/permission-gate
  violations.

No ordinary lifecycle race is represented as malicious corruption. Every frame
with any reason clears **all** process RSS/HWM/rollup values and gives every
process the frame's failure status. Close errors are recorded and never retried;
a root-close failure also demotes the last frame and clears its values. Every
successfully obtained descriptor receives one close attempt, including failure
paths. Earlier independently complete frames can remain consistent if a later
frame fails, while the overall capture reports failure.

`OPTIONAL_DIAGNOSTIC` does not waive the frame failure rule: a smaps_rollup
`EACCES`/`PERMISSION_DENIED` demotes the entire frame to `INCOMPLETE` and clears
every process's RSS/HWM/rollup values, including otherwise consistent status
reads. Prefer `NOT_SAMPLED` for the separately authorized first live smoke.

## B0 review dispositions

- **M1 fixed:** frame and capture windows use actual timestamp extrema;
  regressions stop a two-PID capture on the first PID's closing stat with later
  reads omitted, and retain nonqualification and whole-frame value clearing.
- **M2 fixed:** the fully gated native positive control blocks at the fake root
  open with zero os/clock calls. AST checks require the exact `dir_fd` argument,
  base read-only/no-follow/close-on-exec flags and conditional directory flag,
  with native os calls confined to the three facade methods.
- **M3 fixed:** FakeIO records path, descriptor and read-limit violations in
  external ledgers checked after captures and at fixture teardown, including
  direct adapter calls and incomplete outcomes. Native guards also record
  attempts. Negative controls prove an unauthorized PID cannot silently pass
  the harness even when the adapter returns `INCOMPLETE`.
- **M4 fixed:** comm and Name are opaque bytes, never retained or serialized;
  strict PID/PPID/starttime/state and numeric-tail validation remains. Artificial
  regressions cover unusual names and relocate malformed-byte coverage to
  prefixes, tails and non-Name status fields.
- **O1 fixed:** the facade rechecks its own root/PID/leaf allowlist before os I/O.
- **O2 fixed:** a sealed `KNOWN_CODES` vocabulary maps unknown or non-string
  injected `_Violation` codes to existing `READER_CONTRACT_VIOLATION`, including
  close failures. Known-code spoofing by a trusted injected callback remains
  possible; injection still cannot establish authentic native provenance.
- **O3 documented and pinned by regression:** optional rollup permission failure
  demotes the whole frame; first-smoke guidance is `NOT_SAMPLED`.

Round-one review follow-up fixes the reason-vocabulary test to collect only
code values (including both conditional result branches), excluding strings in
conditional predicates such as the `max_bytes` config key. Required-code sanity
checks prevent an empty or over-narrow extraction from passing. Additional
regressions reject a leading-zero stat PID, verify the sample helper catches a
swallowed fake path violation, and check the blocked native failure envelope.

The schema identifiers, opt-in string, result keys, reason-code vocabulary,
unit conversion, 256-entry cache policy and fixed nonclaims are unchanged.

## Regression coverage and verification handoff

The new tests use hand-written Linux-shaped stat/status/rollup bytes, fake file
descriptors and deterministic clocks only. They cover import/constructor
inertness, static native flags/path surfaces, default deny and source laundering,
input caps, roster completeness, one-parent/one-worker and no-worker frames,
frame identity barriers, u64/i64 endpoints, malformed/truncated/duplicate text,
status-side reparenting as INCOMPLETE, exit races, access/path/I/O errors, partial
reads/digests, sentinel/total/iteration/attempt budgets, clock failure/skew,
close cleanup, leakage, deterministic envelopes, disabled cgroups and predecessor
rejection. Tests do not use skip or xfail.

The implementer did **not** run pytest, test functions, builds, benchmarks, native
sampling or production simulations. Static syntax parsing and repository/hash
inspection are implementation checks only, not test acceptance. Exact source
hashes, review reports, test results, status snapshots and the external ZIP are
orchestrator/auditor handoff work, not acceptance claims in this document.

After independent Claude review PASS with zero blockers/majors, the orchestrator
alone runs the exact eight-suite command in `.ai/TASK.md`: this new suite plus
F2-A, F2-B1, F2-B2, F2-B3, D1, D2-A and D2-B1. The pinned D2-B2-A baseline is 1,499
passed; acceptance requires more than 1,499 passed, zero failed, zero skipped and
zero xfail. These results remain pending orchestration after review PASS.
The independent acceptance audit, evidence ZIP outside this repository, any local
commit, D2-B2-B1 live smoke and D3 production measurement have distinct later gates.
