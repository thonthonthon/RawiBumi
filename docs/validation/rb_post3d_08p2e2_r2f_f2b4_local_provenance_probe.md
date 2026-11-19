# F2-B4-D2-B2-B3-A: injected local provenance probe

This is a code-only, artificial-I/O-only contract. The sole new entrypoint is
`probe_local_provenance(request, *, reader, descriptor, clock, reference=None)`.
It is unwired to production. All three callbacks are mandatory; there is no
native facade, native default, host read, real clock, process creation, or
discovery implementation. Importing this module is inert. The predecessor
adapter and B2 verifier are unchanged.

Every result has source `INJECTED_LOCAL_PROBE` and qualification `NONQUALIFYING`.
Consistent input yields outcome `CONSISTENT`; structural or integrity violations
yield `INVALID`; missing, failed, stale or contradictory continuity observations
yield `INCOMPLETE` unless an invalid reason also exists. The trust ceiling is
`INJECTED_LOCAL_PROBE`, falling to `CALLER_ASSERTED_ONLY` on invalid input.
Caller labels, matching identity strings and recalculated hashes cannot raise
that ceiling. Forbidden future trust claims and arbitrary caller strings are
never echoed in the serialized report.

The independent future native adapter and separate trust-root gate are both
**NOT IMPLEMENTED**. No result attests native origin or independent observation.
The required eventual review status is
`D2B2B3A_REVIEW_PASS_PENDING_INDEPENDENT_AUDIT`; this document does not declare
that review or audit complete. No commit is authorized by implementation.

## Original B3-A request contract

Schema: `rawibumi.local-provenance-probe.f2b4.d2b2b3a.v1`. Every object has exactly
the documented keys. Unknown and missing fields are errors, not extensions.

| Request key | Contract |
| --- | --- |
| `schema` | The schema above. |
| `source_kind` | Exactly `INJECTED`. |
| `clock_domain` | Exactly `INJECTED_MONOTONIC_NS`. |
| `context` | Explicit local probe identity: exactly `pid`, `ppid`, `starttime_ticks`. |
| `targets` | One to 63 identities with those same three keys; independent of the context. |
| `roster_complete` | Boolean caller assertion; false adds `ROSTER_INCOMPLETE`, true does not establish discovery. |
| `limits` | Exactly `max_age_ns`, `max_read_skew_ns`, `max_frame_gap_ns`: nonnegative u64 nanoseconds. |
| `frame_windows` | One to 32 caller-supplied windows, each exactly `start_ns`, `end_ns`; endpoints are u64 nanoseconds or null. |

PID is an exact integer in 1..2,147,483,647; PPID is in 0..2,147,483,647;
starttime is an unsigned 64-bit tick count. Self-parenting and duplicate PIDs
(including a target duplicating the context) are rejected. The request registers
identities; it does not infer parent/worker topology or find children. Tick
counts are compared exactly; no tick-to-time conversion or boot alignment is
invented. Booleans cannot substitute for integers.

Input permits only exact dict/list/str/int/bool/null JSON types. Floats, NaN,
bytes in request trees, subclasses, cycles, NUL strings and lone surrogates are
rejected without invoking user methods. Callback byte buffers are a distinct,
explicitly permitted input surface, decoded as strict UTF-8 JSON with duplicate
keys rejected. Exception messages and unvalidated values are discarded.

## Injected descriptor and reader contract

The probe makes exactly two fixed sweeps of this allowlist, in this order:

1. `boot_id`, `mount`.
2. `pids/<pid>/identity`, `pids/<pid>/namespace` for the context followed by
   each registered target in request order.

These are symbolic fixture names, **not Linux paths**. No caller-supplied path is
used to construct a name. There are no absolute paths, `self` aliases, unrelated
leaves, directory walks, symlink resolution, retries, or open descriptors owned
by this module. Each name is constructed only after numeric PID validation.

`descriptor(name)` returns exactly these keys:

| Key | Required value |
| --- | --- |
| `path` | The exact requested symbolic name. |
| `st_dev`, `st_ino`, `mount_id` | Positive u64 exact integers describing the bound object, including its own mount. |
| `filesystem`, `mount_path` | For non-namespace leaves: `proc`, `proc`. For namespace targets: `nsfs`, `namespace_target`. Mount paths are symbolic descriptors, not Linux pathnames. |
| `symlink` | Exactly false for the bound object; namespace metadata describes the resolved target, never the procfs magic link. |
| `binding` | Exactly `INJECTED_PREBOUND_NO_FOLLOW`. |
| `read_method` | `INJECTED_NAMESPACE_TARGET_DESCRIPTOR` for namespace leaves, otherwise `INJECTED_BOUND_DESCRIPTOR`. |

`reader(name, 4097)` returns exact bytes. At most 4096 bytes are accepted; the
extra requested byte allows a fixture to demonstrate explicit overflow.
The buffer must contain one closed JSON object:

| Name | Exact decoded fields |
| --- | --- |
| `boot_id` | `boot_id`: canonical lowercase UUID text. |
| `mount` | `mount_id`, `filesystem`, `mount_path`, `descriptor_dev`. These must agree with its descriptor; filesystem and mount path are `proc`. |
| `pids/<pid>/identity` | `pid`, `ppid`, `starttime_ticks`, with the request's ranges. |
| `pids/<pid>/namespace` | `st_dev`, `st_ino`, `read_method`; positive u64 numbers must equal the namespace target descriptor, and method must be `INJECTED_NAMESPACE_TARGET_DESCRIPTOR`. |

For each read, the probe takes a clock tick, copies and validates descriptor
metadata, reads and validates bytes, rechecks descriptor metadata, and takes a
second clock tick. It rechecks even after reader failure when initial metadata
was obtained. No callback is retried. Descriptor identity must remain stable
within each read and across sweeps. Distinct non-namespace leaves cannot share
one descriptor device/inode pair. Namespace targets may share a pair because
that is the namespace instance being compared, but no namespace pair may alias
any non-namespace descriptor in either sweep, regardless of observation order.
Distinct non-namespace paths cannot share a pair across sweeps either; the
same path retaining its descriptor across sweeps is permitted.

Both sweeps compare boot identity, namespace device/inode/method, mount ID and
procfs filesystem device. Only non-namespace descriptors participate in the
common procfs mount/device check. Namespace targets carry their own nsfs mount
metadata, outside that procfs check. Across all usable descriptors in both
sweeps, any one mount ID must denote the same device and filesystem, and any
one device must denote the same filesystem even under different mount IDs.
Both contradictions are invalid with `MOUNT_MISMATCH`, including when the
conflicting usable descriptors occur only in different sweeps. Namespace and
procfs device identities cannot coincide. These checks retain independent
device/inode alias detection with `DESCRIPTOR_ALIAS`.
Each schema-valid process identity is compared to its registration: a payload PID differing
from the PID bound to its identity leaf is `IDENTITY_CONTRADICTION` (invalid),
even if that payload PID is registered elsewhere. PPID and starttime changes
remain `PROCESS_REPARENTED` and `PID_REUSE` (incomplete). `UNKNOWN_PROCESS`
remains reserved for truly extraneous/unregistered PID observations, not a
substitution at a registered leaf; this probe does not discover other PIDs.
A read that fails validation contributes no usable value, but its failure
remains recorded.

Linux namespace device/inode describes the **nsfs target** of a namespace magic
link, distinct from the procfs symlink inode and its procfs mount. Here the read
method models an already bound target descriptor; no actual link is followed.
The schema deliberately models target metadata outside procfs mount validation;
it does **not** record a procfs link-location descriptor. `path` is only a
symbolic fixture association with a registered PID. `binding` asserts that the
callback supplies prebound metadata without this probe resolving a link; it
neither describes how the target was acquired nor authenticates its association
with that PID. The nsfs `mount_id` describes the target's mount, never the
procfs link's mount. It need not be exposed as a procfs mountinfo entry.
The kernel's [nsfs implementation](https://github.com/torvalds/linux/blob/master/fs/nsfs.c)
uses its own `nsfs_mnt` for namespace target paths and descriptors.

