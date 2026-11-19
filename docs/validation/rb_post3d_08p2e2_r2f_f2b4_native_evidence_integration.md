# B3-B2 supplied native-evidence integration contract

This stage adds a pure, bounded envelope integration interface. A structurally
consistent result is **NONQUALIFYING**. It authenticates neither native origin
nor an independent kernel. No native acquisition, production measurement,
chronological peak, holder release, or complete worker coverage is established.
The 256-entry memo policy and all predecessor modules are unchanged.

The historical B3-B1 result, `TOY_NATIVE_CORROBORATION_PASS_NONQUALIFYING`, is
reference evidence only. This implementation does not replay that experiment.

## Public API

Module: `scripts.benchmarks.rb_post3d_08p2e2_r2f_f2b4_native_evidence_integration.py`.

```python
integrate_native_evidence(request, *, callbacks=()) -> IntegrationReport
preview_injected_bridge(request, bridge_request, *, providers, clock) -> IntegrationReport
canonical_json(value) -> str
digest(value) -> str
```

`integrate_native_evidence` never invokes a callback. `callbacks`, if supplied,
must be an exact tuple of two callables; it is used solely for object identity
alias checks. An empty tuple means callback objects are unavailable. This is
explicitly supplied data, not an acquisition API. Import, construction and the
normal integration call collect no clock, descriptor, filesystem, host, or
process information. There are no activation flags or default readers.
Lists (including empty lists), nonempty tuples of any length other than two,
and a non-callable element fail as `INVALID` / `CALLBACK_CONTRACT_INVALID`
when the preceding request/reference/limit validation succeeds.
The optional bridge preview checks roster and input stability only; it does
not join the bridge-observed boot, namespace or mount facts to the integration
reference. A consistent preview therefore establishes no environmental agreement
between that artificial bridge fixture and the supplied captures.

`IntegrationReport` is a frozen dataclass containing canonical JSON in
`serialized`. `to_dict()` returns a detached tree; `sha256` hashes the exact
serialized UTF-8 bytes. Canonical JSON uses sorted keys, two-space indentation,
ASCII escaping, no NaN, and a final newline. `digest` uses that same representation
and is intended for already validated trees. Neither helper authenticates data.
Constructing this Python value is not an attestation or a security capability.

The report schema is
`rawibumi.native-evidence-integration.f2b4.d2b2b3b2.v1.report`.
The request schema is that string without `.report` (called `SCHEMA` below).

## Exact supported input

Inputs are exact built-in dict/list/string/int/bool/null trees, or strict UTF-8
JSON **bytes**. JSON strings as the top-level argument, arbitrary objects,
subclasses, floats, NaN, infinities, cycles, duplicate JSON keys, NULs and invalid
Unicode fail closed. A bool is never accepted in an integer field. Unknown or
missing fields are rejected. Objects listed below have exactly the stated keys.
Lists retain their supplied order in capture digests; only the explicitly
documented cross-route PID/path joins use sets/maps for comparison. There is no
normalization, repair, unit conversion, or mutation of caller evidence.

Request keys:

| Key | Value |
| --- | --- |
| `schema` | `SCHEMA` |
| `mode` | exactly `SUPPLIED_ONLY` |
| `native_opt_in` | exactly `False` |
| `reference` | reference object below |
| `routes` | exactly two route objects |
| `limits` | `max_read_ns`, `max_gap_ns`, `max_route_skew_ns`, each integer 1–1,000,000,000 |

`NATIVE`, `NATIVE_OPT_IN`, the adapter's
`ALLOW_BOUNDED_NATIVE_PROCFS_D2B2`, and every other mode or non-False opt-in are
denied with `NATIVE_MODE_DENIED` before callback validation or execution. This
also applies to opt-ins on the separate bridge preview request.

A reference has `boot_id`, `namespace`, `procfs`, `nsfs`, `clock_kind`, `roster`,
`window`, `frame_count`. The environment fields are:

| Field | Exact representation |
| --- | --- |
| `boot_id` | canonical lowercase UUID, 8-4-4-4-12 hex digits |
| `namespace` | `{ "kind": "INODE", "value": positive_integer }` or `{ "kind": "LABEL", "value": label }` |
| `procfs` | `{ "filesystem": "proc", "mount_id": positive_integer, "st_dev": positive_integer }` |
| `nsfs` | same keys, `filesystem` exactly `nsfs`; mount ID and device must differ from procfs |
| `clock_kind` | `INJECTED_MONOTONIC_NS` or `LOCAL_MONOTONIC_NS` |

`roster` is 1–64 identities. Each identity has exactly `pid`, `ppid`,
`starttime_ticks`. PID is 1–2,147,483,647, PPID is 0–2,147,483,647 and differs
from PID; ticks are 0–2^64−1. Duplicate PIDs, including duplicate identical
entries, are invalid. Every registered process is required in each frame;
missing records mean missing evidence. There is no implicit process discovery,
parent inference, or special exemption for an unobserved worker.

`window` has unsigned integer `start_ns`, `end_ns`, with start ≤ end.
`frame_count` is an integer 2–32. Timestamps are already supplied nanoseconds;
ticks are never converted into times. The supplied roster and window are
caller assertions and confer no completeness or clock authenticity.

A route has `provenance`, `capture`, `verification`.
Provenance has exactly `route_id`, `provider_id`, `callback_id`, `method_id`,
`collection_domain`, `data_origin`. The first five are independently supplied
data/method identities, each a label. They describe the claimed collection
route, provider, callback, provenance method and underlying collection domain
(for example the same kernel), respectively. `data_origin` must match the
capture's source state. Differing labels never establish independence.

Labels match `[A-Za-z0-9_-]{1,64}`. Authority/trust terms are forbidden, ignoring
case, `_` and `-`, including when embedded inside another word. The exact
reserved vocabulary is exported as `RESERVED_LABELS`, copied from the H0
bridge policy. Caller labels are hashed rather than echoed in the output.

A capture has exactly `schema`, `source_state`, `source_kind`,
`origin_attestation`, `clock_kind`, `boot_id`, `namespace`, `procfs`, `nsfs`,
`roster`, `frames`. Its schema is `SCHEMA + ".capture"`.
Only these exact provenance combinations are supported:

| `source_state` / `data_origin` | `source_kind` | `origin_attestation` | `clock_kind` |
| --- | --- | --- | --- |
| `INJECTED_TEST_ONLY` | `TEST_INJECTED` | `UNVERIFIED` | `INJECTED_MONOTONIC_NS` |
| `NATIVE_PROCFS_UNVERIFIED` | `NATIVE_PROCFS_UNVERIFIED` | `UNVERIFIED_NATIVE_CAPTURE` | `LOCAL_MONOTONIC_NS` |

These are declarations. A native-shaped supplied capture retains its native
unverified labels; it never becomes injected evidence to satisfy a predecessor
gate. Conflicting labels or mixed route origins are invalid. Matching labels,
boot IDs, namespace or mount facts are not authenticating evidence.

