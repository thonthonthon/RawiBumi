# RB-POST3D-08B3C context propagation

B3C prepares identity-bound transport. Numerical-assumption Level-2 execution
remains unconditionally denied. This is not independent v0.2 verification,
producer software attestation, or executable readiness. Level-3 remains unavailable.

## Production call graph

`canonical.run_canonical_simulation` calls `run_detailed_dispatch`.
Dispatch first calls the frozen selection's `record()`; selected v0.2 evidence
is denied here before runtime resolution or fallback. `_resolve` resolves frozen
assets and calls `pin_detailed_module_inputs` and
`validate_detailed_runtime_support`. `_prepare_backend` pins the same exact
module/topology/parameterization inputs for enabled module instances.

`execute_detailed_mppt_backend` replays snapshots, constructs geometry/local
irradiance histories, and calls `_ordered_interval_results` / `_evaluate_interval`.
The interval kernel calls `build_phase66_series_module_operating_model`, which
calls `build_pvsyst_region_electrical_states` and the existing
`_build_series_model_from_checked_states`. Its V(I) callback uses
`module_iv._module_state_at_current`, protected-substring and parallel-branch
kernels. General series-string IV, parallel MPPT assembly and tracker selection
are unchanged. No sampled-IV replacement, reverse-bias change, bypass-clamp
change or voltage-summation change was made.

The separate public `assemble_nonuniform_module_iv` also forwards witness
metadata to regional parameterization and preserves non-fallback errors.

## Identity and trust boundaries

`DetailedModuleInputSnapshot.witness` stays outside the five-key canonical
payload. Module bytes, scientific digests and attribution source hash fields
retain their existing definition. A shared `SnapshotWitnessContext` stores the
immutable canonical configuration and frozen selection once.

Dispatch passes its actual configuration and
`revision_store.detailed_electrical_inputs` to backend and attribution collector.
`prepare_execution_transport` compares attached witnesses against these expected
inputs using `compare_snapshot_witness_context`, then checks exact snapshot
payload membership before replay. An attached witness cannot supply its own
expected run context. Missing expected inputs fail closed.

The transport contains module witnesses, a parent-selected expected context and
a parent-selected module-instance/revision map. It contains no execution permit.
For legacy snapshots all witnesses are None. In current production a valid
numerical witness cannot reach the solver: frozen replay and snapshot replay
still deny selected v0.2 evidence. Isolated transport tests therefore explicitly
exercise plumbing rather than simulate a successful B3D authorization.

Regional entry checks exact witness/evidence/topology/definition identity when
metadata is present and then invokes unconditional numerical execution denial.
Bare booleans are rejected. Missing witnesses cannot activate execution.

## Serial and process attribution

`DetailedAttributionChunkCollector` retains expected run inputs in its internal
arguments. `execute_detailed_dc_attribution` and
`execute_detailed_attribution_pass` call `_attribution_context`, which compares
snapshots at the parent boundary and retains their witnesses alongside decoded
module inputs. `_evaluate_attribution_interval` forwards each bound witness to
`evaluate_independent_module_bases`; U/B forward it to the series adapter and N
forwards it through `build_bypass_off_module_model` to regional parameterization.
The attribution header and persisted schema do not include transport metadata.

Both spawn initializers (`_initialize_interval_worker` and
`_initialize_attribution_worker`) call `validate_execution_transport` before
installing context. Serial/worker interval entry checks the same membership.
Missing context on assumed inputs, foreign module revisions, substituted
witnesses and inconsistent expected contexts fail closed. Context is sent once
in initializer arguments, rather than with every interval. Pickle preserves
shared references inside that graph. Task exceptions propagate through futures. Initializer rejection instead surfaces
as BrokenProcessPool; dispatch classifies this as numerical_failed, losing the
original exception classification. Parent cleanup prevents finalizing that pass.

Worker checks establish consistency with the parent's selected immutable inputs.
They do not independently authenticate the origin of a serialized parent
context. A wholly caller-created self-consistent transport is not an execution
credential and still encounters unconditional kernel denial. Verifier-side
source/worker authentication is reserved for B3D.

`verify_attribution_sources` now uses the same definition resolver as dispatch:
v0.2 uses the exact evidence-bound revision and parameterization ID; v0.1 must
have a unique ID candidate whose registry key matches its revision. Ambiguous
same-ID definitions cannot silently substitute another revision. Existing
artifact callers and positional signatures remain compatible.

## Classification, scope and compatibility

`NumericalAssumptionInputError` and `SnapshotWitnessError` are re-raised before
generic ValueError wrapping in the adapter and module-IV entry and before
availability fallback in independent-module attribution. Assumed input checks
also precede the dark shortcut. Ordinary legacy solver-domain failures retain
`independent_module_iv_unavailable` and `bypass_off_domain_unsupported` behavior.

Selected v0.2 cell scope is explicitly unsupported: diagnostics require
`region_substring`. The public evidence schema is unchanged. No trusted topology
or provenance enum is promoted. Unselected v0.2 records continue to permit the
existing Level-0 behavior. Optional keyword-only additions preserve legacy calls.
Read-only inspection confirmed downstream merely replays snapshots for quality,
area and rated power; artifacts invokes the compatible attribution verifier;
design replays frozen selection; canonical delegates dispatch. These files need
no changes.

