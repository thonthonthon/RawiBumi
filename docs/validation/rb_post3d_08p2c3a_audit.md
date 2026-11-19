# C3-A exact-work audit (baseline 3873f0f)

Measurement and source analysis only. Production physics, tolerances, authorization,
B2 acceptance, and the 08P1 harness are unchanged. No C2 reuse is restored.

## Source-backed call graph and stages

`engine/simulation/detailed_backend.py:_evaluate_interval` builds Phase-6.6
series models and calls `string_iv.py:assemble_general_series_string_iv` for
physical strings. `detailed_attribution.py:_evaluate_attribution_interval` calls
`dc_attribution.py:evaluate_independent_module_bases`, which validates regional
transport, constructs fresh U/N/B models, and calls `optimize_independent_module`.
That function calls the same string assembler with a one-module solver circuit.

The complete string assembly first validates circuit/model coverage and solver
configuration. `_solve_string_isc` evaluates zero and the common minimum model
current ceiling, then bisects. It returns an evaluated midpoint on convergence,
or an unevaluated final midpoint after exhausting iterations. Assembly next
re-evaluates zero for Voc, then samples `isc * (index / (sample_count - 1))`.
`_string_state_at_current` calls `_evaluate_module` for every ordered model and
sums module voltages in series order. `_evaluate_module` checks current bounds,
calls the model V(I), and validates/normalizes the complete protected state.

MPP and local MPP candidates are selected from stored sampled points. There are
no additional electrical MPP-candidate evaluations, refinement evaluations, or
final operating-state reconstruction calls in this assembler. Samples already
retain the complete module states. Final sample string voltage is explicitly
clamped to zero; raw module states are retained. This distinction matters for
any future reuse boundary.

The Phase-6.6 adapter's V(I) calls `module_iv.py:_module_state_at_current`, then
`substring_reference.py:evaluate_protected_substring_at_current` per substring.
Each protected solve evaluates branch currents at the diode clamp, attempts an
unprotected common-voltage solution, classifies bypass, and reconstructs branch
states. `solve_parallel_branches_at_current` bisects common voltage and requests
branch I(V). `_branch_current_at_voltage_uncached` uses a regional inverse for
single-region branches, otherwise bisects series-branch voltage. Region methods
also evaluate endpoint/domain bounds and parameterization acceptance physics;
these requests are separate from string sampling. Module standalone ISC solves
occur during numerical acceptance. The audit counts these separately.

N constructs regional states with actual irradiance and temperature, derives a
common supported unprotected ceiling from branch endpoints, checks V(ceiling),
and solves unprotected branches directly on each V(I). U uses the area-weighted
`fsum` mean of effective irradiance, preserving temperature. B uses actual local
conditions. Dark bases return not-applicable; unavailable N is not a zero-power
or partial-domain MPP claim.

## Existing counts versus new measurements

The supplied 50-module cold/warm profile reports 310 assemblies (10 physical,
300 independent), 42,996 string-state evaluations (11,376 ISC and 31,620 assembly),
55,524 module evaluations, 100 basis evaluations, and 300 optimizations.
Assembly calls are 102 per assembly: one Voc plus 101 samples. ISC averages
36.70 calls per assembly. These are historical invocation counts, not a new
measurement and not evidence that all invocations are redundant. Cumulative
profile times overlap and must not be added.

## Measured size-10 evidence

The actual evidence is `.ai/validation/rb_post3d_08p2c3a/10module_equivalence.json`,
with process measurements in `10module_audit.stderr` and exit status in
`10module_audit.exit_code` in the same directory. These files were read directly;
review summaries and the earlier size-1 observation are not substitutes for this
size-10 result. The JSON records baseline `3873f0f`, workload size 10,
`completion_status: completed` and `output_fingerprints_unchanged: true`;
the recorded process exit code is 0. All 31 assembly contexts are completed.
The attribution interval starts at `2026-03-21T03:00:00Z` and is evaluated at
`2026-03-21T03:30:00Z`; the physical context does not capture interval metadata.
There is one physical 10-module string assembly and 30 independent single-module
assemblies (10 modules × U/N/B), with 10 basis evaluations and 30 optimizations.

