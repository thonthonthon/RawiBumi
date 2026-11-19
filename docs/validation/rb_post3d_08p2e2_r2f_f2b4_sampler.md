# F2-B4-D1 injection-only process RSS validator

This is synthetic code only, not a live collector. D2 real-reader and D3
production qualification remain separately gated. No actual measurement,
production workload, simulation, holder-release observation, or cache-policy
change is performed by this component. The branch-current memo cap stays 256.

The implementation is scoped to predecessor HEAD
`f7391dc06901e2f826cdea9980af7d0a1052a12b` on
`ai/rb-post3d-08p2-e2-r2a-memo-observe`.

The only public function is
`assess_injected_capture(provider_input) -> dict`, in
`scripts/benchmarks/rb_post3d_08p2e2_r2f_f2b4_sampler.py`.
It consumes supplied dictionaries and raw strings; it does not discover
processes, read files, sample clocks, or launch processes. No CLI is provided.

D1's `PROCESS_RSS_SAMPLE_COMPLETE` is independent of F2-A's
`OBSERVATION_COMPLETE`, F2-B1 comparison, and F2-B2's `FAKE_INPUT_ONLY`
acceptance. It says only that the supplied synthetic sampled series satisfies
this process-only contract. Source declarations are unverified assertions.
A valid seal establishes deterministic content integrity, not authenticity.
Sequential RSS sums are intervals, never instantaneous observations, and do
not bound a true continuous peak. VmHWM is never summed. Cgroup current and
peak counters are diagnostics only and are never combined with RSS.

## Frozen contract and implementation notes

The following schema was frozen by the read-only planner before implementation.
Any later contract change requires a version bump. Closed-object shape/type
errors use SCHEMA_INVALID (unknown keys use UNKNOWN_FIELD); configuration value
constraints use CONFIGURATION_INVALID. S0 failures stop immediately; S1 section
failures stop that section and skip S2–S4. Once S2 begins, independent invalid
and incomplete evidence is retained; INVALID always wins. Cgroup errors do
not erase independently eligible per-frame RSS diagnostics.

Process maxima in the process summary use eligible frame observations.
The VmHWM monotonicity guard also checks verified reads of ineligible frames.
Sequence/time validation never repairs order: after an order failure, the
previous greatest structurally valid sequence/time remains the validation
boundary, so a later record cannot manufacture an ordered applied journal.
Frames use a two-pointer sweep over the applied event journal; source lists
are never sorted or mutated. Empty rosters yield frame-only EMPTY_ROSTER
ineligibility and no manufactured zero. A malformed read is skipped, while its
raw input remains sealed in provider_input. Frame ineligibility codes describe
RSS eligibility; cgroup reasons appear independently in the run verdict.

The optional cgroup diagnostic file names are input `memory_current` and
`memory_peak`; normalized output keys are `memory_current_bytes` and
`memory_peak_bytes`. Process summary keys are `pid:starttime_ticks`; boot
identity is enforced against the capture clock and retained in provider_input.
The normalized `memory_events` diagnostic exposes the recognized low, high,
max, oom, oom_kill and optional oom_group_kill counters. Future raw counter
names are retained in provider_input and checked for decreases/disappearance,
but are not promoted to trusted output keys (including names containing
`peak`). This also enforces the frozen output naming rule.
Raw hashes are SHA256 of the exact UTF-8 supplied strings, including truncated
text. Failed files and absent optional files have null raw hashes.

## Verification status

Regression tests are supplied in
`tests/unit/test_rb_post3d_08p2e2_r2f_f2b4_sampler.py`. They include hand-computed
inline and pool sums, PID reuse, negative lifecycle/identity/ordering/window
cases, cgroup isolation, input caps, strict JSON types, parser robustness,
immutability, independent sealing/reconstruction, and guarded import/call API
checks. No tests, benchmarks, builds, or live probes were executed by the
implementer. The orchestrator must obtain independent review PASS before
running the targeted new tests and the existing F2-A/B1/B2/B3 regression
collection, report actual counts and zero skipped, and inspect scope/guard
hashes. The historical 613-test count has not been reverified here.

No F2B4_D1_FAKE_INJECTION_CODE_ACCEPTED or production qualification decision is
claimed by this implementation. Archive review and independent orchestrator
verification remain required by TASK.md.

