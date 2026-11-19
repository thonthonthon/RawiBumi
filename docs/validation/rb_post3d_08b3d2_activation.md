# RB-POST3D-08B3D2 controlled activation

Implementation and regression fixtures are provided for orchestrator execution.
No tests, builds, benchmarks, manual numerical runs or Huawei pilot were executed
by the implementer. No runtime PASS, measured timing, persisted round-trip success
or B3D2 acceptance is claimed in this document. These remain required verification
results, not assumptions inferred from source inspection.

## Production authorization chain

Frozen selection replay now performs structural membership validation for every
selected v0.2 record, including unused/dark selections. This is the separation
explicitly approved in the binding traceability document §5.1: frozen replay
transports scientific inputs and does not authorize module execution. The
historical constructor, zero-argument replay, frozen fields and canonical bytes
remain unchanged. Unselected numerical records do not confer permission or block
an unrelated legacy Level-0 request.

Dispatch supplies its own configuration and actual frozen selection to
`authorize_selected_assumptions`. That boundary resolves exact revisions, builds
one shared B3B context, constructs module witnesses, compares them against those
independently supplied inputs, and validates complete numerical scientific
acceptance. It runs before availability fallback. Requested/resolved selected
fidelity must be Level 2, fallback must be fail_closed in selection and
configuration, and scientific allow_synthetic_regions must be literal true.
Execution options do not supply that authority. Level 3 and numerical cell scope
remain denied.

Module pinning accepts an optional `authorization_witness`, preserving legacy
calls. Five-key payload bytes and the historical scientific_input_sha256 algorithm
are unchanged. Zero-argument module replay validates exact payload membership
and the complete gate. Numerical inputs cannot pass the historical v0.1 evidence
binding validator. Source-backed Level-2 capability resolution retains its
historical branch and manufacturer/trusted classifications.

The gate reconstructs the witness rather than trusting its boolean. A typed
`NumericalAssumptionAuthority` is returned only after all checks; the regional
contract revalidates its witness and exact selected evidence digest. A manually
constructed authority cannot bypass scientific acceptance. Backend/attribution
parent transport independently compares each witness against dispatch's expected
configuration/selection before module replay. A foreign self-consistent witness
cannot authorize another run.

## Source, asset and physics checks

Existing B1 typed evidence, exact selected module/topology/parameterization
revisions, declaration/consistency digests, asset metadata linkage, source registry
identity and original/retained/assumption source relationships are reconstructed
by the existing selected-witness and B2 validators. Missing source records and
revision or digest substitution fail closed. No source filenames are opened.
The supported SourceRecord fingerprint mode remains available when original PAN
bytes are unavailable; no original bytes are fabricated or claimed independently
possessed. No evidence schema or public package field is added.

B2 uses the installed production evaluator and unchanged G1 and secondary gate
tolerances. The submitted consistency record must equal recomputation. Actual
region state construction and Phase-6.6 series-module assembly participate in
acceptance and execution. No region equations, current/voltage conventions,
reverse domain, bypass behavior, DC accounting or attribution equations change.

A producer-only LRU retains at most 16 validation results, keyed by immutable
configuration/selection, selected revision and installed acceptance/kernel policy
identity. Entries larger than the established 512-KiB witness limit are not
retained. Policy, witness equality and exact membership are checked independently
of cached physics. No global authorization boolean or unbounded cache is used.
The existing B2 numerical calculation cache also remains bounded. For 190 modules
sharing one selected definition, the parent needs one physics acceptance per
configuration/selection identity; each spawned worker independently validates
that identity once. This is a count of acceptance work, not a measured pilot cost.

## Serial and worker integrity

The existing immutable witness transport is retained through backend, region
parameterization and U/N/B attribution. Serial interval entry and both worker
initializers require expected context and module revision membership, then full
scientific acceptance. The historical abbreviated dark-only attribution path
retains its explicit numerical-selection denial.

Assumed process results are wrapped in `NumericalWorkerResult`, carrying the
parent-selected context fingerprints and instance/revision membership digest.
The full shared witness context is sent only in worker initialization, not in
every interval result. The parent rejects
missing or foreign return bindings before accepting a result. This envelope is
internal transport only and is removed before scientific output hashing; legacy
worker return shapes remain unchanged. Pools still use the established bounded
submission and cancellation behavior. NumericalAssumptionInputError and
SnapshotWitnessError propagate through numerical and downstream dispatch cleanup
instead of being converted by broad ValueError handling to ordinary execution
unavailability. No worker integrity failure invokes legacy fallback.

