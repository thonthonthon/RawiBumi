# D2-B2-B3-B0 artificial provenance bridge — H0 hardening

Status: `HOLD_REVIEW_REQUIRED`. This is a code-only acquisition contract.
Independent review, the orchestrator's eleven-suite verification, and its
checksum-verified handoff ZIP remain pending. No native capture, real-procfs
smoke, toy process, production workload, or benchmark is authorized here.

The new module is independently usable and does not import or call B3-A, B2,
the native adapter, the engine, or cache code. Their envelopes stay unchanged.
The memo cap remains 256. No scientific validation evidence is written.

## API and input schema

`acquire_provenance_bridge(roster, request, *, providers, clock) -> BridgeReport`

All three callback slots are mandatory: two `Provider.callback` operations
and one injected clock. Import, `Provider`, `Handle`, and `Operation`
construction acquire no evidence. There is no native implementation, default
I/O, automatic process discovery, arbitrary-path argument, or adapter facade.
The clock must be an artificial callback in this phase. Callers must supply
artificial fixtures only; the bridge cannot authenticate a callback's origin.

`roster` is a list of 1–16 distinct registered identities, each exactly:

```json
{"pid": 100, "ppid": 1, "starttime_ticks": 10}
```

PIDs are integers in 1–2147483647, PPIDs in 0–2147483647, starttimes in
0–2^64−1; booleans are never integers for this contract. PID must differ from
PPID. The roster is closed and declares no completeness or descendant claim.
Order is preserved. A request contains exactly these fields:

```json
{
  "schema": "rawibumi.native-provenance-bridge.d2b2b3b0.v1",
  "mode": "INJECTED_TEST_ONLY",
  "native_opt_in": false,
  "clock_domain": "INJECTED_MONOTONIC_NS",
  "sweeps": 2,
  "limits": {
    "max_elapsed_ns": 100000,
    "max_read_ns": 100,
    "max_gap_ns": 100,
    "max_age_ns": 100000,
    "max_source_skew_ns": 1000
  }
}
```

Each limit is an integer in 1–1,000,000,000 ns. Unknown fields are rejected,
including custom paths, root locations, and claims of a complete roster.
Any mode other than `INJECTED_TEST_ONLY`, or any opt-in value other than
the exact boolean `False`, is denied before any provider or clock call.
`NATIVE_LOCAL_UNVERIFIED` is a reserved module constant only and never appears
as an emitted source state or as a list of future states in a report.

`providers` is a tuple/list of exactly two frozen `Provider` configurations:

```python
Provider(provider_id, source_id, fixture_id, callback,
         declared_origin="INJECTED_TEST_ONLY")
```

The three identifiers use 1–64 ASCII letters, digits, underscores, or hyphens.
Before acquisition, identifier checking removes underscores/hyphens and folds
ASCII case, then rejects substrings containing `NATIVE`, `AUTHENTIC`, `ATTEST`,
`QUALIF`, `VERIFIED`, or `CORROBORAT`. The normalized reserved values
`INJECTED_TEST_ONLY`, `INJECTED_MONOTONIC_NS`, `NOT_ESTABLISHED`, `NOT_IMPLEMENTED`,
`INCONCLUSIVE`, `NOT_OBSERVED`, `CALLER_CONFIGURED_ONLY`, `ALIAS_DETECTED`,
`NOT_ACQUIRED`, `SEQUENTIAL_NONATOMIC`, `CONSISTENT`, `INCOMPLETE`, `INVALID`,
and `AGREES` are also forbidden as substrings; `NONQUALIFYING` and
`NATIVE_LOCAL_UNVERIFIED` are covered by the authority stems. Rejection is
`ORIGIN_INVALID`, with no callback or clock call. Thus suffixes, embedded tokens,
mixed case, and separators within the words cannot evade the check. Handle
tokens retain their existing grammar and are never serialized.
They identify caller-declared acquisition routes and fixture roots; they are
not proof of independent origin. A forged declared origin is rejected before
callbacks or clocks execute. The provider sequence is frozen internally before
acquisition; mutation of its membership is rejected afterward.
Accepted identifiers are echoed only inside the `providers` metadata block.
This lexical restriction is deliberately conservative, not authentication or
a complete detector of misleading natural language. Authority is structural:
caller text cannot set source state, attestation, corroboration, or qualification;
those fields remain bridge constants even on rejected input.

