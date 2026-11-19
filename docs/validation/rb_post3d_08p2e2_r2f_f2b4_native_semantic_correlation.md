# B3-B3 supplied-data semantic correlation

This is an inert additive parser/correlator for the accepted B3-B2 supplied
evidence contract. It performs no acquisition, process discovery, host reads,
clock calls, application networking, callback execution, preview invocation,
production workload, or external writes. Imports are the standard library
`dataclasses`, `hashlib`, `json`, `re`, and the inert B3-B2 integration module (whose
transitive bridge import is also inert). It does not import adapter, probe,
assessment, engine, or collector modules.

`production_memory_qualification=INCONCLUSIVE`,
`production_chronological_peak=NOT_OBSERVED`, and `memo_cap=256` remain fixed.
No native origin authentication, production measurement, chronological RSS
peak, worker absence, or holder release is established. Independently named
routes do not establish independently authenticated kernel sources.

## Public API and immutable reports

The module is
`scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_semantic_correlation.py`.

* `correlate_native_semantics(request, *, callbacks=())` accepts the existing
  B3-B2 request schema, as an exact built-in JSON tree or strict UTF-8 bytes.
  The new output schema is
  `rawibumi.native-semantic-correlation.f2b4.d2b2b3b3.v1.report`.
* `import_upstream_report(kind, raw_bytes)` accepts original upstream JSON
  bytes and returns the separate `.upstream-import` schema under the same new
  version. It **never produces a converted capture**.
* Both return a frozen `SemanticReport` containing only an immutable canonical
  serialized string. `to_dict()` creates a detached copy. `sha256` hashes the
  exact UTF-8 serialized report. `canonical_json` and `digest` use B3-B2's
  sorted-key, indented, ASCII-escaped JSON with a final newline.

Strict decoding reuses B3-B2's bounded exact-type decoder: 8,388,608 input bytes,
65,536 characters per string, 200,000 nodes, depth 24, and bounded integers.
Floats, NaN, arbitrary objects, subclasses, nonstring keys, duplicate JSON keys,
invalid UTF-8, surrogate code points, NUL, and cycles fail closed. The new layer
also rejects **all repeated container identities** in a tree (`INPUT_ALIAS`),
including sharing within one route. Shared immutable primitives are allowed.
JSON whitespace and object-key order need not be canonical. Raw-byte and
canonical-tree SHA-256 values are distinct and are never conflated.

No exception messages, caller paths, labels, or raw read bytes are emitted.
Evidence uses validated symbolic paths, fixed reason codes, original digests,
counts, and permitted source-origin labels. Hashes bind supplied data; they do
not prove source custody or authenticate a kernel.

## Predecessor preservation and precedence

The caller's **original object** goes directly to the public
`integration.integrate_native_evidence`, with its original callbacks tuple.
Copying first would hide the predecessor's source-alias observations. The new
strict copy is then bound to the predecessor's `request_sha256` and, for byte
input, `raw_input_sha256`. The input is checked again before return. No callback
or clock is called during these checks.

Each result embeds the complete, unchanged predecessor report in
`predecessor_report_embedded` and retains its exact serialized SHA-256,
`predecessor_outcome`, and `predecessor_reason_codes`. `SOURCE_DISAGREEMENT`
is never removed. The top-level outcome uses the union of predecessor and
semantic reasons, with INVALID taking precedence over INCOMPLETE, which takes
precedence over CONSISTENT. No predecessor INCOMPLETE result becomes top-level
CONSISTENT.

Only a predecessor CONSISTENT result, or INCOMPLETE with **exactly**
`SOURCE_DISAGREEMENT`, reaches the subordinate comparison. All other outcomes
yield `semantic.classification=NOT_EVALUATED`. This is necessary because
B3-B2's `UPSTREAM_CONVERSION_NOT_IMPLEMENTED` stops validation early.
If the final input-stability check fails, the classification returns to
NOT_EVALUATED and any provisional volatile-divergence evidence is discarded.

The semantic outcome is separate from the predecessor verdict. Its
classification is `STABLE_IDENTITY_CORRELATED`, `NOT_CORRELATED`, or
`NOT_EVALUATED`. A volatile-only disagreement can produce a subordinate
correlation while the top-level outcome remains INCOMPLETE.

Reasons are sorted, unique, partitioned by the sealed INVALID and INCOMPLETE
vocabularies. All B3-B2 reasons retain their severity. Additional INVALID
reasons are `INPUT_ALIAS` and `READ_SIZE_CONTRADICTION`. Additional INCOMPLETE
reasons are `STABLE_IDENTITY_MISMATCH`, `STABLE_READ_DISAGREEMENT`,
`TEMPORAL_NONOVERLAP`, and `UNSUPPORTED_LOSSLESS_CONVERSION`. Unknown internal
reasons are sealed to `REASON_CODE_INVALID` and cannot produce agreement.

