# Huawei 104.5 kWp engineering reference preflight

## Scope and identities

RB-POST3D-07 is a distinct, offline component-intake and engineering-design reference. It does not replace Phase 6.10 B2. The reference binds `rb-post3d-07-jinko-r1` and `rb-post3d-07-huawei-r1` to `rb-post3d-07-scene-r1`, `rb-post3d-07-electrical-r1` and `rb-post3d-07-project-r1`. Candidates are in memory; neither the component catalog nor original fixtures are changed.

The fixed timestamp is `2026-10-11T00:00:00Z`. Every reference has 190 enabled modules, ten strings of exactly nineteen modules, ten independent MPPTs and one inverter. Each MPPT has one reciprocally assigned string. Ten of twenty available DC inputs are selected; no parallel branch allocation is required.

## Manufacturer fingerprints and provenance

| Evidence | Checked-in SHA-256 | Original provenance SHA-256 |
| --- | --- | --- |
| Huawei_Sun2000_100KTL_M1.OND | f4e753a7d4b8057136cb528a0cbcdda0126a059e6d745ece889dce8f889f16de | 391f307112b4e5543ea9135b005e5408856d8e93c677cd60ed485615ab95b6f3 |
| JKM550M-72HL4-V_SGS_6079M3.PAN | aff43dc4f6b5213abd87a14e0814fda47b8bb51bf7cb439bfa5fa590190229f3 | 24bc13172fd13646f1a9a408d3fd462b1e7b6b8ee84923c83335e15e1f1b8764 |
| Huawei_100KTL_M1_Datasheet.pdf | 8a6f1de9b134464c0748881ca33a0ba1b0c61f427a0887eadefd2a9f97fee4dc | Retained PDF identity |

The supplied OND hash matches the checked-in OND exactly. Adding a UTF-8 BOM and converting LF to CRLF reconstructs the recorded original OND (3587 bytes) and PAN (1440 bytes). This is a serialization difference, not a different source revision. The tool verifies both identities and the existing provenance records without rewriting them. Embedded source statements are Manufacturer 2018 (Huawei) and Manufacturer 2020 SGS-CSTC (Jinko). Repository provenance records retain the maintainer's redistribution confirmation; no new license grant is inferred.

