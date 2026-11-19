# Phase 6.9A increment 3: detailed execution through selected MPPT

The validated `phase-6.8-validated` baseline remains unchanged. The new branch
executes detailed physics through tracker selection. It does not call
`simulate_electrical_loss_chain()`, inverter conversion, PCC calculation, energy
aggregation, UI, or a new attribution ledger. The existing tracker kernel's own
zero-loss ideal-tracker diagnostic is preserved without introducing a ledger.

## Verified ordering and irradiance meanings

1. `prepare_temporal_execution()` converts cadence once and constructs the canonical
   interval timeline. Solar evaluation follows its representative-time semantics;
   evaluation times are not forced to be interval midpoints or interior points.
2. `solar_position_from_weather()` supplies SPA and the solar-aware weather QC.
3. `complete_irradiance()` and `calculate_poa()` supply **unshaded incident** beam,
   sky and ground channels for each module's canonical compiled orientation.
4. `derive_electrical_region_map()` and
   `evaluate_electrical_region_visibility()` provide per-module regional visibility.
5. The existing local mapper, with unity optical factors, and
   `collapse_local_irradiance_to_module_equivalent()` supply **area-weighted shaded
   incident POA**. This is the thermal heat-input irradiance, before IAM.
6. `apply_iam()` is evaluated once per module on that shaded incident POA. Isotropic
   sky receives sky IAM, ground receives ground IAM, and beam receives AOI IAM.
   Detailed runtime support restricts transposition to isotropic: circumsolar and
   horizon anisotropic channels are outside this adapter's envelope.
7. **Effective electrical irradiance** in each region is the sum of its original
   unshaded incident channels multiplied by regional visibility and the respective
   IAM factor exactly once. An already geometrically shaded module POA is never
   supplied as `unshaded_poa` to the regional mapper.
8. `solve_pvsyst_module_thermal_coupling()` uses the full chronological shaded
   incident history for heat input, and equivalent post-IAM effective irradiance
   for the existing whole-module SDM efficiency estimate. One temperature per
   module per interval is retained. No transient thermal history or regional
   temperature gradients are claimed. Absorptance enters heat balance separately
   and is not an electrical irradiance multiplier.
9. `build_phase66_series_module_operating_model()` consumes the exact pinned
   regional calibration and final local state at that module temperature. It
   preserves negative module terminal voltage when evaluating a series string;
   it does not clamp the standalone module IV at its Isc.
10. `assemble_general_series_string_iv()` supplies general series-string IV.
11. `assemble_parallel_mppt_iv()` supplies the common-voltage combined IV, retaining
    its represented local maxima and exact interval-quadratic MPP candidates.
12. `select_mppt_operating_point()` explicitly selects the Phase 6.8 ideal global
    tracker point. Voltage/current flags never modify that point.

Module quality remains resolved by `resolve_module_runtime_inputs()` with its
existing signed manufacturing/nameplate-tolerance meaning. Explicit overrides and
component defaults are preserved in pinned inputs and temperature metadata. No
quality multiplier enters thermal efficiency or regional IV. Downstream application
is pending evidence that regional calibration is independent of that adjustment.
A nonzero quality value does not block this physical computation.

## Result and identity contracts

`DetailedMPPTBackendResult` is a frozen canonical byte snapshot with a SHA-256;
`replay()` validates the snapshot and returns an isolated copy. The standalone
`detailed-mppt-backend-result.schema.json` describes its serialized payload.
It contains interval start/end/duration/evaluation identity, canonical MPPT ID and
1-based index, selected voltage/current/power, tracker model, complete combined
curve/state and tracker diagnostics, regional/local inputs, module operating-model
identity/domain, string curves/states, temperature approximation/coupling metadata,
weather QC, canonical component model-resolution assumptions, numerical policy,
and the detailed scientific-input hash.

Selected power must satisfy `P = V × I` with absolute tolerance `1e-7 W` and
relative tolerance `1e-9`. Kernel tolerances are unchanged: series voltage/current
`1e-9`, series maximum iterations `200`, parallel voltage/current `1e-9`, parallel
power `1e-7 W`. Default series sample count remains the kernel default `201`.
Explicit `scientific_options.string_sample_count` must be an integer at least
`101`; the primary Phase 6.8C reference explicitly selects its original `101`.
Both the requested choice and resolved default policy enter scientific identity.

The context pins `detailed_numerical_policy` alongside the existing canonical
revision/configuration/weather/components/frozen-selection inputs.
`DetailedExecutionIdentity` additionally binds `numerical_result_sha256` and
runtime results `mppt_complete`, `constraint_blocked`, or `numerical_failed`.
Paths, execution timestamps, duration and storage/cache metadata do not enter the
scientific or numerical identity. `detailed-mppt-result.json` is covered by the
completion manifest and verified against both run identity and pinned input hash.
Earlier increment-2 scaffolding packages without numerical execution remain verifiable.