## Closed symbolic I/O protocol

Each callback accepts one frozen `Operation(action, path_id, sweep, handle,
max_bytes)`. There are exactly four actions, issued only by the bridge:

| Action | Handle | Result |
| --- | --- | --- |
| `OPEN` | `None` | `Handle(token)` artificial lease |
| `DESCRIBE` | Obtained lease | Descriptor dictionary |
| `READ` | Obtained lease | Read envelope dictionary |
| `CLOSE` | Obtained lease | `None` |

`sweep` is 0 or 1. `max_bytes` is 4097 on READ (one sentinel byte beyond the
4096-byte accepted raw limit), zero otherwise. The only path identifiers are
`boot_id`, `proc_mount`, and, for each registered PID,
`pids/<pid>/identity`, `pids/<pid>/ns_link`, `pids/<pid>/ns_target`.
These are symbolic names relative to prebound artificial descriptors, never
OS paths. No callback receives an absolute path, traversal, arbitrary PID,
or caller-supplied custom path. Returned descriptor paths must match exactly.

A handle token follows the same identifier grammar. It is opaque and has no
fd, pathname, or operating-system meaning. Token sets must be disjoint across
provider slots; reuse is conservatively treated as aliasing in this protocol.
A successful OPEN must return a
`Handle`; a failing OPEN must acquire no resource. Returning any other object
violates the callback contract and does not establish a usable lease. A
callback must never allocate an undisclosed resource or raise after allocation
without returning its lease. Those behaviors cannot be repaired by a consumer
that has no resource identifier. Each obtained lease is registered immediately,
re-described, and closed exactly once even after validation or read failure.
No callback is retried; the second DESCRIBE is a consistency recheck.

Each descriptor contains exactly:

```json
{
  "path_id": "pids/100/ns_link",
  "role": "PROCFS_LINK_LOCATION",
  "st_dev": 5,
  "st_ino": 105,
  "mount_id": 9,
  "filesystem": "proc",
  "symlink": true,
  "binding": "INJECTED_DESCRIPTOR_RELATIVE_NO_FOLLOW",
  "identity": {"pid": 100, "ppid": 1, "starttime_ticks": 10}
}
```

Device, inode, and mount IDs are positive u64 integers. `identity` is the exact
registered identity on PID operations and `null` on the two global operations.
The bridge distinguishes the following roles:

| Symbolic object | Role | Filesystem | Symlink |
| --- | --- | --- | --- |
| Boot ID, proc mount, process identity | `PROCFS_OBJECT` | `proc` | false |
| PID namespace link location | `PROCFS_LINK_LOCATION` | `proc` | true |
| Resolved namespace target | `NSFS_TARGET` | `nsfs` | false |

The nsfs target has its own device and mount ID. It is never required to
inherit the procfs mount ID. Equal namespace-target device/inode pairs across
registered PIDs are legitimate: those processes may occupy the same namespace.
Sharing a procfs object identity between different symbolic paths is rejected.
Symlinks anywhere other than the explicit link-location role are rejected;
the link location itself must remain a symlink. This models the distinction
without implementing native symlink traversal or `openat`/`O_NOFOLLOW`.

The read envelope has exactly `payload`, `raw`, `sha256`, `method`,
`declared_origin`, `sequence`, `status`, and `reason`:

* `INJECTED_STRUCTURED`: `raw=null`; `sha256` hashes the canonical structured
  payload. Canonical JSON uses sorted keys, indent 2, ASCII escapes, no NaN,
  and one final newline, matching the predecessor convention.
* `INJECTED_JSON_BYTES`: `raw` must be exact immutable `bytes`, at most 4096
  bytes. `sha256` hashes those exact original bytes, including whitespace.
  Strict UTF-8 JSON with no duplicate keys must decode to the same bounded
  payload, including exact primitive types (`true` cannot stand for `1`).
  Bytearrays, arbitrary objects, and raw strings are rejected.
* `declared_origin` must be `INJECTED_TEST_ONLY` on every read.
* `sequence` is a u64 counter ordered per provider across both sweeps.
  Decreases are rollback; repetition is stale evidence.
* `status=OK` requires `reason=null`. `status=ERROR` requires one of
  `STALE_HANDLE`, `PERMISSION_DENIED`, `READ_FAILED`, and null payload/raw/hash.
  A missing worker is established by an OPEN failure, rather than a missing
  identity read through an already obtained lease. Unknown statuses/reasons
  fail closed and their arbitrary text is not emitted.

