# Phase 6.9A closure: controlled detailed execution to PCC

No commit is made. The validated Phase 6.6–6.8 numerical implementation and
legacy `_run_fixed_tilt()` are unchanged. This increment does not implement the
counterfactual attribution ledger, UI, or annual acceleration/support validation.
The increment-3 document remains the historical MPPT-boundary checkpoint.

## Scientific preflight: module quality

`components/candidates.py::build_module_candidate()` maps PAN data, calls
`components/pan/semantics.py::assemble_module_semantics()`, and separately calls
`components/pan/pvsyst_sdm.py::complete_parameter_set()`, `validate_at_stc()` and
`validate_off_stc_matrix()`. Quality is not a calibration multiplier in those
functions. STC `pmp_w = vmp_v * imp_a` is distinct from commercial nominal power.

The actual `JKM550M-72HL4-V_SGS_6079M3.PAN` fixture has `PNomTolLow=0.00` and
`PNomTolUp=3.00`. The mapping ledger converts percentages to fractions. Semantic
assembly uses the signed performance offset `lower + 0.25*(upper-lower)` and
negates it for the loss convention: **-0.0075**. It is a nameplate/manufacturing
tolerance adjustment, not an electrical mismatch fraction. The existing loss
chain consequently multiplies input power by **1.0075**, increasing current at
unchanged voltage. `tests/unit/test_phase38a_pan_component_runtime.py` verifies
component/default/override resolution; `tests/unit/test_engine_losses_energy.py`
verifies signed quality gains and the ledger's `gain` classification.

PAN SDM reference currents are derived from Isc/Voc, resistances, ideality factor,
cell count and reference temperature, without reading the quality field. However,
this only proves implementation separation. PAN source evidence and regional/manual parameterization evidence without an
explicit declaration do not establish whether their
source/calibrated electrical values already embed manufacturing tolerance.
`components/templates/module-advanced.yaml` accepts complete supplied electrical
models; `shading/electrical/parameterization.py` and its evidence contracts check
source identities, hashes and passed calibration evidence; historical evidence
has no calibrated quality-baseline declaration. Thus independent downstream application cannot be
proved across supported detailed calibrations.

`resolve_module_runtime_inputs()` retains override → component default → generic
zero precedence and the legacy positive-loss/negative-gain sign convention.
`ElectricalParameterizationEvidence.module_quality_declaration` now declares
`separate_from_parameterization`, `embedded_in_parameterization`, or `unknown`.
The declaration binds the signed `module_quality_loss_fraction`, `source_ids`, and
an explicit rationale to the evidence's existing module/topology revisions,
parameterization identity and exact payload digest. Declaration sources must be
registered and included in the parent evidence sources. Missing declarations
remain unknown for compatibility; PAN tolerance alone establishes no independence.

Separate quality applies once through the existing downstream signed loss chain.
Embedded quality adds no scalar multiplier. Unknown nonzero quality blocks PCC
while preserving valid selected-MPPT physics. Zero quality always proceeds.
A nonzero resolved override must match the declared signed value. The current
global loss-chain envelope also requires one common effective quality factor;
heterogeneous factors are explicitly unsupported. No manufacturer declaration
has been added to the Jinko catalog: its default **-0.0075** stays unknown unless
calibration-specific evidence says otherwise. Controlled regression declarations
prove separate **×1.0075**, embedded **×1**, and unknown **PCC blocked** behavior.

Frozen selections and scientific/run identity hash the entire evidence and source
registry, including the declaration and binding. Replay validates these contracts;
run-package verification checks the scientific context and snapshot identities.
The reproducibility manifest records per-module declarations, evidence IDs and
resolved signed values. Neither quality nor mismatch enters regional IV or thermal
efficiency; no Phase 6.6–6.8 kernel is changed.

## Final execution flow

1. Canonical temporal preparation, SPA/QC, unshaded isotropic beam/sky/ground POA.
2. Regional visibility multiplies each unshaded incident channel once.
3. Area-weighted shaded **incident** POA feeds thermal heat input before IAM.
4. IAM applies once to the appropriate channels. Post-IAM local **effective**
   irradiance feeds the existing detailed electrical module model. Existing
   bounded whole-module efficiency/thermal coupling provides one temperature per
   module; regional temperature gradients and detailed-IV thermal feedback are
   absent. Absorptance is a separate thermal input.
5. Existing Phase 6.6 module operating models → Phase 6.7 general series IV →
   Phase 6.8 parallel IV → explicit ideal global-MPP tracker selection.
6. `compact_selected_states()` projects those results without recomputing physics.
7. `selected_states_to_mppt_bank()` checks P=V×I (absolute **1e-7 W**, relative
   **1e-9**) and known binding current constraints, then creates the generic
   interval-state carrier with truthful detailed metadata.
