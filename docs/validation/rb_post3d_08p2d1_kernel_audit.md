# D1 Lambert-W electrical-kernel audit

Measurement and source analysis only. Production code is unchanged. D1 measurements below are from the completed orchestrator artifact
`.ai/validation/rb_post3d_08p2d1/kernel_measurements.json`. Contract-test
verification is owned by the orchestrator. Codex ran no tests or benchmarks. No runtime improvement,
production eligibility, fingerprint preservation or Huawei pilot qualification is claimed.

## Source-backed call graph

`module_series_adapter.build_phase66_series_module_operating_model` constructs
validated regional states and a model-owned B2 endpoint holder. Its V(I) closure
calls `module_iv._module_state_at_current`, which evaluates protected substrings.
`substring_reference.solve_parallel_branches_at_current` bisects a common voltage;
`currents_at(mid)` visits ordered branches. B2 reuses only exact admitted successful
queries for frozen trusted regional types, with 256 entries per branch binding.
The uncached path calls `PVSystRegionElectricalState.current_at_voltage` directly
for one-region branches; series-region branches require another inversion.

`parameterization.build_pvsyst_region_electrical_states` validates definition,
evidence and map/local bindings, calculates PVSyst coefficients for each region's
irradiance and temperature, and derives ISC/VOC and explicit domains. These
coefficients already reside in immutable tuples; preparation is not repeated by
each regional I(V) invocation. The current method validates finite input and
reverse domain, returns zero above VOC + 1e-10, then uses public
`pvlib.pvsystem.i_from_v(..., method='lambertw')` for nonnegative voltage and active
ISC. Negative voltage and dark regions use the explicit linear reverse law.
Tiny negative delivery current is clamped, larger negatives raise, and the explicit
current ceiling is checked. All these guards remain authoritative.

Installed source inspected in `.venv/lib/python3.12/site-packages/pvlib`:
`pvsystem.py:i_from_v` dispatches to `singlediode.py:_lambertw_i_from_v`.
That wrapper tests six scalar arguments, computes shunt conductance, broadcasts
six arrays, allocates an output array, creates masks and reductions, allocates
indexed intermediates, computes an exponential argument and calls
`ivtools/utils.py:_lambertw_pvlib`. The latter converts to an array, allocates
output and masks, and executes three Halley iterations for arguments <=100;
larger arguments use log-domain initialization and three Newton iterations.
The current wrapper finally assigns masked results and calls `.item()` for scalar
inputs. It documents unhandled exponential overflow. No substitute solver is used.
The planner identified pvlib 0.15.2, NumPy 2.5.3 and SciPy 1.18.1; the diagnostic
records actual installed versions on every run rather than assuming those versions.

## Existing cost evidence

The supplied C1 profile spans two instrumented runs. It reports 4,772,447 public
I(V) calls, 4,824,333 private I(V) calls, 5,202,830 Lambert-W calls,
5,462,586 regional current calls and 5,470,476 uncached branch calls.
Private I(V) self/cumulative times are 90.677/281.745 s; Lambert-W
self/cumulative times are 89.018/134.039 s. Cumulative times overlap and must not
be added. This establishes meaningful wrapper/allocation work (B), alongside
necessary transcendental work (A). Array coefficient preparation within the
wrapper is repeated (C), while physical PVSyst coefficients are already prepared.
Repeated identical evaluations (D) are already partly removed by B2; C3-A reports
215,510 actual B2 hits in its size-10 audit. Adaptive solver organization (E)
limits further batching. C3-B endpoint reuse remains blocked for stateful callables;
C2 attribution reuse is not restored.

Accepted uninstrumented baseline warm execution is 37.997 s for ten modules and
141.981 s for fifty, with 149.332 s including fifty-module verification. These are
historical end-to-end measurements, not results from this diagnostic.

## Inputs and diagnostic mechanisms

The CLI uses the actual Phase-6.6 synthetic regional parameterization/evidence and
reference topology through the existing validated public builder. Values follow
existing B2 regression scenarios: uniform 1000 W/m², nonuniform 1000/200/600 W/m²,
low 100 W/m², dark zero, and 15/25/45 °C. No whole-module coefficients are divided.
Every region is retained. Requests cover zero voltage, half VOC, VOC, above VOC,
reverse voltage, the topology's -0.55 V diode clamp, below-domain voltage and NaN.
Clamp queries are regional inputs relevant to bypass evaluation; they are **not**
measurements of a protected bypass transition or evidence of bypass equivalence.
Fixtures are synthetic v0.1 executable test evidence, not authenticated Level-2
annual runs or manufacturer validation. Their identity fields are retained;
no witness is forged, no authorization function replaced and no gate bypassed.