## Producer and independent verifier

For v0.2 attribution the producer hashes the exact `_selected_witness_payload`
canonical bytes, matching the independent verifier's existing contract. Legacy
source_module_input_hashes retain their existing scientific_input_sha256 bytes.
No selected digest is redefined as a historical v0.1 scientific hash.

Execution limitations retain global engine limitations first, then each active
numerical revision's complete authenticated declaration slice in revision order.
Identical limitations from different revisions are not deduplicated. Existing
execution identities hash these limitations and the verifier derives the same
list, rejecting omission, substitution or reordering after superficial rehashing.

The existing persist_run_package and verify_run_package entry points still invoke
independent context and attribution verification. `_verify_assumption_inputs`
always uses B2 use_cache=False and does not consult producer validation authority.
Fresh rejection or unavailable kernels reject verification. Independent context
and attribution boundaries may each repeat the calculation: their independent
checks are retained rather than sharing producer state. No new cross-call verifier
cache is introduced. RB08B-B3-SD1 applies: installed-verifier scientific consistency
is checked; historical producer build attestation is not established.

## Small execution and negative test fixtures

`test_rb_post3d_08b3d2_activation.py` combines the existing real B2 candidate with
the established canonical detailed fixture. It reduces the scene to one module,
three assumed equivalent regions, one string/MPPT and one diffuse-weather
interval. Module quality override is zero under the existing unknown-quality
contract. It uses canonical geometry, weather/SPA/thermal processing, real
regional series solver, actual attribution and canonical package persistence.
A forwarding spy records real regional solver participation without replacing
its calculation. The tests require finite selected power, attributed source hash
parity, derived limitations and independently verified persisted output.

A second actual run enables both process-worker pools and requires exact
serial/parallel physical and attribution parity and independent package
verification. Timing is printed around the small serial execution and package
verification. The independently observed initial timing is recorded below as PRE-REPAIR evidence; the first repair review measured 50.3 s; timing after the review corrections remains pending.

Negative fixtures cover strict opt-in and misplaced execution options, source/PAN
binding, topology/parameterization revision substitutions, consistency corruption,
a real secondary-gate reverse-domain failure, boolean/missing witnesses, foreign
configuration/selection/module membership, worker initialization and return
binding failures, integrity propagation without fallback, numerical cell scope,
Level 3, explicit_lower_fidelity, persisted changed/removed/reordered limitations,
rehashed forged evidence and fresh verifier failure despite producer caching.
Existing legacy snapshot, source-backed adapter, reverse-voltage, dark-only
attribution and Phase-6.10 canonical serial/process/package regressions are reused
without modifying their assertions.

## Verification status and remaining work

Static AST parsing and git diff --check are implementation checks only. The
orchestrator must run the new suite and relevant B1/B2/B3 and Phase-6.9/6.10 suites,
record exact commands/results/timing, and obtain independent review. Acceptance
requires the actual small package round trip and all negative/legacy checks to
pass. A failed round trip is not partial activation acceptance.

Hashes establish selected scientific content binding, not signatures or human
identity. Source-record-only PAN provenance does not establish original-byte
possession. No manufacturer region validation, physical-yield calibration,
historical software build attestation, annual acceleration or Huawei 600-second
resource target is claimed. Browser request construction is outside this task;
the canonical path must receive an explicitly opted-in scientific configuration.
Remaining Huawei prerequisites include independently reviewed passing activation
verification, actual supported provenance and selected assumptions, engineering
pilot readiness, and separately authorized resource measurement. No weather data
was acquired, manufacturer input changed, dependency introduced or Git staging,
commit, push, branch switch or history rewrite performed.


## B3D2-R regression repair — PRE-REPAIR evidence

