# RB-POST3D-03 — Inverter loss and scientific plausibility audit

## 1. Executive verdict

The retained 48-hour ERA5 run is internally consistent. Its 54.0441615% energy-weighted conversion efficiency follows exactly from the effective inverter curve and the fixture's extremely low load. No conversion units defect or overlapping-loss double count is demonstrated. This is a **FIXTURE_PARAMETER_LIMITATION**, not proof of a physically accurate installation model: a four-module 2.2 kWp array uses a 100 kW inverter definition whose MPPT minimum was deliberately changed from 200 V to 0 V. Actual selected voltages are below every efficiency anchor.

PCC energy is 7705.373802786161 Wh and PR is 0.38190241009638576. Package integrity, numerical consistency, physical inverter validity, design approval and measured-yield validation are separate dimensions. Only the first two have affirmative evidence here. Run timestamps also have a concrete metadata limitation: both fields contain the same entry-event timestamp, not measured start and completion events.

## 2. Repository and artifact checkpoint

Read-only inspection on 2026-10-10: branch `ai/rb-post3d-03-inverter-plausibility-audit`; HEAD `ca86a597f41a00a0bdba33341cb9bd4eb154ed2d`; initial `git status --short` empty, including the index. Only this document is authorized to change. No tests, builds, benchmarks, weather requests, simulation reruns or package verification were executed. Regression is **SKIPPED (documentation-only)**; independent review and orchestration checks remain pending. Numerical inspection used existing pandas/JSON support with bytecode writes disabled, without importing fixture constructors or creating intermediate files.

The plan's assertion that complete component content is missing is incorrect: `detailed-execution-context.json:inputs.component_revisions` persists it in full. Its canonical JSON SHA-256 independently computes to `7f7172dbf42387bb0b2e38f5d151033fa894eccc88d188d7cb99f5384696ad73`, matching the recorded component hash. No reconstruction by executing test helpers was needed. Existing `claude_review_3.json` concerns the earlier streaming attribution reader, with zero blockers/majors, rather than this task; it does not establish acceptance of this audit.

## 3. Evidence map and package identity

All paths below are repository-relative. Define **J** as `.ai/validation/rb_post3d_02/7ddfc7afb1bf43e3b1445d6886520658/`, **P** as `J/packages/run-7ddfc7afb1bf43e3b1445d6886520658/`, and **W** as `J/weather/proj-phase38e-r1/era5-7ddfc7afb1bf43e3b1445d6886520658-r1/`. These aliases expand literally to the retained artifact paths.

| Evidence | Actual artifact and use |
|---|---|
| Supervisor outcome | `J/report.json`: PASS; direct canonical entry point; engineering validation not exercised; physical accuracy not established |
| Existing independent verifier | `J/verification.json`: status passed, returned completion manifest with 58 artifacts; `P/run-package-manifest.json` |
| External timings | `J/execution-resources.json`, `J/verification-resources.json`; both process logs exist and are empty |
| Source weather | `W/acquisition-manifest.json`, `W/weather-dataset.json`, `W/weather-series.parquet` |
| Scientific inputs | `P/detailed-execution-context.json`: full configuration, components, scene, design, frozen selection and numerical policy |
| Outputs | `P/simulation-run.json`, `P/summary-result.json`, `P/timeseries.parquet` (48 rows, 44 columns), `P/reproducibility-manifest.json` |
| Detailed operating states | `P/detailed-selected-mppt.json`; `P/detailed-electrical-interval-index.json`; `P/detailed-electrical-intervals/chunk-00000000.json` through `chunk-00000047.json` |
| Attribution | `P/detailed-dc-attribution.json`, `P/detailed-dc-attribution-energy-summary.json` |

