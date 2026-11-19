# D2-A adaptive electrical batchability

Completed diagnostic evidence and source audit only. No production changes.
The supplied JSON records completed measurements; Codex ran no tests or benchmarks
for this documentation update. D1's completed measurements are documented in the
kernel audit. No end-to-end performance improvement is claimed.

## Recorded D2-A evidence

The exact repository artifact is
`.ai/validation/rb_post3d_08p2d2a/batchability_measurements.json`.
Its SHA-256 checksum is
`c9db96a0885b440079fdc8c6738d9cf3532c3a18f14ac43d3d4e3338eb89257d`.
The artifact reports `status: completed`, schema version `1`, pvlib `0.15.2`,
NumPy `2.5.3` and SciPy `1.18.1`.

The actual workload comprised 3 module models (uniform, nonuniform and dark),
2 requested currents per module and 3 repeats, with a record cap of 4,096.
These are three scenarios of one protected module fixture, not a three-module
string simulation. The fixtures are `tests/unit/test_phase66_nonuniform_module_iv.py`
and `components/reference/module-topology-uat-550.json`; all three model IDs are
`rawibumi.phase67.phase66_series_module_adapter.v0.1`.

| Observed quantity | Result |
| --- | ---: |
| Total regional calls | 1,073 |
| Actual numerical calls | 712 |
| Independent two-request groups | 338 |
| Independent single-request groups | 36 |
| Independent groups of size 3 or 4+ | 0 |
| Maximum observed independent group size | 2 |
| Numerical requests in two-request groups | 676 |
| Empty groups | 227 |
| Excluded callable calls | 216 |
| Sequentially dependent requests across groups | 712 |
| Ungrouped numerical requests | 0 |
| Bypass/reverse/dark regional calls | 361 |
| Observed workload regional guard rejections | 0 |
| Uncaptured or overflowed observations | 0 |

The 676 paired requests plus 36 single requests account for all 712 numerical
calls. Within-group numerical independence does not remove the sequential
dependency between adaptive evaluations: each next voltage depends on previous
summed currents. Empty groups do not represent numerical batches. Excluded
callable calls are a separate diagnostic count, not additional trusted numerical
requests. No production-safe batch eligibility follows from these counts.

For two-request raw public-pvlib probes, the scalar median was
0.495188 ms (approximately 0.495 ms), and the vector median was
0.234317 ms (approximately 0.234 ms), including array construction and result
extraction. Their ratio is approximately **2.11x microbenchmark acceleration**.
The artifact contains three timing samples for each size 1, 2, 3, 4, 6 and 12;
all six finite small-batch comparisons report exact equality. Sizes above 2 are
mechanism probes, not observed adaptive group sizes. Production guards, ordered
failure handling and full solver overhead are outside this raw timing comparison;
it does not establish end-to-end speedup.

There are **258 boundary comparison records**: 180 exact numeric comparisons,
30 non-exact comparisons containing NaN, and 48 dark-case exception mismatches.
These are comparison records, including mixed request probes, rather than a count
of individual request slots. Separately, 72 records have regional boundary error
outcomes. Those deliberately probed boundary errors are distinct from the
**0 observed workload guard rejections**; zero workload rejections do not prove
guard compatibility. NaN outcomes do not count as exact numerical acceptance.

Dark raw probes lack diode coefficients: scalar unpacking raises `TypeError`
with `Value after * must be an iterable, not NoneType`, while the vector call
raises `TypeError` for missing `resistance_shunt` and `nNsVth` arguments.
Equal exception types do not establish equal messages or semantics. These raw
probes are inapplicable to production dark handling, which uses the regional
linear law and retains finite/domain guards.

The scalar sequence stops at its first failing request and skips later slots.
Failing vector probes do not establish a corresponding first-error position;
their error-order parity is unavailable. Production admission would require
preserving first-error position, skipped calls, error type/status and significant
messages, together with the original guard and externally observable call order.

Numerical fingerprint requirements remain strict: preserve exact binary64
results, signed-zero behavior, supported-domain admission, solver evaluation and
summation order, and resulting regional/module/bypass behavior. Raw finite
bit-identical outputs alone do not certify the complete production fingerprint.
Nonfinite values, dark coefficients and unsupported domains cannot bypass
validation; no scientific tolerance or provenance contract is relaxed.

The recorded diagnostic runtime is approximately 1.633 s and peak Python-traced
memory is 9,413,448 bytes. Profiling and memory tracing distort runtime, and native
memory is partly untracked. These are bounded diagnostic observations only.

## Actual request dependencies

String assembly calls each ordered module V(I), through the Phase-6.6 adapter,
`module_iv._module_state_at_current`, protected substring evaluation and
`solve_parallel_branches_at_current`. String Isc and common-voltage midpoint
searches depend on earlier results. They cannot be coalesced across iterations,
module currents, substrings or modules without reorganizing the solver.

A. Within one nested `currents_at(voltage)` invocation, ordered single-region
branches share a known voltage. Their mathematical inputs are independent.
The UAT-550 topology supplies two branches per substring. The low-end probe,
each midpoint and the final common-voltage reconstruction are separate groups,
even if they have equal voltages. The observer uses Python frame call/return
boundaries rather than equality of voltages or callable names.