Successful payloads have these closed shapes:

| Operation | Structured payload |
| --- | --- |
| `boot_id` | `{"boot_id": "canonical-lowercase-UUID"}` |
| `proc_mount` | `{"mount_id": 9, "st_dev": 5, "filesystem": "proc"}` |
| PID `identity` | `{"identity": {...}, "cpu_ticks": 50, "vmhwm_kib": 100, "rss_kib": 80}` |
| PID `ns_link` | `{"namespace_inode": 77}` |
| PID `ns_target` | `{"st_dev": 4, "st_ino": 77}` |

Counters are u64 integers. CPU ticks and VmHWM must not decrease for a
registered PID/starttime across ordered provider-local observations. H0 also
compares the two providers' successful identity records in their shared,
sequential acquisition order, once comparable scope is established for that
PID. This requires all four successful boot-ID records (both providers and
sweeps) to have identical payloads and all four successful namespace-target
records for that PID to have identical device/inode payloads. Missing or
disagreeing scope evidence disables this cross-provider check; existing local
checks and scope/disagreement classifications remain active. Different PIDs
have separate timelines. Successful identity validation pins PID and starttime
to the roster, excluding reused or substituted identities from the timeline.
The closed injected schema supplies the same cumulative-counter semantics and
units on both routes; this is an artificial fixture assumption, not verified
native provenance.

The timeline uses observation-list order, which follows the nonregressing
bridge clock and sequential, nonoverlapping reads (ties retain acquisition
order). It never sorts by provider index or compares provider-local sequence
numbers across sources. A lower CPU/VmHWM value at provider 1 even within one
sweep now adds `COUNTER_ROLLBACK` (`INVALID`), alongside the existing
`SOURCE_DISAGREEMENT` (`INCOMPLETE`). Ordinary growth can still disagree
between snapshots without rollback. The whole-payload snapshot-disagreement
check remains unchanged, including volatile CPU/VmHWM/RSS fields; disagreement
and rollback remain separate reason classes. This preserves accepted evidence
authority. A future native phase must separately resolve volatile-value
comparison policy for sequential reads.

This is the work order's fail-closed cumulative policy, not a claim that VmHWM
cannot be reset on Linux. RSS may decrease. Changed starttime is PID reuse and is never reported
as cumulative-counter rollback. A valid-schema substituted PID, changed PPID,
and PID=PPID are respectively identity substitution, reparenting, and schema
failure. Namespace payloads must agree with their descriptors and link inode.

## Acquisition, integrity, and failure handling

Read order is sweep → provider → boot ID → proc mount → roster order, with
identity/link/target leaves in that order. Each read is OPEN, DESCRIBE, READ,
DESCRIBE, CLOSE. A failed earlier step skips remaining acquisition steps and
still attempts recheck and close for an obtained handle. The report's ordered
observations preserve provider index, sweep, symbolic path, validated structured
payload, original-byte digest or structured digest, separate payload digest,
declared digest, raw byte count, method, declared origin, provider sequence,
provider status/reason, before/after metadata, and acquisition status/reasons.
Operation failures retain the symbolic action, sealed reason, and original
numeric errno when available, preserving ENOENT versus ESRCH without messages.
If the first DESCRIBE fails or is invalid, a successful recheck records the
after-descriptor without inventing `DESCRIPTOR_CHANGED` against a missing
before-descriptor. A change is compared only when both validated descriptions
exist. The original failure class remains, and recheck/CLOSE still run once.
Raw bytes remain internal only until the call returns; they are never written
into the report. Unsafe or unvalidated fields are represented by null rather
than copied into evidence. Error messages are never emitted.

Every observation gets bridge-clock start/end timestamps covering open,
metadata, read, recheck, and close. The single domain is
`INJECTED_MONOTONIC_NS`; provider-asserted timestamps cannot replace it. The
bridge rejects invalid or regressing ticks, elapsed overruns, excessive
per-read windows, adjacent-read gaps, source-to-source corresponding windows,
and stale observations measured against the final tick. Clock/elapsed failure
stops further acquisition after cleanup. Other failed leaves remain explicit
failed/missing evidence; they are never silently omitted from a complete frame.