## 1 Module and API
**Imports and dependencies**
- Only the 3 allowed new files.
- The module imports exactly `hashlib`, `json`, `re` and `from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2a_observer as f2a`.
- No other import anywhere, including inside functions.
- No `__main__` block, no top-level expression calls, and no module state mutated at call time.
- From f2a, use ONLY `parse_stat`, `parse_status`, `parse_smaps_rollup`, `parse_memory_events` and `EvidenceError`.
- Never use F2-A reconcile/compare/seal/canonical_bytes/digest/identity helpers. Never use F2-B1/B2/B3, engine.* or shading.*.
- Never emit OBSERVATION_COMPLETE, COMPARABLE_FAKE_OBSERVATIONS, FAKE_INPUT_ONLY, INVALID_EVIDENCE or ATOMIC_SNAPSHOT. The only exception is text echoed inside provider_input.

**Public API**
- `assess_injected_capture(provider_input) -> dict` is the only public function.
- It never raises for any Python object, never mutates its input, and works only on its own deep copy.

**Public constants**
- `SCHEMA = "rawibumi.process-rss-capture.f2b4.v1"` and `RESULT_SCHEMA = SCHEMA + ".result"`.
- `INVALID_CAPTURE`, `INCOMPLETE_CAPTURE`, `PROCESS_RSS_SAMPLE_COMPLETE`.
- `PHASES = (setup, producer, attribution, persistence, verification, teardown)`.
- `POOLS = (parent, producer, attribution)`.
- `REASON_CLASSES` (code → INVALID or INCOMPLETE), `WARNING_CODES`, and the caps.

**Canonical bytes and sealing** (implemented locally, same format as F2-A)
- Canonical bytes = `json.dumps(v, sort_keys=True, indent=2, allow_nan=False, ensure_ascii=True) + "\n"`, encoded UTF-8.
- `integrity = {"algorithm": "sha256", "scope": "canonical result excluding integrity", "sha256": hex}`.
- `input_sha256` = sha256 of the canonical bytes of the copied input.

**Caps**
- MAX_DEPTH = 32.
- MAX_NODES = 1,000,000. Check a container's length BEFORE traversing or allocating.
- MAX_TEXT_BYTES = 262144 UTF-8 bytes per string, keys included.
- MAX_TOTAL_TEXT_BYTES = 33554432.
- MAX_INTEGER_BITS = 63 (by bit_length).
- MAX_EVENTS = 4096, MAX_FRAMES = 4096.
- MAX_IDENTITIES = 128 (parent plus workers).
- MAX_READS_PER_FRAME = 128.
- MAX_WHITESPACE_RUN = 64.

## 2 Stages
**S0 copy**
- Accept only exact built-in types: dict with str keys, list, str, int, float, bool, None.
- Tuples, subclasses, non-str keys, NaN/Inf, cycles and lone surrogates → INVALID INPUT_NOT_JSON.
- Any cap exceeded → INVALID INPUT_CAP_EXCEEDED.
- On failure, provider_input, input_sha256, run_id and source_type are all null, and analysis stops.

**S1 root**
- Every object is CLOSED. An unknown key → INVALID UNKNOWN_FIELD.
- A missing key, wrong type, bool-as-int, float-as-int, or an empty/whitespace label → INVALID SCHEMA_INVALID.
- A label is a str whose strip() is non-empty. Integers are checked with `type(x) is int`.
- Validate the sections independently in this order: root, schema, source_type, run_id, clock, source_provenance, capture, configuration, topology. Within a section, stop at the first failure, giving one reason per failing section.
- Any S1 INVALID skips S2–S4: frames=[], processes={}, phase_coverage={}, cgroup_observations=[]. INCOMPLETE capture flags are still recorded.

**S2, S3, S4**
- S2 processes events, S3 frames, S4 run-level coverage.
- In S2 and S3, an invalid record or read is recorded and skipped (not applied), and processing continues. All reasons are kept.
- Any unexpected exception after S0 → the only reason is INTERNAL_VALIDATION_FAILURE at "root". provider_input is retained and no exception text is included.

## 3 Input schema (exact root keys)
**schema, source_type, run_id**
- `schema` must equal SCHEMA, else SCHEMA_VERSION_MISMATCH.
- `source_type` must be "INJECTED_SYNTHETIC". "REAL_PROCFS" or anything else → SOURCE_TYPE_NOT_ACCEPTED.
- The output echoes source_type verbatim if it is either of those two strings, else null. It never relabels.
- `run_id` is a label.