8. `execute_detailed_downstream()` validates evidence-bound quality, rejects nonzero legacy
   mismatch fractions, and calls the unchanged `simulate_electrical_loss_chain()`.
9. Existing chain: declared quality / zero residual mismatch terms → global DC I²R wiring →
   inverter MPPT voltage eligibility → startup → voltage-dependent conversion →
   AC clipping → self-consumption → net inverter AC at the existing PCC identity
   boundary. No extra downstream AC losses are invented.
10. Existing duration-based energy integration, KPI calculation, standard artifact
    projection and summary machinery. Irradiance reference for PR is explicitly
    module-surface-area-weighted **unshaded incident** POA, consistent with the
    existing geometry-aware PR denominator choice. No electrical-shading energy
    attribution is claimed: summary shading energy remains unavailable.

`MPPTAggregationResult` is used only as its generic carrier contract. Its legacy
`aggregate_parallel_strings()` function assumes common identical string MPP/Voc
and is never called. Detailed Vmp/Imp/Pmp fields carry the selected ideal-global-MPP
state. Isc/Voc come directly from the combined parallel curve; no common-string
Voc or independent-string power sum is invented. String count/IDs are actual
coverage. Current constraints remain flags and known binding constraints block
before any loss can mask them. Unknown current limits stay unknown. Voltage
flags never clip the selected state: the existing inverter alone books voltage
eligibility loss. Absolute unsafe Voc blocks there. Global positive wiring
resistance retains the existing restriction on heterogeneous active voltages.
No MPPT power limit or reverse/backfeed operating model is introduced.

## Dark and night states

The detailed producer declares `inactive_dark` only when all regional effective
irradiances in every module of every connected string are exactly zero. It skips
string/parallel IV and tracker selection for those branches. Diagnostics retain
interval/evaluation identity, module/local-state provenance, MPPT/string identities,
electrical revision and scientific input hash. `power_w` is exactly zero;
`selected_operating_point`, `tracker_state`, and `combined_curve` are null, with
`inactive_reason=no_photovoltaic_operating_point`. No curve or Voc is invented.

The compact contract carries inactive availability, false active state, zero power,
and null V/I/Isc/Voc/curve hash. Null quantities remain unavailable (NaN in pandas
and null in Parquet) through the downstream carrier. An inactive branch contributes
zero to the array current sum, which is distinct from assigning a tracker operating
current. The inverter omits explicitly dark trackers from conversion evaluation,
retaining the existing startup/standby/night/self-consumption calculations and
explicit-duration PCC integration. Legacy inputs and their zero-state behavior
retain their existing paths.

A dark MPPT and an independent active MPPT may coexist. Mixed dark and active
strings on the same MPPT remain explicitly unsupported because omission would
assume a reverse/backfeed dark-branch model. Partially illuminated strings still
use the unchanged kernels and their fail-closed envelope. Darkness is an execution
state, not a runtime failure. Deterministic daylight → dark → daylight replay and
fully dark execution are covered by closure integration tests.

## Compact and diagnostic artifacts

`CompactDetailedMPPTResult` is immutable canonical bytes with a content hash and
schema. Per interval it contains start/end/evaluation identity and explicit
duration; per MPPT it contains identity/index, connected strings, selected V/I/P,
active state, authoritative Isc/Voc, availability/constraint flags, tracker model
and combined-curve hash. Per-module scalar POA/temperature and approximation
metadata supply downstream KPI inputs without retaining regional curves.

Every detailed run stores `detailed-selected-mppt.json`. Completed runs additionally
store normal ledger/DC/inverter/PCC scalar time series in `timeseries.parquet`,
selected MPPT scalar/availability columns, normal SummaryResult and
ReproducibilityManifest. The compact and full diagnostic hashes are both bound
into immutable execution identity, together with the existing pinned scientific
context and requested/resolved fidelity. The context retains all inputs needed
to regenerate omitted diagnostic curves and verify their recorded result hash.

Full module/string/parallel curves, tracker diagnostics and regional intermediate
states remain available in the immutable in-memory backend result. They are
persisted separately in `detailed-mppt-result.json` only with explicit
`output_configuration.detailed_diagnostics=true`. The reference/parity fixture
opts in; its physical assertions and tolerances are unchanged. Compact files
are checked against the full projection when both artifacts exist. Existing
increment-2/3 packages remain verifiable. Package byte/hash verification detects
tampering; detailed verification additionally checks scientific, compact and
full numerical identities and embedded/external reproducibility consistency.