The independently observed initial checkpoint had **55 passed** B3D2 tests,
**358 passed / 8 skipped** Phase-6.9/6.10 regressions, and **20 failed / 444 passed**
earlier-stage regressions. The real one-module, three-region, one-interval
execution plus independent verification round trip took approximately **46.7 s**.
The persisted package verified independently and producer/verifier attribution
fingerprints agreed. These are PRE-REPAIR observations, not final-tree results.
The complete original IDs, assertions and actual traceback evidence are retained
in `.ai/validation/b3d2_r_failure_inventory/{failure_inventory.md,pytest.log,junit.xml}`.
The inventory was read before edits. The table uses its failure numbering and
records every ID, including duplicate coverage imported by B3C.

Classification keys: I = INTENTIONAL_ACTIVATION_CHANGE;
F = INVALID_OLD_FIXTURE; O = VALIDATION_ORDER_REGRESSION.
No separate ACTUAL_BEHAVIOR_REGRESSION was found beyond the ordering defect.
An I classification means the final authorized activation intentionally changes
that expectation; F and O are not expected failures.

| # | Exact test ID (under `tests/unit/`) | Class | Original assertion → observed result; retained property and correction |
|---|---|---|---|
| 1 | `test_rb_post3d_08b2_region_physics.py::test_acceptance_does_not_authorize_pin_or_public_builder` | I | Public builder schema_version error → NumericalAssumptionInputError/B3 authorization boundary. Retain unwitnessed public-kernel denial with its scientific exception. |
| 2 | `test_rb_post3d_08b3b_snapshot_witness.py::test_opt_in_and_self_consistent_external_witness_never_execute[None]` | I | Unconditional authenticated-execution denial → requires scientific opt-in. Keep absent opt-in denial, on real B2 fixture. |
| 3 | `test_rb_post3d_08b3b_snapshot_witness.py::test_opt_in_and_self_consistent_external_witness_never_execute[False]` | I | Unconditional authenticated-execution denial → requires scientific opt-in. Keep false opt-in denial, on real B2 fixture. |
| 4 | `test_rb_post3d_08b3b_snapshot_witness.py::test_opt_in_and_self_consistent_external_witness_never_execute[True]` | F/I | Unconditional denial under true opt-in → B1 linkage failure intercepted it. Real B2 fixture now replays under explicit opt-in; paired missing-witness and foreign expected-context negatives remain. |
| 5 | `test_rb_post3d_08b3b_snapshot_witness.py::test_shared_bytes_across_distinct_module_snapshots_and_foreign_membership` | F | Second-module denial → B1 linkage failure. Reseal actual B2 assets/provenance for both revisions; shared bytes remain identical objects, authorized replay succeeds and foreign membership/missing witness still deny. |
| 6 | `test_rb_post3d_08b3b_snapshot_witness.py::test_schema_valid_selected_v02_dispatch_denied_without_downgrade[False-fail_closed]` | F/I | Dispatch unconditional denial → B1 linkage failure. Real B2 fixture with false opt-in stays blocked, no fallback, no resolved fidelity. |
| 7 | `test_rb_post3d_08b3b_snapshot_witness.py::test_schema_valid_selected_v02_dispatch_denied_without_downgrade[False-explicit_lower_fidelity]` | I | Dispatch unconditional-denial message → require fail_closed policy. Real B2 fixture retains explicit_lower_fidelity denial and no downgrade. |
| 8 | `test_rb_post3d_08b3c_context_propagation.py::test_worker_boundary_denies_invalid_context[foreign_module-_initialize_interval_worker]` | O/F | Foreign-module SnapshotWitnessError → B1 physics/linkage exception before membership. Check all foreign keys first, with B2-valid worker fixture. |
| 9 | `test_rb_post3d_08b3c_context_propagation.py::test_worker_boundary_denies_invalid_context[foreign_module-_initialize_attribution_worker]` | O/F | Foreign-module SnapshotWitnessError → B1 physics/linkage exception before membership. Same repair for attribution initializer. |
| 10 | `test_rb_post3d_08b3c_context_propagation.py::test_pickle_shared_identity_is_membership_only` | F | Pickle membership validation then unconditional replay denial → B1 linkage error at validation. Real B2 input validates/replays; shared context identity survives pickle and foreign post-pickle membership denies. |
| 11 | `test_rb_post3d_08b3c_context_propagation.py::test_public_kernel_cannot_authorize[missing-build_phase66_series_module_operating_model]` | I | Adapter schema_version wrapper → B3 authorization-boundary NumericalAssumptionInputError. Keep missing authority, boolean and false-opt-in negatives on B2 input. |
| 12 | `test_rb_post3d_08b3c_context_propagation.py::test_public_kernel_cannot_authorize[missing-assemble_nonuniform_module_iv]` | I | Assembly schema_version wrapper → B3 authorization-boundary NumericalAssumptionInputError. Same public-boundary negatives. |
| 13 | `test_rb_post3d_08b3c_context_propagation.py::test_public_kernel_cannot_authorize[missing-build_pvsyst_region_electrical_states]` | I | Regional builder schema_version wrapper → B3 authorization-boundary NumericalAssumptionInputError. Same public-boundary negatives. |
| 14 | `test_rb_post3d_08b3c_context_propagation.py::test_serial_attribution_plumbing_forwards_same_witness` | F | Plumbing sentinel/identical witness → B1 linkage intercepted sentinel. Real B2 fixture, real replay, no mocked physical PASS; sentinel remains after authority checks. |
| 15 | `test_rb_post3d_08b3c_context_propagation.py::test_public_dispatch_denied_without_downgrade[fail_closed]` | F/I | Imported fail_closed dispatch denial → B1 linkage failure. Same repair as #6, retains fail-closed/no-downgrade intent. |
| 16 | `test_rb_post3d_08b3c_context_propagation.py::test_public_dispatch_denied_without_downgrade[explicit_lower_fidelity]` | I | Imported explicit_lower_fidelity denial message → require fail_closed policy. Same repair as #7. |
| 17 | `test_rb_post3d_08b3c_context_propagation.py::test_shared_context_without_large_copies` | F | Imported shared-context assertion → B1 linkage failure. Same real two-revision fixture and membership coverage as #5. |
| 18 | `test_rb_post3d_08b3c_context_propagation.py::test_backend_plumbing_forwards_original_witness` | F | Backend forwarding sentinel → B1 linkage failure. Real B2 fixture reaches the forwarding spy with original witness identity. |
| 19 | `test_rb_post3d_08b3c_context_propagation.py::test_repeated_interval_entries_do_not_revalidate_schemas` | F | Repeated-interval sentinel and zero schema calls → B1 linkage failure. Validate real B2 boundary before counting warm interval schemas; retain foreign transport rejection after cache hits. |
| 20 | `test_rb_post3d_08b3d1_verification.py::test_execution_stays_disabled` | I | Freeze/replay unconditional denial → no exception (structural replay). Retain pin-without-witness denial and assert structural replay grants no opt-in authority. |