**clock**
- `{kind: "CLOCK_MONOTONIC", unit: "ns", domain_id, host_id, boot_id, pid_namespace_id}`; the last four are labels.
- A wrong kind or unit → CLOCK_DOMAIN_INVALID.

**source_provenance**
- `origin_attestation` must be "UNVERIFIED", else SOURCE_TYPE_NOT_ACCEPTED.
- Labels: kernel_release, os_description, workload_id, input_id, configuration_id, source_tree_fingerprint, sampler_code_version, registration_protocol.
- `requested_worker_counts: {producer: int≥0, attribution: int≥0}` is informational only and is NEVER used as a roster.

**capture**
- Fields: `declared_event_count` (int≥0), `declared_frame_count` (int≥0), `truncated` (bool), `sampler_termination` ("NORMAL" or "ABNORMAL"), `capture_completeness_declared` (bool).
- truncated → INCOMPLETE EVIDENCE_TRUNCATED.
- ABNORMAL → SAMPLER_TERMINATED.
- capture_completeness_declared false → CAPTURE_DECLARED_INCOMPLETE.
- A declared count different from the actual list length → DECLARED_COUNT_MISMATCH at root.capture.

**configuration**
- `max_read_skew_ns`: int≥0. `max_frame_gap_ns`: int≥1.
- `phase_plan`: exactly the keys parent, producer, attribution. Each is a list of unique PHASES names; parent must be non-empty.
- `cgroup_requirement`: "CORROBORATION_REQUIRED" is the only accepted value.
- `smaps_rollup_policy`: "NOT_SAMPLED" or "OPTIONAL_DIAGNOSTIC".
- A bad value → CONFIGURATION_INVALID.

**topology**
- `execution_mode`: "inline" or "spawned".
- `parent_identities`: exactly 1 entry `{pid: int≥1, starttime_ticks: int≥0, boot_id: label, ppid: int≥0}`.
- `actual_workers`: entries `{pid, starttime_ticks, boot_id, parent_pid: int≥1, pool: "producer" or "attribution"}`.
- `registration_coverage`: "DECLARED_COMPLETE" or "NOT_ESTABLISHED".
- TOPOLOGY_INVALID when:
  - there is not exactly 1 parent;
  - a worker's parent_pid differs from the parent's pid;
  - inline mode has any worker or a non-empty producer/attribution plan;
  - spawned mode has zero workers;
  - in spawned mode, a pool's plan is non-empty but the pool has no workers, or vice versa.
- A duplicate (pid, starttime) → DUPLICATE_IDENTITY.
- A boot_id different from clock.boot_id → CLOCK_DOMAIN_MISMATCH.
- More than 128 identities → INPUT_CAP_EXCEEDED.
- registration_coverage NOT_ESTABLISHED → INCOMPLETE REGISTRATION_NOT_ESTABLISHED.

**events and frames lists**
- Both must be lists within their caps, else INPUT_CAP_EXCEEDED.

**Record shapes**
- Identity reference: exactly `{pid, starttime_ticks, boot_id}`. Its key string is "pid:starttime_ticks".
- Event:
  - START and PHASE: `{sequence: int≥0, time_ns: int≥0, clock_domain_id, kind, identity, phase}`.
  - EXIT: the same fields without phase.
  - Any other kind, including CREATE/RELEASE, → SCHEMA_INVALID.
- FileRead is exactly one of:
  - `{result: "OK", start_ns, end_ns, text}`
  - `{result: "TRUNCATED", start_ns, end_ns, text}`
  - `{result: "FAILED", start_ns, end_ns, error}`, where error is one of ENOENT, ESRCH, EACCES, EPERM, EIO.
- Frame: `{frame_sequence, clock_domain_id, frame_kind, frame_start_ns, frame_evaluation_ns, frame_end_ns, expected_live: [identity], process_reads: [ProcessRead], cgroup: CgroupObs or null}`.
  - frame_kind must be "BOUNDED_SEQUENTIAL_RSS_FRAME". Anything else → FRAME_KIND_NOT_ACCEPTED, and the frame is ineligible.
- ProcessRead: `{identity, stat_before, status, smaps_rollup (FileRead or null), stat_after}`.
- CgroupObs: `{clock_domain_id, cgroup_version, cgroup_path, memory_events, cgroup_procs, memory_current, memory_peak}`.
  - cgroup_version must be 1 or 2; any other value → SCHEMA_INVALID.
  - cgroup_path is a label starting with "/".
  - memory_events and cgroup_procs are FileReads; memory_current and memory_peak are FileRead or null.

