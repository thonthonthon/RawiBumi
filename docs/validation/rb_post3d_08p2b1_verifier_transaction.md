# RB-POST3D-08P2-B1 verification transactions

Implementation is ready for orchestrator verification. Codex ran no tests,
builds or benchmarks. New wall timings and observed after-counts are pending
measurement; no measured speedup is claimed.

## Authority and call graph

| Boundary | Calls and authority | Reuse |
| --- | --- | --- |
| Producer execution | `authorize_selected_assumptions` and producer physics cache validate execution witnesses | Never supplies verifier acceptance |
| Persistence pre-write integrity | `persist_run_package` checks context, then attribution sources on its shallow copy | One transaction, exact canonical bytes |
| Embedded disk verification | Persistence invokes `verify_run_package`, rereading stored package | Fresh transaction, independent of pre-write checks |
| Independent package verification | Each `verify_run_package` checks context, physical artifacts and attribution | Fresh per invocation; source check reuses only that invocation's context validation |
| Standalone context verification | `verify_detailed_context` → `_verify_assumption_inputs` → `validate_numerical_assumption_acceptance(use_cache=False)` → `evaluate_numerical_assumption_acceptance` | Always fresh |
| Standalone attribution verification | `verify_attribution_sources` applies its historical schema/snapshot/numerical-selection condition and verifies context | Always independently validates when required |

The profile's twelve context checks across two runs comprise four package,
two persistence and six attribution-source checks. Three checks per run are
proven duplicates: the attribution check following each pre-write or disk
context check. Identical package hashes across invocations supply no authority.

## Implementation and scientific binding

A private context manager captures full canonical context bytes, completes
`verify_detailed_context`, confirms unchanged bytes, then yields a scope-local
private scoped result. It compares full canonical bytes again at reuse and rejects
changed inputs. Its `finally` block expires the result on success or exception.
No global state, persisted authorization receipt, caller-controlled public
verification flag, approximate key or ID-only binding is introduced.

Only the two artifact paths receive this result through the private keyword
`_context_check`. Existing positional arguments and payload keywords are preserved.
The package path still calls the module-level `verify_attribution_sources` hook,
including its streaming resource lifetime and fail-closed exception behavior.
The private keyword accepts only the exact internal result type, rejecting arbitrary
callables. Standalone calls omit it and perform fresh verification. Attribution
payload, module/solver identities, topology/parameterization membership,
physical source bindings, diagnostics and energy checks continue unchanged.
Persistence adds storage references after source verification; the embedded disk
verifier creates its own scoped result over the resulting persisted context.

The binding includes every input, snapshot, witness/provenance field, identity,
limitations and reference. Selected revisions, evidence digests, B1 relationships,
B2 tolerance and real-kernel acceptance, strict scientific opt-in, fail_closed,
Level-2 fidelity, v0.2 source fingerprints and historical v0.1/B3C dark behavior
retain their existing validators. `_verify_assumption_inputs` still explicitly
uses `use_cache=False`. No Level-3 activation, numerical solver edit or new
production dependency is made.

This assumes the established synchronous verifier model: private in-process
functions are trusted code; persisted package data is untrusted. The scoped result
confers no execution witness or permission. Cross-thread mutation of verifier
locals is not a newly supported interface.

## Before/after evidence and measurement handoff

Historical evidence is the P1 staged JSON and P2A hotspot/caller reports. P1
records 1-module warm independent verification at 12.440 s and 10-module at
12.667 s, uninstrumented. Instrumented warm verifier times were 12.541/12.677 s.
Do not combine these timing populations or derive speedup from wrapper counts.

| Metric (one selected assumption with attribution) | Before, observed/source traced | After, expected from source; pending runtime measurement |
| --- | --- | --- |
| Fresh B2 in pre-write integrity alone | 2 | 1 |
| Fresh B2 in persistence including embedded verifier | 4 | 2 |
| Fresh B2 per independent disk verifier | 2 | 1 |
| Context checks per execution plus explicit verifier | 6 | 3 |
| Duplicate context checks per execution plus explicit verifier | 3 | 0 |
| One-module independent verifier wall time | 12.440 s warm uninstrumented | Pending |
| Ten-module independent verifier wall time | 12.667 s warm uninstrumented | Pending |

The regression fixture separately counts full `_evaluate_numerical_candidate_physics`
entries, fresh requests and context wrapper calls. Expected cold execution is
three actual physics computations: one producer miss, one pre-write validation,
one independent disk validation. Two subsequent package-verifier invocations
must each add one real computation even when producer caches are warm or forbidden.
Tests also exercise full-context change/expiry, standalone freshness, rehashed
package corruption, established worker protections, Level-3 denial, legacy
payload/dark behavior and serial/spawn solver parity. Positive tests use real
acceptance and reuse existing fixture/assertion helpers.

The orchestrator should run the new targeted file, B2/B3B/B3C/B3D1/B3D2, P1
benchmark contract tests, and the accepted Phase-6.9/6.10 selection. Capture
before/after counts and instrumented versus uninstrumented wall times for
**only 1 and 10 modules**, using the existing harness child case interface and
unchanged historical baseline. Do not run its default staged entrypoint, which
can attempt 50 modules. Missing timings remain pending, not an implementation
failure. The P1 document records the completed 50-module timing pass and its
600-second full-case timeout without claiming completed instrumentation.

No Huawei pilot readiness, physical-yield validation or numerical speedup is
asserted. Acceptance of the current repair remains pending orchestrator execution.

## Review repair and verification status

The BLOCKER hook bypass is repaired without editing the Phase-6.10 tests.
The MAJOR corruption assertions now require specific scientific diagnostics
from both standalone context and package verification, with regenerated run
identity/input hashes and reproducibility bindings. Foreign attribution is
exercised by a changed module source hash, rather than a storage-reference hash.
An explicit historical v0.1 dark package round trip is added. Existing B3D2
worker, Level-3 and solver parity tests remain in the orchestrator selection
without importing them for duplicate collection. The historical harness command
and review-response summary are retained in P1. No tests or benchmarks were
run during this repair; all runtime results and after timings remain pending.

## Review round 2 test repair

The supplied `full_tests_round_2.txt` records 1676 passed, 8 skipped and one
failure in 2119.82 s. The foreign-attribution regression failed during fixture
payload copying, before invoking verification: `deepcopy(replay_stream())`
attempted to append into a sealed `ElectricalIntervalStore`. The test now uses
the existing `DetailedDCAttributionResult.replay()` compatibility API, which
validates the original payload and returns an isolated, fully decoded document.
It still corrupts the module source hash and requires the specific
`attribution module/solver binding mismatch` rejection after real context
acceptance. No production behavior or rejection assertion changed in this
repair. Codex executed no tests or benchmarks; rerun results and 1-/10-module
after timings remain pending. The saved full-suite result does not establish
acceptance of this repaired test.
