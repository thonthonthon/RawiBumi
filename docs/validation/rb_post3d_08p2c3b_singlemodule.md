# C3-B single-module feasibility: blocked

No production optimization was made. Requirement 2 cannot be satisfied for
endpoint-state reuse under the existing runtime model contract. This is the
task's permitted precise-blocker outcome, not implementation or performance
qualification. Only this document and the authorized regression file are added.

## Source-level stages

Complete implementations inspected: `string_iv.py`, `dc_attribution.py`,
`module_iv.py`, and `module_series_adapter.py`. Mandatory C3-A JSON, audit,
50-module hotspots and B2 hot-path documentation were also inspected.

| Stage | Exactly one module versus multiple modules |
| --- | --- |
| Validation | Circuit identity, polarity, enabled status, exact model coverage, identity hashes, supported domains and configuration remain necessary. |
| Domain | Minimum supported ceiling is the sole model ceiling; finding a ceiling does not locate Isc. |
| Isc | `_solve_string_isc` evaluates zero and ceiling, validates the bracket, then bisects with the same stopping conditions. A protected nonlinear module still needs the root solve. |
| Voc | Assembly calls `_string_state_at_current` at zero again and checks positive Voc. |
| Sampling | Each original `isc * (index / (sample_count - 1))` point is evaluated; sample zero repeats zero and the last sample repeats Isc. Raw module states survive string endpoint voltage clamping. |
| MPP candidates | Global selection and `_local_mpp_candidates` use stored samples, with original ties, tolerances and sorting. No electrical evaluation can be removed here. |
| Refinement | No continuous candidate refinement exists. |
| Final state | Sample states already contain module and protected-substring operating states; no extra electrical reconstruction exists. |
| Serialization | Physical, scientific, execution and state payloads/hashes and canonical curve validation remain required. Single-module output is still a string contract. |

`_string_state_at_current` evaluates each ordered model, adds voltage starting
at `0.0`, and constructs module power and provenance-bound state in series
order. `_evaluate_module` validates current, calls V(I), normalizes returned
substring state and propagates failures. One-module aggregation reduces the
loop length, not the required physical domain or represented search space.
Bypassing normalization or returning standalone module IV would change contracts.

## Concrete candidate and blocker

The concrete candidate is direct reuse of the zero-current state already
evaluated in `_solve_string_isc`, for Voc and sample zero. For a deterministic,
unchanged model it would remove two evaluations with identical arguments,
without changing bisection, represented currents, arithmetic or MPP search.
The converged Isc state is another repeat, but iteration exhaustion returns an
unevaluated midpoint; it cannot always supply a reusable endpoint.

However, `SeriesModuleOperatingModel` declares `voltage_at_current` as an
arbitrary callable returning a mapping. Its docstring and
`_validate_module_models` require neither determinism nor freedom from side
effects. Frozen model fields do not freeze the callable's captured state.
`_evaluate_module` deliberately invokes that authority on every request and
wraps later exceptions. Replacing second/third zero calls with an earlier
success can suppress an error or change returned values. The new regression
wraps real Phase-6.6 physics with a callable rejecting the second or third zero
request and pins current failure propagation. It does not mock acceptance.

Real adapter closure behavior and B2's exact-keyed branch holder explain the
observed repeat equality, but do not establish purity for every model accepted
by this assembler. Model ID strings are caller-supplied, not purity proofs.
Claude's plan suggests assuming adapter determinism is sufficient; repository
contract evidence does not support extending that assumption to arbitrary
accepted callers. A material compatibility/purity decision requires escalation
under AGENTS.md. No new admission contract, dependency or independent solver
has been introduced. Generic exact-current caching is also outside task intent.

## Counts and numerical/attribution evidence

No operations changed: before and after are the same source algorithm. The
new tests pin three zero requests and the exact 25 sampled current requests
using real uniform and shaded modules at 25 and 45 degrees C. They compare
complete repeated assembly results including samples, bypass states, MPP and
all serialized fingerprints without tolerance relaxation. These are baseline
regressions, not a before/after optimized algorithm comparison or reduction.

Historical C3-A evidence at baseline `3873f0f`: 31 assemblies, 4,302 string
states, 93 repeats (2.16%), 5,562 module evaluations, and zero additional
electrical MPP/refinement/reconstruction evaluations. Zero overflow was recorded.
Backend hash: `2c4b02e1235128b6a53b58ca5f5c7d8267f30eabe6e277d0233841d8d98d6f2e`.
Attribution hash: `e00c5c8e3a817d4f8febaac49b2ccd2d9b40980a816305b5c91e8228991b8850`.
These are historical control/observer equivalence, not fresh C3-B results.
No cross-instance equivalence was proven.

U retains area-weighted uniform irradiance and temperature; N retains its
unprotected common supported domain and unavailable status; B retains actual
protected regional physics. `evaluate_independent_module_bases` constructs
separate models and `optimize_independent_module` uses the unchanged assembler.
No basis/status, baseline/counterfactual power, mismatch/bypass semantics,
module binding, fingerprint or independent authorization path changes.

## Verification and limitations

Codex ran zero tests, builds, simulations or benchmarks, as instructed.
New tests are pending orchestrator execution. Existing Phase-6.5/6.6/6.7,
Phase-6.9 attribution, B2, historical hash and authenticated Level-2 package
verification/unsupported-assumption denial suites remain necessary verification;
they are not claimed covered or passed by the new blocker regressions.
Requirement 9 has no work reduction to assert on this outcome. Full fourteen-item
optimization equivalence coverage is deferred because no optimization exists.
Prior review artifacts concern earlier tasks and contain no unresolved applicable
BLOCKER/MAJOR requiring an out-of-scope production edit.

Recorded B2 baseline: 10-module warm execution 37.997 s; 50-module warm
execution 141.981 s; warm execution plus verification 149.332 s. The initial
target is 127.783 s. No new uninstrumented measurement or speedup is claimed.
There is no production change to benchmark on this blocker path. Human-operated
future measurements must use the unchanged 08P1 harness. No 190-module
simulation or Huawei qualification is claimed.