## 4 Events (S2, in list order; location "event:<index>")
**Per-event checks** (every failure except SEQUENCE_GAP skips the event)
- Schema → SCHEMA_INVALID or UNKNOWN_FIELD.
- Wrong clock_domain_id, or an identity boot_id that differs from the clock → CLOCK_DOMAIN_MISMATCH.
- sequence ≤ the previous structurally valid event's sequence → SEQUENCE_ORDER_INVALID.
- First sequence ≠ 0, or a jump → INCOMPLETE SEQUENCE_GAP. The event is still applied.
- time_ns lower than the previous event's → CHRONOLOGY_INVALID. Equal times are allowed.
- Identity not in the topology → UNROSTERED_PROCESS.

**Lifecycle semantics**
- LIFECYCLE_CONTRADICTION:
  - a duplicate START, or a START after the identity's own EXIT;
  - a worker START while the parent is not live;
  - any event after the parent's EXIT;
  - PHASE or EXIT on a non-live identity;
  - a PHASE equal to the current phase.
- PID_REUSE_OR_IDENTITY_RACE:
  - a START whose pid is held by another live identity;
  - a START whose starttime_ticks is ≤ that of an earlier lifetime with the same pid.
- A START or PHASE naming a phase outside that pool's plan → PHASE_PLAN_CONTRADICTION.
- A parent EXIT while workers are still open is applied anyway.
- Output of this stage: start_ns, exit_ns and the ordered phase segments for each identity.

## 5 Frames (S3, in list order; window [a=frame_start_ns, b=frame_end_ns], closed)
**Frame-level checks**
- Schema or unknown field → skip analysis.
- Clock mismatch → CLOCK_DOMAIN_MISMATCH, skip.
- frame_sequence is checked like event sequences: SEQUENCE_ORDER_INVALID, or INCOMPLETE SEQUENCE_GAP.
- Not a ≤ frame_evaluation_ns ≤ b → READ_WINDOW_INVALID, skip.
- a ≤ the previous analyzed frame's b → FRAME_CHRONOLOGY_INVALID, skip. Frames may not touch.
- More than 128 reads → INPUT_CAP_EXCEEDED, skip.
- An applied START or EXIT with time in [a,b] → INCOMPLETE ROSTER_CHANGED_IN_FRAME.
- An applied PHASE with time in [a,b] → INCOMPLETE AMBIGUOUS_PHASE_FRAME.

**Liveness**
- possibly_live: start ≤ b, and either no exit or exit ≥ a.
- live (defined only when no lifecycle event falls in the window): start < a, and either no exit or exit > b.

**expected_live**
- Each entry gets the identity schema, boot, duplicate and roster checks (SCHEMA_INVALID, CLOCK_DOMAIN_MISMATCH, DUPLICATE_IDENTITY, UNROSTERED_PROCESS).
- An entry that is not possibly_live → ROSTER_CONTRADICTION.
- If live is defined and some live identity is missing from expected_live → INCOMPLETE ROSTER_INCOMPLETE.

**ProcessRead j — structure** (location "frame:i/read:j[/file]")
- Schema → SCHEMA_INVALID or UNKNOWN_FIELD; the read is skipped.
- Boot mismatch → CLOCK_DOMAIN_MISMATCH.
- Not in the topology → UNROSTERED_PROCESS.
- Same identity read twice in the frame → DUPLICATE_IDENTITY.
- Not possibly_live → ROSTER_CONTRADICTION.

**ProcessRead j — read windows** (any violation → READ_WINDOW_INVALID)
- Every file has start ≤ end.
- File order is stat_before, status, smaps_rollup (if non-null), stat_after, with each previous end ≤ the next start.
- All files lie inside [a,b].
- The previous read's stat_after end ≤ this read's stat_before start.

**ProcessRead j — policy and file results**
- smaps_rollup_policy NOT_SAMPLED with a non-null smaps → SMAPS_POLICY_VIOLATION.
- A mandatory file FAILED → INCOMPLETE PROCESS_READ_FAILED.
- A mandatory file TRUNCATED → INCOMPLETE RAW_READ_TRUNCATED.
- Every OK text is still parsed.