Frames (0–32 supplied, with the reference's expected count checked separately)
have exactly `index`, `start_ns`, `end_ns`, `observed_pids`, `processes`,
`read_complete`, `reason_codes`. Index must equal its zero-based list position;
timestamps are unsigned integers and ordered. `observed_pids` has at most 64
distinct valid PIDs. `read_complete` is a bool. Frame reason codes are sorted,
unique entries from `READ_CODES`: `READ_FAILED`, `PERMISSION_DENIED`,
`PROCESS_VANISHED`.

Each process (at most 64 per frame) has exactly `identity`, `descriptors`,
`reads`. Each descriptor has `path_id`, `role`, `filesystem`, `mount_id`,
`st_dev`, `st_ino`; its last three fields are positive integers. Exactly these
three symbolic paths are required for each process; these are not OS paths:

| Path | Role | Filesystem and mount/device source |
| --- | --- | --- |
| `pids/{pid}/identity` | `PROCFS_OBJECT` | capture's `procfs` |
| `pids/{pid}/ns_link` | `PROCFS_LINK_LOCATION` | capture's `procfs` |
| `pids/{pid}/ns_target` | `NSFS_TARGET` | capture's `nsfs` |

Namespace targets must match the supplied namespace inode when that is the
representation. Multiple target paths may share that namespace descriptor;
other cross-path device/inode aliases are invalid. A descriptor must remain
unchanged for a path across frames. These are supplied descriptor facts, not
proof of descriptor binding, symlink safety, or a real procfs mount.

Each read has exactly `path_id`, `start_ns`, `end_ns`, `status`, `sha256`,
`byte_count`, `reason_codes`. It uses one of the three symbolic paths, once per
process; reads follow sequential supplied list order within a frame. Times must
be within the frame and nondecreasing across processes/reads. `byte_count` is
0–65,536. `reason_codes` uses the frame vocabulary. Status is `OK` if no codes,
`FAILED` otherwise. A digest is 64 lowercase hex digits; null is permitted only
for failed reads. The digest preserves a supplied raw-byte identifier; without
the raw bytes, this interface cannot verify its content or byte count. Raw text,
OS descriptors and filesystem paths are not accepted.
Repeated read paths are invalid with `DUPLICATE_READ`; repeated descriptor
paths or prohibited device/inode aliases use `DESCRIPTOR_ALIAS`.

Empty/partial process, descriptor or read lists fail as incomplete. A missing
PID or disagreement between observed PID and process lists never proves
absence. Extra PIDs, roster changes, PID reuse and PPID changes fail closed.
Early/late observation codes concern presence in supplied frames only; they
make no claim about birth, death, release, or ticks-to-clock alignment.

## Supplied provenance-verification outcomes

The verification **summary** schema is `SCHEMA + ".verification"`. It has
exactly `schema`, `validator`, `upstream_schema`, `outcome`, `reason_codes`,
`invalid_reason_codes`, `incomplete_reason_codes`, `report_sha256`,
`capture_sha256`.

| `validator` | `upstream_schema` | Outcome with no reasons |
| --- | --- | --- |
| `ADAPTER_D2B2` | `rawibumi.native-procfs-adapter.f2b4.d2b2a.v1.result` | `CAPTURE_CONSISTENT_NONQUALIFYING` |
| `PROBE_B3A` | `rawibumi.local-provenance-probe.f2b4.d2b2b3a.v1.report` | `CONSISTENT` |
| `BRIDGE_H0` | `rawibumi.native-provenance-bridge.d2b2b3b0.v1.report` | `CONSISTENT` |

All code lists must be sorted and unique; the lists of invalid and incomplete
codes must be the exact respective partitions of `reason_codes`. Outcome is
INVALID if any invalid codes, otherwise INCOMPLETE if any incomplete codes,
otherwise the table's success string. Unknown codes and contradictory outcomes
are invalid. Vocabularies remain namespaced; for example the probe's namespace
mismatch is incomplete while the bridge's namespace contradiction is invalid.
Literal adapter/probe vocabularies are pinned by regression drift checks; the
injected bridge vocabulary is consumed directly.

`capture_sha256` must equal `digest(route["capture"])` for this **new fact
schema**, not the hash of an adapter report. `report_sha256` is the caller's
identifier for the original upstream report. Both must be lowercase SHA-256
strings. This binding is a consistency check, not cryptographic authentication.
The original upstream report is not supplied to this API, so its hash and the
asserted relationship to the fact capture cannot be independently verified.
The result explicitly marks every summary and the overall verification
provenance `CALLER_ASSERTED`. Even a complete fabricated summary cannot promote
trust. Injected bridge/probe summaries are rejected on native-shaped captures.

No conversion of original adapter, probe, assessment, or bridge reports is
implemented. Supplying one of their recognized schemas as `capture.schema`
returns `INCOMPLETE` / `UPSTREAM_CONVERSION_NOT_IMPLEMENTED`; no original report
is relabeled. For B3-A, only the `.report` schema is a recognized upstream
report. The bare `rawibumi.local-provenance-probe.f2b4.d2b2b3a.v1` is a request
schema and yields `INVALID` / `SCHEMA_INVALID` in either `capture.schema` or
a `PROBE_B3A` summary's `upstream_schema`.
In particular, this interface does **not** check an original
adapter's `integrity.sha256`, invoke `assess_provenance`, or reproduce its full
verification logic. Supplying an original report as a verification summary
also fails the exact schema check. A full assessment has additional notes and
an `UNVERIFIED` success outcome; it is deliberately not squeezed into a simpler
success vocabulary. Its conversion remains `NOT_IMPLEMENTED`.

These representational limits are intentional: predecessor capture reports do
not carry all method/descriptor facts required here, the injected-only bridge
cannot consume native records, and importing the native assessment/probe stack
would import the protected native adapter and its filesystem/clock facilities.
Nothing here supplies the missing authenticator. Future separately authorized
code may supply facts in this schema, without modifying predecessor validators.
It must retain original reports and separately establish their relationship;
this code-only contract alone cannot do so.

## Validation, precedence and bounds

All report reason codes come from exported `INVALID_CODES` and
`INCOMPLETE_CODES`; upstream codes stay inside their verifier summary or bridge
preview. The lists in the report are disjoint, sorted and unique. Precedence is
INVALID, then INCOMPLETE, then CONSISTENT. `structure_consistent` is true only
in the last case. `INDEPENDENCE_NOT_ESTABLISHED` is a constant status, not a
reason that makes every artificial structure test incomplete.
An unknown internal code is sealed as `REASON_CODE_INVALID`, never dropped to
a consistent outcome; known accompanying reasons retain their classifications.

Validation order is deterministic: exact-dict acquisition denial; bounded
decode/copy; decoded-dict acquisition denial; request, reference and limits;
callback identities/shared-container aliases; then each route in order
(metadata, schema/origin, environment, roster,
frames/identities/descriptors/reads, verification); finally input stability.
Hard validation errors stop at the first failure. Recoverable incomplete
observations accumulate; any subsequently detected invalid condition dominates.
Frame duration is checked during each route's frame validation; cross-route
endpoint skew is checked after validating the second route's verification.
Both timing codes accumulate when both conditions are detected, remain in the
incomplete partition, and never override an invalid reason. Reports sort all
reason lists lexically; neither timing condition takes precedence over the other.
An unsupported conversion also stops with its explicit incomplete code. This
is not a complete inventory of faults in an otherwise malformed request.

Important reason groups:

| Condition | Result/code |
| --- | --- |
| wrong shape/version or unexpected fields | INVALID / `SCHEMA_INVALID` |
| malformed JSON, cycles, unsupported types, NUL/Unicode | INVALID / `INPUT_NOT_JSON` |
| duplicate JSON keys, numeric/type violation, budget overflow | INVALID / `DUPLICATE_KEY`, `INTEGER_INVALID`, `INPUT_CAP_EXCEEDED` |
| promotion, mixed/conflicting origins | INVALID / `SOURCE_LABEL_CONFLICT` |
| duplicate PID, self-parent | INVALID / `DUPLICATE_IDENTITY`, `IDENTITY_INVALID` |
| PID reused, PPID changed, missing/extra worker, roster changed | INCOMPLETE / `PID_REUSE`, `PROCESS_REPARENTED`, `MISSING_WORKER`, `UNKNOWN_PROCESS`, `ROSTER_DRIFT` |
| noncanonical/conflicting boot or conflicting numeric namespace | INVALID / `BOOT_ID_NONCANONICAL`, `BOOT_ID_CONFLICT`, `NAMESPACE_CONTRADICTION` |
| label namespace, incomparable clocks | INCOMPLETE / `NAMESPACE_UNCOMPARABLE`, `CLOCK_DOMAIN_UNCOMPARABLE` |
| filesystem/device/mount or descriptor contradictions | INVALID / `MOUNT_CONTRADICTION`, `DESCRIPTOR_INVALID`, `DESCRIPTOR_ALIAS`, `DESCRIPTOR_CHANGED` |
| repeated read path in a process | INVALID / `DUPLICATE_READ` |
| unallowed symbolic path | INVALID / `PATH_POLICY_VIOLATION` |
| reversed times, reads outside frame or frame outside comparable reference window | INVALID / `CLOCK_REGRESSION`, `READ_WINDOW_INVALID` |
| invalid main-entry callback container/length/element | INVALID / `CALLBACK_CONTRACT_INVALID` |
| alias, failed/partial reads, absent frames, gaps/endpoints | INCOMPLETE / `SOURCE_ALIAS`, read code, `PARTIAL_FRAME`, `FRAME_MISSING`, `READ_GAP_EXCEEDED`, `COVERAGE_GAP` |
| frame `end_ns - start_ns > max_read_ns` | INCOMPLETE / `FRAME_DURATION_EXCEEDED` |
| corresponding route frame/read endpoint difference `> max_route_skew_ns` | INCOMPLETE / `ROUTE_SKEW_EXCEEDED` |
| worker observed after first/before last frame | INCOMPLETE / `WORKER_LATE_OBSERVATION`, `WORKER_EARLY_LAST_OBSERVATION` |
| supplied route structure or byte facts disagree | INCOMPLETE / `SOURCE_DISAGREEMENT` |
| inconsistent verification partitions/outcome or digest/binding | INVALID / `OUTCOME_CONFLICT`, `DIGEST_INVALID` |
| upstream invalid/incomplete | INVALID / `UPSTREAM_INVALID`; INCOMPLETE / `UPSTREAM_INCOMPLETE` |
| changed caller data | INVALID / `INPUT_CHANGED` |

Maximum input: 8,388,608 UTF-8 bytes for encoded input; depth 24; 200,000 visited
nodes including dictionary keys; 65,536 characters per string; and an 8,388,608
byte copy budget counting UTF-8 strings plus eight bytes per visited node.
Integers in the copy are bounded to ±(2^64−1); field validators impose tighter
nonnegative bounds. The canonical serializer can expand whitespace/escapes,
but is bounded by those finite node, string and depth limits. Outputs contain
at most two route summaries and 32 frame summaries each; they contain fixed
trust values, digests, sealed codes and numeric windows/counts. No raw text,
caller labels, exception messages, identity payloads or host paths are echoed.
Bounded byte inputs retain an exact `raw_input_sha256`, including on decode
failure; canonical `request_sha256` is available after request schema validation.
These hashes are integrity identifiers only.

Frames must be monotonic; frame duration is bounded by `max_read_ns`, consecutive
frame and intra-frame read gaps by `max_gap_ns`. A duration equal to
`max_read_ns` is accepted; exceeding it emits only the duration diagnostic
`FRAME_DURATION_EXCEEDED`, independently of cross-route endpoint comparisons.
Reference endpoint shortfalls or missing expected frames are incomplete. Small
accepted sampling gaps do not establish continuous interval coverage. There is
no interpolation, chronological peak bound or atomic snapshot claim.

Cross-route comparison pairs frames by validated index, processes by validated
PID, and reads/descriptors by symbolic path. `SOURCE_DISAGREEMENT` compares frame
counts, indices, observed PID sets, process PID sets, exact process identities,
exact descriptor facts and path sets, read path sets, read statuses/reason codes,
frame reason codes and `read_complete`. Process/descriptor/read list ordering
is not itself a cross-route agreement requirement; each route must still satisfy
its own sequential timing validation. Identities are joined by PID, and descriptor
and read paths must refer to that process's PID (`PATH_POLICY_VIOLATION` otherwise).
There is no separate inference of identity substitution from frame position.

Per-read `sha256` and `byte_count` must also match exactly across paired reads.
These are caller-supplied byte facts, not timestamps or verified raw content.
Changing bytes therefore makes the supplied captures disagree even when both
read statuses are OK. This contract supplies no semantic parser or normalization
for volatile raw process content.

Timing is checked separately: the absolute difference between corresponding
`start_ns` endpoints and between corresponding `end_ns` endpoints must each be
at most `max_route_skew_ns`, for both paired frames and paired reads. Exceeding
that inclusive tolerance adds `ROUTE_SKEW_EXCEEDED`; timing differences alone never
add `SOURCE_DISAGREEMENT`. Missing counterparts are structural disagreement,
without inventing timestamps. Route source-state equality pins a common declared
clock kind before this comparison; differing reference clocks remain explicitly
uncomparable. Per-route reference endpoint coverage remains exact and independent
of route skew tolerance. Within-tolerance timings can be structurally consistent,
but cannot authenticate clocks, bytes, source origin or independence.

`FRAME_DURATION_EXCEEDED` and `ROUTE_SKEW_EXCEEDED` are bounded integration
`INCOMPLETE_CODES`; both keep qualification `NONQUALIFYING`. The integration
reason vocabulary no longer accepts or emits `READ_SKEW_EXCEEDED`. That spelling
is retained only in unchanged predecessor vocabularies and original upstream
summaries/previews, with their original meanings. A supplied predecessor skew
reason maps to `UPSTREAM_INCOMPLETE`, without inventing either integration timing
diagnosis. An unsupported internal integration code fails as `REASON_CODE_INVALID`.

Same route/provider/callback/method/domain IDs, same callback object, Python
bound methods sharing an owner (including method versus callable owner), or
shared dict/list subtrees across routes produce `SOURCE_ALIAS`. Object alias
checks use identity and exact `MethodType.__self__`, never arbitrary attribute
access. Empty callback metadata cannot prove distinct real methods. Kernel
identity is caller-asserted, including when supplied boot/namespace facts agree;
neither differing IDs nor agreeing routes establishes an independent kernel.

Input is copied and hashed, then compared again before return. The preview
also checks data after callbacks, including malformed mutations. Mutating a
caller tree after return cannot change a frozen report. Callers must not mutate
trees concurrently while they are being traversed; this API supplies no locking
or atomic snapshot guarantee. A later separately supplied mutation is a new
request, not a retroactive update to an earlier report.

## Optional injected bridge preview

The preview first requires a completely consistent integration request with
both routes explicitly injected. An invalid or incomplete base result returns
unchanged, with `bridge_preview=null`, before bridge entry, provider inspection
or clock execution. For matching routes with a partial frame this is exactly
`INCOMPLETE` / `PARTIAL_FRAME`; removing the last expected frame from both routes
is exactly `INCOMPLETE` / `COVERAGE_GAP`, `FRAME_MISSING`.
Native-shaped facts are refused before bridge
entry, provider inspection or clock execution. It then validates the artificial
bridge request's mode and opt-in and calls the **unchanged** H0 bridge, passing
the copied reference roster and the original provider objects. H0 retains its
own schema, preflight, artificial callback protocol, bounds and cleanup rules.

Only deterministic artificial providers and a deterministic artificial clock
are authorized. Arbitrary Python callbacks cannot be sandboxed by this API;
calling the preview with a live reader violates its contract. The main
integration entry point executes none of them. Ordinary callback errors follow
H0's failed-evidence rules; H0's BaseException cleanup/propagation is preserved.

The preview retains the exact original bridge serialized result **by SHA-256**,
plus its original outcome, reason codes, request hash, source state and
qualification. The original result is neither edited nor relabeled. The digest
can be compared against the retained original report; this is not a tamper-proof
signature. An invalid/incomplete bridge cannot yield a consistent preview.
A consistent bridge output does not upgrade any trust field and authenticates
no real capture. The preview checks roster and input/provider-list stability.
An artificial bridge request rejected during H0 schema preflight (for example,
`sweeps=3`) returns an original `INVALID` bridge preview with `SCHEMA_INVALID`
and an empty registered roster. For an otherwise consistent integration request,
the integration result is exactly `INVALID` / `PREVIEW_ROSTER_MISMATCH`,
`UPSTREAM_INVALID`; the bridge's schema reason stays inside the preview. It is
not diagnosed as an integration-input schema error.
Bridge boot/namespace/mount observations are not cross-checked against the
supplied reference; a consistent preview does not establish that relationship.
It does not compare memory magnitudes or bridge KiB against another source.

## Fixed scientific/trust limits

Every output, including errors and previews, has:

- `qualification=NONQUALIFYING`, `independence=INDEPENDENCE_NOT_ESTABLISHED`;
- `source_origin_authenticated=false`, `worker_roster_complete=false`,
  `production_memory_qualified=false`, `peak_observed=false`;
- `native_origin_authentication=NOT_IMPLEMENTED`, `live_native_integration=NOT_IMPLEMENTED`,
  `independent_kernel_attestation=NOT_ESTABLISHED`;
- `worker_absence_proven=false`, `holder_release=NOT_ESTABLISHED`;
- `production_memory_qualification=INCONCLUSIVE`,
  `production_chronological_peak=NOT_OBSERVED`, `production_workload_measured=false`;
- `bound_claim=NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK`, `atomic_snapshot=false`, `memo_cap=256`.

The new schema, supplied-fact boundary and caller-asserted verification summaries
are implementation choices permitted by this work order, not changes to any
existing schema or engineering semantics. Live integration and D3 measurements
still require separate explicit authorization and independent evidence.

## Deferred optional items

O1: Roster comparison remains order-sensitive. No roster normalization or
comparison change is part of this repair.

O2: Callback alias detection retains its existing identity/bound-owner checks;
distinct wrappers around a shared provider are not unwrapped or discovered.
Differing wrappers or caller labels still cannot establish independence.

O3: Exact per-read byte-count/hash comparison and exact reference coverage
endpoints remain enforced. Volatile procfs bytes may differ across real reads,
and live routes may not share exact coverage endpoints; these requirements can
therefore prevent future live-route consistency even for related captures.
Real integration requires a separately authorized semantic-comparison design
before proceeding. This repair introduces no normalization, hash relaxation,
coverage tolerance, or claim of live integration.

## Regression and verification handoff

The new unit suite covers inert module execution/construction, acquisition
denial, injected/native source preservation, identity/object/data aliasing,
roster/identity/environment/descriptor contradictions, windows/skew/gaps and
worker appearances, failed/partial observations, strict JSON and input budgets,
closed namespaced upstream outcomes, deterministic frozen output, absence of
raw/secret text, and an actual artificial H0 preview with mutation/failure
controls. Its autouse guard blocks native filesystem operations, host reads,
real clocks, process creation and network calls. The sole source read is static
inspection/import replay of the integration module. Negative controls exercise
the guard without making those operations.

The targeted MINOR-closure additions assert exact outcomes and complete reason
sets for invalid main-entry callback contracts, a bridge-INVALID preview,
incomplete base frames skipping the preview, and a native capture whose
`data_origin` contradicts its source state. Timing cases cover duration and
route-skew inclusive boundaries, separate and combined reasons, invalid
precedence, and preservation of predecessor skew vocabularies. All new cases
use deterministic artificial data under the existing guard.

No pytest, npm tests, builds, benchmarks, production workloads or native
experiments were executed by the implementer. Verification remains pending
with the V1.1 orchestrator using the exact 12-suite `TARGETED_VERIFICATION`
contract in `.ai/TASK.md`. The previous eleven suites and their accepted 2,454
tests are preserved. Acceptance still requires more than 2,454 passes, zero
failures/skips/xfails/xpasses and independent review with zero BLOCKER/MAJOR.
This document makes no claim that those checks have already passed.

Only the three authorized new source/test/document files belong to this change.
The orchestrator owns guard comparisons, review and verification logs, final
verdict and the upload ZIP. The implementer does not modify workflow records,
stage, commit, push, or create files outside these three paths.