The PDF is retained at `.ai/evidence/rb_post3d_07/Huawei_100KTL_M1_Datasheet.pdf`; its [official source](https://solar.huawei.com/-/media/Solar/attachment/pdf/apac/datasheet/SUN2000-100KTL-M1.pdf) is recorded as attribution only. No network request or PDF extraction is performed. Supplemental values are explicit transcriptions pinned to its hash.

## Intake and canonical interpretations

The existing raw parsers, mapping ledgers, candidate builders and source-overlay implementation govern interpretation. Full mapping records, unmapped fields, derivations, component findings, source conflicts, source IDs and field-level inverter provenance are retained in generated JSON.

| Field | Value | Basis |
| --- | --- | --- |
| Rated / maximum AC active power | 100000 / 110000 W | OND PNomConv / PMaxOUT |
| Selected AC voltage and phase | 380 V, three phase | OND VOutConv / MonoTri |
| AC frequency | 50 Hz | Pinned datasheet supplement |
| Absolute DC / MPPT voltage | 1100 V / 200–1000 V | OND VAbsMax / VMppMin / VMPPMax |
| Startup voltage | 200 V | Pinned datasheet supplement; distinct from startup power |
| MPPTs / available inputs | 10 / 20 | OND NbMPPT / NbInputs |
| MPPT operating / short-circuit current | 26 / 40 A | Pinned datasheet supplement |
| Recommended nominal / maximum PV array nameplate | 130000 / 130000 W | OND PNomDC / PMaxDC; existing ledger array-sizing interpretation |
| PV-array sizing current field | 40 A | OND IMaxDC; not physical total or operating MPPT current |

OND POutf_PIn conversion curves at 200, 650 and 1000 V remain intact, with eight active Pin/Pout samples per anchor. No synthetic curve, efficiency or clipping approximation is introduced. PV-array sizing fields remain separate from physical conversion limits and AC clipping. Input-specific operating/Isc limits and physical total-inverter DC operating/Isc limits are unknown and are not fabricated. The existing engineering rule set governs their warnings; capability flags cannot convert unknown limits into a pass.

The OND fragment has priority 50 and the manufacturer-datasheet fragment priority 100. Readiness flags are removed from the base fragment and recomputed by `build_candidate_from_fragments`. The tool also checks those computed flags against `inverter_capabilities`. Unsupported overlay keys/values and changed source fingerprints fail closed. Legitimately unmapped OND fields are disclosed rather than silently interpreted.

## Module and electrical arithmetic

The original Jinko PAN supplies 550 W nameplate, Vmp 40.90 V, Voc 49.62 V, Imp 13.450 A and Isc 14.030 A. Its muVocSpec −137.9 mV/K maps to −0.1379 V/K. Maximum system voltage is 1500 V. Existing module mapping and single-diode STC/off-STC validation are used; there is no copied synthetic B2 model.

The repository intentionally distinguishes PAN PNom from Vmp × Imp. Nameplate is 550 W; mapped reference MPP is 550.105 W. Thus the requested nameplate array is **104500 Wp**, DC/AC **1.045**, while validator power calculations use the existing mapped MPP semantics (104519.95 W, ratio 1.0451995). Neither value is overwritten to force agreement.

STC string values are Vmp **777.10 V**, Voc **942.78 V**, Imp **13.45 A**, Isc **14.03 A**. STC values alone do not establish temperature compliance.

## Numerical design envelope and geometry

**NUMERICAL TEST ASSUMPTION:** −10 °C minimum and +70 °C maximum cell temperature, 1000 W/m² design irradiance. These are not certified site extrema. Configuration mirrors `apps/api/study.py::_validation_configuration`; a regression checks equality, including 5% fallback voltage/current uncertainty and the existing detailed-then-linear model policy.

**NUMERICAL TEST ASSUMPTION:** a 60 × 40 m synthetic flat support surface, ten rows of nineteen portrait modules, uniform 10° tilt and 0° azimuth, 3 m row pitch, 0.02 m module gaps and 0.2 m mounting height. Geometry provenance uses canonical `user_override`. No actual roof, verified installation, geolocation, protection design or approved plant layout is asserted.

The validator's existing module-temperature resolver supplies the envelope. Generated JSON records its model basis, evidence grade, downgrade status and endpoint Voc/Vmp/Imp/Isc values and uncertainty fractions. Its complete findings retain all voltage, current, module-system-voltage, sizing, ratio, topology, AC and capability checks. The real in-memory validator run resolves `validated_pvsyst_singlediode`, evidence grade `validated_detailed_model`, with `downgraded=false` and voltage/current uncertainty fractions both **0.0**. The configured 5% uncertainty applies only if the model falls back; it is not applied here. The tool intentionally reuses the validator's private `_module_state` resolver for supplemental envelope evidence; regression coverage binds its currents to the actual report.

| Endpoint check | Validator-derived result | Limit / margin |
| --- | --- | --- |
| 19S cold Voc | 1032.0147 V | 1100 V; 67.9853 V margin |
| 19S cold Vmp | 871.0483 V | Below 1000 V |
| 19S hot Vmp | 654.2485 V | Above 200 V |
| Cold / hot Imp per MPPT | 13.2631 / 13.4223 A | Below 26 A |
| Cold / hot Isc per MPPT | 13.8001 / 14.3256 A | Below 40 A |

Cold string Voc is also below the module's 1500 V system-voltage limit. Connected mapped MPP power 104519.95 W is below the source's 130000 W array-sizing limit.

An independent +1/+2/+3% positive Voc sensitivity sweep is explicitly test-only, applied to cold nominal Voc with margins to 1100 V. PAN +3% PNom tolerance is a **power tolerance**, not evidence of a Voc tolerance. Sensitivity does not change configured uncertainty or the design verdict. The 20S × 10 candidate appears only as comparison: 110 kWp, ratio 1.10, with cold nominal and conservative Voc and margin. It never replaces 19S. Its actual cold Voc is **1086.3313 V**, with only **13.6687 V** margin; conservative Voc is identical because this model has zero uncertainty. A separate +2% numerical Voc sensitivity would exceed 1100 V for 20S; no manufacturer Voc tolerance is asserted.

## Actual report and readiness

`--validate` invokes the real `validate_engineering_design()` with the exact scene, electrical revision, source-backed components, canonical configuration and fixed report identity. It retains the complete returned report, status, blocking flag, counts, rule set, revision IDs and every finding in `.ai/validation/rb_post3d_07/validation.json`. No substitute PASS report is constructed. A blocking report is written as evidence and causes nonzero exit. Invalid/missing provenance or mandatory intake errors fail before design execution.

An actual in-memory call to the real validator returned **`valid_with_findings`**, **`blocking_simulation=false`**, with 13 findings: two warnings and eleven informational findings. Warning rule IDs are `INVERTER_TOTAL_DC_CURRENT_LIMIT_UNAVAILABLE` (aggregate operating current 134.2227 A) and `INVERTER_TOTAL_DC_ISC_LIMIT_UNAVAILABLE` (aggregate Isc 143.2559 A). Their source boundary is the absence of independently supported total-inverter limits; both warnings are retained. Informational rules are `INVERTER_DC_AC_RATIO` (once) and `STRING_DESIGN_CURRENT_COMPUTED` (ten times). There are no blocking findings or model-downgrade warnings. The returned report remains authoritative. Codex ran no tests, builds, benchmarks or simulation; targeted test execution remains owned by the orchestrator.

| Status tier | Verdict |
| --- | --- |
| SOURCE_BACKED_COMPONENT | Achieved for the pinned sources and source-backed intake |
| ENGINEERING_DESIGN_VALIDATED | Achieved: actual nonblocking `valid_with_findings` report; two warnings retained |
| LEVEL_2_EXECUTION_READY | Not achieved |
| PHYSICAL_YIELD_VALIDATED | Not achieved |

A nonblocking `valid_with_findings` result is an engineering-design gate only. It does not establish protection/connector evidence, actual installation approval, full thermal-derating reference basis, source-backed module substring/bypass parameterization or externally calibrated yield accuracy. The accepted RB-POST3D-03/04 audits and RB-POST3D-05/06 evidence remain the scientific boundary; GoodWe is historical context. Existing MPPT current-binding runtime limitations remain enforced. No Level-2 execution at 190 modules, signed module-quality inference, temperature/inverter/shading physics changes or energy simulation is authorized or performed.

## Usage and reproducibility

From the repository root:

```sh
python tools/rb_post3d_07_huawei_design_preflight.py --help
python tools/rb_post3d_07_huawei_design_preflight.py --preflight
python tools/rb_post3d_07_huawei_design_preflight.py --validate
```

Preflight is read-only: it verifies pinned sources, original serialization, PDF signature, mapped mandatory values and exact configuration arithmetic; it writes no artifacts. Validation writes only the isolated ignored JSON artifact, rejects redirected output paths, never acquires weather and never imports simulation orchestration. The weather provider module is imported transitively by existing dependencies, but its acquisition entry point is not called. Stable IDs, timestamps, ordering and JSON serialization make repeated validation outputs reproducible. Accepted run packages are untouched. No new dependencies are introduced.

Orchestrator test target: `tests/unit/test_rb_post3d_07_huawei_design_preflight.py`. Coverage includes identity, arithmetic, capability derivation, topology reciprocity, real validator execution, envelopes, physical current violations, fail-closed sources/overlay, missing-overlay blocking, offline CLI behavior and deterministic output. Tests were added and corrected, not executed; orchestrator testing and independent review remain pending.
