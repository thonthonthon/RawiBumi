# F2-B4-D2-B2-B2: supplied provenance and coverage

This gate is code-only and artificial-I/O-only. It assesses supplied records; it
does not collect evidence. The earlier isolated toy smoke remains
`ISOLATED_NATIVE_SMOKE_PASS_NONQUALIFYING` and authorizes no additional native
operation. No production caller, native opt-in, predecessor, memo policy, or
scientific record is changed.

## API and immutability

`assess_provenance(captures, requests, evidence) -> Assessment` accepts three
equal-length, ordered, exact Python lists containing one to eight corresponding
records. A single capture uses one-item lists. The sequence declares continuity
of one boot, PID namespace, procfs mount and registered process set. Separate
boots or unrelated sessions require separate assessments. Missing or changed
identities in a declared sequence cannot silently establish continuity.

`Assessment` is a frozen dataclass holding `serialized`, the canonical JSON
assessment string. `to_dict()` returns a detached JSON-safe tree on each call.
Neither returned dictionaries nor later edits to inputs change the assessment.
The verifier first copies bounded plain JSON data. It never mutates the request,
result, source labels, recorded digest, or probe records, including on failure.
Callers must not concurrently mutate inputs during that copy.

The only predecessor imports are `SCHEMA`, `RESULT_SCHEMA`, and `canonical_json`
from the hardened native adapter. Import and assessment have no file, process,
network, clock, namespace, system-boot, discovery or callback surface. In
particular the verifier does not construct an adapter or a native facade.

## Exact input contracts

The request and capture use the existing native-adapter schemas. Additional keys
at every validated schema level are rejected. Requests retain their original
`capture_mode`, `source_kind`, config, roster and frame rosters. Every process
registration contains PID, PPID, starttime ticks, boot ID, namespace label and
role. The adapter's numeric bounds and parent/worker registration rules apply.
Booleans never substitute for integers. Boot IDs must already be lowercase
canonical UUID text (`8-4-4-4-12` hexadecimal); uppercase, braces and shortening
are rejected without normalization. This B2 restriction is intentionally stricter
than the adapter's mixed-case UUID acceptance.

One evidence object has exactly these keys:

| Key | Contract |
| --- | --- |
| `environments` | One to eight environment records, described below. |
| `processes` | Zero to 64 independent process claim records. Each has exactly `pid`, `ppid`, `starttime_ticks`, each a field record. Missing claims cause incomplete coverage. |
| `alignment` | `null`, or exactly `monotonic_ns` and `boottime_ns`, each a field record. |
| `coverage` | Exactly `frame_phases`, `required_phases`, `max_frame_gap_ns`. |
| `claimed_trust` | One of the three supported tiers or a recognized future-only tier, which is rejected. |
| `discovery` | Field record with value `UNKNOWN`, `ROSTER_ONLY`, or `INDEPENDENT_INJECTED`. All remain unauthenticated. |
| `cgroup_diagnostic` | `null` or a field record containing an unsigned 64-bit byte counter; diagnostic only. |

Every field record has exactly `value`, `source`, `status`:

| Field | Vocabulary and meaning |
| --- | --- |
| `source` | `CALLER`, `INJECTED`, `EXTERNAL_PROBE`; all are declarations, without authentication. |
| `status` | `CALLER_ASSERTED`, `UNAVAILABLE`, `INCONSISTENT`, `VERIFIED_BY_INDEPENDENT_PROBE`. |
| `value` | Typed as below. `UNAVAILABLE` requires exactly `null`; other statuses require a typed value. |

`INCONSISTENT` makes the assessment invalid. Any declaration of
`VERIFIED_BY_INDEPENDENT_PROBE` makes it invalid, including an `EXTERNAL_PROBE`
declaration: B2 has no authenticator to support that status. Passing an assertion
from a fake probe cannot verify host identity. A structurally valid unavailable
environment field contributes unverified evidence, not an invented identity.
An unavailable process field additionally leaves process coverage incomplete.

Each environment has exactly these field records:

| Key | Value type and range |
| --- | --- |
| `boot_id` | Canonical lowercase UUID text. |
| `namespace_inode` | Integer 1 through unsigned 64-bit maximum. |
| `namespace_device` | Integer 0 through signed 64-bit maximum. |
| `namespace_label` | Adapter-style label, at most 96 characters; no `..`. This binding to inode/device is itself asserted. |
| `mount_id` | Integer 1 through unsigned 64-bit maximum. |
| `mount_type` | Exactly `proc`; another filesystem type contradicts a procfs claim. |
| `clk_tck` | Integer 1 through 1,000,000 ticks per second. |
| `monotonic_start_ns`, `monotonic_end_ns` | Integers 0 through signed 64-bit maximum, bracketing observed capture reads. |

PID and PPID ranges are respectively 1..2,147,483,647 and 0..2,147,483,647.
Starttime ticks and optional cgroup bytes are unsigned 64-bit integers.
Alignment values use nonnegative signed 64-bit nanoseconds.

All available environment identities are compared within and across records;
unavailable readings cannot erase an earlier available identity. Boot, opaque
namespace binding and `clk_tck` must also agree with the capture's request.
Mount inode/device, mount ID and mount type remain independently supplied
assertions; the request has no authenticated mount identity to bind them to.
Changing namespace inode/device or mount ID between captures is invalid.

`coverage.frame_phases` has one phase or `null` for each **requested** frame,
including unrecorded interrupted frames. `required_phases` is a duplicate-free
list selected from `setup`, `producer`, `attribution`, `persistence`,
`verification`, `teardown`. `max_frame_gap_ns` is a positive signed 64-bit integer.
Phase assignment itself is caller asserted. A phase is covered only by a
complete frame with no adapter reason codes; no phase plan means no production
chronology claim. The plan is required explicitly, even if required phases are
empty. Invalid evidence never becomes a qualifying coverage result.

## Integrity, structure and trust

Hashes use the adapter's serializer exactly: sorted keys, two-space indentation,
ASCII escaping, no NaN, and a trailing newline. Request integrity compares the
supplied original request against `input_sha256`. Result integrity compares the
entire supplied result excluding `integrity` against its original SHA-256. The
supported integrity descriptor is exactly `sha256` / `canonical result excluding
integrity`. Other descriptors produce `DIGEST_CONTRACT_UNSUPPORTED`; no
replacement digest or new capture is manufactured. Rejected-request envelopes
with `input_sha256=null` produce `REQUEST_INTEGRITY_UNAVAILABLE` and invalid
`CAPTURE_REQUEST_REJECTED`, never `REQUEST_HASH_VERIFIED`.

Hash agreement is an independent gate, not an authentication or validation
shortcut. B2 also checks exact config/roster/run echoes (canonical equality,
including numeric types), requested frame count, observed PID rosters, registered
process order, before/after stat identities, read label/kind/PID sequence,
timings, byte/read-call totals, reason propagation, frame/process/result status,
failed-frame memory clearing and fixed nonclaims. Read-level reason lists retain
the adapter's emission order; frame/process/result code lists must be sorted and
unique. Optional rollup counters accept the enumerated standard counter names
in the source, require `Rss` and `Swap`, and remain unsigned byte counters.
Additional rollup schema keys are rejected.

Recorded frames cannot outnumber requested frames. Excess frames are rejected
with `REQUEST_RESULT_MISMATCH` before frame processing or phase-plan indexing,
including when their capture hash agrees. Fewer recorded frames leave capture
coverage incomplete. An unknown extra process probe contributes `UNKNOWN_WORKER`;
`PROBE_IDENTITY_MISSING` is reserved for absent registered claims or unavailable
process fields.

The maximum permitted trust, in declared order, is:

1. `CALLER_ASSERTED_ONLY`: fallback for invalid or unassessable records.
2. `INJECTED_STRUCTURALLY_CONSISTENT`: supported injected capture structure.
3. `NATIVE_SOURCE_UNVERIFIED`: a structurally consistent native-labelled
   envelope, whose origin remains unauthenticated.

A tier is a ceiling on evidence type, not acceptance of its content. Incomplete
observations can retain their source ceiling while their outcome is incomplete.
A claim above the ceiling is **invalid**, with `TRUST_OVERCLAIM`. Future-only
`NATIVE_SOURCE_VERIFIED` and `PRODUCTION_CHRONOLOGY_ASSESSED` are always rejected;
their input strings are never echoed. The result tier is the least trusted
ceiling in an ordered sequence, or caller-only when invalid.