**stat checks**
- Parse error → RAW_TEXT_MALFORMED.
- stat pid ≠ identity pid → IDENTITY_CONTRADICTION.
- starttime ≠ identity, or stat_before and stat_after disagree on (pid, starttime) → PID_REUSE_OR_IDENTITY_RACE.
- ppid ≠ expected, or stat_before and stat_after ppid differ → IDENTITY_CONTRADICTION. Expected ppid is the topology ppid for the parent and the parent's pid for workers.
- State Z, X or x → PROCESS_READ_FAILED, and status memory is NOT parsed.

**status checks**
- A run of more than 64 consecutive `\s` characters → RAW_TEXT_MALFORMED, checked BEFORE calling f2a.
- An f2a INCONSISTENT_COUNTER → COUNTER_INCONSISTENT.
- Any other EvidenceError, or a ValueError/TypeError/OverflowError → RAW_TEXT_MALFORMED. Never echo the detail.
- Any parsed value ≥ 2**63 → RAW_TEXT_MALFORMED.
- Pid or PPid mismatch → IDENTITY_CONTRADICTION.
- VmHWM below this identity's previous maximum → COUNTER_INCONSISTENT.
- VmSwap > 0 → INCOMPLETE OOM_OR_SWAP_OBSERVED.

**smaps checks** (OPTIONAL_DIAGNOSTIC policy)
- FAILED or TRUNCATED → warning OPTIONAL_SMAPS_UNAVAILABLE only.
- OK → same whitespace guard and error mapping as status.
- Swap > 0 → OOM_OR_SWAP_OBSERVED.
- smaps Rss never replaces VmRSS.
- kB means 1024 bytes.

**Verified reads**
- A read is VERIFIED only if all 3 mandatory files are OK, parse, are identity-consistent, are not exiting, and carry no INVALID reason at that read.
- Member byte values are non-null only for VERIFIED reads.

**Missing reads, empty roster, skew**
- If live is defined, a live identity with no read → INCOMPLETE PROCESS_READ_MISSING.
- An empty live roster → frame-level code EMPTY_ROSTER only: no run reason and no zero.
- read_skew_ns = max(stat_after.end) − min(stat_before.start).
- Skew above max_read_skew_ns → INCOMPLETE READ_SKEW_EXCEEDED. Skew exactly equal to the bound is OK.

**Eligibility and aggregates**
- A frame is ELIGIBLE only if all of these hold:
  - it was analyzed and its frame_kind was accepted;
  - no lifecycle or phase event falls in its window;
  - the live roster is non-empty and equals expected_live;
  - there is exactly one VERIFIED read per live identity and no other read;
  - no INVALID reason sits in the frame outside the cgroup;
  - skew is within the bound.
- Cgroup results, swap/OOM and warnings never affect eligibility.
- An eligible frame's aggregate is the sum of VmRSS bytes over exactly the live roster. Otherwise the aggregate is null, never 0.
- smaps_rss_diagnostic_bytes is set only when the frame is eligible and every member has a parsed smaps.

**Cgroup — presence and provenance** (every frame)
- null → INCOMPLETE CGROUP_CORROBORATION_INCOMPLETE.
- Clock mismatch → CLOCK_DOMAIN_MISMATCH.
- cgroup_version 1 → CGROUP_CORROBORATION_INCOMPLETE.
- A path different from the first observed path → INCOMPLETE CGROUP_HIERARCHY_AMBIGUOUS.
- Windows lie inside [a,b], are ordered memory_events, cgroup_procs, memory_current, memory_peak, and touching is allowed. Any violation → READ_WINDOW_INVALID.
- memory_events or cgroup_procs FAILED or TRUNCATED → CGROUP_CORROBORATION_INCOMPLETE.

**Cgroup — memory_events**
- Parsed with f2a.parse_memory_events; an error → RAW_TEXT_MALFORMED.
- oom, oom_kill or oom_group_kill > 0 → OOM_OR_SWAP_OBSERVED.
- max > 0 → CGROUP_LIMIT_EVENT.
- A counter that decreases or disappears relative to the previous OK observation → COUNTER_INCONSISTENT.

**Cgroup — cgroup_procs**
- Lines must be ASCII `[0-9]+`, ≥1 and unique, else RAW_TEXT_MALFORMED. An empty text means an empty set.
- When live is defined:
  - extra pids → INCOMPLETE CGROUP_NOT_ISOLATED;
  - roster pids missing → CGROUP_HIERARCHY_AMBIGUOUS;
  - an exact match → PROCS_MATCH_ROSTER.