| Measured quantity | Size-10 result |
| --- | ---: |
| String-state evaluations | 4,302 |
| Distinct exact currents, summed within assemblies | 4,209 (135–137 per assembly) |
| Exact-current repetition distribution | `{"3": 31}` |
| Distinct current values requested more than once | 62 (2 per assembly) |
| Repeated evaluations beyond the first request | 93 (3 per assembly; 2.16% of string states) |
| String-level module evaluations | 5,562 |
| Repeated identical complete module states | 120 (30 physical; 3 per independent assembly) |
| Changed module results at identical requests | 0 |
| ISC endpoint string-state evaluations | 62 |
| ISC bisection string-state evaluations | 1,078 |
| Voc string-state evaluations | 31 |
| IV sampling string-state evaluations | 3,131 (101 per assembly) |
| Additional electrical MPP-candidate / refinement / final reconstruction evaluations | 0 / 0 / 0 |
| String ISC solves | 31 (1,140 endpoint plus bisection states) |
| Standalone module ISC solves | 18 |
| Lower-level module V(I) calls | 7,054 |
| Protected-substring evaluations | 21,414 |
| Branch-current requests | 955,508 |
| Uncached branch-current invocations | 739,998 |
| Actual B2 cache-hit returns | 215,510 (also the apparent request-minus-uncached count) |

Each assembly requests zero current three times: ISC endpoint, Voc and sampling
index zero. This accounts for 62 repeated requests. Each also samples the exact
converged ISC bisection midpoint again, accounting for the other 31. These are
repeated `_string_state_at_current` requests within assemblies, not duplicated
full module-IV solves or duplicated assemblies. The 120 full module-state repeats
require the same live model, exact current and tolerance and identical serialized
returned state. Lower-level module V(I) counts include work outside string-level
module evaluations and must not be added to them as disjoint work.

### Capture completeness and process measurements

Summed per-assembly `current_overflow` and `module_overflow` are both 0.
Top-level `context_overflow`, `payload_budget_overflow` and `skipped_assemblies`
are each 0. No diagnostic truncation is reported by these counters. Retained
payload is 4,314,370 bytes against a 67,108,864-byte (64 MiB) budget.
All 30 attribution assemblies have complete source-input payloads. Thus the
recorded attribution comparisons are complete within the observer's capture
scope and anchor-only comparison scheme. Physical source inputs are absent by
design, not because of overflow; physical-versus-B evidence remains unavailable.
Any nonzero relevant overflow or skipped-assembly count in a future run must mark
cross-module evidence incomplete, with repeat/distinct counts only lower bounds.
No instrumentation redesign or new completeness field is needed for this record.

`/usr/bin/time` stderr reports maximum RSS **226,880 KB** and elapsed wall time
**5:02.70 (302.70 seconds)**. Neither value is a JSON field. These are process-level
diagnostic measurements covering fixture construction, control and profiled
observed runs, package verification and observer/profiler overhead. They are not
production timings, per-stage timings, or estimates of optimization savings.

### Scientific fingerprint comparison

Control and observed SHA-256 fingerprints match for both replay streams:

| Stream | Control and observed SHA-256 |
| --- | --- |
| Backend | `2c4b02e1235128b6a53b58ca5f5c7d8267f30eabe6e277d0233841d8d98d6f2e` |
| Attribution | `e00c5c8e3a817d4f8febaac49b2ccd2d9b40980a816305b5c91e8228991b8850` |

