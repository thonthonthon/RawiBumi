# RB-REV-A — independent review, batch A

Reviewed 2026-11-13 at `5e2278641401fd10dc95f57de7f438aba18e74c8`, branch `feat/use1-usable`.

What this change does: these five commits add MPPT current limiting, annual Gaussian Pxx, row-phase packing and per-tracker string lengths, browser self-shading, and stored-series reporting. The ordinary numerical cases pass, including direct U1 parity. Five MAJOR findings prevent acceptance of USE1, UNC1 and USE3b.

Authority: `AGENTS.md`, then `.ai/TASK.md` (RB-REV-A). Archived work orders and validation evidence were read as evidence, not substituted for the active order. No source, test, schema or config was changed. Only this report was written in the repository. Tests and exploratory runs used temporary storage; no server port was opened. Pre-existing tracked changes under `var/weather` were left untouched. No commit, push, checkout, index or branch mutation was performed.

## Findings

### A1 — MAJOR — the MPP power cap invents a voltage and can admit an out-of-window operating point

**Commit:** `c199136` (USE1). **Location:** `engine/inverter/model.py:484`, especially line 488; voltage-window consumption at line 581.

**Scenario → wrong result:** use `tests/unit/test_rb_use1_usable.py::mppt_frame(resistance=3.0)`: 14 modules in series, two parallel strings, current factor 0.95, the test's diode parameters, and a 3 Ω circuit. Set the current limit to 99% of the post-loss MPP current, `24.817376101347005 A`, and the inverter's upper MPPT voltage to `777 V`.

The solved terminal voltage is **777.2647285393431 V**, outside that window. Capping power at the old MPP and then assigning `vmp = power/current` changes it to **776.5269524461278 V**. The inverter consequently accepts **19,271.361431688354 W DC**, reports **zero voltage-threshold loss**, and produces **18,884.765892718482 W net AC**. Under the existing drop-whole-MPPT policy, the solved point should be rejected.

**Evidence:** executed the fixture through both `constrain_mppt_current` and `simulate_voltage_dependent_inverter`; independently evaluated `14 * v_from_i(limit/(0.95*2), *SDM) - limit*3`. The cap counter was one. The same issue exists at the ordinary 0.4 Ω fixture resistance, although the voltage displacement near the cap is much smaller.

**Assessment:** the documented conservative power cap is defensible as an accounting convention; changing the physical voltage to preserve `P=VI` is not sufficient to establish a new point on the IV curve. That voltage subsequently governs eligibility and voltage-dependent efficiency. Keep the power convention and the solved-voltage authority explicit; resolving their relationship requires the engineering decision called for by the work order.

**Test gap:** the cap test only asserts `limited_power <= old_power`. It never checks the capped voltage against the solved curve or exercises a window edge.

### A2 — MAJOR — suggestion sizing copies the first MPPT's input capacity to every MPPT

**Commit:** `c199136` (USE1). **Location:** `apps/api/stringing_suggestion.py:113`–119.

**Scenario → wrong result:** a supported explicit two-MPPT inverter has input counts **1 and 2**, both trackers allow 12- or 13-module strings, and the pool contains 38 identical enabled modules. The suggestion uses `[[13], [13]]`: **26 modules used, 12 left**. The valid layout `[[12], [13,13]]` uses all 38.

**Evidence:** ran `suggest_mppt_layout` against a temporary `Project(..., 38, weather=False, strings=False)` with an explicit two-tracker definition. The window was set from the validator's module state to `11.9 * Vmp_hot` through `13.1 * Vmp_cold`; operating and short-circuit limits were 100 A. Rebuilt the canonical tracker instances with `change_inverter_definition`. Applied `[[12], [13,13]]` to a separate trial through the real topology editor and ran `validate_design`: **no INVALID findings**. The actual suggestion returned `modules_used=26`, `modules_left=12`.

The helper already accepts a tracker index, but it is called once with `specs[0]["index"]`, outside the loop. Candidate validation prevents an overfilled tracker from being accepted in the opposite case; it cannot recover valid candidates omitted during sizing.

**Required correction:** resolve each tracker's own capacity before ranking candidates. Test unequal explicit input counts, including the reversed order.

