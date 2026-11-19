# B3-B4 supplied-raw-read evidence assembly

Code-only implementation for parent `a2ca31a4dd2144c7503c952bf2ad9ac2d9f8d838`.
Independent review, targeted verification, independent audit and any separately
authorized guarded commit remain later gates. No test run or review pass is
claimed by this document.

`assemble_supplied_evidence(template, raw_reads, upstream_reports=None)` lives in
`scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_native_evidence_assembly.py`.
Its report schema is
`rawibumi.native-evidence-assembly.f2b4.d2b2b3b4.v1.report`.
It performs bounded in-memory assembly of caller-supplied observations. It has
no acquisition entry point, callbacks, clocks, filesystem access, processes,
network access, native adapters or bridge preview. Imports are stdlib plus the
accepted B3-B3 semantic module, which exposes B3-B2 integration. Their inert
transitive bridge import is never executed as an acquisition API.

## Exact input grammar

`template` is an exact Python `dict` containing exact JSON `dict`/`list` trees,
or exact `bytes` containing strict UTF-8 JSON. B3-B2's bounded decoder rejects
duplicate JSON keys, malformed UTF-8, unsupported scalar types, integer overflow,
excessive strings, depth, nodes and accounted JSON size. JSON floats, including
NaN, are rejected. No coercion or arbitrary object serialization occurs.

The template is the accepted B3-B2 request schema with `mode="SUPPLIED_ONLY"`,
`native_opt_in=false`, exactly two routes, and each capture's `CAPTURE_SCHEMA`.
Roster, origins, clock domains, boot/namespace/mount facts, descriptors, reference
window, frame/read timestamps, limits and verification summaries are independently
supplied by the caller. No metadata is inferred from procfs-like payloads.
`INJECTED_TEST_ONLY` and `NATIVE_PROCFS_UNVERIFIED` keep their accepted meanings.
All source and provenance label validation remains governed by B3-B2.

`raw_reads` is an exact finite `list` of exact `dict` records, each with exactly:

```python
{
    "route_index": 0,           # exact int, 0 or 1
    "frame_index": 0,           # exact int, 0..31, explicit template index
    "pid": 100,                 # exact int, 1..2147483647
    "path_id": "pids/100/identity",
    "payload": b"supplied bytes"
}
```

The symbolic path is precisely `pids/<canonical decimal PID>/<leaf>`, where
`leaf` is `identity`, `ns_link` or `ns_target`, and the PID equals the record's
PID. OS paths, leading-zero PIDs and other leaves are rejected. Index tuples
`(route_index, frame_index, pid, path_id)` must be unique. Raw bytes are opaque:
non-UTF-8 and NUL bytes are legitimate byte observations. JSON decoding applies
only to the template and original upstream report bytes. Payloads must have
exact type `bytes`; subclasses, bytearrays, memoryviews, strings, streams,
handles, generators and callbacks are rejected. Booleans cannot serve as ints.

Every template `OK` read must either contain both claimed `sha256` and integer
`byte_count`, or contain null for both placeholders. Both claims must match the
computed SHA-256 and length of the exact bytes; contradictions are rejected and
never overwritten. Only paired null placeholders can be filled. An empty
successful payload is legitimate and receives SHA-256 of empty bytes.

Failed reads must contain `sha256=null`, `byte_count=0`, `status="FAILED"` and
their original failure codes. No raw record may bind a failed read, including
an empty byte record. Failure codes and supplied timestamps remain unchanged;
failure never proves worker absence. Missing bytes for an `OK` read yield
`RAW_READ_MISSING` / `INCOMPLETE`, with no assembled request and both predecessors
`NOT_EVALUATED`. Unexpected raw keys, conflicting claims and bytes for failures
yield `INVALID`. Missing template reads/frames or missing workers are never
added; when the remaining read bindings are complete, the exact defective
structure reaches B3-B2 for its original diagnostics.

`upstream_reports` is omitted/None, or an exact finite list of exact dictionaries:

```python
{"route_index": 0, "kind": "ADAPTER_D2B2", "payload": b"original JSON report"}
```

There is at most one original report per route. Kind must be `ADAPTER_D2B2`,
`PROBE_B3A` or `BRIDGE_H0`, and must equal that route's verification validator.
Dictionary/list subclasses, repeated containers anywhere within or across the
three input objects, and cycles are rejected before copying. Immutable byte
objects may be shared; sharing identical bytes establishes no independence.
All indexing and output ordering is deterministic and independent of submission
order. Explicit `None` has the same meaning as an omitted upstream list.