The diagnostic hashes `encoded(stream.replay())`, using sorted JSON keys and
lossless `float.hex()` representations, including signed zero. The observed
scientific fingerprint equality therefore supports identical serialized replay
outputs under that encoding (subject to the usual hash-collision limitation),
and identical numerical values represented in those streams. It is not a direct
byte-by-byte comparison, a separate comparison of all in-memory numerical objects,
or a claim that persisted artifact bytes or directory/timing metadata are
identical. It also does not establish physical equivalence between modules.

## Observer and execution contract

Recorded diagnostic invocation (execution belongs to the orchestrator):

```sh
python3 -B scripts/benchmarks/rb_post3d_08p2c3a_audit.py --size 10 --output .ai/validation/rb_post3d_08p2c3a/10module_equivalence.json
```

Size 50 is optional; 190 is rejected. A child has a 600-second budget and 4096 MiB
address-space cap; the parent also enforces 600 seconds. BLAS threads and fixture
workers are one. The existing authenticated Level-2 08P1 fixture and canonical
production run are used. No witness is cached, replaced or retained by the
observer. A current-thread Python profiler observes original function code,
including imported aliases, and restores profiling on all exits. It never
replaces a numerical return value. Instrumentation overhead is not a performance
measurement.

Storage admits at most 512 assemblies, 4096 exact current records and 4096
module-state records per assembly; individual state payloads are capped at
16 KiB and complete attribution input payloads at 64 KiB. A shared 64 MiB
UTF-8 byte budget bounds retained serialized current keys, module states and
source payloads across all assemblies, with a global overflow counter. Container
and small context overhead have separate entry/assembly caps and the process
address-space limit. Overflow is explicit;
repeat/distinct counts then become lower bounds. Every retained current uses
`float.hex()` and stores stage counts. Full module repeats require the same
live model, exact current/tolerance, and identical lossless complete returned
state. Nearby values are never merged. Bypass-active evaluations and observed
flag changes in request order are recorded separately: request-order changes
are not a physical transition search. Negative terminal voltage is counted.

Control and observed canonical runs use the same fixture and independently
verify persisted packages. Before each pass the harness clears only
`_validated_producer_physics` and `_cached_numerical_candidate`; other process
state may remain warm after the control pass. Counts are therefore not labelled
as a fully cold process measurement. Complete
backend and attribution replay streams are compared via lossless diagnostic
serialization SHA-256. Mismatch prevents completion. Directory/timing metadata
is excluded; scientific/provenance stream fields are included. Tests additionally
compare complete real assembler results. Execution failures and timeouts produce
an explicit blocked JSON. The recorded size-10 diagnostic completed as documented above. Contract-test
verification for this documentation change belongs to the orchestrator; Codex
executed neither tests nor the diagnostic.

## Equivalence and cache interpretation

B2 branch memo keys use exact voltage hex, voltage/current tolerances and iteration
limit within an immutable branch binding; admitted pure regional laws are checked.
The audit reports branch requests, actual uncached entries and successful cache
returns separately. Successful hits are observed at the real early return with
an existing slot/key and no uncached result local; request-minus-uncached counts
are labelled apparent hits, not hypothetical module-current caching. Holders are fresh per model and not shared across bases,
module instances, or backend/attribution. Reported hits do not imply cross-module
reuse. Rejected/invalid inputs would require separate accounting before interpreting
the subtraction as successful hits.

Adapter scientific identity includes instance ID, topology revision/full hash,
region-map and local-state hash (trusted existing payload hash or fallback),
parameterization ID/hash, evidence hash, region model/version, solver, ceiling,
and operation semantics. N's identity instead hashes model ID/basis,
parameterization, topology, actual local state, solver and ceiling. Those hashes
have different constructions and cannot establish U/N/B equivalence.

Complete attribution source inputs are recorded verbatim with exact float
representations: pinned parameterization/evidence/topology (including branch,
substring, bypass and reverse characteristics and revisions), region mapping,
basis-specific irradiance/temperature, regional solver, adapter identity/domain,
and assembly configuration. `exact_complete_context_repeat_groups` reports
identical complete contexts, including provenance, with strict basis separation.