### A3 — MINOR — the detailed branch cutoff does not cover the accepted quality-gain range

**Commit:** `c199136` (USE1). **Location:** `engine/simulation/detailed_downstream.py:99`–107; missing-model check at `engine/inverter/model.py:454`.

**Scenario → wrong result:** the raw selected point is `(600 V, 16 A)` and the current limit is 20 A. `_current_limit_branch` omits the curve at exactly 80% of the limit. An explicit module-quality fraction of `-0.30` makes `k=1.3`, moving the post-loss current to **20.8 A**. The inverter then refuses the interval for lack of an IV model, although the sampled curve was available upstream.

**Evidence:** executed `_current_limit_branch` on the curve `(600,16), (650,10), (700,0)`, obtaining `{}`; passed the correctly scaled post-loss frame to `constrain_mppt_current`, obtaining the “carries no IV model; full IV operating-point solving is required” error. `engine/losses/array.py` and `schemas/loss-settings.schema.json:148` accept quality fractions strictly between -1 and 1. The 0.8 cutoff only guarantees coverage for gains below 25%.

This fails closed and does not fabricate energy. The large gain is an edge case, not a claim about a typical module. The branch-retention decision nevertheless needs to cover the accepted input domain or declare and enforce a narrower domain. The existing cutoff test does not apply a downstream gain.

### A4 — MINOR — the legacy chain's stage-order metadata omits the current-limit stage

**Commit:** `c199136` (USE1). **Location:** `engine/losses/chain.py:115`–125, a caller not updated by this commit.

**Scenario → wrong result:** call the legacy `simulate_electrical_loss_chain` with a binding 22 A limit. Its ledger includes `dc_wiring → mppt_current_limit → mppt_voltage_threshold`, but the enclosing result's `metadata.stage_order` still says `dc_wiring → mppt_voltage_threshold`.

**Evidence:** executed the raw single-diode fixture with quality `-0.0075`, module mismatch 0.02, string mismatch 0.01 and 0.4 Ω wiring. Current-limit loss was **1,762.6740490145603 W** and ledger annual residual was **0 kWh**. Printed both metadata lists: only the ledger list contains the new stage. The staged-chain return already derives its order from the ledger.

Energy accounting passes; consumers of the legacy chain's declared execution order receive incomplete provenance. Test the enclosing result as well as `with_current_limit`.

### A5 — MAJOR — the packer's estimate can hide the best exact phase entirely

**Commit:** `5e22786` (USE3b). **Location:** `geometry/pvfield/packing.py:299`, and the estimate gate at lines 433–437.

**Scenario → wrong result:** a one-module-wide roof has vertices `[(0,0), (1,-0.2), (1,6.1), (0,6.3)]`. Use the existing packing-test module (physical width 1 m, height 2 m), portrait, tilt 10°, azimuth 0°, pitch 2 m, zero gaps and setbacks. The production packer returns **two modules**. Phase `k=2`, offset **0.25 m**, passes the existing exact rules with **three modules**.

**Evidence:** executed the production packer and separately enumerated all 16 phases with `_candidate_valid`, using the same x centre, footprint and `last_y` bound. Exact counts were `[2,2,3,2,2,2,2,2,2,2,2,2,2,2,2,2]`. `_phase_estimator` returned **zero for every phase**: `contains_properly` excludes the rectangles touching the roof's vertical edges, while the exact rule permits those contacts at zero setback. Production therefore chooses phase zero and never exact-checks phase two. Forcing phase two's ranking in memory also produced three actual packed modules with the normal exact placement guard.

The exact guard guarantees that an adopted shift beats the anchor. It does **not** guarantee the requested maximum accepted count: approximate ties and misrankings can suppress better candidates before the exact check. This case also exercises the last-row bound; all three winning centres, approximately `1.034808, 3.034808, 5.034808 m`, are within it.

**Required correction:** the estimate must not determine which potentially better exact placements are unreachable. Add a boundary-touching narrow-roof regression, alongside the current wide-roof skew example. Preserve the strict exact comparison so true ties retain phase zero and its identities.

### A6 — MAJOR — the per-MPPT length search misses valid layouts when shorter strings must come first

**Commit:** `5e22786` (USE3b). **Location:** `apps/api/stringing_suggestion.py:59`–70.