## Accounting and capacity

Every read is at most 65,536 bytes. Combined admission is at most 8,388,608 bytes,
inclusive. The exact budget formula, which includes indexing/record overhead,
is:

```text
sum(read payload byte length + 64 + ASCII byte length of path_id)
+ sum(original report byte length + 64 + ASCII byte length of kind)
```

The fixed 64 bytes per record accounts for its index and fixed record overhead;
this is a deterministic logical admission budget, not a claim about Python heap
size or RSS. Upstream bytes participate in the same budget and are additionally
subject to B3-B3's 8,388,608-byte original-report cap. At most 12,288 read records
and two upstream records can be admitted. Admission is atomic: failed admission
returns empty custody, rather than an ambiguous partial index.

The template separately retains B3-B2's 8,388,608-byte accounted JSON budget,
200,000 nodes, depth 24, string limit 65,536 and integer bounds. Original-container
alias checks also bound each input tree to 200,000 nodes and depth 24; decoding
and filling placeholders do not relax predecessor budgets. The reference
requires 1–64 registered PIDs and 2–32 frames. Actual missing frames are retained
as an incomplete supplied capture. The limits intersect: 64 PIDs with few frames
and 32 frames with a small roster are supported, while 64 PIDs times 32 frames
times two complete routes exceeds the unchanged predecessor node cap. That
case is `INVALID / INPUT_CAP_EXCEEDED`.

The human-readable report has a fixed 8,388,608-byte serialization budget. If the
read digest table would exceed it, classification becomes `INVALID` with
`INPUT_CAP_EXCEEDED`, the table is omitted explicitly (`read_summary_omitted`),
and its count, custody and both original predecessor reports remain available.
The finite predecessor/frame/import limits bound the remaining report envelope.

## Byte custody and detachable outputs

The returned `AssemblyReport` is frozen and contains an immutable serialized
canonical JSON string, its computed `.sha256`, an immutable `ByteCustody`, and
the optional assembled request serialization. `to_dict()` and `to_request()`
return newly decoded, detached copies; request access returns None when binding
was impossible. Mutating either copy or the caller's original input cannot
change the stored result. The request contains full caller-supplied metadata;
it is a deliberate in-memory evidence API, separate from the sanitized report.

Custody contains tuple indexes of frozen `ByteEvidence` records. Each record
holds a key, exact immutable `bytes`, digest and byte-count property. Accessors
`custody.read_bytes(route, frame, pid, path_id)` and
`custody.upstream_bytes(route, kind)` check the stored SHA-256 before returning
the exact immutable bytes. `read_keys` and `upstream_keys` are immutable tuples;
no mutable dictionaries escape. Byte evidence and report representations hide
payloads. The caller receives custody with the result and controls its lifetime;
there is no persistence, filesystem custody or signed attestation.

Once index admission succeeds, bytes remain available even if later binding,
upstream validation or a predecessor verdict is unfavorable. Observations rejected
by admission itself are not retained. Custody includes exact original upstream
JSON bytes, including original whitespace, while import reports record their
raw and canonical hashes distinctly. If template rejection prevents import,
admitted original reports still have visible identifiers, counts and hashes,
with `import_evaluation=NOT_EVALUATED` and a null import report. The B3-B3 import's own historical custody
limitation remains verbatim in that embedded report; the assembler's separate
custody object supplies the retention that B3-B3 itself does not provide.

The sanitized report includes symbolic read indexes, lengths, digests, request
and route/capture/provenance/verification hashes, safe origin enums, submitted
upstream report identifiers/import results, fixed trust fields and the entire
original B3-B2/B3-B3 reports with their exact canonical hashes. It does not
serialize read bytes, original upstream bodies, arbitrary provenance labels,
OS paths or exception text. Supplied timestamps may appear in predecessor
reports; no timestamp is generated.

## Predecessor and upstream lineage

The complete assembled request is detached independently for
`integrate_native_evidence(..., callbacks=())` and
`correlate_native_semantics(..., callbacks=())`. The latter's embedded
predecessor and hash must equal the direct integration result exactly. Both
entire original reports are retained in separate fields, along with their
canonical SHA-256 values. Original diagnostic lists are unchanged, including
`SOURCE_DISAGREEMENT`, `PID_REUSE`, reparenting, namespace/mount/descriptor
contradictions, missing-worker coverage, duration/gap/skew and verification
failures.