Run ID is `run-7ddfc7afb1bf43e3b1445d6886520658`; project `proj-phase38e-r1`, scene `scene-phase38e-r1`, electrical revision `elec-phase38e-r1`, configuration `simcfg-phase38e-001`, engine version `rb-post3d-02`. Weather ID is `era5-7ddfc7afb1bf43e3b1445d6886520658`, revision that ID plus `-r1`. Component revisions are `inv-phase38e-huawei-r1` and `mod-rawibumi-uat-550-r1`. Fixture identity is `987dae99268c158410bf4e567ec9c3cbd746b8e352c9b623d7244ed3c203b8eb` (runner's preserved unaffected-input identity, not a design approval).

Canonical/detailed scientific input hash is `3dab7ff8ad9611027e5088d1947eaeb0b4368797c84fa051f4f80d4fc0d76760`; execution identity `e99bffe6f9290e60462ade9327b6b8151e7a017487904160bd37fa8191f9afee`; numerical result `6582e43c9f74b53ee83fe41aa4932bc053be78cd43914846b01cea2505e6a22f`; compact result `b69cee3ee3f8d69cd166a20b56c36246052dd9c6991330882c8b248455310dd5`. Requested/resolved fidelity is `level_2_bypass_substring`, support `pcc_complete`, fallback false, failure reasons empty.

The actual timeline is June 30 00:00 through July 2 00:00 exclusive, UTC+07:00, 48 × 3600 s; midpoint solar evaluation, zero offset. Configuration uses SPA, isotropic POA, PVSyst steady-state thermal, single-diode module physics, ideal global MPP, 101 string samples, workers 1/1 and diagnostics false (runner settings). Detailed curves remain present in retained chunks.

Full source contains 8784 rows, December 31 2024 06:00 through January 1 2026 05:00 inclusive; 8760 starts belong to local 2025. Raw response SHA-256 is `865eda75bc207417b8174c1ccf87be2294ca5b3d1869e54067b0adab1a8ac1da`; full-source weather fingerprint is `d3af981735ac9c39e1d3d2aee840189e71fea2b84a74ba5a6b305f65b298ff26`, unchanged before/after and on persistence. Manifest logical weather-series hash is `83cc12ecb837548bad215e5f395e6a9f8dfaf54fcce763318e520c9f683c0fa0`. Detailed dispatch hashes this logical-hash string again through canonical semantic hashing, giving `e6e6d5ac8f6f1eba00033de276ed9ee6ff7e02706c48e0fa80adf8d9399235cd`; these are different hash definitions, not a mismatch.

`tools/rb_post3d_02_era5_validation.py:bind_fixture` preserves full weather and fixes the period. `engine/simulation/detailed_dispatch.py:run_detailed_dispatch` hashes full inputs before `_select_weather_period` executes the selected 48 rows; configuration period plus numerical interval identities bind execution to the window. `engine/simulation/detailed_downstream.py:complete_detailed_run` also hashes the selected weather dataset metadata, whereas context retains the full dataset. Do not interpret differently scoped dataset hashes as corrupted weather. `docs/audits/rb_post3d_01_real_weather_execution_audit.md` and `docs/validation/rb_post3d_02_era5_validation.md` describe this architecture; this audit uses actual retained artifacts for results.

## 4. Component and inverter curve provenance

`tests/unit/test_phase38e_canonical_simulation_run.py:_inverter_definition` parses `tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND` with `components/ond/parser.py`, maps it via `components/ond/mapper.py:map_ond` and `components/ond/mapping-ledger.yaml`, and builds the candidate via `components/candidates.py:build_inverter_candidate`. `components/ond/semantics.py` assembles voltage curves from Pin/Pout pairs, efficiency = Pout/Pin; trailing zero padding is not an operating point. PNomConv=100.000 is **kW**, converted to 100000 W; curve pairs and PSeuil are already W. There is no missing factor of 1000 in the effective persisted data.

The manufacturer fixture README/provenance identifies a maintainer-supplied manufacturer-distributed file, `DataSource=Manufacturer 2018`. This supports source provenance, not measured accuracy at the simulated load and voltage. It would be incorrect to call the original OND wholly synthetic. The effective integration revision is intentionally altered: `tests/integration/test_phase69a_detailed_backend.py:_canonical_fixture` sets MPPT minimum 0 V, maximum 1000 V, current limit None; `tools/benchmark_phase610_fixtures.py:build_fixture` chooses B2 and quality override zero. The persisted definition proves those exact overrides despite retaining the Huawei label and revision ID.

| Effective field | Value / interpretation |
|---|---|
| Model | `inverter.voltage_dependent_efficiency.v0.1`, voltage-dependent curves |
| AC nominal / maximum | 100000 / 110000 W, three phase, nominal 380 V; current nameplate 152 / 168.8 A |
| Absolute DC voltage | 1100 V maximum |
| MPPT window | 0–1000 V effective; OND originally 200–1000 V; nominal 1000 V |
| MPPT inputs | Template 10 trackers / 20 inputs; actual fixture uses one MPPT, two parallel two-module strings |
| Physical operating-current limit | None; 40 A array-sizing field is a contractual limit, not physical clipping |
| Startup / minimum | No separate startup field; minimum_input_power_w=500; strict accepted power >500 activates conversion |
| Night / standby | 2 W night; no standby value, runtime defaults to 0 W |
| Derating | 110 kW at 30°C, 100 kW at 40°C, 36 kW at 60°C, absolute limit 62°C; temperature basis unknown |

Voltage anchors are 200, 650 and 1000 V; all three have identical Pin/Pout pairs: (500,0), (3000,2831.2), (5000,4818.5), (10000,9784.5), (20000,19707.6), (30000,29618.7), (60000,59280), (100000,98660.4), W. Reference maximum/European efficiency fields 0.9897/0.9882 are metadata, not constants used at low load.

`engine/inverter/model.py:_curve_ac_output_w` linearly interpolates **powers**, bounds output to [0,Pin], holds first output below the first point, and holds endpoint efficiency above the last point. `_quadratic_voltage_output_w` clamps voltage to the anchor range, then uses the nearest three anchors with bounded quadratic interpolation (linear for fewer anchors). It does not interpolate efficiency linearly from zero to 94%. The OND's TCubicProfile label does not make this implementation a cubic interpolator. Identical anchor curves mean voltage interpolation has no numerical contribution here. Operating below 200 V remains physically unvalidated even though the fixture's widened acceptance window allows it.

`_ac_power_limit` uses maximum AC power when runtime inverter temperature is absent; available AC=min(unclipped AC,limit). Detailed downstream supplies no inverter temperature, so derating is not applied. If supplied, the source uses linear breakpoint segments and requires explicit temperature basis; absolute-limit behavior is fail-closed.

## 5. Per-interval and aggregated conversion analysis

`engine/simulation/detailed_backend.py:_evaluate_interval` assembles module/string/parallel IV and calls `shading.electrical.select_mppt_operating_point`; persisted selected states feed `engine/simulation/detailed_downstream.py:compact_selected_states`, `selected_states_to_mppt_bank`, and `execute_detailed_downstream`. `engine/losses/chain.py:simulate_electrical_loss_chain` then calls the existing inverter model. All 48 detailed chunks were read; their selected P/V/I equal Parquet MPPT fields (maximum absolute difference 0). No operating-point solve was rerun.

Twenty-four daylight intervals have finite selected operating points and `selected_unconstrained_state`; 24 dark intervals are `inactive_dark`, P=0 and V/I null. Current-limit-known is false throughout, above-limit null, not a false claim of compliance. Nine daylight intervals are at or below 500 W and lose all DC to the power-threshold channel; 15 convert. MPPT window loss and clipping are zero in all 48 rows. For converting intervals, eta below is **derived** from persisted AC_unclipped/DC_to_converter; instantaneous efficiency itself is not a standard Parquet column. Dark/threshold eta is inapplicable, not a measured zero efficiency.

For every converting interval, Pin=533.437737… through 1426.826113… W (0.533–1.427% of nominal AC rating), entirely within the first curve segment:

`Pout = (2831.2/2500) × (Pin−500) = 1.13248 × (Pin−500)`.

The maximum absolute difference from persisted AC across all 15 intervals is 0 W. Summing gives `1.13248 × (14346.367090620726 − 15×500) = 7753.373802786161 Wh`; eta_weighted=0.5404416152055046. Individual eta spans 7.0987795–73.5627157%, not a constant 54%. Conversion loss is the complementary 6592.993287834567 Wh. This directly proves the leading explanation without assuming it.

All rows below last 3600 s, timestamps UTC+07:00. DC is pre-threshold selected array power; accepted is converter Pin. Loss is conversion loss (threshold loss separately shown). PCC W numerically equals interval Wh only because duration is one hour.

| Start | DC W | Accepted W | Vmp V | Imp A | Derived eta % | AC W | Threshold W | Conversion W | PCC W |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 06-30 06:00 | 35.518881 | 0.000000 | 74.551854 | 0.476432 | — | 0.000000 | 35.518881 | 0.000000 | 0.000000 |
| 06-30 07:00 | 250.348290 | 0.000000 | 79.139231 | 3.163390 | — | 0.000000 | 250.348290 | 0.000000 | 0.000000 |
| 06-30 08:00 | 575.892825 | 575.892825 | 81.724297 | 7.046776 | 14.924 | 85.947107 | 0.000000 | 489.945719 | 85.947107 |
| 06-30 09:00 | 1041.221216 | 1041.221216 | 80.609636 | 12.916833 | 58.866 | 612.922203 | 0.000000 | 428.299013 | 612.922203 |
| 06-30 10:00 | 1294.345217 | 1294.345217 | 79.886312 | 16.202340 | 69.501 | 899.580072 | 0.000000 | 394.765146 | 899.580072 |
| 06-30 11:00 | 1426.826113 | 1426.826113 | 67.348463 | 21.185726 | 73.563 | 1049.612036 | 0.000000 | 377.214077 | 1049.612036 |
| 06-30 12:00 | 1373.869570 | 1373.869570 | 67.455725 | 20.366982 | 72.033 | 989.639810 | 0.000000 | 384.229759 | 989.639810 |
| 06-30 13:00 | 999.751504 | 999.751504 | 80.974040 | 12.346568 | 56.610 | 565.958583 | 0.000000 | 433.792921 | 565.958583 |
| 06-30 14:00 | 733.806996 | 733.806996 | 81.283369 | 9.027763 | 36.083 | 264.781747 | 0.000000 | 469.025249 | 264.781747 |
| 06-30 15:00 | 533.437737 | 533.437737 | 81.492108 | 6.545882 | 7.099 | 37.867569 | 0.000000 | 495.570169 | 37.867569 |
| 06-30 16:00 | 185.704864 | 0.000000 | 78.167917 | 2.375717 | — | 0.000000 | 185.704864 | 0.000000 | 0.000000 |
| 06-30 17:00 | 23.403312 | 0.000000 | 71.576925 | 0.326967 | — | 0.000000 | 23.403312 | 0.000000 | 0.000000 |
| 07-01 06:00 | 29.041488 | 0.000000 | 73.574993 | 0.394720 | — | 0.000000 | 29.041488 | 0.000000 | 0.000000 |
| 07-01 07:00 | 246.223969 | 0.000000 | 78.646204 | 3.130780 | — | 0.000000 | 246.223969 | 0.000000 | 0.000000 |
| 07-01 08:00 | 536.280055 | 536.280055 | 81.448724 | 6.584266 | 7.661 | 41.086436 | 0.000000 | 495.193618 | 41.086436 |
| 07-01 09:00 | 815.149873 | 815.149873 | 81.064370 | 10.055588 | 43.783 | 356.900929 | 0.000000 | 458.248945 | 356.900929 |
| 07-01 10:00 | 1130.840483 | 1130.840483 | 80.295388 | 14.083505 | 63.176 | 714.414231 | 0.000000 | 416.426253 | 714.414231 |
| 07-01 11:00 | 1239.887496 | 1239.887496 | 67.647945 | 18.328532 | 67.579 | 837.907791 | 0.000000 | 401.979705 | 837.907791 |
| 07-01 12:00 | 1015.091478 | 1015.091478 | 67.895157 | 14.950867 | 57.466 | 583.330797 | 0.000000 | 431.760681 | 583.330797 |
| 07-01 13:00 | 972.123943 | 972.123943 | 79.856221 | 12.173428 | 55.000 | 534.670923 | 0.000000 | 437.453020 | 534.670923 |
| 07-01 14:00 | 657.842584 | 657.842584 | 81.431041 | 8.078524 | 27.173 | 178.753570 | 0.000000 | 479.089014 | 178.753570 |
| 07-01 15:00 | 494.015436 | 0.000000 | 81.264326 | 6.079118 | — | 0.000000 | 494.015436 | 0.000000 | 0.000000 |
| 07-01 16:00 | 191.574561 | 0.000000 | 78.775322 | 2.431911 | — | 0.000000 | 191.574561 | 0.000000 | 0.000000 |
| 07-01 17:00 | 23.659956 | 0.000000 | 71.929883 | 0.328931 | — | 0.000000 | 23.659956 | 0.000000 | 0.000000 |
| Both days 00–05 and 18–23 (24 rows) | 0 | 0 | null | null | — | 0 | 0 | 0 | −2 each |

June 30 15:00 is the minimum-efficiency conversion interval; June 30 11:00 is the peak. On July 1 15:00, 494.015436 W goes entirely to threshold loss. Standby is zero for all nine threshold rows; 24 dark rows consume 2 W each, hence 48 Wh, not 96 Wh. These are source-backed night/standby definitions (`engine/inverter/model.py:simulate_voltage_dependent_inverter`), not consumption at every hour.

Ranked causes: (1) extremely low load on the imported curve, exactly proven; (2) first-segment linear Pin/Pout policy, exactly proven and physically unvalidated here; (3) 500 W startup threshold explains an additional 1479.49 Wh before conversion; (4) widened voltage window is a design limitation, but identical curves rule out voltage-dependent variation as the cause of the conversion loss. No evidence implicates normalization, repeated per-tracker fixed losses, loss double counting or numerical solver error. Model discretization affects represented IV behavior; its physical accuracy is not established by arithmetic agreement.

## 6. Complete energy/loss reconciliation

Durations are explicitly 3600 s; integration uses sum(P×duration/3600), with signed PCC import retained. The independent read-only interval residual `raw_array_mpp − voltage_threshold − power_threshold − conversion − clipping − self_consumption − PCC` has maximum magnitude 2.842170943040401e−14 W. Parquet channel sums agree with `summary-result.json`:

| Ledger boundary or subtraction | Wh |
|---|---:|
| Raw selected-array reference DC | 15825.857846868941 |
| Module quality / residual module mismatch / residual string mismatch / wiring | 0 / 0 / 0 / 0 |
| MPPT voltage-threshold loss | 0 |
| Inverter power-threshold loss | 1479.4907562482144 |
| Converter input | 14346.367090620726 |
| Inverter conversion loss | 6592.993287834567 |
| Unclipped AC | 7753.373802786161 |
| Clipping | 0 |
| Available AC | 7753.373802786161 |
| Night / standby | 48 / 0 |
| Net PCC | 7705.373802786161 |

Thus `15825.857846868941 −1479.4907562482144 −6592.993287834567 −48 =7705.373802786161` within floating-point precision. Threshold fraction uses raw DC (9.3485659%); conversion fraction uses accepted input (45.9558385%); clipping/self-consumption use available conversion output. Summing these fractions would be invalid. `conversion_loss_w` aliases `inverter_conversion_loss_w`; `clipping_loss_w` aliases its inverter counterpart; these must not be counted twice. The projected `inverter_output_power_w` is net here: its sum equals PCC, not pre-consumption AC.

The raw DC reference already includes geometry, IAM, thermal and detailed electrical effects. Zero residual mismatch ledger terms do not mean zero physical mismatch. The separate attribution is explicitly `explanatory_only_never_applied_to_actual_ledger`.

`shading/electrical/dc_attribution.py:evaluate_independent_module_bases` and `engine/simulation/detailed_attribution.py:CHANNEL_PAIRS` define U=independent uniform-effective module reference, N=nonuniform independent modules with bypass off, B=nonuniform independent modules with bypass enabled, S=sum independent string MPPs, C=combined MPPT global MPP, T=selected tracker point. U is uniformized actual effective irradiance at the same temperature, not unshaded nameplate ideal energy. In `P/detailed-dc-attribution-energy-summary.json:payload.periods[0]`:

| Basis | Signed integrated Wh |
|---|---:|
| U | 17360.922484732055 |
| N | 16859.978877579335 |
| B | 16859.97887814579 |
| S | 16260.507255304883 |
| C | 15825.857846868941 |
| T | 15825.857846868941 |

Signed channels are U−N=500.943607152718; N−B=−0.0000005664544886485601 (gain, preserved); B−S=599.4716228409068; S−C=434.64940843594127; C−T=0 Wh. Their telescope is U−T=1535.0646378631116 Wh with recorded residual 0, allowed residual 2.4e−6 Wh, maximum interval residual 0. These counterfactual interactions are not extra losses to subtract from T. T is already the raw selected DC boundary used above. All six bases/channels have 24 applicable, available intervals (86400 s), no unavailable intervals, and 24 dark not-applicable intervals. Dark attribution nulls remain null; availability fraction 1 means complete applicable coverage, not 48 physically operating hours.

`engine/simulation/attribution_energy.py:_assemble`, `_coverage`, `_telescope`, `verify_energy_summary` preserve these signs, common coverage and local start-based day/month assignment. `J/verification.json` records successful fresh-process public `verify_run_package` completion, including existing attribution/energy checks. That is retained evidence, not a new verification or evidence of measured physical accuracy.

## 7. Performance-ratio calculation and interpretation

`engine/simulation/detailed_downstream.py:execute_detailed_downstream` weights unshaded incident POA by actual component surface area, then integrates explicit durations. Four modules each have mechanical area 1.134×2.278 m²; installed nameplate is 4×550=2200 Wp. These component areas, not the fixture's controlled geometry footprint, set KPI weights. `engine/losses/energy.py:calculate_pv_kpis` uses grid/PCC kWh, installed kWp, incident POA kWh/m² and default reference irradiance **1 kW/m²**.

Persisted unshaded POA integration is 9171.040938825485 Wh/m² =9.171040938825485 kWh/m²; shaded incident POA is 8811.480752012374 Wh/m². Numerator is signed net PCC 7.705373802786161 kWh. Denominator is 2.2 kWp ×9.171040938825485 h =20.17629006541607 kWh. Specific yield=7.705373802786161/2.2=3.502442637630073 kWh/kWp (numerically Wh/Wp). PR=7.705373802786161/20.17629006541607=0.38190241009638576, exactly the reported value and manifest's `module_surface_area_weighted_unshaded_incident_poa` basis.

A descriptive factorization is `0.7843789812476898 ×0.9065143406086562 ×0.5404416152055046 ×0.9938091466733164 = PR`: raw selected DC / ideal unshaded nameplate reference, threshold retention, conversion retention, PCC consumption retention. The first factor includes shaded irradiance, IAM, module temperature and detailed electrical behavior; it is not an isolated physical loss or an additional attribution term. PR is consequently not inverter efficiency alone. Annual energy and quantified shading-energy loss/basis are null; no annual PR or separate temperature/shading energy effect can be inferred from these 48 hours.

## 8. Fixture/model limitations

The direct canonical route never exercised the engineering-design gate or produced a DesignValidationReport. Effective inverter `basic_design_ready=False`, `mppt_design_ready=False`; acceptance here demonstrates integration capability. Four 550 W modules, two series strings feeding one tracker, synthetic regional parameterization/bypass constant-drop assumptions, and the widened voltage range are not an approved Huawei installation. The imported OND curve provenance does not validate the effective modified revision.

Persisted thermal settings Uc=20 W/m²K, Uv=0 disable wind-dependent cooling. Temperature is one scalar per module, based on shaded incident POA before IAM with whole-module single-diode efficiency coupling; regional gradients are absent. Configured module-quality override zero supersedes the fixture's −0.0075 default; attribution and selected-MPPT physics do not silently apply quality again. Residual mismatch and DC resistance are zero; nonzero configured mismatch is rejected to prevent overlap with detailed IV physics.

Unknown MPPT physical current limit prevents current-clipping validation; tracker constraints are flags, not a clipping solver. Nameplate array current is not a substitute. Inverter temperature/basis is absent, so derating is unused despite available breakpoint data. Ideal global-MPP selection omits real tracking dynamics. Finite IV sampling and piecewise-linear source-current representation, coarse sky/ground visibility grids, disabled self-shading, front-only irradiance and synthetic reverse/bypass calibration limit physical fidelity. Mixed dark/active branches are unsupported and fail closed; this run avoids that unsupported state. No external measured yield or low-load inverter measurement is retained. These limitations cannot be repaired by tuning this audit's input data.

## 9. Timestamp and provenance review

`P/simulation-run.json` has started_at=completed_at=`2026-10-10T12:43:31.408731Z`. `engine/simulation/canonical.py:run_canonical_simulation` resolves `now=_timestamp(executed_at)` once at entry. `_timestamp` uses UTC now if no override, otherwise the caller's timestamp. Detailed dispatch's pcc_complete path creates a run using `canonical.py:_failed_run`, which assigns both fields from the supplied executed_at; `detailed_downstream.py:complete_detailed_run` changes status/results but never replaces these timestamps. The ordinary canonical completed path also assigns both fields from the same `now`. This is one entry event reused, even though detailed run-object construction occurs after numerical work; it is not a measured completion time.

`J/execution-resources.json:wall_seconds` is 505.9789661929972 s; separate verification wall time is 5.3599944400193635 s. `tools/rb_post3d_02_era5_validation.py` externally supervises the execution worker (acquisition, QC, simulation and persistence), so 505.98 s is not an isolated numerical kernel timing. `execution.log` and `verification.log` are 0 bytes and provide no additional event chronology. Sampled peak execution PSS is 249899008 bytes, verifier 198368256 bytes; these are sampled peaks, not strict bounds.

Identical timestamps follow a confirmed assignment behavior. They inaccurately represent execution duration if read as actual start/end, but no source evidence establishes an intended zero-duration schema convention. Classify as **METADATA_OR_PROVENANCE_ISSUE**, not a conversion-engine defect. External wall duration mitigates timing loss; exact numerical-stage completion time is unresolved with these artifacts. Scientific hashes and numerical reproduction remain intact; package timestamps must not be rewritten.

## 10. QC and weather relevance

Source is Open-Meteo Historical Archive, explicit ERA5, land cell selection, upstream ECMWF/Copernicus attribution; `W/acquisition-manifest.json` preserves source URL, terms/license reference and raw-response identity. No acquisition was performed for this audit. Requested coordinate −6.425,106.831 is canonical; returned grid −6.5,106.75 is 12.209563784423848 km away. Returned elevation 94 m differs from fixture 93 m by +1 m but canonical elevation remains None; solar uses 0 m default and complete ERA5 pressure. Passing the 40 km screen establishes neither local meteorological accuracy nor project validation.

The retained weather Parquet and dataset preserve hourly interval starts. Adapter radiation labels shift back one hour from upstream preceding-hour means; instantaneous state observations are assigned to that interval without interpolation. Solar evaluation uses midpoint, not upstream label; no additional timestamp shift is warranted.

`J/report.json:stages.full_source_validation` records base QC 0 errors/0 warnings; solar-aware QC 0 errors and two warning categories, three instances each. Component-closure examples: March 29 17:00, March 30 17:00, August 16 06:00 2025 (+07). Daylight near-zero GHI examples: January 9 06:00, April 1 17:00, June 18 06:00. Each finding's count is three and all three examples are present; none falls in June 30–July 1. Closure maximum residual is 8.997290475925851 W/m²; high-zenith tolerance 15%, low-zenith 8%, minimum component sum 50 W/m². Near-zero screening uses GHI<5 W/m² with true elevation>5°. These retained source-wide warnings do not explain selected-window inverter losses. The numerical package's selected-weather base QC has no findings; it must not erase source-wide solar warnings.

## 11. Classified findings and risk register

Severity below concerns interpretation and engineering use, not a claim that an integration fixture failed its contract.

| Finding | Classification | Severity | Evidence / impact |
|---|---|---|---|
| 100 kW curve on 2.2 kWp array, first-segment 7–74% eta | FIXTURE_PARAMETER_LIMITATION | High for yield interpretation | Effective component, 15 Parquet conversion rows and exact formula; dominant loss is explained but not validated physically |
| 0 V MPPT minimum and operation below 200 V anchors | FIXTURE_PARAMETER_LIMITATION | High for design interpretation | `_canonical_fixture`, effective revision and MPPT V/I; artificial acceptance cannot confer real inverter compatibility |
| 500 W threshold and 2 W dark consumption | EXPECTED_MODEL_BEHAVIOR | Informational | Inverter model, nine threshold and 24 dark rows; explains threshold/self-consumption totals |
| Ledger, attribution telescope, PR arithmetic | EXPECTED_MODEL_BEHAVIOR | Informational | Persisted summary/energy audit and interval residual; internal consistency confirmed, not measured accuracy |
| Unknown physical current limit, absent derating temperature, synthetic bypass and thermal approximations | SCIENTIFIC_VALIDATION_GAP | High for engineering use | Effective component/configuration and detailed identity limitations; missing physical constraints/refinements |
| Same started_at/completed_at from entry timestamp | METADATA_OR_PROVENANCE_ISSUE | Medium | Canonical/detailed construction path and supervisor resources; run fields cannot measure elapsed time |
| Exact numerical-stage end time unavailable | UNRESOLVED_WITH_AVAILABLE_EVIDENCE | Low | Empty logs, aggregate worker duration only; no invented timing breakdown |
| No design gate or measured-yield validation | SCIENTIFIC_VALIDATION_GAP | High for approval claims | Runner report and direct entry point; integration success does not approve design or calibrate yield |

No **CONFIRMED_IMPLEMENTATION_DEFECT** in the conversion calculation is supported by this audit. Manufacturer-distributed curve provenance is affirmative, but physically plausible behavior in this modified fixture's voltage/load domain remains unvalidated. Existing package verification is affirmative retained evidence. Engineering-approved design and external measured-yield validation are absent. None of these acceptance dimensions substitutes for another.

## 12. Single recommended next task

Recommend one bounded task: **define and engineering-validate a separate inverter/array fixture with source-backed voltage compatibility and efficiency data covering its actual DC load range**, preserving B2 as a numerical regression fixture. This addresses the dominant interpretation risk without editing the retained run or tuning its curves to improve PR. Do not authorize a rerun, annual benchmark or design approval from this recommendation. Timestamp correction is recorded as a limitation, not a second proposed task. Stop this audit at documentation; no production change is justified or authorized here.
