# RB-POST3D-05 — GoodWe GW2500-XS-30 evidence intake

## 1. Executive verdict

**Reasonable preliminary candidate; incomplete readiness.** The GoodWe GW2500-XS-30, XS G3 family, is a 2500 W single-phase grid-connected inverter. Four manufacturer Jinko JKM550M-72HL4-V modules in **4S1P** give 2200 Wp, a DC/AC nameplate ratio of 0.88, and STC voltage/current within the published MPPT range and per-MPPT limits. These are screening results, not engineering approval. Rated-power voltage suitability, actual site electrical envelopes, DC-array restrictions, connector compatibility and thermal behavior remain conditional.

**FULL_EFFICIENCY_CURVE_EVIDENCE_MISSING.** The supplied PDF has summary efficiencies, not a Pin/Pout transfer curve. No model-specific original OND or equivalent curve was found in the repository or supplied evidence folder. Existing ingestion/overlay interfaces can represent an incomplete source-backed candidate without production changes, but source completeness, canonical schema readiness, derived design capabilities, design-report acceptance and physical accuracy are distinct outcomes. No candidate or revision was created or finalized.

The existing engineering validator reports `basic_yield_ready=false` as a WARNING, while false basic/MPPT design flags are INVALID and blocking. Missing efficiency evidence therefore does not itself prove that an electrical design report must block: a legitimately assembled datasheet candidate could support conditional electrical validation with findings. Detailed execution still requires the absent voltage-dependent curves. Source-backed whole-module PAN data also does not establish the Level-2 substring topology and region/reverse/bypass evidence required for representative execution. Genuine project/site/revision inputs are absent. No engineering-validation PASS or simulation is claimed.

## 2. Manufacturer evidence and source fingerprint

Inspection checkpoint: 2026-10-10; branch `ai/rb-post3d-05-inverter-evidence-intake`; HEAD `7f641fc1952e5407c24dcc7edaf1fb9801e67639`. Initial working tree/index were clean. References below are repository-relative paths and function names at this checkpoint.