The permitted label triples are exactly:

| Request | Result source / origin / clock |
| --- | --- |
| `INJECTED` / `TEST_INJECTED` | `TEST_INJECTED` / `UNVERIFIED` / `INJECTED_MONOTONIC_NS` |
| `NATIVE` / `NATIVE_REQUEST` | `NATIVE_PROCFS_UNVERIFIED` / `UNVERIFIED_NATIVE_CAPTURE` / `LOCAL_MONOTONIC_NS` |

Partial relabelling is invalid, with hash mismatch and/or label conflict.
Fully relabelled and rehashed artificial data cannot be distinguished from a
native-origin claim by a pure verifier. It remains source-unverified and
nonqualifying. Local hashes protect recorded integrity, not authenticity; raw
read digests cannot prove that the omitted bytes parsed to the recorded RSS or
identities. B2 does not reconstruct omitted raw procfs contents.

## Identity, races and observed windows

PID/starttime differences within reads, between probes and requests, or between
ordered captures are possible reuse races and remain `INCOMPLETE`. Changed PPIDs
remain `INCOMPLETE` reparenting observations. A PID contradiction, self-parenting,
or contradictory registered parent/worker topology is `INVALID`. Duplicate
identities are invalid; vanished/unreadable processes, missing/unknown workers,
incomplete registration, interrupted captures and absent process probes leave
coverage incomplete. Failure codes already recorded by the adapter retain the
adapter's invalid/incomplete classification.

The actual read execution order is frame, then barrier label (`stat_before`,
`status`, optional `smaps_rollup`, `stat_after`), then registered process. Every
recorded start/end is checked in that order across the entire declared capture
sequence. Equal clock ticks are allowed. Regression or start-after-end is
invalid. Frame and capture windows are minimum observed start and maximum
observed end, including partial failures. They are not calculated from successful
reads alone. A complete window requires both endpoints for every requested read.
Skew is the end minus start of that envelope; exceeding the request's maximum
is incomplete. Frame gaps and gaps between supplied captures are next observed
start minus previous observed end and are checked against the incoming coverage
limit. The output also reports maximum frame skew and aggregate observed bounds.
Unknown endpoints remain null; no observation is interpolated.
Probe windows constrain only recorded capture endpoints. A missing end tick
retains its adapter failure classification without inventing a conflicting
probe end. Frame gaps require endpoints in adjacent frames; a frame without an
end interrupts gap accounting, so no gap is measured across that frame.

Optional boot alignment uses integer arithmetic:
`starttime_ticks * 1_000_000_000 // clk_tck`. Boottime cannot precede the paired
monotonic reading. Process start cannot exceed the aligned first read plus one
tick of tolerance (rounded up to nanoseconds). Alignment is only an injected
consistency check, never a calibrated or authenticated clock relation. A paired
offset cannot account for an unobserved change in suspend offset during capture.
The starttime check requires an available injected `clk_tck`; if it is
unavailable, this check is omitted rather than substituting the request's
asserted clock frequency. Alignment remains unverified in either case.

Summaries expose input capture hashes, integrity booleans, observed times,
per-frame and aggregate missing/unknown identity counts, gaps, and sorted
uncovered phases. They omit PIDs, namespace identifiers, run IDs, arbitrary
locations, keys, exception messages and raw evidence strings. A frame's `usable`
means its supplied adapter codes and read-window completeness permit structural
phase accounting; the assessment outcome still governs whether any of that
accounting is valid. A structurally failed capture may have no summary; reasons
still report the failure and any completed preceding summaries remain bounded.

Recorded process RSS is approximate and sequential. It is not an atomic
aggregate snapshot, guaranteed instantaneous peak, or valid lower-bound estimate
of true instantaneous aggregate occupancy. No sum or peak estimate is emitted.
A complete caller roster, asserted discovery record or cgroup byte diagnostic
never establishes unregistered worker coverage or proves worker absence.

## Bounds and invalid data