The normal result reference, summary, timeseries, and legacy backend result remain
unavailable in detailed mode. `CanonicalSimulationExecutionResult` exposes the
separate immutable `detailed_backend_result`. The overall SimulationRun is still
`failed` with an explicit downstream-unavailable finding even when this narrower
backend reports `mppt_complete`; it does not claim a completed energy simulation.

## Dispatch and fail-closed behavior

| Request/state | Execution | Detailed runtime result |
| --- | --- | --- |
| No detailed request | Existing legacy pipeline | No detailed identity/result |
| Valid Level 2 and supported inputs | Detailed backend through tracker only | `mppt_complete` |
| Known selected-point voltage/current violation | Preserve physical point and flag; block continuation | `constraint_blocked` |
| Invalid persisted identities, revisions, coverage or unsupported preflight | No detailed physics | `blocked` |
| Unsupported input with permitted explicit lower-fidelity policy | Existing geometry-only branch, with recorded reason | `fallback_to_geometry_only` |
| Geometry, numerical options, QC or kernel execution failure | No fabricated result/legacy retry | `numerical_failed` |

Unknown current limits remain `None`. Unlike the legacy inverter limit adapter,
the detailed path uses Phase 6.8 `_constraints()` and rejects an explicitly
nonpositive current limit instead of silently converting it to unknown.

## Evidence and remaining limits

`tests/integration/test_phase69a_detailed_backend.py` compares canonical results to
independent direct calls using the same pinned local states and numerical settings:
local state, operating-model identity/domain, string curve/state, parallel
curve/state, tracker state and flags are exactly equal. The controlled Phase 6.8C
reference additionally uses the original four receivers, one shaded region, two
strings/shared MPPT, 1000 W/m² beam and 25°C fixture temperature. Only solar
boundary inputs and temperature are controlled for this isolation test; all
Phase 6.6–6.8 electrical kernels are real. The canonical tests use real SPA,
partial sky visibility, nonunity IAM and real module thermal coupling. They
independently rebuild unshaded POA and temperature histories.

Regional temperature gradients and detailed-IV feedback into thermal efficiency
remain unresolved model extensions. Calibration/quality independence is unresolved.
Series-grid convergence beyond the existing represented-curve guarantees is not
claimed. Parallel reverse/backfeed current and per-MPPT power-limit enforcement
remain outside the Phase 6.8 contract. The Phase 6.7 solver rejects zero-generation
strings pending a dedicated dark-state representation; a detailed run containing
such an interval fails closed rather than inventing a nighttime curve.

The adapter currently retains full diagnostics in memory and JSON. Storage grows
with intervals, modules, regions and IV samples; this reference backend does not
claim annual-scale performance or streaming support. Fixture runtime/RSS/payload
observations are printed by the controlled reference test; process peak RSS is a
high-water observation, not an isolated measurement of fixture allocations.

## Increment-3 checkpoint validation (2026-10-03)

- Phase 6.4–6.8 unit/integration tests plus all Phase 6.9A tests:
  **131 passed**, one existing Starlette/httpx deprecation warning, **317.37 s**.
- Complete repository suite: **780 passed**, the same warning, **453.03 s**.
- Controlled Phase 6.8C one-interval backend: **11.585 s**; immutable diagnostic
  payload **406,699 bytes**; process peak RSS **257,036 KiB**. No additional
  high-water RSS increase occurred during that fixture; this does not imply zero
  allocations. Setup and independent direct-kernel recomputation are outside the
  timed backend call; solar inputs and 25°C temperature are controlled in this test.
- HEAD and `phase-6.8-validated^{}` remain
  `fbf345c9911306605072ef2720271a8d2d0c76be`. The legacy runner, geometry validator,
  Phase 6.6–6.8 kernels, and existing Phase 6.1–6.8 tests/tolerances are unchanged.
- No commit or downstream numerical connection was made.

Files introduced in this increment: `engine/simulation/detailed_backend.py`,
`schemas/detailed-mppt-backend-result.schema.json`,
`tests/integration/test_phase69a_detailed_backend.py`, and this document.
Files updated from the earlier increments: `engine/simulation/detailed_dispatch.py`,
`engine/simulation/detailed_inputs.py`, `engine/simulation/canonical.py`,
`engine/simulation/artifacts.py`, `schemas/detailed-execution-identity.schema.json`,
`tests/unit/test_phase69a_canonical_dispatch.py`, and
`tests/unit/test_phase69a_detailed_inputs.py`.

## Closure superseding the historical dark/quality boundary

Phase 6.9A closure adds explicit inactive-dark transport and evidence-bound module
quality continuation; see `phase69a-detailed-pcc.md`. The earlier fail-closed
all-dark and unconditionally unknown quality statements above describe increment 3.
Daytime kernels, tolerances and parity remain unchanged.