| Evidence property | Inspected result |
|---|---|
| Local read-only source | `.ai/evidence/rb_post3d_05/GoodWe_XS_G3_Datasheet.pdf` |
| Original manufacturer URL | [GoodWe XS G3 datasheet](https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_XS-G3_Datasheet-EN.pdf) |
| Manufacturer product page | [GoodWe XS G3](https://en.goodwe.com/xs-g3) |
| Local SHA-256 | `18357e657ebadb379792bd8aecc26c16ba207c46c3ddd1fc9225a179131b7591` |
| Local size / identity | 400137 bytes; PDF 1.4; two page objects |
| Document manufacturer / family | GoodWe / XS G3; page 1 identifies single-phase, one-MPPT residential solar series |
| Footer version / date | `GoodWe-Single page-20250703-EN-V2.1`; EN-V2.1, 2025-07-03 |
| Exact column | Page 2, fifth model column: **GW2500-XS-30**; not GW2500-XS or GW2500-XS-11 |
| Relevant sections | Page 1 series/features; page 2 Input, Output, Efficiency, Protection, General Data and footnotes *1/*2 |

Local compressed PDF content streams and text/font mappings were inspected read-only using Python standard-library decompression; no PDF parser dependency was installed. The model-specific text positions distinguish the fifth model column from merged series-wide rows. The manufacturer-hosted PDF and product page were also opened as corroboration; the local retained document governs this intake. The website extraction reports the same footer and relevant specifications, but remote-byte hash equality was not established. Manufacturer hosting, embedded GoodWe identity, exact model table and local fingerprint together support attribution; filename/URL alone and cryptographic hashing alone do not establish authenticity or measured performance. No digital-signature or independent laboratory authentication is claimed.

The user manual referenced by footnote *2 is **unavailable in supplied evidence and not inspected**. No contents are inferred. External certificates mentioned in the footer likewise were not inspected. The original PDF remains in ignored `.ai`, unchanged and uncopied to tracked paths.

Manufacturer statements below concern only the datasheet. Arithmetic and assessments are repository-derived conclusions. Prior context read: `docs/audits/rb_post3d_03_inverter_loss_scientific_plausibility.md` and `docs/audits/rb_post3d_04_representative_design_readiness.md`. Historical `.ai/reports/claude_review_3.json` concerns attribution streaming, has zero blockers/majors and is not acceptance of this intake. Independent review of this document remains pending.

## 3. Verified inverter parameter matrix

Classification scope is the supplied original PDF: `SOURCE_VERIFIED` means directly stated; `DERIVED_FROM_SOURCE` means transparent arithmetic/interpretation; `NOT_PRESENT_IN_SOURCE` means absent; `SEMANTICALLY_AMBIGUOUS` means a statement exists but does not resolve the proposed engineering meaning. Each row has one classification. Page 2 applies unless stated otherwise; “model” means the GW2500-XS-30 column and “series” means a merged row.

| Parameter | Value / source scope | Classification | Engineering interpretation |
|---|---|---|---|
| Nominal AC active power | 2500 W, Output/model | SOURCE_VERIFIED | Nameplate reference |
| Maximum AC active power | 2500 W, Output/model | SOURCE_VERIFIED | No additional active-power overload allowance stated |
| Nominal / maximum apparent power | 2500 / 2500 VA, Output/model | SOURCE_VERIFIED | Reactive-power dispatch must also respect apparent/current limits |
| Phase / terminals | Single phase, p1; L/N/PE, Output/series | SOURCE_VERIFIED | Grid-connected residential candidate |
| Nominal AC voltages | 220 / 230 / 240 V, Output/series | SOURCE_VERIFIED | Alternatives; actual site selection not supplied |
| Output voltage range | 154–288 V according to local standard, series | SOURCE_VERIFIED | Country/grid configuration must be resolved |
| Nominal frequency / ranges | 50 / 60 Hz; 45–55 / 57–63 Hz, series | SOURCE_VERIFIED | Alternatives, not one canonical scalar |
| Maximum output current | 11.4 A, Output/model | SOURCE_VERIFIED | Do not infer unrestricted 2500 W at all voltages/PF |
| Power factor / THD | Approximately unity; adjustable 0.8 leading to 0.8 lagging; THD <3%, series | SOURCE_VERIFIED | No full P/Q capability or control curve |
| Recommended DC-array nameplate power | No numeric recommendation | NOT_PRESENT_IN_SOURCE | Cannot fill contractual recommended PV power |
| Maximum DC-array / physical DC input power | No explicit W limit | NOT_PRESENT_IN_SOURCE | Neither a 5000 W cap nor a physical clipping limit established |
| DC oversizing claim | 200% DC input oversizing, p1 series feature | SEMANTICALLY_AMBIGUOUS | Basis/conditions absent; cannot map as approved maximum PV-array power |
| Absolute maximum input voltage | 600 V, Input/series, footnote *1 | SOURCE_VERIFIED | Standby at 550–600 V; distinct from operating ceiling |
| Startup voltage | 50 V, Input/series | SOURCE_VERIFIED | Voltage criterion, not input-power activation threshold |
| MPPT operating voltage | 40–550 V, Input/model | SOURCE_VERIFIED | Smaller series models instead have 40–450 V |
| Nominal input voltage | 360 V, Input/series | SOURCE_VERIFIED | Not rated-power voltage window or minimum |
| MPPT range at nominal power | Deferred to user manual, footnote *2 | NOT_PRESENT_IN_SOURCE | Manual unavailable; rated-power suitability unresolved |
| MPPT count / strings per MPPT | 1 / 1, Input/series | SOURCE_VERIFIED | Proposed 4S1P uses one string on one MPPT |
| Operating current per MPPT | Maximum 16 A, Input/series; p1 per-string feature agrees | SOURCE_VERIFIED | Physical MPPT limit, not contractual array current |
| Short-circuit current per MPPT | Maximum 25 A, Input/series | SOURCE_VERIFIED | Separate safety check |
| Total DC operating / Isc limits | Single MPPT gives candidate aggregate bounds 16 / 25 A | DERIVED_FROM_SOURCE | Same one-tracker electrical path; not independently stated total-inverter ratings |
| Maximum efficiency | 97.6%, Efficiency/model | SOURCE_VERIFIED | Summary metric only |
| European efficiency | 97.0%, Efficiency/model | SOURCE_VERIFIED | Weighted summary, not a part-load curve |
| Full voltage-dependent Pin/Pout curve | No plot, points, voltage anchors or transfer coefficients | NOT_PRESENT_IN_SOURCE | Cannot derive curve from summary metrics |
| Minimum input / startup / shutdown power | No W threshold | NOT_PRESENT_IN_SOURCE | 50 V is not an equivalent |
| Night self-consumption | <3 W, General Data/series | SOURCE_VERIFIED | Strict upper bound; not exact 3 W loss |
| Standby consumption / voltage shutdown hysteresis | No exact losses or complete switching specification | NOT_PRESENT_IN_SOURCE | Footnote standby state does not quantify consumption |
| AC clipping control / overload duration | No transfer/control law or overload time | NOT_PRESENT_IN_SOURCE | Maximum ratings known; dynamic behavior absent |
| Operating temperature | −25 to +60 °C, General Data/series | SOURCE_VERIFIED | Equipment operating range, not module cell design temperatures |
| Temperature derating curve / reference basis | No power-versus-temperature data or resolved basis | NOT_PRESENT_IN_SOURCE | Operating range is not a derating model |
| Altitude / cooling | Maximum 4000 m; natural convection, series | SOURCE_VERIFIED | Altitude derating curve absent |
| Humidity / ingress / isolation | 0–100%; IP66; non-isolated, series | SOURCE_VERIFIED | Installation suitability still needs manual/site review |
| DC connector / conductor | MC4, 4–6 mm², series | SOURCE_VERIFIED | Mating type, ampacity and installation instructions not established |
| AC connector | Plug-and-play connector, series | SOURCE_VERIFIED | No complete cable/protection specification |
| Weight / dimensions | 4.6 kg; 306 × 218 × 119 mm, series | SOURCE_VERIFIED | Mechanical information, not clearance approval |
| Protection / optional features | Integrated anti-islanding, reverse polarity, insulation/residual-current monitoring and AC protections; Type III DC/AC SPD, Type II optional; AFCI/remote shutdown optional, Protection/series | SOURCE_VERIFIED | Presence claims do not establish jurisdictional certification |
| Night power-supply feature | Optional, Protection/series | SOURCE_VERIFIED | Separate from <3 W self-consumption |

## 4. Jinko 4S1P preliminary electrical screening

Original source: `tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN`. Embedded manufacturer Jinkosolar, model JKM550M-72HL4-V, `DataSource=Manufacturer 2020 SGS-CSTC`, SGS-CSTC Standards Technical Service Co., Ltd comment. Adjacent `provenance.json` and `README.md` record maintainer-supplied manufacturer redistribution, no invented SPDX license and possible repository line-ending normalization. Original received hash is `24bc13172fd13646f1a9a408d3fd462b1e7b6b8ee84923c83335e15e1f1b8764`, 1440 bytes; inspected checked-in hash is `aff43dc4f6b5213abd87a14e0814fda47b8bb51bf7cb439bfa5fa590190229f3`, 1365 bytes. These are distinct provenance anchors, consistent with the documented normalization boundary; no original-byte equality is asserted.

PAN electrical values: PNom=550 W, Vmp=40.90 V, Voc=49.62 V, Imp=13.450 A, Isc=14.030 A at GRef=1000 W/m² and TRef=25 °C. `muISC=6.57` mA/K, `muVocSpec=−137.9` mV/K, `muPmpReq=−0.345` %/K. IEC/UL maximum system voltage=1500 V. NCelS=72, NCelP=2, NDiode=3; width/height=1.134/2.278 m. These cell/diode counts do not establish canonical substring interconnections. PAN SDM fields include RSerie=0.238 Ω, RShunt=1100 Ω, Rp_0=9000 Ω, Rp_Exp=3.60, Gamma=0.969 and muGamma=−0.0003. These are whole-module model inputs, not independent IV validation.

`components/pan/parser.py:read_pan`, `components/pan/mapper.py:map_pan`, the temperature ledger in `components/pan/mapping-ledger.yaml`, and `components/candidates.py:build_module_candidate` preserve this source pathway: alpha becomes 0.00657 A/K, beta −0.1379 V/K, relative gamma −0.00345/K becomes absolute −1.8975 W/K from 550 W, with `coefficient_basis=absolute` and recorded derivation. No B2 synthetic revision is substituted.

| STC screening quantity | Recomputed from source | Interpretation |
|---|---|---|
| Array nameplate | 4 × 550 = **2200 Wp** | Nameplate sum, not simulated output |
| String Vmp | 4 × 40.90 = **163.60 V** | Inside 40–550 V at STC |
| String Voc | 4 × 49.62 = **198.48 V** | Below 600 V at STC |
| String Imp / Isc | **13.45 / 14.03 A** | Series current unchanged; below 16 / 25 A at STC |
| DC/AC ratio | 2200 / 2500 = **0.88** | Advisory sizing, not a manufacturer compliance rule |
| STC electrical-point product | 4 × 40.90 × 13.45 = 2200.42 W | Source rounding; do not replace 2200 Wp nameplate |
| Topology | 4 series, 1 parallel string, 1 MPPT | Matches published tracker/string counts provisionally |

**Conditional sensitivity only.** No site minimum/maximum cell temperature or design irradiance is supplied. The following temperatures are illustrative assumptions, not climate data; irradiance is fixed at the PAN reference 1000 W/m². No SDM solver, validator or simulation was executed. Arithmetic follows the explicit linear fallback approximation in `validation/engineering/electrical.py:_fallback_module_state`:

- `Voc_string(T)=4[49.62−0.1379(T−25)]` V.
- `alpha_rel=0.00657/14.03=0.0004682823/K`; `beta_Vmp_rel≈−0.00345−alpha_rel=−0.0039182823/K`. This Vmp coefficient is **repository policy approximation**, not manufacturer data.
- `Vmp_string(T)=163.60[1+beta_Vmp_rel(T−25)]`; `Imp(T)=13.45[1+alpha_rel(T−25)]`; `Isc(T)=14.03+0.00657(T−25)`.
- The default fallback guards in `_config` / `_symmetric_envelope` are ±5% voltage/current. These are evidence uncertainty margins, not a prescribed code-compliance Isc multiplier. Site policy may differ.

| Assumed cell T °C | String Voc V | Voc upper +5% V | Approx. string Vmp V | Vmp ±5% envelope V | Imp upper +5% A | Isc upper +5% A |
|---:|---:|---:|---:|---:|---:|---:|
| −10 | 217.786 | 228.675 | 186.036 | 176.734–195.338 | 13.891 | 14.490 |
| 0 | 212.270 | 222.883 | 179.626 | 170.644–188.607 | 13.957 | 14.559 |
| 25 | 198.480 | 208.404 | 163.600 | 155.420–171.780 | 14.123 | 14.732 |
| 60 | 179.174 | 188.133 | 141.164 | 134.106–148.222 | 14.354 | 14.973 |
| 75 | 170.900 | 179.445 | 131.548 | 124.971–138.126 | 14.453 | 15.076 |

Within these assumptions, the guarded cold Voc stays below both 600 V inverter and 1500 V module limits; approximate cold/hot Vmp stays within 40–550 V and above 50 V startup. This does not prove dawn/low-irradiance activation or rated-power operation. String voltage around 132–186 V is well below nominal input 360 V; footnote *2 prevents either a rated-power pass or fail conclusion.

Currents remain below 16/25 A **only for this reference-irradiance sensitivity**. The validator fallback deliberately rejects non-reference irradiance. Higher irradiance/current enhancement, temperature extremes and applicable short-circuit safety factors need actual design evidence and, where required, a validated detailed model. `_module_state` first attempts validated PVsyst SDM (`detailed_sdm_ready=true` and validated parameters); only supported policy permits guarded fallback. `_string_voltage_envelope` sums series voltages; `_string_current_envelope` takes minimum series current, with parallel-string currents subsequently summed. This intake does not execute those paths or establish their flags for a new revision.

DC-array limits remain unresolved despite modest nameplate ratio. MC4/4–6 mm² does not prove Jinko lead mating compatibility, cable ampacity, fuse/protection or installation clearance. The PAN supplies no explicit series-fuse rating. The 4S1P arrangement is retained exactly; no topology adjustment is used to force compliance.

## 5. OND and efficiency-curve evidence assessment

Supplied evidence folder contains only the GoodWe PDF. Repository OND inventory is `tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND` (100 kW, different manufacturer/model) and `tests/fixtures/panond/synthetic_inverter.ond` (synthetic 250 kW). `components/reference/` contains synthetic 150 kW definitions; its README explicitly denies vendor authenticity. No GoodWe original OND, canonical curve or equivalent traceable transfer source was found. No unofficial third-party file was downloaded.

**FULL_EFFICIENCY_CURVE_EVIDENCE_MISSING** includes low-load transfer behavior at the candidate's actual string voltages. Maximum and European efficiency cannot recover activation, part-load shape, voltage dependence or interpolation domain. Neither constant 97.6% nor the Huawei curve is justified.

| Minimum original manufacturer evidence | Required content / repository use |
|---|---|
| DC-to-AC transfer and part load | Exact GW2500-XS-30 identity/version, Pin/Pout W/W samples including low input and rated load, measurement/reference conditions and provenance |
| Voltage dependence | Verified voltage anchors and sufficient power points covering roughly 132–186 V illustrative operation, with defined supported domain; at least two curves for detailed runtime, exactly three anchors for current OND assembler |
| Activation | Minimum/startup/shutdown power, voltage conditions and hysteresis; distinguish threshold from conversion loss |
| Interpolation domain | Units, profile mode, effective point count, voltage/power coverage, extrapolation limits and enough evidence to review repository interpolation against source semantics |
| Clipping | Maximum active/apparent/current limits plus voltage, power-factor and overload/control conditions |
| Night/standby | Exact values or supported operating-dependent model, conditions and optional-feature effects; <3 W alone is a bound |
| Thermal derating | Power-temperature breakpoints/curve, ambient/internal/heatsink basis, absolute limits and installation/altitude conditions; runtime temperature basis must match |

`components/ond/parser.py` and `mapper.py` preserve/map raw evidence through `mapping-ledger.yaml`. `components/ond/semantics.py:_assemble_efficiency_model` supports `POutf_PIn`, exactly three voltage anchors and complete active `NPtsEff` sets; it derives efficiency=Pout/Pin and records inputs. Unsupported/incomplete data warns rather than fabricating curves. Existing YAML or curve CSV ingestion can represent canonical supplemental evidence, but the PDF is not automatically converted into OND.

`engine/inverter/model.py:_runtime_ready` requires `voltage_dependent_curves` with at least two curves. `_curve_ac_output_w` interpolates Pin/Pout linearly, holds first output below first point and endpoint efficiency above last. Voltage interpolation clamps to anchors, using nearest-three bounded quadratic interpolation when available, otherwise linear. These are repository numerical semantics, not GoodWe-verified physical behavior. Low-load/domain coverage is therefore essential. Activation uses startup power or minimum-input-power fallback, absent threshold defaults to zero; absent night/standby losses likewise default to zero. Such runtime defaults are not verified GoodWe zeros. `_ac_power_limit` requires complete compatible temperature evidence when temperature is supplied; no temperature input uses the AC maximum without proving derating irrelevant.

## 6. Canonical component mapping/readiness matrix

This is a read-only mapping proposal, not an assembled component. Path **Y** means `components/user_yaml.py:parse_component_overlay_yaml` → `ComponentSourceFragment` → `components/source_overlay.py:build_candidate_from_fragments`; future caller supplies distinct definition/revision/candidate IDs. No IDs or flags are assigned here.

| Canonical field | Manufacturer evidence | Mapping/overlay path | Present / missing / ambiguous | Readiness impact / verification required |
|---|---|---|---|---|
| manufacturer, model, family, phase_configuration | GoodWe, GW2500-XS-30, XS G3, single phase | Y, same canonical keys | Present | Preserve exact generation/identity and source fingerprint |
| dc_limits.max_dc_voltage_v | 600 V, footnote *1 | Y | Present | Absolute limit; retain separate standby footnote |
| dc_limits.startup_voltage_v / nominal_dc_voltage_v | 50 / 360 V | Y | Present | No invented power threshold/rated window |
| dc_limits.min_voltage_for_nominal_power_v | Manual deferred | Y if later evidenced | Missing | Rated-power suitability open |
| dc_limits.max_dc_power_w | No physical W limit | Y if later evidenced | Missing | Not inferred from 200% marketing |
| dc_limits.max_dc_current_a / max_dc_short_circuit_current_a | One-MPPT bounds 16 / 25 A | Y with explicit derivation/source notes | Ambiguous as independently published total ratings | Per-MPPT mapping direct; aggregate mapping needs documented one-path interpretation |
| mppt_template.count / total_input_count / input_count_per_mppt | 1 tracker, 1 string per tracker | Y; input counts derived from published string provision | Present, input-count interpretation derived | Verify connector/input interpretation in manual |
| mppt_template.min/max_operating_voltage_v | 40 / 550 V | Y | Present | Voltage readiness potentially supported |
| mppt_template.max_operating_current_a / max_short_circuit_current_a | 16 / 25 A | Y | Present | Physical current checks potentially supported |
| ac_limits.nominal_ac_power_w / max_ac_power_w / max_ac_apparent_power_va / max_ac_current_a | 2500 / 2500 / 2500 / 11.4 | Y | Present | No overload extrapolation |
| ac_limits.nominal_ac_voltage_v / nominal_frequency_hz | 220/230/240 V; 50/60 Hz | Y requires one supported scalar selection | Ambiguous selection | Actual grid context required; alternatives cannot silently become 230 V/50 Hz |
| array_sizing_limits.nominal/max_pv_array_power_w / max_pv_current_a | No contractual numerical ratings | Y only with further evidence | Missing | 200% claim not an approved 5000 W mapping; per-MPPT current not contractual PV current |
| efficiency_model.reference_metrics.max/european_efficiency_fraction | 97.6 / 97.0% | Y; divide by 100 → 0.976 / 0.970 | Present | Summary metrics only, no supported transfer model |
| efficiency_model.model_type / curves / curve_power_basis | No curve | OND assembly or canonical Y/curve CSV from actual evidence | Missing | No basic yield/detailed efficiency established |
| operating_thresholds.minimum_input_power_w / startup_power_w / shutdown_power_w | No W thresholds | Y only after source evidence | Missing | Absent runtime default must be disclosed |
| operating_thresholds.night_loss_w / standby_loss_w | <3 W night bound / no standby value | Y expects exact scalar | Ambiguous / missing respectively | Preserve bound in evidence/notes, do not assign 3 W |
| temperature_derating_model / curve, altitude_derating_curve | Operating range/altitude only | Y if proper breakpoints/basis obtained | Missing | No derating readiness established |
| source_ids / field provenance | Retained PDF and manufacturer URL | Y source metadata and merged field provenance | Present as intake evidence | Later ingestion needs source record/field citations; source attachment is not approval |

Y prunes nulls rather than inventing values. `merge_component_fragments` rejects manufacturer/model identity conflicts, merges priority-ordered values and retains field provenance/conflicts; arrays such as curves are atomic. Unknown source data must remain absent, with qualifiers in evidence/source notes instead of unsupported canonical exact values.

`build_inverter_candidate` is the OND-specific alternative: mapping → semantic assembly → `validate_inverter` → `inverter_capabilities` → definition schema checks. Fragment assembly validates/derives capabilities similarly. `finalize_candidate` requires schema readiness and no error/blocking-error candidate findings, then labels `auto_validated`; this does not produce a DesignValidationReport or manufacturer certification. An incomplete candidate may be schema-ready because efficiency is not a mandatory definition core, yet lack yield capabilities.

In `components/validation.py:inverter_capabilities`, MPPT voltage readiness needs identity, positive absolute voltage and coherent tracker window/count; physical operating current adds MPPT design readiness. Basic design further requires AC power/voltage/frequency/phase and source association. After genuine grid selection these design flags are potentially derivable without curve data, but **not evaluated here**. Basic yield separately requires a supported efficiency model; reference metrics alone supply none. Detailed efficiency needs curve data. Array-sizing and derating readiness depend on their own supplied fields and do not follow from design flags. No manual override is authorized.

**Pipeline conclusion:** existing code can assemble a partial candidate and later ingest sufficient original evidence without a demonstrated code change. It cannot transform this datasheet into a complete efficiency model. Choosing a supported site grid scalar is also still required. Bound-valued loss evidence, multivalue grid alternatives and unspecified rating conditions must remain documented rather than silently coerced; no schema change is proposed.

## 7. Engineering-validation gap matrix

Actual path: `validation/engineering/electrical.py:validate_engineering_design`, using `components/design_integration.py:inverter_design_snapshot`, revision-pinned Scene/ElectricalDesign/components and explicit `EngineeringValidationConfiguration`. `engine/simulation/design.py:design_validation_gate` checks report schema, matching revisions/configuration, current rule set and blocking consistency before `run_validated_design_simulation`. Neither a source attachment nor a candidate finalization bypasses these gates.

| Requirement | Evidence available now | Actual validator / remaining gap |
|---|---|---|
| Module reference electrical/temperature data | Original PAN nameplate, coefficients, SDM inputs | `_module_state` detailed-first/fallback policy; new revision model validation and actual conditions not executed |
| Inverter source-backed voltage/current limits | 600 V absolute, 40–550 V MPPT, 16/25 A per MPPT | Supported envelope/current comparisons after canonical ingestion; source existence alone does not make report |
| Cold Voc safety | Coefficient and 1500 V module limits | Conservative upper string envelope compared with inverter/module limits; no site cold-cell minimum |
| Hot/cold Vmpp window | Repository explicit fallback approximation available | Full envelope outside range is INVALID; guarded boundary crossing WARNING; genuine conditions and rated-power window absent |
| Current under design conditions | STC currents, Isc coefficient | Series minimum/parallel sum, conservative upper Imp/Isc checks; non-reference irradiance fallback rejected; project irradiance and safety policy missing |
| Tracker and string structure | One MPPT/one string matches proposal | Checks tracker index, reciprocity, nonempty strings, module resolution/uniqueness, length/orientation consistency; actual design objects absent |
| Nameplate sizing | 2200 Wp / 2500 W = 0.88 | DC/AC ratio INFO, configured advisory range WARNING; not an approved DC-array-power check |
| Design capability flags | Source-backed fields largely present; grid scalar unresolved | Explicit false basic/MPPT design flags block; future derivation must use real values |
| Efficiency / simulation capability | No supported transfer model | Explicit `basic_yield_ready=false` produces WARNING `INVERTER_BASIC_SIMULATION_CAPABILITY_UNAVAILABLE`, not a blocking finding; detailed runtime independently requires curves. A nonblocking electrical report does not establish efficiency readiness |
| Total DC current limits | Single-MPPT aggregate interpretation possible | Missing total-current/total-Isc ratings produce WARNING, not automatic proof; document derivation before mapping |
| Genuine project/site and revisions | None supplied for this new design | Exact pinned project/scene/electrical/config/report identities required; no manufactured report |
| Level-2 substring/region evidence | PAN cell/diode counts only | Additional topology, parameterization, bound validation/source records and frozen model selections required; engineering electrical report alone cannot resolve these |

Separate constraints **not enforced by this engineering validator** include startup voltage/hysteresis, rated-power voltage window, physical/contractual DC-array power caps, manufacturer one-string/connector input-count limits as an explicit capacity gate, conductor/mating/installation restrictions, AC apparent/current/PF dispatch and local grid certification, inverter temperature/altitude derating. Inverter snapshots carry some of these fields, but carrying a field does not demonstrate a corresponding rule. They need separate source/design review even with a nonblocking report. Runtime AC clipping and supplied-current fail-closed behavior are separate from engineering validator coverage.

## 8. Level-2 scientific evidence limitations

| Boundary | Established / unresolved |
|---|---|
| Inverter part load / manufacturer OND | Summary efficiency verified, actual transfer/domain evidence absent; low-load accuracy unknown |
| Module independent IV | Manufacturer whole-module PAN/model inputs present; independent IV dataset/validation not established by this intake |
| Bypass topology and reverse regions | NCelS/NCelP/NDiode and PAN reverse tokens do not resolve canonical coverage/interconnections or independently validated regional physics; synthetic reference topology is not Jinko evidence |
| MPPT current-constrained operation | `shading/electrical/mppt_tracker.py` evaluates constraints; `engine/inverter/model.py:simulate_voltage_dependent_inverter` fails closed when supplied operating current binds, rather than approximating a constrained IV solve |
| Thermal derating basis | No inverter curve/basis or inverter-temperature series; equipment temperature range cannot substitute |
| Shading/mismatch assumptions | Genuine geometry, regional irradiance/temperature, bypass model and tracking assumptions needed; ideal global MPP, sampling, single-module temperature and residual wiring/mismatch choices constrain accuracy |
| Site/weather compatibility | Genuine coordinates/elevation/timezone and site-compatible retained weather revision not established; B2 weather cannot be relabeled as new-project truth |
| Measured yield | No external measured-yield comparison or calibration; numerical consistency cannot establish field accuracy |

Source adequacy establishes what was stated. Design validity requires actual conditions and covered checks plus separate restrictions. Numerical readiness requires supported revision-bound models and inputs. Physical accuracy requires independent measurement/model validation. None substitutes for another.

RB-POST3D-02's accepted genuine ERA5 integration result and RB-POST3D-03's explanation of B2's 100 kW curve at low loading remain independent and unchanged. B2's existing component/scientific hashes, 48-hour execution and package-verification evidence are preserved, not recomputed or reused as approval of GoodWe/Jinko 4S1P. No simulation, weather acquisition or benchmark was performed.

## 9. Classified missing evidence and severity

Severity concerns proposed representative use, not a defect in the accepted B2 integration.

| Finding | Classification | Severity / impact |
|---|---|---|
| Full GoodWe Pin/Pout/voltage model absent | SOURCE_DATA_MISSING — FULL_EFFICIENCY_CURVE_EVIDENCE_MISSING | High: prevents supported yield model/detailed execution; electrical validator issues a warning rather than a curve-specific blocker |
| Nominal-power MPPT manual absent | SOURCE_DOCUMENT_UNAVAILABLE | High: approximately 164 V STC is not proven suitable for rated-power operation |
| Site cell temperatures/irradiance and genuine revisions absent | DESIGN_INPUT_MISSING | High: conditional arithmetic cannot approve design |
| Activation, standby/exact night loss, thermal/altitude derating absent | SOURCE_DATA_MISSING | Medium/high for representative yield and limits; defaults/bounds cannot be promoted to manufacturer values |
| 200% oversizing lacks defined engineering basis | SOURCE_SEMANTIC_AMBIGUITY | Medium: no explicit DC-array power cap/recommendation established |
| Grid alternatives and connector/installation details unresolved | DESIGN_SELECTION_AND_SOURCE_GAP | Medium: supported site grid scalar and physical installation review needed |
| Independent IV / topology / region/reverse/bypass calibration absent | SCIENTIFIC_EVIDENCE_GAP | High for source-backed Level-2 physical accuracy; PAN counts insufficient |
| Binding current solve absent | EXISTING_RUNTIME_LIMITATION | High if binding: runtime fails closed; no current-clipping approximation authorized |
| DC sizing, startup, connector, grid/thermal restrictions not comprehensively enforced | EXISTING_VALIDATOR_COVERAGE_LIMITATION | Medium/high: a nonblocking report would not certify these constraints |

Missing curves/manual/site/topology are findings, not workflow blockers under TASK.md. No required production change, irreconcilable source contradiction or inaccessible primary source was found. Historical reviews supply no applicable unresolved BLOCKER/MAJOR for this task.

## 10. Single next-task recommendation

**Obtain and fingerprint one original manufacturer-issued GW2500-XS-30 OND or equivalent voltage-dependent Pin/Pout evidence package, then assess its source/domain sufficiency read-only against the existing importer and the 4S1P voltage/load range.** Include its associated threshold/loss/reference-condition metadata; if manufacturer evidence cannot be obtained, record that outcome rather than synthesize data. This is the smallest justified next task because a supported inverter efficiency model is a decisive missing dependency. It does not authorize component finalization, site approval, production changes or simulation. Remaining manual/site/topology constraints stay recorded prerequisites, not additional recommended tasks.

Decision answers: (1) preliminary candidate **yes**; (2) verified values are precisely the SOURCE_VERIFIED rows in §3, with PAN values in §4; (3) all-limits compatibility **conditional**, not established; (4) full inverter model already present **no**; (5) partial candidate representable through existing ingestion/overlay **yes**, with grid selection and missing evidence retained honestly; (6) actual report cannot be established without design conditions/revisions and legitimately derived design fields; missing efficiency evidence warns in electrical validation and blocks detailed runtime readiness; rated-power/manual restrictions and source-backed Level-2 assets also remain unresolved; (7) only next task is the original curve-evidence intake above.

## 11. Explicit unsupported conclusions

This document does not establish manufacturer digital authentication, independent certification, complete engineering approval, a rated-power voltage-window pass/fail, all-weather 16 A compliance, a 5000 W allowable DC array, constant 97.6% conversion, exact 3 W night consumption, zero standby/activation power, a validated thermal curve, independent IV accuracy, manufacturer substring/reverse/bypass truth, solved binding-current operation, measured yield accuracy or annual representative readiness. It creates no DesignValidationReport or component revision and makes no readiness-flag override.

Assumptions are limited to the requested four original Jinko modules in 4S1P and the explicitly illustrative reference-irradiance temperature table with repository fallback guards. No climate design temperature or grid scalar was chosen. The document is the only authorized repository change. Original PDF/PAN/provenance, accepted audits/run evidence, B2 hashes, production schemas/semantics/validation gates and Git branch/HEAD remain unchanged. No staging, commit, push, branch switch or history rewrite occurred.

Verification: read-only source inspection, fingerprints, hand-formula arithmetic and Git scope inspection only. **Python regression: SKIPPED (not executed)**. Tests, npm tests, builds, benchmarks, validators and simulations were not run, per task/workflow instructions. Independent Claude review and orchestrator acceptance verification remain pending; no test PASS is reported.