For example, procfs leaves on mount 9/device 5 and resolved namespace targets on
nsfs mount 10/device 4 are consistent artificial metadata. Keeping mount 9 while
changing to target device 4 is rejected. Assigning all nsfs targets device 5
while retaining their own mount 10 and non-aliasing inode 77 is also invalid,
with exactly `MOUNT_MISMATCH`. Assigning all procfs leaves device 4 (including
matching mount payload metadata) likewise yields exactly `MOUNT_MISMATCH`.
The valid mount 9/device 5 and nsfs mount 10/device 4 case remains `CONSISTENT`
with no reasons. This corrects the initial unreviewed
v1 fixture's impossible mixed identity; the closed descriptor keys are unchanged
and namespace filesystem/path values now explicitly identify nsfs targets.

Linux semantics are described in [namespaces(7)](https://man7.org/linux/man-pages/man7/namespaces.7.html)
(namespace identity via device/inode of the target) and
[statx(2)](https://man7.org/linux/man-pages/man2/statx.2.html)
(mount identity belongs to the mount containing the described file).
Text `pid:[inode]` alone is never an independent namespace certificate.
Matching procfs mount IDs do not authenticate a mount, and a procfs mount is not
a process PID namespace. Internally matching metadata remains a caller
assertion; both authentication flags are false and
`mount_namespace_binding=UNVERIFIED`. No trusted link-to-target binding or native
source claim is inferred.

## Clocks, gaps and bounded work

`clock()` returns an exact u64 nanosecond observation from the single documented
injected clock domain. Equal ticks are permitted; regression is invalid. Failed
or regressing ticks remain null, never interpolated. A failed starting tick
suppresses that read's descriptor/reader callbacks. The ending tick is still
attempted, and all attempted-read records retain their actual endpoints.

After the two sweeps one final injected tick checks age of read starts and every
available requested frame endpoint. Future endpoints are invalid; ages exceeding
`max_age_ns` and read spans exceeding `max_read_skew_ns` are incomplete. A frame
missing either endpoint always adds `FRAME_TIMESTAMP_MISSING` and
`COVERAGE_UNBOUNDED`. The last known frame end is retained across missing ends
to detect a known excessive gap, but this never fills a missing timestamp.
Frame windows are caller assertions; even a complete list proves no continuous
sampling, instantaneous peak or bounded production coverage.

| Limit | Hard maximum / rejection behavior |
| --- | --- |
| JSON copy depth | 24, counting the entrypoint's joint request/reference wrapper. |
| JSON copy nodes | 200,000, including dict keys, with explicit rejection above the cap. |
| JSON UTF-8 string bytes | 8 MiB in aggregate; 65,536 per string. |
| Canonical serialization used for digest | 8 MiB; streamed into SHA-256, rejected above the cap without accumulating an oversized serialized buffer. |
| Descriptor metadata per callback | 128 nodes, 4096 UTF-8 string bytes, depth 4. |
| Reader buffer | 4096 bytes accepted per callback; no accumulation/retry loop. |
| Registered processes | 64 total including context. |
| Frame windows | 32. Same-domain reference windows combined across captures also cap at 32. |
| Reference captures/requests/evidence | Equal-length lists, one to eight. |
| Callback invocations | At most 260 reads, 520 descriptor calls, 521 ticks, for 1301 calls total. |

Limits bound the module's copying, parsing, iteration and callback counts.
Callbacks must be synthetic and nonblocking. Python cannot sandbox a supplied
callable, preempt it, or prevent its own unrelated side effects. The test harness
guards native operations with `BaseException`, which deliberately escapes the
probe. Ordinary callback `Exception` instances are mapped to fixed codes.

## Optional B2 reference and immutability

`reference` is null, or exactly `payload` and `sha256`. `payload` has exactly
`captures`, `requests`, `evidence`, using the **unchanged B2 contracts**. Its
digest is SHA-256 of the adapter's canonical JSON (sorted keys, two-space indent,
ASCII escapes, no NaN, final newline). The probe bounds and copies the input,
recomputes the outer digest, then passes those copies to the unchanged public
`assess_provenance` API. B2 invalid/incomplete results remain failures here;
rehashed structural tampering cannot bypass that validator.

The reference roster (excluding the local context) must match target PID/PPID/
starttime exactly. Available B2 boot, namespace device/inode, mount ID and mount
type must agree with local observations; unavailable reference readings are
incomplete. Same-domain reference frame windows, concatenated in capture order,
must exactly match requested windows. Different declared clock domains add
`CLOCK_DOMAIN_UNCOMPARABLE`; their timestamps are not aligned or compared with
local timestamps. Matching domain labels themselves remain caller assertions.

An adapter-rejected request with `input_sha256=null` adds explicit
`REQUEST_INTEGRITY_UNAVAILABLE` and `CAPTURE_REQUEST_REJECTED`. No request hash is
invented for that artifact. The report's `input_sha256` instead identifies the
new local probe request, and `reference_sha256` identifies the detached reference
payload. Neither authenticates origin. After callbacks, bounded recopying and
recanonicalization detect changes to the caller-owned request or reference.
Inputs must not be concurrently mutated during copying. A mutation that is made
and restored entirely between inspections cannot be detected by this contract.

The module never writes accepted evidence or any input object. `ProbeReport` is
a frozen dataclass containing canonical `serialized` JSON. `to_dict()` returns a
new detached tree each time. Output includes explicit numeric context and target
identities, digests, per-read source, start/end, failure codes, injected
provenance label, raw-byte hash when decoded, and descriptor-stability flag.
No raw buffer, boot string, exception message or caller trust label is echoed.

## Failure vocabulary

All reason lists are sorted and unique. Every emitted code belongs to exactly
one of the module's disjoint, sealed `INVALID_CODES` or `INCOMPLETE_CODES`
vocabularies. Their union exactly equals `reason_codes`. An unknown/unclassified
code is replaced with `REASON_CODE_INVALID` at both per-read and report emission
boundaries; its arbitrary label is discarded. It cannot yield `CONSISTENT`,
erase a known failure or leak a caller trust token. Invalid reasons take
precedence in the outcome; they never erase incomplete reasons.

| Invalid codes | Meaning |
| --- | --- |
| `INPUT_NOT_JSON`, `INPUT_CAP_EXCEEDED` | Unsafe types/encoding/cycles or exceeded copy, serialization, cardinality or buffer limits. |
| `SCHEMA_INVALID`, `INTEGER_INVALID`, `DUPLICATE_FIELD`, `INVALID_UTF8` | Wrong fields, types/ranges, duplicate JSON key or invalid read encoding. |
| `SOURCE_KIND_INVALID`, `CLOCK_DOMAIN_INVALID` | Unsupported source/domain declaration. |
| `DUPLICATE_IDENTITY` | Repeated PID in context/targets. |
| `IDENTITY_CONTRADICTION` | Payload PID contradicts the PID bound to the identity leaf; invalid with trust limited to `CALLER_ASSERTED_ONLY`. |
| `PATH_POLICY_VIOLATION`, `SYMLINK_REJECTED` | Substituted source descriptor, prohibited symlink metadata, or callback path-resolution failures: `ENOTDIR` maps to path policy and `ELOOP` to symlink rejection. Both are invalid, never generic `READ_FAILED`. |
| `DESCRIPTOR_INVALID`, `DESCRIPTOR_CHANGED`, `DESCRIPTOR_ALIAS` | Invalid binding, metadata race, distinct non-namespace leaves sharing one descriptor identity, or any namespace target aliasing a non-namespace leaf. |
| `MOUNT_MISMATCH` | Wrong procfs/nsfs filesystem or symbolic mount path, inconsistent procfs mount/device, one mount ID claiming different devices/filesystems, or one device claiming different filesystems under any mount IDs across either sweep. |
| `NAMESPACE_METHOD_INVALID`, `NAMESPACE_DESCRIPTOR_MISMATCH` | Unsupported target method or namespace data disagreeing with target descriptor. |
| `READER_CONTRACT_VIOLATION` | Non-bytes reader result or missing/noncallable callback. |
| `CLOCK_FAILURE`, `CLOCK_REGRESSION`, `READ_WINDOW_MISMATCH` | Failed/invalid tick, decreasing/future tick, reversed window or reference window mismatch. |
| `REFERENCE_DIGEST_MISMATCH`, `REFERENCE_INVALID`, `INPUT_CHANGED` | Outer reference integrity failure, B2 rejection/invalid reference structure, or changed caller envelope. |
| `REASON_CODE_INVALID` | Unclassified internal reason replaced by a sealed invalid code; the original label is not emitted. |

| Incomplete codes | Meaning |
| --- | --- |
| `PERMISSION_DENIED`, `PROCESS_VANISHED`, `READ_FAILED`, `CALLBACK_EXCEPTION` | Permission, disappearance, other OS failure or ordinary callback exception. Messages are never copied. |
| `BOOT_ID_CHANGED`, `NAMESPACE_MISMATCH` | Environment continuity contradiction. |
| `PID_REUSE`, `PROCESS_REPARENTED` | Registered process starttime or PPID changed. |
| `UNKNOWN_PROCESS`, `ROSTER_INCOMPLETE` | Truly extraneous/unregistered PID observation or insufficient declared roster; a substituted PID at a bound leaf is invalid instead. |
| `READ_SKEW_EXCEEDED`, `STALE_READING` | Excess read span or observation age. |
| `FRAME_TIMESTAMP_MISSING`, `FRAME_GAP_EXCEEDED`, `COVERAGE_UNBOUNDED` | Missing endpoint, known excessive gap or inability to bound observations. |
| `REFERENCE_INCOMPLETE`, `REFERENCE_ROSTER_MISMATCH`, `REFERENCE_ENVIRONMENT_MISMATCH` | Failed/missing B2 observation or disagreement with the local roster/environment. |
| `REQUEST_INTEGRITY_UNAVAILABLE`, `CAPTURE_REQUEST_REJECTED` | Explicit reference request-rejection semantics; B2 also makes the reference invalid. |
| `CLOCK_DOMAIN_UNCOMPARABLE` | No authorized temporal comparison across declared clock domains. |

## Carryovers, limitations and verification gate

The new test file drives all eight mandatory B2 reason codes through its public
API with rehashed adapted captures as applicable: `FRAME_REASON_MISMATCH`,
`REASON_PROPAGATION_MISMATCH`, `CAPTURE_STATUS_MISMATCH`, `REASON_CODE_INVALID`,
`PHASE_PLAN_MISMATCH`, `CROSS_CAPTURE_ROSTER_CHANGED`,
`INPUT_CARDINALITY_MISMATCH`, `TRUST_CLAIM_INVALID`. Tests assert exact invalid
and incomplete sets. Changed cross-capture rosters remain B2 `INCOMPLETE`.
No mandatory case is declared uncovered.

Two existing B2 limitations are pinned, without editing it. Rejected-request
envelopes return early and summarize the failure as `CAPTURE_REQUEST_REJECTED`,
dropping the adapter's detailed invalid code. A frame with no end timestamp
resets adjacent-frame gap accounting. A three-frame synthetic capture with an
unreadable middle frame demonstrates that B2 omits the spanning gap while still
remaining incomplete. B3-A explicitly marks this case unbounded and checks the
known remaining gap. Missing or rehashed mismatched frame times never establish
usable coverage.

B2 cap tests require explicit `INPUT_CAP_EXCEEDED`, empty capture summaries and
no truncation for >8 MiB of strings, nine captures, 33 requested frames, 65
processes, and an ordinary adapter-generated 32×64 envelope. The latter has
about 280,000 nodes, exceeding B2's 200,000-node limit despite meeting nominal
frame/process caps. Thus a planned full-size native envelope exceeds the
existing verifier budget and is not assessable here. B2 also retains its closed
smaps counter vocabulary; future native counter extensions require a later
gate. This implementation changes neither cap nor predecessor semantics.

The suite includes import replay under native-operation guards, static bans on
native capabilities in the new module, guard negative controls, synthetic
success, failure/encoding/path/race/identity/clock attacks, digest tamper, caller
trust inflation, immutable output and deterministic replay. Guards fail using
`BaseException`; path-aware stat/lstat guards avoid patching pytest internals.
Fixtures have their own exact symbolic allowlists. No skips/xfails are added.

Targeted repair regressions cover Linux-faithful separate nsfs target metadata,
namespace aliases to earlier and later procfs leaves, impossible mount/device
combinations, exact reason-code partitioning and adversarial unclassified codes.
They also cover `None` and noncallable reader/descriptor/clock callbacks, missing
and extra reference envelope fields, SHA tamper, nine captures, 34 aggregate
same-domain reference windows, and all three forbidden trust tokens injected
into rehashed reference evidence. Forbidden tokens must never be echoed.
Reader, descriptor-before and descriptor-after `ELOOP`/`ENOTDIR` failures are
explicit invalid regressions. Second-repair regressions pin exact reason sets
for both directions of procfs/nsfs device collision with distinct mount IDs,
the valid separate-device baseline, and disjoint usable sweeps in both orders.
The disjoint cases deliberately fail the complementary reads with
`PERMISSION_DENIED`: without inode aliasing the exact set is
`MOUNT_MISMATCH` plus `PERMISSION_DENIED`; with aliasing it additionally
contains `DESCRIPTOR_ALIAS`. Thus neither a same-sweep comparison nor a
`DESCRIPTOR_CHANGED` failure can mask a missing cross-sweep check.
Second-sweep PID substitution at `pids/200/identity` (payload PID 300 or context
PID 1000, retaining PPID 100 and starttime 20) is schema-valid and has exactly
`IDENTITY_CONTRADICTION`, an `INVALID` outcome and `CALLER_ASSERTED_ONLY` trust.
Substituting only PID 100 instead leaves `pid == ppid`; that schema-invalid
payload is rejected before identity comparison with exactly `SCHEMA_INVALID`,
an `INVALID` outcome and `CALLER_ASSERTED_ONLY` trust.
PPID/starttime regressions retain their exact
incomplete categories. These tests are supplied for review and the
guarded runner; they have not been executed by the implementer.

The implementer does not execute tests, builds or benchmarks. After independent
review PASS, only the orchestrator runs the exact ten-suite pytest invocation
(the new suite plus the nine accepted predecessors), requiring more than 1848
passes and zero skipped/xfail/xpass, BLOCKER or MAJOR findings. Any native-trust
finding blocks acceptance regardless of generic severity. The independent
audit and any guarded three-file commit require subsequent gates.

Production remains `INCONCLUSIVE` / `NOT_OBSERVED`. Holder release and RSS
reclamation are separately `NOT_ESTABLISHED`. End-of-use observations, holder
release and RSS reclamation are distinct events. Nothing here establishes
complete worker discovery, worker absence or an atomic RSS peak. No production
simulation, memory-policy change, native measurement, scientific evidence edit,
package installation, staging, commit or push is part of this gate.