Two diagnostic candidates execute the actual installed electrical mathematics:

- Public array I(V), with independent voltage/coefficient arrays prepared inside
  each timed invocation. It amortizes dispatcher/broadcast/mask allocations.
- Private scalar `_lambertw_i_from_v`, bypassing public dispatch only. This is
  explicitly compatibility-risky and retains the expensive scalar NumPy wrapper.

Both compare raw forward pvlib outputs and every boundary request against
identical public scalar requests. Per-case candidate records include raw reverse,
below-domain, zero, VOC, above-VOC, NaN and dark/None-parameter outcomes.
Mixed valid/boundary/valid arrays expose nonfinite masking or whole-call failure;
the scalar sequence stops at its first exception, whereas array preparation can
fail before the kernel executes. Exception types and messages are retained,
without treating raw-layer parity as regional guard parity. Regional boundary/error
outcomes are also recorded separately by the original regional method. There is no candidate regional wrapper, so regional exception
parity and guard compatibility are not certified. All candidates remain ineligible
for production in this audit, regardless of their timing or equality result.
No prepared-coefficient formula is reimplemented: changing arithmetic grouping
could change binary64 results and requires separate exact comparison evidence.

## Numerical and measurement reporting

The JSON records per-point float.hex values, bit equality including signed zero,
finite/nonfinite classification, separate binary bit identity, case metadata,
maximum absolute/relative differences and binary64
ULP distance. Nonfinite differences are unavailable and never counted exact.
Relative difference against zero is unavailable unless both values are zero.
Opposite signed zeros have distinct bit identities (ULP distance one in the ordered
binary encoding). Array SIMD exp/log/log1p may differ from scalar paths; closeness
does not prove scientific fingerprint preservation. No tolerances are broadened.
Regional failures record original exception type/message on every fresh invocation.
The CLI does not cache failures, states or numerical outputs globally.

Human/orchestrator invocation (not executed by Codex):

```sh
.venv/bin/python scripts/benchmarks/rb_post3d_08p2d1_kernel.py --output /tmp/d1.json --points 128 --repeats 3
```

Limits are 1–256 large-batch points and 1–7 repeats; defaults are 128 and 3.
The eight boundary requests per region in six scenarios are independent of this
budget. Each boundary is submitted separately to scalar, public array and private
scalar paths, and to a mixed three-element scalar sequence and array. Dark states
have no diode tuple: these are intentional raw preparation failure probes, not
physical single-diode inputs. Regional dark execution remains the original law.

`branch_equivalence` contains 54 groups: six scenarios, three topology substrings,
and three shared voltages (zero, half the minimum branch VOC, minimum branch VOC).
Each uses exactly the two single-region branches in topology order. These are
bisection-relevant probes, not a trace of actual adaptive midpoints. Failed raw
groups, including dark groups, retain exception evidence and are excluded from
`branch_timings`. Successful groups are timed as ordered scalar pairs versus
independent public length-two arrays; coefficient-array construction is included.
The larger mixed batch remains an upper-bound mechanism probe.

Each mechanism has one discarded warm-up and multiple recorded samples with
minimum, median, maximum and median seconds per evaluated point. Warm-up and
successful timing evaluations have separate counts. Boundary/comparison counts
are submitted request slots: an exception may prevent later scalar slots or all
array slots from reaching the mathematical kernel. `total_request_slots` includes
these slots and the one private availability probe; it does not mislabel failed
requests as successful evaluations. No B2 memo is active.

Stdlib tracemalloc reports peak Python traced bytes, excluding some native library
allocations. Tracing overhead affects timing; an existing caller trace is preserved
and its peak may include earlier allocations. Timing mechanisms still run in fixed
order, so warmth/order bias remains a limitation. All fixtures, comparisons and
retained arrays are bounded; bounds are not a hard wall-clock deadline. The private
symbol is imported lazily: its ImportError is reported as candidate unavailable,
without preventing public diagnostics from running. CLI failures emit error JSON
and a nonzero exit status.

## Recorded D1 results