Storage choice, paths, run IDs, execution timestamps, duration telemetry and cache metadata
are excluded from scientific hash inputs. Diagnostic opt-in changes neither the
scientific input/run hash nor numerical results. Full diagnostics are still
computed in memory; memory/annual acceleration is deliberately not implemented.

## Changes and validation coverage

Increment-4 implementation files: `engine/simulation/detailed_downstream.py`,
`engine/simulation/detailed_dispatch.py`, `engine/simulation/artifacts.py`,
`schemas/detailed-selected-mppt.schema.json`, and
`schemas/detailed-execution-identity.schema.json` (compact hash, PCC-complete and
downstream-failed states). No legacy schema/value changes are introduced.

New `tests/integration/test_phase69a_detailed_pcc.py` covers adapter/PVI/current
constraints, direct loss/inverter/PCC parity, zero/nonzero quality and negative
loss gain semantics, mismatch rejection, wiring once, eligibility once, conversion
and clipping once, standby, consumer night behavior, unavailable dark Voc,
explicit interval duration, canonical one-interval and short multi-interval runs,
deterministic replay, diagnostic opt-in/hash independence and tamper detection.
Existing detailed tests retain shading/IAM/thermal ordering, direct Phase 6.8
kernel parity, explicit inactive-dark behavior and known/unknown current limits.
Legacy canonical/API tests check numerical and bodyless request compatibility.
All existing Phase 6.1–6.8 tests and tolerances remain unchanged.

## Increment-4 checkpoint results

- Broad focused run: **103 passed**, one existing Starlette/httpx deprecation,
  **278.77 s**. Final PCC contract run after the last adapter checks:
  **12 passed**, **65.30 s**.
- Complete suite: **792 passed**, the same existing deprecation, **545.00 s**.
  Logs: `/tmp/rawibumi-phase69a-inc4-focused.log`,
  `/tmp/rawibumi-phase69a-inc4-final-pcc.log`,
  `/tmp/rawibumi-phase69a-full.log`.
- Actual three-interval canonical fixture selected DC powers:
  **701.7163393820699, 1045.5445244063715, 1376.2543190509427 W**.
  Selected voltages: **80.84892266768922, 80.57746595765256,
  79.41146286205155 V**; currents: **8.679352998509485,
  12.975644145422205, 17.330675817440646 A**.
- Corresponding unclipped AC/PCC powers:
  **228.43972002340652, 617.8182629997275, 992.3404912388115 W**.
  PCC energy: **1838.5984742619455 Wh** for the three explicit hourly
  intervals. Direct existing chain versus SimulationRun ledger equality is exact
  (`assert_frame_equal`); P=V×I uses **1e-7 W absolute / 1e-9 relative**.
  The normal ledger's existing reconciliation tolerances are unchanged.
  Separate cases force 100 W clipping, voltage-window rejection, I²R wiring,
  startup standby and unsafe Voc; they do not alter the baseline fixture.
- Final controlled three-interval run/setup observation: **37.64 s**;
  compact selected-state JSON **13,658 bytes**; standard Parquet **29,822 bytes**;
  whole production package **416,441 bytes**, including pinned scientific inputs
  and normal manifests; full diagnostics were not persisted. Its immutable
  diagnostic canonical payload is **1,161,691 bytes**, recorded by hash.
- Controlled one-interval execution: **12.76 s**; compact JSON **8,431 bytes**;
  Parquet **29,363 bytes**. Explicit reference execution's diagnostic JSON is
  **901,709 bytes** (canonical payload **412,286 bytes**). The separately controlled
  original Phase 6.8C direct reference payload remains **406,699 bytes**.
- Process peak RSS during the final focused fixture observation:
  **216,668 KiB (~211.6 MiB)**. This is whole-process high-water RSS, not isolated
  backend allocation or an annual memory bound. Timing is an observation from
  this environment, not a benchmark guarantee.

Remaining unsupported physics/scales: nonzero downstream module quality without
an evidence-bound declaration; mixed dark/active strings on one MPPT; heterogeneous effective quality factors;
constrained-current IV tracking; reverse/backfeed current; invented MPPT power
limits; regional temperature gradients/detailed-IV thermal feedback; unsupported
anisotropic transposition/transient thermal configurations; heterogeneous active
tracker voltages with positive global DC-array resistance. Annual-scale execution
has not been validated or accelerated, and diagnostics still consume memory
inside the frozen backend. Attribution and browser UI are not implemented.

`HEAD` and `phase-6.8-validated` both remain
`fbf345c9911306605072ef2720271a8d2d0c76be`. No Phase 6.1–6.8 test source or tolerance,
Phase 6.6–6.8 kernel was changed. Closure narrowly extends the detailed
producer/adapter and dark-state handling in the loss/inverter consumers. No commit was made.