**Scenario → wrong result:** allowed lengths `[12,13]`, capacities `[1,2]`, pool 38. `_layouts` ranks `[[13], [12,12]]` first: **37 used**. It never generates `[[12], [13,13]]`: **38 used**. The search assigns the longer length only to a prefix of MPPTs, so reversing the required length order is impossible.

**Evidence:** directly executed `_layouts([12,13], [1.0,2.0], 38)`. Also isolated this from A2 in the temporary real-project test: gave both MPPTs two physical inputs, but limited the first tracker's design Isc capacity to one string (`Isc_max = 1.5 * module_design_Isc`). The actual suggestion returned **37 used, 1 left**. Applying the 38-module alternative through the editor and `validate_design` again yielded **no INVALID findings**.

An additional small exhaustive comparison found the same omission for lengths `[4,5]`: capacities `[1,2]`, 14 modules, gives 13 instead of 14; capacities `[2,1]`, 13 modules, gives 12 instead of 13. These are feasible omissions, not disagreements about tie-breaking.

**Test gap:** both existing `_layouts` assertions use equal capacities. Validation of generated candidates does not establish completeness of candidate generation.

### A7 — MINOR — the chosen row phase is not recorded in packing metadata

**Commit:** `5e22786` (USE3b). **Location:** `geometry/pvfield/packing.py:438`, and result construction at lines 564–592.

**Scenario → wrong result:** a skewed roof causes the search to choose a shifted row grid. The returned field and `PackingResult` contain positions and an input hash, but no phase step or offset. A caller expecting the explicit phase record required by the USE3b work order cannot inspect which offset won.

**Evidence:** inspected the assignment and all result construction; inspected the returned fields in both small-roof and 10,000-module probes. No offset/phase field was emitted. Archived `.ai/TASK.RB-USE3B_ACCEPTED.md`, scope item 1, explicitly requires recording the offset in the result's packing metadata. Positions allow later inference in some cases, but are not the promised metadata.

Use existing permitted metadata rather than changing a public schema without approval. Add an assertion for a nonzero winning phase and for zero on a tie.

### A8 — MAJOR — annual Pxx trusts the mutable bundle summary instead of the verified run mean and period

**Commit:** `65972bd` (UNC1). **Location:** `apps/api/study.py:863`–886 and line 898.

**Scenario → wrong result:** complete a genuine **24-hour** temporary browser run and save a valid uncertainty ledger. Change only the bundle copy of its `summary_result.annual_energy_wh` to `1e9`, retaining the run ID and input hash. The immutable package still has `annual_energy_wh = null`, `period_duration_hours = 24`. The Pxx route nevertheless returns **status `available`, P50 = 1,000,000 kWh**, with a newly computed source hash for the changed copy. Marking that record `package_omitted=true` also leaves Pxx available.

**Evidence:** executed this sequence using the existing `Project` fixture, its temporary store and the real `annual_pxx` service. Read the package's `summary-result.json` to establish the unchanged 24-hour authority. The route never invokes the verified source/summary boundary used by S15. The deliverable path at `apps/api/study.py:845`–850 reads its main summary from the verified package but obtains Pxx from this mutable copy, so the two sources can disagree inside one deliverable.

This is a provenance and eligibility defect, not a Gaussian-formula defect. The hash describes supplied bytes; it does not prove that they belong to the verified run result. Imports or damaged/stale bundle summaries must not silently replace the canonical mean. UNC1's archived route scope also lists `PACKAGE_OMITTED` as an unavailable reason.

**Required correction:** bind mean, period and source hash to the authoritative run result, and explicitly handle missing packages under the approved provenance policy. Test disagreement between bundle and package, a partial-year run with a misleading bundle flag, and summary-only imports. Current tests only exercise an honest partial-run summary.

### A9 — MINOR — zero or negative production loses the installed DC nameplate in S15

**Commit:** `0dc2e5e` (S15). **Location:** `reporting/exports/series.py:71`–73 and lines 96–103.

**Scenario → wrong result:** an installed array has a completed zero-output period, for example when its DC is rejected by the inverter window. Its total energy and specific yield are both zero. `monthly` returns `dc_kwp=null`, monthly specific yield `null` and PR `null`, even with positive unshaded POA; the corresponding finite-capacity values should retain the installed nameplate and zero yield/PR. A net-consuming period similarly fails the `yield > 0` gate.