No verification summary is ever edited, even to compute an apparently helpful
`capture_sha256` or `report_sha256`. With placeholders, callers must supply
their capture hash over the eventual completed capture. A hash over the
unfinished template produces B3-B2's original `DIGEST_INVALID`, which remains
visible. A supplied summary is always `CALLER_ASSERTED`.

Original upstream bytes, when present, go through B3-B3 `import_upstream_report`.
The assembler requires the summary's raw-report hash, schema, validator,
original outcome and all three reason lists to match exactly, plus compatible
declared origin. A mismatch is invalid; rejection of the original envelope is
invalid. Accepted original reports with unfavorable verdicts retain those
verdicts and their `UPSTREAM_INVALID` / `UPSTREAM_INCOMPLETE` markers. Original
envelope inspection is not verifier replay: it checks B3-B3's accepted envelope
and selected nested invariants, not every possible original-data contradiction.
Neither a valid envelope nor matching hashes establish authenticity of supplied
claims. There is no supported lossless conversion, so `converted_capture=null`
and `conversion="UNSUPPORTED_LOSSLESS_CONVERSION"` remain explicit. No descriptor,
mount, clock or timing facts are manufactured from an original report.

The isolated unsupported-conversion marker does not lower the assembler's
classification when separately supplied capture metadata and raw reads are
complete. Any other unfavorable upstream-import reason does. Missing original
reports have custody `NOT_SUPPLIED` and binding `UNAUTHENTICATED_NOT_CHECKED`;
even matched originals have binding
`HASH_AND_ENVELOPE_MATCH_CALLER_ASSERTED`, with `source_authenticated=false`.
Identical original reports on both routes never demonstrate independence.

## Classification and scientific boundary

Assembler-only reasons live in `assembly`; top-level reasons combine them with
both predecessor verdicts and unfavorable upstream-import reasons. Reason
vocabularies are sealed, sorted and unique. Unknown internal codes map to
`REASON_CODE_INVALID` without echoing arbitrary text. Severity precedence is
`INVALID > INCOMPLETE > ASSEMBLED_NONQUALIFYING`. The last classification
requires B3-B2 and B3-B3 consistency and subordinate
`STABLE_IDENTITY_CORRELATED`. A non-evaluated/non-correlated semantic stage can
never improve the overall result.

For example, different volatile `pids/<pid>/identity` bytes may produce B3-B3's
subordinate stable-identity correlation. Both exact payloads/digests remain in
custody, B3-B2's `SOURCE_DISAGREEMENT` remains unchanged, and overall classification
is `INCOMPLETE`. Stable namespace bytes do not receive that volatile exception.

All paths preserve fixed nonqualifying trust claims:
`production_memory_qualification=INCONCLUSIVE`,
`production_chronological_peak=NOT_OBSERVED`, `memo_cap=256`,
`INDEPENDENCE_NOT_ESTABLISHED`, unauthenticated origins, unproven worker absence,
and `atomic_snapshot=false`. Self-consistency of supplied bytes establishes
neither source authenticity nor production RSS qualification, continuous process
coverage, an atomic snapshot or a production chronological peak. Sequential
aggregate observations cannot be relabeled as any such claim.

## Regression and workflow status

The new unit suite uses artificial in-memory bytes and literal original-format
adapter, probe and bridge envelopes. It covers complete injected/native-shaped
assemblies; raw custody, hashes, immutability and leakage; volatile and stable
divergence; claimed-digest/length corruption; missing/extra/duplicate reads and
frames; predecessor diagnostics; failed reads; exact temporal and payload
boundaries and +1; capacity intersections; exact types, aliases, recursion/nodes
and duplicate JSON; upstream binding, rejection, original unfavorable verdicts
and unsupported conversion; deterministic serialization and sealed severity.

Module-local stubs reject bridge acquisition and preview calls without changing
global filesystem/clock hooks. In-memory code inspection checks forbidden I/O
and acquisition names and the allowed dependency namespace. The suite itself
does not open source files; immutable dependency hashes and branch/HEAD/status
guards belong to the orchestrator.

No pytest command, build, benchmark or application execution was performed by
the implementer. The orchestrator must first obtain zero BLOCKER/MAJOR/MINOR
findings, then execute the exact 14-suite `TARGETED_VERIFICATION` command in
`.ai/TASK.md`, preserving the 2,884-test predecessor baseline with more than
2,884 total passes and zero failures/skips. Only the three permitted new files
are implementation outputs. Review-pass and independent-audit classifications
remain pending; no staging, commit, branch change or push is authorized here.