## Phase 6.9A closure checkpoint

The closure stops here; Phase 6.9B attribution, browser UI, annual acceleration,
and new physical shading models are not implemented. No commit was made.

Files changed:

- `engine/simulation/detailed_backend.py`
- `engine/simulation/detailed_downstream.py`
- `engine/simulation/detailed_dispatch.py`
- `engine/simulation/detailed_inputs.py`
- `engine/losses/array.py`
- `engine/inverter/model.py`
- `schemas/detailed-mppt-backend-result.schema.json`
- `schemas/detailed-selected-mppt.schema.json`
- `shading/electrical/electrical-parameterization-evidence.schema.json`
- `tests/integration/test_phase69a_closure.py` (new)
- `tests/integration/test_phase69a_detailed_backend.py`
- `docs/phase69a-detailed-pcc.md`
- `docs/phase69a-detailed-mppt-backend.md`

The inactive contract is `inactive_dark`, with
`inactive_reason=no_photovoltaic_operating_point`, exactly zero PV DC power,
and unavailable selected operating point, tracker state, IV curve, Voc, Isc,
voltage and current. Module/local-state provenance, MPPT/string identities,
interval/evaluation identity and scientific hashes remain bound. An inactive
branch's zero contribution to aggregate array current is not a selected tracker
current. Inactive tracker constraints have no operating point to evaluate;
known current-limit availability is preserved and its violation result is null.

The real canonical daylight → dark → daylight fixture gives:

| Interval | PV DC W | PCC W | Selected V | Selected A |
| --- | ---: | ---: | ---: | ---: |
| Daylight | 701.7163393820699 | 228.43972002340652 | 80.84892266768922 | 8.679352998509485 |
| Dark | 0 | -2 | unavailable | unavailable |
| Daylight | 1376.2543190509427 | 992.3404912388115 | 79.41146286205155 | 17.330675817440646 |

Its three explicit hourly intervals integrate to **1218.780211262218 Wh** at
PCC. Replay has identical numerical bytes and scalar time series. A 900-second
dark interval with 2 W night consumption gives **-0.0005 kWh (-0.5 Wh)**.
A fully dark single MPPT and a controlled independent dark/active MPPT pair also
pass. No dark curve, Voc or tracker operating point is fabricated.

Module-quality declarations live in parameterization evidence, binding the signed
fraction, rationale and registered sources to the existing exact parameterization
payload digest and module/topology revisions. Frozen selection replay and
run-package verification validate declaration shape and source bindings, in
addition to scientific identities. Tampering with the declaration is detected
even after outer package checksums are regenerated.

| Jinko resolved quality -0.0075 | Additional downstream scalar | PCC continuation |
| --- | --- | --- |
| `separate_from_parameterization` | Signed loss -0.0075: power ×1.0075, once | Allowed when value/evidence bind |
| `embedded_in_parameterization` | None; no second quality factor | Allowed when value/evidence bind |
| `unknown` or missing declaration | None | Blocked; selected MPPT physics remains valid |

Zero quality proceeds under every declaration. No Jinko catalog declaration was
invented: the three explicit declarations in tests are controlled calibration
fixtures, not manufacturer evidence or a PAN-tolerance inference.

Validation:

- Broad focused suite: **111 passed**, **514.91 s**, one existing Starlette/httpx
  deprecation. Log: `/tmp/rawibumi-phase69a-closure-focused-complete.log`.
- Final closure/input-binding focused rerun after strengthening frozen replay:
  **27 passed**, **165.69 s**. Log:
  `/tmp/rawibumi-phase69a-closure-binding-focused.log`.
- Complete suite on the final implementation: **798 passed**, **679.37 s**, the
  same existing deprecation. Log: `/tmp/rawibumi-phase69a-closure-full.log`.
- `git diff --check` passes. Existing daytime parity, legacy sign conventions,
  `_run_fixed_tilt()`, electrical kernels and numerical tolerances are preserved.

The sandboxed API regression stalled at FastAPI/TestClient; the approved sandbox
override allowed the broad focused and complete suites to finish. An initial
full run was interrupted to strengthen declaration validation during frozen
replay; the final complete run above includes that change.

Remaining Phase 6.9A limits: unknown nonzero quality; heterogeneous effective
quality factors; mixed dark/active strings on one MPPT; constrained-current IV
tracking; reverse/backfeed and new tracker power-limit physics; heterogeneous
active voltages with positive global DC resistance; regional temperature gradients
and detailed-IV thermal feedback; unsupported transposition/thermal variants.
Annual scale is not validated or accelerated and full diagnostics still consume
memory. Electrical-shading energy attribution remains unavailable. Phase 6.9B
attribution and browser UI remain outside this closure.