**Evidence:** executed `monthly` on a one-hour `ExportSource` with `pcc_power_w=0`, unshaded POA 1,000 W/m², explicit 3,600 s duration, and a matching zero-energy summary. Reconciliation passed, but all three fields were null. The engine's KPI function supports zero and negative grid energy with a positive installed capacity. The selected energy/yield inversion is undefined at zero, so this is a limitation of the reporting reconstruction rather than a second physical nameplate definition.

Retrieve the run's authoritative installed capacity for this case; do not substitute the current design's module count. Existing S15 tests cover positive production only.

### A10 — MINOR — the active approved-contract inventory is incomplete

**Commits:** all five, as detailed below. **Location:** the concrete source boundaries in the table; comparison against `.ai/TASK.md`, “Contracts”.

**Scenario → discrepancy:** accepting the batch as containing only the active order's enumerated contract changes would omit the following observable response, run-record and export changes. This is an approval/traceability finding, not a claim that these additions caused a runtime failure. Several have explicit earlier user approval in the archived work orders; they should not be described as newly unauthorized.

| Commit | Boundary and file:line | Additional observable contract / evidence |
|---|---|---|
| `c199136` | `apps/api/service.py:2183`; `apps/api/catalog.py:129`; `apps/api/catalog.py:84`; `engine/inverter/model.py:722` | Electrical dry-run adds `topology_checks`; catalogue adds `inputs_per_mppt`, `inputs_per_mppt_source` and `superseded_by`; inverter result metadata adds per-tracker binding/cap counts. Read the commit diff and USE1 A3–A4 notes. |
| `65972bd` | `apps/api/server.py:1260`, `apps/api/server.py:1264`; `reporting/exports/csv_export.py:281` | GET annual-Pxx view, PUT uncertainty-assumptions request, and optional `annual-pxx.json`/manifest fields extend the bundle-field approval. Explicitly described in UNC1's archived decisions and implementation notes. |
| `5e22786` | `apps/api/stringing_suggestion.py:157` and line 152 | Suggestion adds `string_lengths`; rejected candidates use `layout` instead of the earlier `string_length`. The retained top-level `string_length` now means the maximum, rather than a common length. Read the parent/current diff. The summary route itself is already on the active approved list. |
| `ce6c0d2` | `apps/api/study.py:758` | New run-record field `module_self_shading`; the configuration default also intentionally changes physical results for generated fields. Explicitly approved in archived 4D amendment A2. |
| `0dc2e5e` | `apps/api/server.py:97`, `apps/api/server.py:1268`; `apps/api/study.py:760`; `apps/api/catalog.py:106` | Export request gains `formats`/`deliverable` and a new deliverable file/manifest contract; GET timeseries returns a new view; run records gain `readiness_warnings`; catalogue gains `nominal_power_w`. S15's archived decisions also explicitly approve the nominal-vs-model-Pmp reporting/validation basis alignment. |

The two schema-file additions in this batch are the approved optional compact `current_limit_branch` and bundle `uncertainty_assumptions`. The carried SDM columns remain internal, selected explicitly out of standard exports. No additional unit conversion defect or canonical topology-contract change was found. S15 intentionally changes validation/display capacity from model STC Pmp to datasheet nominal power; the SDM and temperature-coefficient physics continue to use their existing values. The active inventory should reflect these archived approvals and the changed suggestion response semantics.

## Numerical checks that passed, and their limits