## Replay cost and caches

Three bounded per-process LRUs retain structural consistency only. Context-free
module membership tuples have 128 entries and contain no execution permit. A fresh
witness is constructed with the caller's own context on every call, including
when equal-but-distinct contexts share a cache entry. Cache values never return
a witness bound to an earlier context. Cache keys still retain context references. The context
cache has 16 entries; selected canonical module bytes have 128 entries. Keys
include the full immutable configuration and frozen-selection dataclass byte
identities, claimed digests, module revision where relevant, and
`b3c-context-structure.v1` implementation/policy identity. Inputs over 512 KiB
(combined configuration and frozen selection) bypass retention. The conservative retained context-byte bound across all three caches is
(16 + 128 + 128) * 512 KiB = 136 MiB, plus parsed structures and selected
payload projections. Shared keys commonly reduce this, but are not assumed in
the bound. The threshold is a defensive retention limit, not justified by a
measured production selection size. Oversized selections remain a performance
limitation requiring measurement before B3D activation. Shared contexts are retained
by reference, not copied for each module. No permission or physics acceptance
result is cached.

Exact byte-key equality prevents altered bytes from hitting stale entries.
Cache misses validate canonical configuration, hashes, frozen selection and
schemas. Module replay always checks outer module bytes/digest and exact selected
payload membership. Parent expected-run comparison occurs independently of cache presence.
Interval and worker checks compare the immutable parent-selected context directly,
then verify cached immutable membership and current module bytes; they do not
reconstruct or schema-validate configuration at every timestep. The serial
collector builds its transport once and rejects sampling-policy changes.
Cached parsed structures are copied before returning so callers cannot mutate
shared cache values. Repeated replay avoids reparsing the full selection and rereading
selected schemas; it still hashes/canonicalizes module payloads and validates
the denial path. Oversized inputs remain correct but do not receive this cache
optimization. Spawn processes begin with fresh structural caches.

## Verification and remaining obligations

No pytest, npm test, build, benchmark, full suite or numerical execution was run
by the implementer, as required by the task. Read-only source/diff inspection and
`git diff --check` were performed. Regression tests were authored in
`test_rb_post3d_08b3c_context_propagation.py`; execution and acceptance are the
orchestrator's responsibility. No performance timing or 190-module run is claimed.

Coverage includes legacy module bytes, real regional/series kernels, negative
voltage, public denial, fallback preservation, exact-revision resolution,
serial plumbing, both worker initializers, pickle sharing, foreign membership,
cache bounds/eviction and repeated schema-validation counts. Deterministic
initializer and serialization tests are worker-boundary tests, not complete
spawn-pool integration. The serial witness-forwarding test explicitly replaces
replay to observe plumbing and stops before numerical execution.

B3D must independently recompute B2 kernels, authenticate package inputs, check
persisted limitations, re-pin exact sources/revisions during verification,
verify worker/source identity, reject post-persistence tampering, and control
activation. None of those deferred obligations is assumed complete here.

The no-witness public regional builder retains its established validation order
and ElectricalParameterizationError schema diagnostic for v0.2 definitions.
The public series adapter and module-IV assembler wrap that diagnostic as
Phase66SeriesModuleAdapterError and NonuniformModuleIVError respectively. These
legacy ValueError types deny the call but are not non-fallback classifications.
Production transport and independent-module attribution perform their assumed
input checks before reaching this layer. Regression tests assert each exact
layer's error type and the schema diagnostic rather than claiming a non-fallback
kernel error when no witness was supplied.
Witness-bearing calls retain non-fallback integrity checks. The existing pinned
Phase-6.6 current/voltage-domain regression supplies the explicit 7.5 A / -1.5 V
reverse-bias reference; B3C tests invoke that reference regression.

Round-2 review corrections add an equal-but-distinct context identity regression
and supply all fields used by backend interval entry so its schema-validation
count test reaches the intended rejection point. These corrections have not
been executed by the implementer. The orchestrator must run targeted regressions
and the full suite against the final diff; earlier-round results are not final
verification evidence.

Before B3D attachment/activation, remaining transport work includes measuring
production selection sizes or removing the oversized-context uncached path,
reducing repeated per-interval module serialization/hash work without losing
integrity checks, preserving initializer rejection diagnostics across
BrokenProcessPool, and independently binding worker instance/revision maps to
trusted run selection. The current map derives from pinned snapshot bytes;
exact witness membership is checked separately against the frozen selection.
None of these limitations grants execution permission in B3C.

## B3C-R-SD1 legacy dark attribution repair

The confirmed eight Phase-6.10 failures began with an unconditional witness
access on historical abbreviated module inputs. Guarding that access alone
would expose later assumptions about canonical bytes, module/evidence revision
records, and regional topology. Those fixtures historically performed no
regional electrical work.