The initial copy accepts only exact built-in dict/list/str/int/bool/None types,
exact string keys, acyclic graphs, and integers in signed-64-minimum through
unsigned-64-maximum range. Floats (finite or nonfinite), subclasses and arbitrary
objects are rejected before conversion, comparison or callback execution.
Semantic integer fields then reject bools. Invalid input returns an assessment,
not a traceback or an echoed exception string.

Global copy limits include the outer three-list wrapper: depth 24, 200,000
visited nodes (keys included), 8,388,608 UTF-8 string bytes and 65,536 bytes and
characters per individual string. Repeated aliases count on every visit.
Container sizes are checked before descent. Semantic caps include eight
captures, 32 requested/recorded frames per capture, 64 registered processes,
eight environment probes and 128 read calls per record. Result reason entries
are capped at 20,000. These are intentionally lower than the largest theoretical
adapter result. The global 200,000-node budget also excludes an ordinary full
32-frame, 64-process successful capture with `NOT_SAMPLED` rollup policy and
two read calls per record (roughly 280,000 nodes). The effective frame/process
capacity depends on read calls, policy, evidence and capture count; approximately
20 frames of 64 processes can fit under this node budget, with less room when
optional diagnostics or more records are supplied. The budget covers the entire
assessment, not each capture separately. Otherwise adapter-valid oversized
inputs fail closed with `INPUT_CAP_EXCEEDED`; they are never silently truncated
or partially accepted. There is no new production dependency.

## Reason codes and outcome precedence

`reason_codes`, `invalid_reason_codes`, and `incomplete_reason_codes` are sorted,
deduplicated fixed-vocabulary lists. Outcome precedence is `INVALID` over
`INCOMPLETE` over `UNVERIFIED`. There is no qualifying success outcome.

| Category | B2 codes |
| --- | --- |
| Input/schema invalid | `INPUT_NOT_JSON`, `INPUT_CAP_EXCEEDED`, `INPUT_CARDINALITY_MISMATCH`, `SCHEMA_INVALID`, `SCHEMA_VERSION_MISMATCH`, `INTEGER_INVALID`, `LABEL_INVALID`, `BOOT_ID_NONCANONICAL`, `REASON_CODE_INVALID`, `PHASE_INVALID`, `PHASE_PLAN_MISMATCH`, `PROBE_SCHEMA_INVALID` |
| Integrity invalid | `DIGEST_INVALID`, `DIGEST_CONTRACT_UNSUPPORTED`, `CAPTURE_HASH_MISMATCH`, `REQUEST_HASH_MISMATCH`, `REQUEST_RESULT_MISMATCH`, `CAPTURE_REQUEST_REJECTED` |
| Identity/probe/trust invalid | `BOOT_ID_MISMATCH`, `PID_NAMESPACE_MISMATCH`, `CLK_TCK_MISMATCH`, `PROCFS_TYPE_MISMATCH`, `ENVIRONMENT_PROBE_CONFLICT`, `CROSS_CAPTURE_ENVIRONMENT_CONFLICT`, `PROBE_INCONSISTENT`, `PROBE_VERIFICATION_OVERCLAIM`, `DUPLICATE_PROBE_IDENTITY`, `DUPLICATE_IDENTITY`, `PARENT_RELATION_CONTRADICTION`, `IDENTITY_CONTRADICTION`, `TRUST_CLAIM_INVALID`, `TRUST_OVERCLAIM`, `SOURCE_LABEL_CONFLICT`, `FIXED_NONCLAIM_CONFLICT` |
| Structure/time invalid | `READ_WINDOW_MISMATCH`, `READ_SEQUENCE_INVALID`, `READ_STATUS_MISMATCH`, `READ_ACCOUNTING_MISMATCH`, `BYTE_PROVENANCE_CONFLICT`, `IDENTITY_READ_MISMATCH`, `FRAME_INDEX_MISMATCH`, `FRAME_REASON_MISMATCH`, `FRAME_STATUS_MISMATCH`, `PROCESS_STATUS_MISMATCH`, `PROCESS_ROSTER_MISMATCH`, `REASON_PROPAGATION_MISMATCH`, `CAPTURE_STATUS_MISMATCH`, `FAILED_FRAME_MEMORY_PRESENT`, `COUNTER_INCONSISTENT`, `SMAPS_POLICY_MISMATCH`, `COVERAGE_CLAIM_CONFLICT`, `CLOCK_REGRESSION`, `PROBE_CLOCK_REGRESSION`, `PROBE_WINDOW_CONFLICT`, `BOOT_ALIGNMENT_CONFLICT`, `STARTTIME_ALIGNMENT_CONFLICT` |
| B2 incomplete | `PROBE_IDENTITY_MISSING`, `UNKNOWN_WORKER`, `CROSS_CAPTURE_ROSTER_CHANGED`, `PID_REUSE`, `PROCESS_REPARENTED`, `CAPTURE_STOPPED`, `FRAME_GAP_EXCEEDED`, `PHASE_COVERAGE_GAP` |
| Integrity observations | `CAPTURE_HASH_VERIFIED`, `REQUEST_HASH_VERIFIED`, `REQUEST_INTEGRITY_UNAVAILABLE` |
| Always unverified/limited | `PROBE_EVIDENCE_UNVERIFIED`, `DISCOVERY_UNVERIFIED`, `NONATOMIC_SEQUENTIAL_RSS` |
| Optional limitations | `PROBE_FIELD_UNAVAILABLE`, `MOUNT_ID_UNAVAILABLE`, `MOUNT_TYPE_UNVERIFIED`, `BOOT_ALIGNMENT_UNAVAILABLE`, `BOOT_ALIGNMENT_UNVERIFIED`, `CGROUP_DIAGNOSTIC_ONLY` |