`potential_cross_module_equivalence_groups` instead compares different module
instances at the same interval and basis against the first captured instance.
The misleading “groups” name does not mean that every entry is an equivalence
group: the script appends comparisons whether or not physical inputs match.
It compares decoded `source_inputs` (`pinned`, `region_map`, basis-specific
`local`, and `region_solver`), assembly `solver`, and adapter `models`.
These cover parameterization/evidence/topology, connectivity and bypass/reverse
characteristics, mapping geometry, local conditions, provenance, model identity,
current ceiling, sample count, tolerances and iteration limit. Other context keys
are not recursively compared by this list; basis and interval select the anchor.
`field_differences` reports differing leaves, or a whole list path if lengths
differ. The legacy `all_unlisted_fields_equal_exactly` value is hard-coded True;
it is not an independently computed completeness check or mathematical proof
of complete physical equivalence. Conclusions here come from the captured inputs,
reported `differing_fields`, and implementation scope, not that indicator.

The measured `exact_complete_context_repeat_groups` is empty. All 27 listed
cross-module entries compare modules 2–10 against module 1 separately for U, N
and B (9 per basis). Every comparison has differences in
`/source_inputs/local/module_temperature_c/float.hex` and in
`/source_inputs/local/regions/{0,1,2}/effective_irradiance_w_m2/float.hex`.
Additional reported differences include instance and region identifiers,
provenance hashes, mapping vertices, some area values, U's uniform irradiance and
actual-state provenance, and N/B sky-diffuse POA and visibility fields.
No comparison has an empty difference list: **zero listed comparisons are actual
complete-input equalities**, and none has matching irradiance and temperature.
All remain labelled `candidate, not proven` by the script, but the measured
physical-input differences rule out treating these entries as exact-input reuse
candidates. No cross-module scientific-curve equality is demonstrated.

The scheme is anchor-only, not all pairs. It establishes neither equality nor
non-equivalence between non-anchor modules 2–10. U/N/B are never compared across
bases. Complete source inputs are captured only for attribution, so
physical-versus-B equivalence is outside the evidence. Zero overflow establishes
capture integrity within this scope; it does not remove these comparison limits.
Reporting semantics and compatibility keys are unchanged in this closure.

## Reuse safety, mechanism, and C3-B recommendation

A possible narrowly bounded mechanism is retaining successful complete
`_string_state_at_current` results for exact currents within a single assembly
and unchanged ordered models/tolerance configuration. It would remove repeated
zero/ISC requests without interpolation or changes to summation order. It must
not reuse the final clamped string voltage as raw V(I), conflate models/bases,
cache exceptions, or expose mutable retained results to callers. Stateful custom
callables are a further barrier: current `SeriesModuleOperatingModel` does not
promise purity for arbitrary callers. Real-model repeated results are observed,
not a general proof for custom models.

The audit does not demonstrate enough significant exact reuse to justify a
production cache optimization for C3-B. The measured repeat set is only 93 of
4,302 string requests (2.16%), consists entirely of the structural zero/ISC
repeats, and contains no proven cross-module reuse. The 120 module-state repeats
show identical returned states at those requests, not full duplicated IV solves.
No measured wall-clock benefit from an additional cache layer is established.

Recommend examining algorithmic costs in single-module string-IV optimization,
short-circuit root solving (1,078 bisection evaluations across 31 assemblies),
and 101-point IV sampling, including the lower-level regional inverse and
common-voltage branch solves behind 955,508 branch requests. MPP candidate
selection operates on stored samples here; additional electrical MPP candidate
evaluation and candidate refinement are structurally absent and measured as 0.
They are follow-on source-analysis questions, not measured bottlenecks in this
assembler. Any follow-on must preserve physical inputs, tolerances, summation
order and provenance, verify numerical/attribution fingerprints, and demonstrate
independent wall-time benefit. No production implementation, additional full
simulation, 50-module audit or Huawei pilot is part of this closure.