Limits are checks on returned clock values. They cannot interrupt a blocking
callback or authenticate the clock. There are at most 200 reads, 1000 provider
calls, and 401 ticks. These maxima include rechecks/cleanup and the final tick;
fewer callbacks run when acquisition fails. There are zero retries. Each
copied tree is capped at depth 12, 2048 visited nodes, and 16 KiB of accounted
strings/primitive overhead; each raw byte object is capped at 4096. Cycles,
oversized values, and quota overruns are rejected rather than truncated.

Cross-sweep/provider checks maintain mount-ID→(device, filesystem) and
device→filesystem maps. All procfs locations must match that sweep/provider's
proc mount. Descriptor identities must be stable across sweeps and providers;
boot IDs and each PID's namespace bindings must agree. Equal ordinary values
alone do not imply aliasing. Aliasing is demonstrated by a shared callback,
shared bound instance, a callable object paired with its own bound `__call__`
in either provider order, equal provider/source/fixture identifiers, a handle
token reused across providers, or a shared mutable response/subtree. Strong
references avoid Python object-ID reuse during these checks. Response objects
are bounded and recopied after acquisition to reject post-return mutation,
including digest tampering. Request/roster and provider-list mutation are also
checked. Mutation comparisons preserve primitive types as well as values.
Output is a frozen serialized string; every `to_dict()` is detached.

Different wrappers with dishonest, unrelated source IDs may conceal a common
fixture. Distinct providers, digests, and metadata therefore never establish
independent acquisition or authenticate Linux origin, even when no alias is
detected. The report says `NOT_ACQUIRED`, `CALLER_CONFIGURED_ONLY`, or `ALIAS_DETECTED` and
always says `independent_corroboration=NOT_ESTABLISHED`.
Bound-owner inspection uses only exact Python `MethodType` instances and
does not execute arbitrary callable-object attribute access. Distinct objects,
including one object's bound `__call__` paired with another object, are not
aliases by this identity test. Distinct textual IDs cannot override a shared
callback/owner, and absence of a detected alias never establishes independence.

OSError errno mapping distinguishes ELOOP (symlink substitution), ENOTDIR
(path policy), EACCES (permission), ENOENT/ESRCH during a PID OPEN (missing
worker), and ENOENT/ESRCH after a handle is obtained (stale handle).
Global OPEN disappearance is a missing frame, not a stale handle. Other
OSError failures are failed reads. Ordinary callback exceptions are failed
evidence. Close exceptions are recorded, with no close retry. A
`BaseException`-derived fake-I/O assertion propagates after cleanup; recheck
or close failures cannot replace an original assertion. All obtained handles
are closed before acquisition advances, so a later clock error has no pending
resources. Unknown internal reason codes are sealed to `REASON_CODE_INVALID`.

## H0 M1–M5 disposition matrix

The following are implemented dispositions with deterministic injected fixtures;
test execution and independent review remain orchestrator-owned and pending.
Every case retains `INJECTED_TEST_ONLY`, `NONQUALIFYING`, and
`independent_corroboration=NOT_ESTABLISHED`.

| Requirement | Disposition | Explicit unit tests in the companion bridge suite |
| --- | --- | --- |
| M1 / F1 | Compare only two existing validated descriptors; preserve original errno/invalid class and cleanup. | `test_first_describe_errno_does_not_invent_descriptor_change` (EACCES/ENOENT/ESRCH on global and PID paths); `test_invalid_first_descriptor_retains_only_original_failure_after_valid_recheck`; `test_descriptor_recheck_detects_change_inside_one_read_window` |
| M2 / F2 | Reject object/self-bound-call aliasing in either order with exactly `SOURCE_ALIAS`; retain other alias checks. Handle-token aliasing also yields `FRAME_MISSING` because affected observations fail. | `test_provider_object_and_its_own_bound_call_are_aliases_in_either_order`; `test_alias_detection_never_attests_independence`; `test_distinct_provider_object_and_bound_call_do_not_alias` |
| M3 / F3 | Check cumulative counters in global acquisition order only for comparable PID/starttime scope; preserve local checks and snapshot disagreements. | `test_cumulative_rollback_across_providers_uses_global_fake_clock_order`; `test_cumulative_growth_does_not_use_provider_major_order`; `test_cross_provider_rollback_requires_complete_comparable_scope`; `test_cumulative_counters_of_unrelated_pids_are_not_compared`; `test_cross_provider_rss_decrease_is_snapshot_disagreement_without_rollback`; `test_reused_pid_with_lower_counters_is_only_pid_reuse`; existing `test_both_providers_can_observe_a_lower_rss_without_failure` |
| M4 / F4 | Pin full invalid/incomplete sets rather than membership for distinction-critical failures. | `test_errno_matrix_preserves_missing_worker_vs_stale_handle`; `test_missing_global_evidence_is_not_reported_as_a_stale_handle`; `test_registered_identity_and_separate_schema_invalid_pid_equals_ppid`; the M1 tests above |
| M5 / F5 | Reject reserved/authority substrings in all three caller labels before I/O, for either provider; keep authority fields constant. | `test_untrusted_authority_labels_rejected_before_any_io`; `test_benign_labels_serialize_only_as_caller_provider_metadata`; existing forged-origin and reserved-name controls |