## Identity and read-byte semantics

Validated `(pid, ppid, starttime_ticks)` must equal the reference roster on both
routes for every required frame. B3-B2 validates the 2–32 frame count, PID reuse,
reparenting, worker roster, first/last appearance, partial frames, read presence,
read status/reasons, descriptor stability, duplicate identities/reads, and
source-label independence. Those failures are never relaxed here.

Boot UUID, procfs/nsfs filesystem/mount/device identity, clock kind, source state,
source kind, origin attestation, and data-origin labels must agree. Namespace
kind must be INODE with an equal validated value; equal LABEL values are still
uncomparable. Descriptor identity is joined by symbolic `path_id` and must agree
exactly, including role, filesystem, mount ID, device, and inode. Both routes
and all relevant frames retain these requirements.

Only `pids/<pid>/identity` raw reads are treated as volatile, and only with both
statuses OK and equal reason codes. A differing SHA-256 and possibly byte count
does not override the separately supplied validated identity. Each cross-route
divergence retains frame index, symbolic path, both original hashes and counts,
and `VOLATILE_IDENTITY_READ_BYTES_DIFFER` in deterministic order. This is a
conservative fixed policy, not a caller-configurable allow-list. Parser-derived
values are never inferred from hashes.

`ns_link` and `ns_target` bytes must agree across routes and frames. Equal
SHA-256 with unequal byte counts anywhere in eligible read evidence is a hard
contradiction. Failed reads, different status/reasons, stable descriptor changes,
origin conflicts, permission errors, process disappearance, and missing reads
cannot produce correlation.

Frame order, roster order, process/read chronological order, and route order
retain the predecessor contract. The comparison joins processes by PID and
descriptors/reads by path; observed-PID and descriptor-list order have no semantic
meaning. A reordered caller object can still have a different request digest.

## Temporal rule

All observations remain non-atomic. B3-B2 enforces the supplied reference window,
exact first/last endpoints, `max_gap_ns`, `max_read_ns` frame duration, per-read
frame containment, monotonically ordered frames/reads, and endpoint route skew.
Missing workers on any frame or missing first/last worker observations keep their
original failure reasons.

For each paired frame and each paired read, let the closed intervals be
`[a0,a1]` and `[b0,b1]`, with `T=max_route_skew_ns`. Require:

```text
abs(a0-b0) <= T
abs(a1-b1) <= T
a0 <= b1 + T
b0 <= a1 + T
```

The last two inequalities explicitly define overlap within bounded tolerance;
all boundaries are inclusive. `T+1 ns` fails closed. Endpoint skew already
implies this bounded overlap; in the public API an out-of-skew predecessor
normally stops before semantic comparison. Tests cover both that gate and the
explicit closed-interval predicate. Duration and gap tests cover their exact
limit and +1 ns. No intervals are synthesized or merged. There is no claim of
simultaneous observation, continuous-time coverage, or a merged RSS peak.

## Original upstream import: no supported lossless conversion

The separate import entry point recognizes exactly:

| Kind | Original schema | Missing semantic information |
| --- | --- | --- |
| `ADAPTER_D2B2` | `rawibumi.native-procfs-adapter.f2b4.d2b2a.v1.result` | second route, descriptor identities, procfs/nsfs mount identity, reference window, route provenance |
| `PROBE_B3A` | `rawibumi.local-provenance-probe.f2b4.d2b2b3a.v1.report` | second route, supplied reference window, route provenance, bound original inputs |
| `BRIDGE_H0` | `rawibumi.native-provenance-bridge.d2b2b3b0.v1.report` | reference window, frame count, per-frame windows, limits, route provenance |

This is an **original-envelope inspection API, not a successful converter or a
reimplementation of upstream verification**. There is no supported conversion
path. It validates the exact original top-level fields/schema, sealed reason
vocabulary, outcome/partition consistency, fixed nonqualifying trust fields,
origin/clock labels, declared hash syntax, and adapter canonical integrity hash.
Selected nested roster/read/provider consistency is checked as well. It rejects
schema substitution, B3-B2 verification summaries, extra/missing top-level
fields, malformed byte input, trust tampering, broken checkable hashes, and
contradictory success summaries. This does not authenticate an original report
or prove that its claimed execution occurred.