B. The exact frozen `PVSystRegionElectricalState` owns prepared immutable diode
coefficients. A real numerical request becomes known only after B2 lookup,
branch open/end/ceiling checks, regional finite/domain/VOC checks and active
forward-law admission. The spy wraps the original class method and public
pvlib function, invokes both originals, and retains exact state types and B2.
Construction and numerical acceptance probes occur before observation.

C. Successive midpoint voltages require the previous sum of branch currents.
Multi-region branches instead bisect a V(I) curve sequentially. Neither is an
independent regional Lambert-W batch. The report retains individual frame groups;
it never merges them to manufacture large batches. `sequentially_dependent_requests`
counts retained requests in midpoint/final groups after the low-current probe
has completed in their owning solve frame. These may also be independent within
a group; the counts describe two different dependency dimensions.

D. Arbitrary caller-supplied module or regional functions carry no purity contract.
Frozen model fields and model ID strings do not freeze captured state. Those
callables remain invoked in original order, are never cached by this diagnostic,
and are not admitted by the exact numerical-state predicate. C3-B's blocker holds.

E. Negative voltage and dark ISC use the production linear reverse law. Below-domain
and nonfinite inputs fail closed; above-VOC inputs return zero. Branch open/end
checks may avoid regional calls entirely. Numerical output negative-current and
ceiling checks still apply. A preceding branch error stops the scalar sequence;
a public array call cannot establish the same first-error order from raw parity.
Thus mathematical independence is insufficient for an eligible production boundary.

Protected `_branch_states_at_voltage` interleaves branch I(V) and branch V(I)
reconstruction; its numerical calls are observed as ungrouped, not eligible groups.
Bypass clamp and reverse/dark invocations are counted together as actual regional
reverse/dark behavior. This is not protected-bypass equivalence certification.
The dc_attribution bypass-off generator is explicitly outside this workload.

## Bounded diagnostic

Human or orchestrator command (not executed by Codex):

```sh
.venv/bin/python scripts/benchmarks/rb_post3d_08p2d2a_batchability.py --output /tmp/d2a.json --currents 2 --repeats 3 --records 4096
```

One module model for each of uniform, nonuniform and dark conditions uses the
existing real Phase-6.6 topology, parameterization, evidence and handoff builders.
Up to four fractions (0.2, 0.5, 0.8, 1.0) of each model's supported current ceiling
are evaluated. B2 remains enabled. There is no 50- or 190-module run.
The budgets are currents 1–4, repeats 1–7, retained records/groups 1–20000.
Overflow increments a counter and makes captured counts incomplete. Budgets bound
work and retention, not wall-clock duration. No global numerical cache is added.
Spies and profiler are restored in finally; existing profiling is rejected rather
than overwritten. Native allocations may escape tracemalloc; timing includes its
instrumentation overhead and fixed scalar-before-array order bias.

The JSON contains completion status, versions, fixture/model identity, budgets,
actual regional and public I(V) counts, captured group sizes (1/2/3/4+), maximum,
sequential and ungrouped counts, guards, reverse/dark, overflow, records and groups.
Empty groups from memo/endpoint returns are separate. Guard rejections count
regional exceptions; pre-regional branch guards and B2 hits are not separately
quantified. Every actual numerical call is counted even when retention overflows.

Public small-batch probes use validated compatible fixture coefficients for sizes
1, 2, 3, 4, 6 and 12. They report multiple scalar and total-array elapsed samples,
per-point costs, construction, kernel and extraction costs, and exact binary64
comparisons. These are separate mechanism probes; sizes exceeding the observed
independent maximum cannot be claimed reachable. No private pvlib/scipy API is used.

Boundary and mixed valid/boundary/valid probes preserve original regional outcomes,
raw candidate outcomes, exception messages and mismatch evidence. Error-order
parity is unavailable on failures even when error type and message match. D1 dark
raw failures arose from missing diode coefficients, whereas production uses the
linear law; they are retained as inapplicable raw probes. Nonfinite values never
count as exact scientific parity. No tolerances or scientific acceptance change.

## D2-B decision

Production eligibility is FALSE. The current source proves an immutable numerical
law and mathematical same-voltage independence, but does not demonstrate a
validated batching boundary preserving ordered guards, first errors and externally
observable calls. Close batching for the existing solver as blocked/infeasible
unless a separately authorized proposal supplies that boundary and all seven D2-B
evidence gates. The measured 2.11x two-request raw ratio suggests limited kernel
savings but does not resolve the production compatibility blockers; the 73.4x
D1 raw ratio and 2.17x branch probe ratio cannot substitute for adaptive evidence.
The artifact records `production_eligible: false` and a BLOCKED decision because
no validated ordered-error batch boundary exists. **D2-B is not authorized** and
is not implemented. This is the diagnostic's conservative outcome, not a
request to alter contracts or architecture.

This documentation update was checked against the supplied JSON and its SHA-256
checksum. No tests, builds or benchmarks were executed by Codex, and this document
does not infer regression-test or review status from diagnostic completion.
Only this evidence document was modified for the update; production source and
tests were not changed, and nothing was staged, committed or pushed.