The artifact completed with installed pvlib **0.15.2**, NumPy **2.5.3** and
SciPy **1.18.1**. The 128-point finite raw forward comparison matched **128/128**
bit-identically for both public arrays and private dispatcher, with zero maximum
ULP difference. This is raw-kernel equality, not complete regional, bypass,
provenance or scientific-fingerprint verification.

| Diagnostic mechanism | Recorded median | Ratio to scalar |
| --- | --- | --- |
| 128-point public scalar | 32.512 ms | reference |
| 128-point public vector batch | 0.443 ms | 73.4x |
| 128-point private scalar dispatcher | 35.817 ms | slower than reference |
| 90 branch points, scalar sequences | 21.976 ms | reference |
| 90 branch points, public length-two batches | 10.107 ms | 2.17x |

These are diagnostic ratios only; neither is a measured real-simulation speedup.
The private dispatcher regressed despite its identical finite results.
The 54 shared-voltage branch probe groups yielded 45 exact numerical comparisons
and nine dark-case exception mismatches; the 45 successful pairs supplied the 90
timed branch points. They were constructed probes, not adaptive execution traces.

All **288** boundary records remain in the artifact. Public individual arrays
had **48** exception mismatches and mixed arrays had **48**, all dark-category
requests. Dark states have `diode_parameters=None`; scalar tuple expansion and
array argument preparation fail differently. The raw diode comparison is
inapplicable to these requests: production executes its explicit linear law and
domain guards instead. Matching exception types alone do not establish parity,
and those failures are not hidden or recast as physical acceptance.

Finite equality uses binary64 bits including signed zero. Nonfinite pairs never
count as exact numerical equality even when their binary encodings match;
nonfinite absolute, relative and ULP differences are unavailable. Raw nonfinite
or out-of-domain behavior cannot bypass production validation. Array failure
order differs from an ordered scalar sequence that stops at its first exception.
The fixture, warm-up, fixed mechanism order, tracing/native-memory, raw guard and
private-API limitations above apply to the recorded results.
**Production eligibility remains FALSE.** No end-to-end improvement is measured.

## D2 recommendation and limitations

Source evidence supports investigating wrapper allocation overhead, but does not
authorize an implementation yet. Millions of independent uncached forward calls
could plausibly benefit if the overhead can be removed at a narrow trusted layer.
The adaptive solver cannot batch successive midpoints, which depend on previous
results. Its only immediately independent set is branches at one common voltage,
exactly two single-region branches in this fixture. The diagnostic now measures
that shape separately for each scenario/substring at shared forward voltages.
Only those length-two equality and timing records can inform the immediate
batching opportunity; large-batch ratios cannot establish that opportunity. Batching modules or intervals
would require solver reorganization outside this task.

Any D2 proposal must establish purity at the exact frozen trusted regional-state
layer, retain ordered first-error behavior, preserve all guards and tolerances,
and retain B2 semantics. Arbitrary V(I) callables cannot be cached, suppressed,
batched or reordered. Public batch equality alone cannot satisfy these criteria.
Require measured bit compatibility and plausible per-call savings, then separately
inspect the recorded length-two branch results (including nonuniform scenarios),
then verify regional first-error/guard parity and an authorized end-to-end run before claiming
material improvement. Private API stability remains an additional blocker for the
dispatch candidate. Do not project microbenchmark ratios into ten/fifty-module
speedups or a 190-module prediction. D2 authorization still requires these
evidence gates; this audit makes no scientific or architectural assumption change.


## Round-1 review disposition

M1 is addressed by topology-derived length-two groups with metadata, exact/ULP
comparisons and separate scalar/array timing distributions. M2 is addressed by
per-category raw candidate boundary/error outcomes and mixed-array failure probes.
These additions are executable measurement mechanisms; their recorded D1 results are summarized above. Tests cover the report records, real nonfinite outputs, dark preparation
errors, branch shape, signed bit identity, lazy private availability and all changed
paths via read-only Git porcelain (including untracked files). Cache checks include
bare decorators and functools imports. No verification commands were executed by
Codex; the orchestrator must run the new contract file and bounded CLI.

The optional isolated private Lambert-W-core timing was not added. The private
dispatcher probe only isolates public dispatch; wrapper versus transcendental
allocation cost still rests on the supplied overlapping cProfile evidence, not a
new isolated measurement. This limitation prevents an isolated scalar-wrapper
savings claim. No D2 implementation is authorized until measurements and regional
compatibility evidence satisfy the gates above.