- **Standard constrained point:** the required test independently bisects `i_from_v`; the 22 A constrained point matches the `v_from_i` implementation within the asserted 1e-9 relative tolerance, lies right of the raw MPP and reduces power. Current scaling divides by both `k` and parallel-string count. The series-module factor and voltage drop are applied after the module solve.
- **Recovered loss mapping:** independently ran the staged chain with LID 0.01, quality -0.0075, module mismatch 0.02, string mismatch 0.01, degradation 0.02 and resistance 0.4 Ω. Recovered `k=0.9483477002999998`, versus the factor product `0.9483477003`; recovered `R=0.39999999999999797 Ω`. This verifies the independent-circuit `preserve_vmp_map_power_factor_to_imp` mapping. It does not establish a general coupled-network interpretation of legacy pooled equivalent resistance after unequal tracker changes.
- **Ledger reconciliation:** the legacy binding case in A4 closed at 0 kWh annual residual. The staged case above lost 1,283.4511904490391 W to the current limit and closed within `7.105427357601002e-15 kWh`. The required suite also passed its inverter identities, channel placement, mixed known/unknown-limit zero-fill and monthly reconciliation checks. Algebraic closure does not validate A1's off-curve voltage.
- **Detailed branch:** the existing secondary-peak test selects `(900 V,19.9 A)`, **17,910 W**, instead of the 25 A boundary at about **15,583.33 W**. A separate one-interval canonical shaded fixture with a binding 2 A limit completed, carried its branch, verified its package and reconciled: raw DC 701.7163393816724 W, limit loss 519.5128108397616 W, remaining DC 182.2035285419107 W, annual residual 0 kWh. This case's PCC output was zero because of the downstream power threshold; it is a branch/ledger test, not evidence of nonzero-AC efficiency parity under limiting. Continuous-curve optimality beyond the sampled representation was not claimed or tested.
- **No-bind identity:** loaded `c199136^:engine/inverter/model.py` into an isolated in-memory module, without checking out or writing it. Every one of its 17 pre-existing output columns was exactly equal to the current implementation on the nonbinding fixture. Source review confirms unchanged original SDM solves and original converter arithmetic on the identical-string, nonbinding path; extra zero channels do not alter those powers. This supports the planner's reported 31,830,825.79661493 Wh identity, but I did **not** independently rerun that real-weather annual or claim an independent measurement of that number.
- **U1:** read the original U1 release ZIP from the allowed anchoring directory, SHA-256 `ed6097c2228381bb112e597614f47457143a2e800365a699b2bc56eda36a7fa9`. Executed its kernel in memory and compared all three original input/result fixtures directly with the native kernel. Quantiles, sigma, covariance, variance components, negative-support probability and signed allocations were exactly equal. P90: independent **421,165.08977524645 kWh**, correlated **413,800.9885890888 kWh**, explicit-zero **450,000 kWh**. The PSD elimination and tolerances match the original U1 implementation. Required tests passed the non-PSD, singular-PSD, double-count, negative-tail, zero-sigma and fraction/kWh cases. P99 remains unavailable. Honest historical/typical-year labels pass; A8 concerns the authority of the mean, not the chosen historical-year-as-mean policy.
- **Pitch and topology lifecycle:** required tests passed the independent pitch formula for aligned and side sun, horizon refusal, removal retaining unassigned strings, undo, model change retaining existing tracker indices, and engineering current-warning versus Isc-blocking behavior. No change to canonical units or the definition of series/parallel topology was found in those paths.
- **Self-shading policy:** `study._phase5_configuration` enables self-shading for every browser run, and the run record records the flag. The archived 4D report supplies multi-row on/off measurements and a single-row control; those annual measurements were read, not rerun. The added 4D test was also run independently, as recorded below.
- **One DC nameplate:** `module_nameplate_w`, the existing engine installed-capacity selection and the updated validation/UI callers use nominal power when provided, else STC Pmp. The existing 550 W nominal versus unequal model-Pmp fixture passes. A9 covers the reporting inversion's zero-production edge.

## Packing correctness and cost

True exact ties cannot change placement: the final comparison is strictly `>`, and approximate score ties prefer step zero. The unchanged-layout tests and the large aligned probe preserved entire generated module-instance records, including IDs. Existing phase-4.3 tests passed rebuild/identity behavior. A5 concerns missed improvements, not an invalid or worse adopted placement.

Timing probes used the 1 × 2 m packing-test module, 10° tilt, 100 m-wide roofs and about 100 rows. “Old” disables only the new estimator/search in memory, preserving the original anchored placement loop; no source was edited. Each row below is a single measurement on this host, not a stable performance benchmark.