Exact errno assertions distinguish PID OPEN `MISSING_WORKER` from later
`STALE_HANDLE`; global OPEN disappearance is only `FRAME_MISSING`. ELOOP,
ENOTDIR, EACCES, and EIO each retain their own reason class with the missing
frame. Identity tests separately pin `IDENTITY_SUBSTITUTION`, PID=PPID
`SCHEMA_INVALID`, `PROCESS_REPARENTED`, and `PID_REUSE`, excluding contradictory
siblings and rollback. The new counter fixtures pin explicit artificial
start/end times and cover rollback even when each provider alone grows.

No optional O1–O4 code change is part of H0. The sequential snapshot-disagreement
limitation (O2) is explained above as needed to define M3 without changing
accepted evidence authority. Cleanup during `BaseException` and failed-record
retention remain as accepted.

## Evidence authority and handoff

Every returned report has `source_state=INJECTED_TEST_ONLY` and
`qualification=NONQUALIFYING`. `CONSISTENT` means only that the artificial
structural checks agreed; failures are `INCOMPLETE` or `INVALID`. Independent
source acquisition, structural agreement, native authentication, roster
completeness, and chronological qualification are separate report fields.
No path emits authenticated origin, independent-host attestation, descendant
completeness, or production qualification.

Native origin authentication and host attestation are `NOT_IMPLEMENTED`.
Worker-roster completeness, whole-process-tree coverage, RSS chronological
qualification, holder RELEASE, and RSS reclamation are `NOT_ESTABLISHED`.
`production_memory_qualification=INCONCLUSIVE` and
`production_chronological_peak=NOT_OBSERVED`. RSS sampling is sequential and
non-atomic, never a continuous peak. No holder logical-owner exit/RELEASE
relationship is inferred. No real data is passed to B3-A under an injected
label, and no predecessor envelope is rewritten.

The new suite uses only artificial callbacks and a fake clock. Its autouse
guards permit only the bridge source file for intentional AST code inspection
through Python file-open functions, and prohibit ambient data reads including
procfs/sysfs reads, native fd reads, process discovery,
spawning, socket use, filesystem writes, and acquisition clock access. Negative
controls prove those guards. AST inspection also excludes native-capability
imports and calls from the bridge. The regression cases cover ordinary and
raw-byte agreement, distinct procfs/nsfs roles, multiple PIDs, aliasing,
forgeries, identity changes, missing frames/workers, errno distinctions,
counter policy, source mutation, quotas, cleanup, clocks, and determinism.

Implementation-time tests/builds/benchmarks are not run, as instructed. The
orchestrator owns independent review, exactly eleven scoped suites with strictly
more than 2,250 passes and no failures/skips/xfails/xpasses, source/evidence guards,
final Git snapshots, and the checksum-verified ZIP with review, verification
log, and stop reason. Until that succeeds, keep `HOLD_REVIEW_REQUIRED`; only
the acceptance workflow may issue
`B3B0_H0_REVIEW_PASS_PENDING_INDEPENDENT_AUDIT` after a positive Claude PASS
with zero BLOCKER, MAJOR, and MINOR findings and the required verification.
The future B3-B1 isolated native opt-in validation gate requires separate
authorization; H0 supplies no native acquisition or opt-in path. Production
D3, independent WSL acceptance, independent audit, and any guarded local commit
remain separate gates. Scientific HOLD remains
`production_memory_qualification=INCONCLUSIVE`,
`production_chronological_peak=NOT_OBSERVED`, holder RELEASE unknown, and memo
cache cap 256 unchanged. No commit, stage, push, or branch change occurs here.