Recorded adapter codes use the pinned source's sealed `ADAPTER_INVALID` and
`ADAPTER_INCOMPLETE` vocabularies reproduced in this standalone validator. They
propagate without arbitrary input strings becoming new reasons. In particular
permission denial, disappearance, read failure, stopped capture, reparenting,
reuse, unknown/missing processes, incomplete roster and excessive skew stay
incomplete. A newly derived contradiction absent from recorded frame reasons
additionally produces `FRAME_REASON_MISMATCH`, rather than trusting a rehashed
success label. Unknown reason codes are invalid. Verified and mismatched hash
observations may both appear for a multi-capture sequence; per-capture booleans
disambiguate completed summaries.

## Fixed nonclaims and interpretation of tests

Every assessment, including invalid input, preserves
`production_memory_qualification=INCONCLUSIVE`,
`production_chronological_peak=NOT_OBSERVED`, `holder_release=NOT_ESTABLISHED`,
`worker_absence_proven=false`, `unregistered_worker_coverage=NOT_ESTABLISHED`,
`atomic_snapshot=false` and all other adapter nonclaims. Synthetic identities
agreeing do not qualify any native source or production chronology. The
verifier is not wired into predecessor acceptance gates.

The new suite uses a hand-written in-memory fd facade and integer clock, plus
hand-edited evidence and rehashed tampering controls. Its native-labelled case
only changes data; it never executes the native branch. Autouse guards block
native descriptors, namespace/boot APIs, native monotonic clocks, proc/sys opens,
process creation, networking and native-facade construction. Negative controls
explicitly trigger those guards and the artificial facade's path allowlist;
their `BaseException` sentinel escapes ordinary adapter exception handling.
Static import/capability checks and a guarded reload cover import safety.
There are no skips or expected failures.

Regression cases cover extra usable frames with and without updated hashes,
an ordinary 32-by-64 capture exceeding the copy budget, isolated probe and
alignment contradictions, and adapter-generated oversized reads, root-open
failures, descriptor-close failures, optional rollup failures and total-byte
exhaustion. These adapter incomplete paths must add no structural invalid codes.
A rejected end tick must retain only the adapter's original clock invalid code.

Implementation-stage test execution is prohibited. No pytest, build, benchmark,
native read or experimental run was performed by the implementer. Independent
review must pass before orchestration runs the pinned nine-file pytest argv in
`.ai/TASK.md`. The recorded predecessor baseline is 1,592 passed; the required
combined result is more than 1,592 passed with zero skips/failures. No new pass
count, independent acceptance, authenticated recapture, commit authorization, or
production readiness is claimed here.