**Cgroup — memory_current and memory_peak**
- FAILED or TRUNCATED → warning CGROUP_DIAGNOSTIC_UNAVAILABLE.
- OK text must be ASCII `[0-9]+` with an optional trailing `\n`, else RAW_TEXT_MALFORMED.
- Diagnostic only: never added to RSS and never treated as a frame sample.

## 6 Run level (S4)
**Lifecycle**
- Parent missing START or EXIT → INCOMPLETE PARENT_LIFECYCLE_GAP.
- A worker that never started, has no EXIT, or has 0 eligible observations → WORKER_LIFECYCLE_GAP.
- No eligible frames at all → NO_ELIGIBLE_FRAMES.

**Gaps** (computed over ELIGIBLE frames, in order)
- first a − parent start > max_frame_gap_ns → SAMPLE_GAP at run:initial.
- next a − previous b > max_frame_gap_ns → SAMPLE_GAP at frame:<next index>.
- parent exit − last b > max_frame_gap_ns → SAMPLE_GAP at run:terminal.
- A gap exactly equal to the bound is OK.

**Phase coverage**
- Each (process, phase entered) with no eligible observation → PHASE_COVERAGE_GAP at process:<key>/phase:<p>.
- Each (pool, phase in its plan) with no eligible frame containing a member of that pool in that phase → PHASE_COVERAGE_GAP at pool:<pool>/phase:<p>.

**Outcome**
- Any INVALID reason → INVALID_CAPTURE.
- Otherwise, any INCOMPLETE reason → INCOMPLETE_CAPTURE.
- Otherwise → PROCESS_RSS_SAMPLE_COMPLETE, which also requires a non-null sampled maximum.
- Warnings never change the outcome.
- SHARED_PAGES_MAY_BE_COUNTED_REPEATEDLY is emitted at "run" only when some eligible frame has 2 or more members.

## 7 Codes (each code has one fixed class)
- **INVALID:** INPUT_NOT_JSON, INPUT_CAP_EXCEEDED, SCHEMA_VERSION_MISMATCH, SOURCE_TYPE_NOT_ACCEPTED, SCHEMA_INVALID, UNKNOWN_FIELD, CONFIGURATION_INVALID, TOPOLOGY_INVALID, CLOCK_DOMAIN_INVALID, CLOCK_DOMAIN_MISMATCH, DUPLICATE_IDENTITY, UNROSTERED_PROCESS, SEQUENCE_ORDER_INVALID, CHRONOLOGY_INVALID, FRAME_CHRONOLOGY_INVALID, FRAME_KIND_NOT_ACCEPTED, READ_WINDOW_INVALID, LIFECYCLE_CONTRADICTION, PHASE_PLAN_CONTRADICTION, PID_REUSE_OR_IDENTITY_RACE, IDENTITY_CONTRADICTION, ROSTER_CONTRADICTION, RAW_TEXT_MALFORMED, COUNTER_INCONSISTENT, SMAPS_POLICY_VIOLATION, INTERNAL_VALIDATION_FAILURE.
- **INCOMPLETE:** EVIDENCE_TRUNCATED, SAMPLER_TERMINATED, CAPTURE_DECLARED_INCOMPLETE, DECLARED_COUNT_MISMATCH, SEQUENCE_GAP, REGISTRATION_NOT_ESTABLISHED, PARENT_LIFECYCLE_GAP, WORKER_LIFECYCLE_GAP, ROSTER_CHANGED_IN_FRAME, ROSTER_INCOMPLETE, PROCESS_READ_MISSING, PROCESS_READ_FAILED, RAW_READ_TRUNCATED, READ_SKEW_EXCEEDED, SAMPLE_GAP, NO_ELIGIBLE_FRAMES, AMBIGUOUS_PHASE_FRAME, PHASE_COVERAGE_GAP, OOM_OR_SWAP_OBSERVED, CGROUP_LIMIT_EVENT, CGROUP_CORROBORATION_INCOMPLETE, CGROUP_HIERARCHY_AMBIGUOUS, CGROUP_NOT_ISOLATED.
- **Warnings:** SHARED_PAGES_MAY_BE_COUNTED_REPEATEDLY, OPTIONAL_SMAPS_UNAVAILABLE, CGROUP_DIAGNOSTIC_UNAVAILABLE.