### Exact fixes and negative coverage

`validate_execution_transport` now checks mapping structure, foreign witness and
revision keys, independently expected context, exact revision membership, witness
structure/digests and full payload/source membership for every module before
entering its scientific acceptance pass. A foreign key always raises
SnapshotWitnessError; new tests count zero authorization/B2 calls for both valid
and B1-invalid physics fixtures. No ID-only asset lookup replaces content checks.

The selected and regional boundaries bind assets first, then pass an authority
candidate to the existing contract validator. That validator still reconstructs
and validates the entire witness; constructing NumericalAssumptionAuthority or
passing a boolean never grants authority. Each regional/selected operation now
invokes the full authority validator once instead of twice. A forwarding counter
regression verifies both paths using the real evaluator.

A bounded structural cache stores immutable configuration and selected-policy
bytes under the complete immutable witness context/revision/policy identity.
Every authorization call still parses and checks opt-in, Level-2 and fail_closed;
no execution permission is cached. This removes the full configuration/selection
deep copy previously done for each warm authority call. Oversized contexts bypass
the cache. Producer physics caches remain separate from fresh verifier acceptance.

B1-only witness fixtures remain for the unchanged structural tests. The tests
exercising execution transport now construct real B2 candidates and mutate only
the fault under test. The second module has separately revision-bound evidence,
resealed topology/parameterization digests and its own assumption SourceRecord;
no physical acceptance PASS is mocked. Nonboolean scientific options, foreign
configuration/selection, forged/missing witnesses, revision/source tampering,
invalid consistency and secondary physics, invalid worker context, Level-3 and
explicit_lower_fidelity remain negative cases. B3D2 corruption fixtures are
constructed outside expected-exception blocks and structural/scientific failures
are asserted with specific exception types and diagnostics. The first repair
review identified three incorrect expectations; the follow-up uses the observed
SnapshotWitnessError/residual diagnostic for selected consistency corruption,
NumericalAssumptionInputError/Phase66SeriesModuleAdapterError current-ceiling
diagnostic for the secondary gate, and ElectricalShadingContractError/residual
diagnostic for persisted forged evidence. The latter is structural evidence
validation, outside the R/M/P solver wrappers governed by traceability F-007;
no production exception contract is changed.