The internal attribution context now separates abbreviated inputs from standard
DetailedModuleInputSnapshot transport. Only a parameterization-only replay with
no witness can enter the compatibility path. Frozen selections, when supplied,
are checked first using the existing selected-assumption denial and selection
source bindings; referenced evidence must also satisfy its schema and registry
identity. Resolved valid v0.1 selections may use this no-work path. Missing or
invalid selected evidence is rejected, and v0.2 denial remains non-fallback.

Every interval is checked for nonempty module/region coverage and exactly zero
effective irradiance, completed dark MPPT states, and absent electrical curves.
A later illuminated chunk is rejected. The path emits the historical U/N/B
not-applicable bases and empty curve hashes without constructing witnesses or
revision maps. It runs in the parent for all worker counts; worker initialization
explicitly rejects dark-only contexts. Standard snapshot transport, regional
validation ordering, exact revision checks, and final physical source/coverage
binding remain unchanged. This is zero-electrical-work attribution compatibility,
not acceptance of abbreviated numerical-region inputs.

New regression cases are intended to verify parent-only serial/parallel equivalence with diagnostics,
a later illuminated chunk, selected v0.2 and stripped evidence, missing registry
entries, missing witnesses, boolean witnesses, dark worker rejection, and foreign
parent inputs. Existing tests retain physical coverage rejection and strict
worker/context/kernel checks. The original Phase-6.10 test file is unchanged.

No tests, builds, or benchmarks were executed by the implementer, as explicitly
required by the workflow. The orchestrator must execute the affected Phase-6.10
interval suite and B1–B3C, parallel, package, and electrical regressions against
this final diff. No PASS or resolution of the eight failures is claimed from
static inspection; fresh verification and independent review remain pending.


### Round 2 review corrections and verification handoff

The five fixture failures reported in `.ai/reports/claude_review_1.json`
were corrected without changing production authorization or solver behavior:

- The later illuminated interval is passed directly to the interval evaluator
  using the context established by the first completed dark chunk. This targets
  the per-interval darkness gate instead of failing during backend freeze of an
  inconsistent inactive-dark physical state.
- Missing-registry fixtures decode immutable frozen bytes rather than replaying
  a selection whose v0.2 denial is intentional. The assertion targets the dark
  caller's selected-evidence rejection.
- Foreign-selection fixtures change source metadata in a structurally valid
  frozen bundle; the expected rejection is configuration/selection mismatch.
- Worker fixtures use a complete schema-valid configuration from the witness
  fixture, changing only string_sample_count. The scientific projection returned
  by the internal reader omits execution_options and is unsuitable as a complete
  configuration argument.

For the abbreviated zero-electrical-work path, scientific_configuration is not
cross-bound to frozen_selection. This path produces no authorization decision,
creates no witness or revision map, and performs no numerical electrical work.
The supplied frozen selection is still checked for selected-assumption denial
and invalid or unresolved evidence before darkness is considered. Configuration
binding remains mandatory on standard witnessed transport. This documents the
existing narrow behavior in response to review finding F4; it does not expand
numerical acceptance.

The previous reviewer reported the command
`pytest tests/unit/test_phase610_stage3a_interval_contract.py tests/unit/test_rb_post3d_08b3c_context_propagation.py`
with **104 passed, 5 failed**, including resolution of the eight original
Phase-6.10 failures. These are prior-round reviewer results, not verification of
this revision. The broader run was incomplete in that report. No pytest, npm
tests, builds, benchmarks, or other test suites were run by this implementer in
round 2, as required by the workflow. Static diff inspection was performed.

The orchestrator must rerun the above targeted suites and the related B1–B3C,
Phase-6.10 parallel/package, Phase-6.6 and Phase-6.9 regressions and record exact
commands and results before acceptance. All current-revision pass counts remain
pending; no PASS claim is made here.

### Round 3 review corrections and verification handoff

Review R2-F1 identified a stale scientific hash in the foreign-selection fixture.
The fixture now uses the existing B3B `_raw_frozen` helper to recompute both
payload and scientific hashes after changing source metadata. This is intended
to reach the parent foreign-context comparison rather than the frozen-selection
integrity rejection. Production context checks are unchanged.

Review R2-F4 is addressed by classifying malformed abbreviated snapshot replay
and malformed frozen-selection access as `SnapshotWitnessError`. Existing
`NumericalAssumptionInputError` and `SnapshotWitnessError` propagate unchanged.
New regression cases cover missing, noncallable and invalid snapshot replay,
and a non-mapping selection. These changes grant no authorization.

The round-2 reviewer reported this exact command:
`python -B -m pytest -p no:cacheprovider -q tests/unit/test_phase610_stage3a_interval_contract.py tests/unit/test_rb_post3d_08b3c_context_propagation.py`
with **108 passed, 1 failed**. The failure was R2-F1; all eight original
Phase-6.10 failures passed in that prior revision. The broader regression run
was incomplete. These counts are reviewer evidence for the prior revision,
not PASS evidence for the current changes.

No tests, builds or benchmarks were run by the round-3 implementer under the
explicit workflow restriction. `git diff --check` passed. R2-F2 and R2-F3 remain
verification obligations: the orchestrator must run the targeted command and
the related regression set, then record exact commands and pass/fail/skip counts
for this revision before acceptance. No current-revision PASS is claimed.