**Entry formats**
- A reason is `{code, class, location}`; reasons are deduplicated and sorted by (code, location).
- A warning is `{code, location}`; warnings are deduplicated and sorted.
- Locations: root, root.<section>, event:<i>, frame:<i>, frame:<i>/read:<j>, frame:<i>/read:<j>/<file>, frame:<i>/cgroup, frame:<i>/cgroup/<file>, process:<key>, process:<key>/phase:<p>, pool:<pool>/phase:<p>, run, run:initial, run:terminal.

## 8 Output (exact top-level keys)
**Envelope** (these 4 constants appear in EVERY result)
- production_memory_qualification = "INCONCLUSIVE".
- production_chronological_peak = "NOT_OBSERVED".
- holder_release = "NOT_ESTABLISHED".
- actual_measurement_performed = false.

**Top-level keys**
- schema, input_schema, source_type, origin_attestation = "UNVERIFIED", outcome, the 4 envelope constants above.
- run_id, input_sha256, provider_input (a deep copy, or null).
- reasons, invalid_reason_codes, incomplete_reason_codes, warnings.
- frames, sampled_rss, phase_coverage, processes, cgroup_observations, caveats, integrity.

**frames[i]**
- index, frame_sequence, frame_kind, frame_start_ns, frame_evaluation_ns, frame_end_ns.
- live_roster (sorted keys, or null), read_skew_ns, eligible, ineligibility_codes.
- members, in read order: `{identity, pool, phase, read_status ("VERIFIED" or "NOT_VERIFIED"), vmrss_bytes, vmhwm_bytes, vmswap_bytes, smaps_rss_bytes, smaps_swap_bytes, raw_sha256 (per file, or null)}`.
- sampled_aggregate_rss_bytes, aggregation_status ("BOUNDED_SEQUENTIAL_RSS_SUM" or "NOT_AGGREGATED"), smaps_rss_diagnostic_bytes.

**sampled_rss**
- statistic = "MAX_OF_BOUNDED_SEQUENTIAL_VMRSS_SUMS".
- frame_semantics = "BOUNDED_SEQUENTIAL_RSS_FRAME".
- metric_status = "COMPLETE_SAMPLED_SERIES" only when the outcome is COMPLETE; otherwise "DIAGNOSTIC_ONLY".
- comparability = "NOT_COMPARABLE".
- bound_claim = "NO_BOUND_ON_TRUE_INSTANTANEOUS_PEAK".
- sampled_max_rss_bytes and sampled_max_frame_index (the lowest index that attains the max).
- eligible_frame_count and attempted_frame_count.
- max_eligible_read_skew_ns, configured_max_read_skew_ns, clock_kind.

**phase_coverage**
- `{pools: {pool: {phase: "OBSERVED", "UNOBSERVED" or "NOT_APPLICABLE_BY_DECLARED_WORKLOAD"}}}`, covering all POOLS × PHASES.

**processes** (one entry for every topology identity)
- pool, pid, starttime_ticks, start_ns, exit_ns, entered_phases, observed_phases, eligible_observation_count.
- max_observed_vmrss_bytes and max_observed_vmhwm_bytes. VmHWM is never summed.

**cgroup_observations**
- frame_index, cgroup_version, cgroup_path, memory_events, cgroup_procs_pids, memory_current_bytes, memory_peak_bytes.
- isolation: PROCS_MATCH_ROSTER, NOT_ISOLATED, HIERARCHY_AMBIGUOUS or NOT_EVALUATED.
- A fixed semantics string saying these values are never added to RSS.

**caveats**
- A fixed constant list covering these points:
  - synthetic data, and not a live collector;
  - frames are not atomic and give no bound on the true peak;
  - shared pages, so the RSS sum is not unique memory;
  - VmRSS/VmHWM inaccuracy;
  - cgroup values are never combined with RSS;
  - holder release is not established;
  - the data's origin is unverified.

**Naming rule**
- Outside provider_input, no output key may contain "peak" except production_chronological_peak and memory_peak_bytes.

## 9 Doc
- Restate sections 1–8, including the reason table, precedence, envelope and limitations.
- State that D1 is independent of F2-A COMPLETE, of F2-B1 and of F2-B2 FAKE_INPUT_ONLY.
- State that D2/D3 remain gated, that this is not a live collector, and the version-bump rule.