Each selected corruption now also checks freezing: structural faults reject with
an exact exception type and diagnostic, while the secondary numerical fault
freezes structurally and rejects at scientific authorization. Fixture construction
still occurs outside the expected-exception block.

The real-solver serial/process runs, independent persisted-package verification,
source fingerprint equality and regenerated-hash tampering rejection remain in
the activation suite. Historical dark-only and v0.1 tests remain intact. The
older B3D1 reviewer major about six diagnostics is already reflected in the
checkpoint's typed opt-in and specific source/revision/hash assertions; none of
those six is in the supplied current 20-failure inventory.

### Revalidation cost and pending measurements

No tests, builds or benchmarks were executed by Codex. Final-tree measurements
are pending the independent orchestrator. The completed real-run fixture prints
`one_interval_run_validation_counts`, `independent_package_validation_counts`
and elapsed seconds, counting witness authorizations, producer B2 requests,
fresh verifier B2 requests and actual full physics evaluations. Producer caches
are cleared before this measured run. The run counters include canonical
persistence verification; the independent-package delta isolates the subsequent
standalone verifier. These counters are observations to be populated by execution,
not an asserted runtime result.

Static call-path accounting: a numerical backend interval checks transport once
and invokes regional authorization once per module; attribution checks transport
once and authorizes each real counterfactual regional build. Worker return binding
adds a transport check in the child and one in the parent. Every transport pass
revalidates witness membership for every module before B2 authorization. Warm
producer physics requests reuse the existing full-input/kernel-bound cache;
the independent verifier always requests use_cache=False per selected revision
at each context verification boundary. Package verification currently verifies
context directly and again through attribution; both fresh checks are retained.
The new direct regression requires one authority evaluation per regional call.
The repeated-interval regression counts zero warm schema revalidations.

Remaining avoidable work includes repeated payload serialization/hash/membership
checks, independent context and attribution verifier recomputation, and uncached
large-context replay/deep copies. Safe removal of these boundaries would require
broader review; this repair does not cache mutable worker transport or arbitrary
permission. The initial round trip was approximately 46.7 s PRE-REPAIR; the first
repair review measured 50.3 s. No final speedup, full regression PASS, annual acceleration
or Huawei resource-target compliance is claimed. Claude/orchestrator must run
all directly affected tests, B1–B3D2, Phase-6.9/6.10, actual small package verification
and independent final-diff review, and report final counts, measurements and risks.


### First repair review and follow-up status

The supplied independent review (`.ai/reports/claude_review_1.json`) observed
**427 passed** across B1/B2/B3A/B3B/B3C/B3D1 and confirmed that all 20 inventory
regressions were resolved. B3D2 had **52 passed / 3 failed**, caused by incorrect
exception expectations; production rejected all three tampering cases. The real
Level-2 execution and persisted independent verification still completed, with a
**50.3 s** round trip. These observations precede the follow-up assertion and
freeze-coverage changes and do not establish a final-tree PASS.

The review measured **21 witness revalidations and 1 producer B2 request** for the
one-interval run. Fresh verifier request/full-evaluation counts were not supplied
in the review; the orchestrator must capture the existing counter output. Repeated
witness validation remains a performance limitation. A shared witness is still
authorized once per transport key after all structural checks; the optional
review suggestion to deduplicate this work is deferred, with no permission cache
introduced. Phase-6.9/6.10 was still running when the review verdict was issued
and remains unconfirmed for the repaired tree. The orchestrator must rerun B3D2
and the required regression/package checks after these changes. Codex ran no
tests, builds or benchmarks in this follow-up.