| Roof | Anchored count → searched count | Anchored → searched seconds | Ratio | Identity |
|---|---:|---:|---:|---|
| 100 × 200 m aligned, pitch 2 m | 10,000 → 10,000 | 0.558 → 1.128 | 2.02× | Entire module records identical |
| Same size, low edge skewed 0.2 m | 9,900 → 9,990 | 0.577 → 1.752 | 3.04× | Placement changes as expected |
| Aligned, pitch equals projected module depth | 10,000 → 10,000 | 0.541 → 1.181 | 2.18× | Entire module records identical |

The archived USE3b amendment accepts exceeding 2× when a better layout is found, covering the skewed outcome. The unchanged examples slightly exceed the original 2× budget on this host. There is no timing/work budget in the implementation: all 16 estimates run. Treat the unchanged-layout budget as unproven across inputs and machines; the single timings are insufficient to assign a separate major performance defect. Hole/obstacle setbacks are still enforced by the original exact rule. Nonzero setback/hole boundary combinations were inspected but not exhaustively enumerated across all phases.

## Test adequacy and execution

The principal coverage gaps correspond to A1–A9: cap-induced voltage eligibility; unequal tracker input and Isc capacities; quality gains crossing the branch-retention threshold; the legacy enclosing metadata; approximate ties that conceal exact improvements; phase provenance; unverified bundle/verified-package disagreement; and zero/net-consuming reporting periods. The current secondary-peak assertion checks the helper on a hand curve, while the existing detailed integration fixture explicitly uses an unknown current limit. Passing those tests alone is not end-to-end evidence for a binding shaded limit. The additional canonical probe above covers one binding interval, with the stated zero-PCC limitation.

Required command executed unchanged, with environment-only isolation (`PYTHONDONTWRITEBYTECODE=1`, temporary `RAWIBUMI_PROJECT_STORE` and `TMPDIR`, and `PYTEST_ADDOPTS` disabling the cache provider and placing pytest basetemp in `/tmp`):

```text
.venv/bin/python -m pytest -q tests/unit/test_rb_use1_usable.py tests/unit/test_rb_use3b_quick_fixes.py tests/unit/test_engine_inverter.py tests/unit/test_rb_unc1_annual_pxx.py tests/unit/test_rb_s15_results_export.py tests/unit/test_phase43_pvfield_packing.py tests/integration/test_phase69a_detailed_pcc.py
```

**Result: 109 passed, 3 warnings in 140.79 s.** Warnings: one existing Starlette/httpx deprecation and two pvlib divide-by-zero warnings in the annual synthetic-weather fixture. No failure was bypassed or test changed.

Additional pytest command, with the same temporary-storage/cache isolation:

```text
.venv/bin/python -m pytest -q tests/unit/test_rb_4d_self_shading.py
```

**Result: 1 passed, 1 warning in 2.73 s.** The warning is the same existing Starlette/httpx deprecation. The numerical, suggestion, packing and provenance probes described above ran as inline Python with assertions/printed values and temporary projects, or entirely in memory. They were not added as test files, in accordance with the write restriction.

## Verdict per commit

| Commit | Verdict |
|---|---|
| `c199136` — USE1 | **Blocked by A1 and A2 (MAJOR).** Also A3/A4 and its contract inventory entries. |
| `65972bd` — UNC1 | **Blocked by A8 (MAJOR).** The native U1 mathematics passes; run-result provenance does not. |
| `5e22786` — USE3b | **Blocked by A5 and A6 (MAJOR).** Also A7 and the performance/contract notes. |
| `ce6c0d2` — 4d | **PASS**, with the nonblocking contract-inventory note A10. No independent repeat of its annual on/off measurements. |
| `0dc2e5e` — S15 | **PASS**, with nonblocking A9/A10. Positive-production monthly reconciliation and nominal-power alignment pass. |

These are per-commit findings, not approval of the combined branch: inheriting the blocked commits prevents a batch-A PASS. No BLOCKER-severity finding was established. Assumptions are explicit throughout: sampled shaded curves, existing drop-whole-MPPT voltage policy, original U1 additive Gaussian method, and synthetic temporary fixtures. Broader UI review belongs to batch C; broader data/history review belongs to batch B.

Not checked: the full suite, live/demo browser suites, real user projects/weather/library, or the planner's real-weather annual identity measurement. No production source was repaired; the MAJOR findings remain open.