Adapter envelope inspection distinguishes request rejection from attempted
capture. NOT_ESTABLISHED coverage requires INVALID, null request metadata, no
frames, and zero acquisition counters. Attempted captures require the original
adapter run-label grammar, input hash, config/roster objects, and a positive
requested frame count. The frame count must match unless CAPTURE_STOPPED is
present. Reason-free captures require REGISTERED_ROSTER_OBSERVED; captures with
reasons require UNCERTAIN. Frame indices and status/reason summaries must agree,
and each frame's timing summary and the overall timing summary must equal the
minimum/maximum supplied read endpoints and their difference (or null when an
endpoint is unavailable). Read-window completeness must match endpoint presence.
These are supplied-envelope checks, not a replay of procfs parsing or capture.

Reason-free bridge envelopes require both providers and both sweeps to contain
exactly `boot_id`, `proc_mount`, and each registered PID's `identity`, `ns_link`,
and `ns_target` paths, without missing or duplicate observations. Both original
INJECTED_STRUCTURED and INJECTED_JSON_BYTES methods remain unsupported for
lossless conversion. The probe's distinct `mount` path is unchanged.

An accepted envelope returns `conversion=UNSUPPORTED_LOSSLESS_CONVERSION`,
`converted_capture=null`, and the missing-field list. Its outcome is INCOMPLETE;
an original INVALID report additionally retains `UPSTREAM_INVALID` and remains
INVALID; original incomplete reasons additionally retain `UPSTREAM_INCOMPLETE`.
Invalid envelopes return `conversion=REJECTED` and INVALID. Neither
path reconstructs absent descriptors, windows, namespaces, or trust values.

The result retains original schema, verbatim permitted origin label, original
outcome and exact reason partitions, SHA-256 of **exact supplied bytes**, and
SHA-256 of their canonical tree. The original outcome is explicitly
`CALLER_SUPPLIED_NOT_REVERIFIED`, and validation scope is
`ORIGINAL_ENVELOPE_ONLY`. Probe input/reference hashes cannot be rechecked
without their original inputs; bridge/adapter request hashes also remain
caller-supplied. Only the adapter's report integrity hash is recomputed.

Exact original bytes remain with the caller. They are not retained by this
module, which makes no writes. The result's explicit custody limitation is
`DIGEST_ONLY_EXACT_BYTES_REMAIN_WITH_CALLER_NOT_RETAINED_OR_AUTHENTICATED`.
This is an immutable digest link, not a custody guarantee. Unknown fields never
become fabricated semantic evidence.

## Nonqualification and verification handoff

Every success and failure fixes qualification to NONQUALIFYING; independence to
INDEPENDENCE_NOT_ESTABLISHED; origin authentication, complete worker-roster,
production qualification, peak, worker absence, production workload, atomic
snapshot, continuous coverage, and merged peak booleans to false. Native/live
integration remains NOT_IMPLEMENTED; kernel attestation and holder release
remain NOT_ESTABLISHED. Verification provenance is CALLER_ASSERTED, peak bound
is NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK, and the science/memo constants above do
not change. `INJECTED_TEST_ONLY` and `NATIVE_PROCFS_UNVERIFIED` stay distinct.

New artificial regressions cover these fields exactly on success and failure,
predecessor preservation, volatile divergence, stable identities and descriptors,
temporal boundaries, worker/frame coverage, aliasing and mutation, strict bounded
JSON, upstream import rejection and unsupported outcomes, determinism, immutable
returns, and source import/call restrictions. Module-local raising stubs prove
that neither the optional preview nor the bridge acquisition seam is reached.
Injected provider and bound-callback objects exercise the identity-only callback
contract without invoking the preview, providers, callbacks, or clocks. No global
OS, filesystem, network, or clock hooks are monkeypatched.
Literal successful adapter and two-provider/two-sweep bridge fixtures cover
preserved original outcomes, schemas, origin labels and both report hashes.
Resealed contradictory adapter summaries and missing/substituted bridge paths
are rejected. No acquisition API constructs these fixtures.

Implementation tests, builds, benchmarks, and pytest collection were **not run
by the implementer**. The orchestrator must run the exact 13-suite command in
`.ai/TASK.md` (the new suite followed by the accepted 12 predecessor suites),
confirm more than 2,671 passed with zero failed/skipped, verify all 53 immutable
source guards and three preexisting historical E2 files, obtain independent
Claude review with zero BLOCKER/MAJOR/MINOR findings, and prepare the ZIP.
No test count or independent PASS is claimed here. The implementer creates only
the three authorized new files and does not stage, commit, push, or create a ZIP.
Independent audit and the separate local commit remain acceptance steps.
