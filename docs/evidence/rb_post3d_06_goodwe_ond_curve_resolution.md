# RB-POST3D-06 — GoodWe OND and conversion-curve evidence resolution

## 1. Executive verdict

**SOURCE_EVIDENCE_UNRESOLVED.** No authentic, exact-model OND or complete manufacturer-supported voltage-dependent Pin/Pout profile for **GoodWe GW2500-XS-30, XS G3, 2500 W single-phase** was located in the accessible evidence. This is a bounded negative finding, not proof that an OND does not exist. Manufacturer attribution is established for the published documents; manufacturer confirmation of an exact-model OND or transfer profile is not established.

The datasheet's 97.6% maximum and 97.0% European efficiencies remain summary metrics. Neither determines a conversion curve. The newer manual provides additional electrical and thermal information, but does not resolve the missing transfer data. No component, candidate, curve, reference design or simulation was constructed.

The repository can ingest a future OND **conditionally**, through its existing verified `POutf_PIn` pathway. It cannot promise compatibility with an unseen OND variant. Datasheet-based electrical design validation can be pursued separately, subject to all existing gates and site evidence; detailed canonical execution cannot be justified from these summary efficiencies.

## 2. Sources examined and provenance

Inspection date: 2026-10-10. Branch: `ai/rb-post3d-06-goodwe-curve-evidence`. HEAD: `309d863b44c26f2af8b67d343b65347c98d1d437`. Initial working tree and index were clean. Paths below are repository-relative; function references describe code at this HEAD.

| Retained source | Fingerprint and identity | Status |
|---|---|---|
| `.ai/evidence/rb_post3d_05/GoodWe_XS_G3_Datasheet.pdf` | 400137 bytes; SHA-256 `18357e657ebadb379792bd8aecc26c16ba207c46c3ddd1fc9225a179131b7591`; two pages; `GoodWe-Single page-20250703-EN-V2.1` | Original retained manufacturer document, unchanged; hash matches RB-POST3D-05. Page 2 fifth column is GW2500-XS-30. |
| `.ai/evidence/rb_post3d_06/GoodWe_XS_G3_User_Manual.pdf` | 8352844 bytes; SHA-256 `926d9b8afbc5b2454465336f239e78c74bcdab77914f9489d57dbe31b35f5f19`; PDF page count 67; embedded `V1.9-2026-06-29` and GW2500-XS-30 | Supplied retained manufacturer manual, git-ignored, unchanged; not an OND export or reconstructed profile. |

The local datasheet is the governing baseline. Its specifications and attribution were reviewed through [RB-POST3D-05](rb_post3d_05_goodwe_gw2500_xs30_intake.md), whose fingerprint was independently recomputed. Read-only context also included [RB-POST3D-04](../audits/rb_post3d_04_representative_design_readiness.md) and [RB-POST3D-03](../audits/rb_post3d_03_inverter_loss_scientific_plausibility.md). Their results are historical evidence, not new execution or acceptance of the GoodWe case. The available previous intake review has zero BLOCKER/MAJOR findings and does not constitute review of this audit.

Local manual inspection used standard-library PDF stream decompression and text-fragment inspection. No PDF extraction utility or Python PDF library was available; no dependency was installed. This inspection corroborates version, model identity and selected numeric text, but is not a complete rendered-page inspection. Page-level citations below refer to the accessible official online manual; remote/local byte equality was **not** established. Hashes identify retained bytes, not independent laboratory accuracy or a digital signature.

| Official public source accessed on inspection date | Observed result / boundary |
|---|---|
| [GoodWe XS G3 product page](https://en.goodwe.com/xs-g3) | Exact target listed; Datasheet, User Manual and More Files resources examined. No OND link identified in extracted listing. |
| [Manufacturer datasheet URL](https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_XS-G3_Datasheet-EN.pdf) | Accessible two-page PDF; corroborative only, not assumed byte-identical to retained source. |
| [Supplied manual URL](https://us.goodwe.com/Ftp/EN/Downloads/User%20Manual/GW_XS%20G3_User%20Manual-EN.pdf) | Browser retrieval failed with internal error; not a negative finding about its contents. |
| [Manual reached through product-page resource](https://en.goodwe.com/Skippower/downloadFileF?id=1928&mid=60) | Accessible 67-page V1.9 manual; applicability table includes target, printed p1 / PDF p5. |
| [More Files destination](https://en.goodwe.com/download-xs-plus-series) | Product-page link reaches XS Plus+ listing, a different family. No OND/PVsyst text found in extraction; its assets are not target-model evidence. |
| [XS G3 resource-listing lead](https://en.goodwe.com/download-xs-g3-series) | Followed XS G3 link from that listing; retrieval failed with cache miss. Contents unexamined. |
| [PVsyst database documentation](https://www.pvsyst.com/help/component-database/grid-inverters/inverters-in-the-database.html) | Accessible explanatory documentation, not an exported database or exact-model record. |

Manufacturer hosting, document identity and model applicability support attribution. No correspondence or explicit confirmation was obtained. No open-source redistribution grant was established. The online manual's copyright notice (PDF p2) requires prior written authorization for public reproduction/transmission. Retention, processing and redistribution permissions must be distinguished; original PDFs were not copied into tracked documentation.

## 3. OND/database availability assessment

Repository filename inventory, including hidden non-ignored paths, found two OND files: `tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND` and `tests/fixtures/panond/synthetic_inverter.ond`. The former is a different manufacturer's 100 kW fixture; the latter is synthetic 250 kW evidence. The reference catalog is explicitly synthetic. GoodWe references in prior audits are evidence-intake references, not a GoodWe database export. Known ignored GoodWe evidence paths contain the supplied PDFs; no exact-model OND was supplied.

| Independent route | Finding | Candidate identity, status and rights |
|---|---|---|
| A. Original GoodWe OND | Not located locally or in accessible official resource listings | No candidate file; version/date, size/hash, original/exported status and manufacturer confirmation unavailable. Redistribution permission unresolved. |
| B. PVsyst database entry/export | No legitimately accessible exact-model entry/export supplied or examined | Installed database not accessed; no claim of an exhaustive search. Export version, edits, bytes/hash and target applicability unknown. |
| C. Equivalent manufacturer performance data | Published datasheet/manual provide ratings and summary metrics, no complete Pin/Pout samples at identified voltage/load conditions | Exact target applicability supported for documents in §2; documents are original publications, not reconstructed curves. No manufacturer-confirmed equivalent performance profile. |

PVsyst describes manufacturer submissions and release-based database updates, and also permits user-created or edited entries. Therefore database presence alone would establish neither laboratory validation nor the originality of an individual export. Exact model/generation, software/database version, edit/export history and manufacturer confirmation would still need inspection. [PVsyst documentation](https://www.pvsyst.com/help/component-database/grid-inverters/inverters-in-the-database.html)

No third-party OND was downloaded or promoted to manufacturer-backed status. Other XS ratings, GW2500-XS, GW2500-XS-11, XS Plus+ and regional alternatives are not interchangeable with GW2500-XS-30.

## 4. Required inverter performance evidence

Classification is element-specific: `SOURCE_VERIFIED` means directly published, not independently measured; `DERIVED_WITH_EXPLICIT_BASIS` means transparent conversion/arithmetic; `MISSING` means absent from examined evidence; `AMBIGUOUS` means published information does not settle the required semantics; `NOT_APPLICABLE` means the stated element is irrelevant to the specified representation. Partial ratings do not make the overall transfer model complete.

| Required element | Classification | Accessible evidence and remaining requirement |
|---|---|---|
| DC input-power coordinate | MISSING | No exact-model sequence of Pin samples, with measurement conditions. |
| Corresponding AC output power | MISSING | Ratings are not paired Pout samples. |
| Defined voltage dependency | MISSING | No measured transfer dependence on DC voltage. |
| Applicable DC voltage anchors | MISSING | Nominal input voltage 360 V is not an efficiency anchor. Need actual reference voltages and validity domain. |
| Part-load region / curve endpoints | MISSING | Need low-load through rated/clipping-region coverage and endpoint/extrapolation restrictions. |
| Startup voltage | SOURCE_VERIFIED | Retained datasheet p2: 50 V; distinct from power activation. |
| Startup/input-power activation threshold | MISSING | Need W threshold, voltage conditions, shutdown/hysteresis and self-check timing semantics. |
| Low-load/no-load transfer | MISSING | No transfer points or complete off/standby behavior. |
| Nominal/maximum AC active-power ratings | SOURCE_VERIFIED | Retained datasheet p2: 2500/2500 W; apparent ratings 2500/2500 VA, maximum output current 11.4 A. |
| Physical clipping/control law | MISSING | Ratings do not define voltage/PF/current-dependent control, overload or transient behavior. |
| Night self-consumption bound | SOURCE_VERIFIED | Retained datasheet p2: <3 W; not exact 3 W or zero. |
| Exact night/standby consumption model | MISSING | Conditions and optional nighttime-feature effects unresolved. |
| Thermal derating reference | AMBIGUOUS | Manual publishes 45 °C derating temperature, but no complete power-temperature curve or resolved sensor/reference basis. Operating range −25 to +60 °C does not supply breakpoints. |
| Original transfer units / normalization | MISSING | No supplied transfer profile from which to establish W, kW or fractional/nameplate bases. |
| Summary efficiency unit conversion | DERIVED_WITH_EXPLICIT_BASIS | 97.6% / 100 = 0.976; 97.0% / 100 = 0.970; metadata only. |
| Normalization of existing W/W runtime points | NOT_APPLICABLE | Existing canonical curves use absolute W; no normalization is needed for that representation. Source-specific conversion would still require evidence. |

Additional manual evidence: printed p56 / PDF p60 gives target nominal-power MPPT range **213–480 V** and labels **5000 W** as maximum input power. Printed p58 / PDF p62 publishes **45 °C** derating temperature. These resolve some prior document absences, but do not authorize interpreting 5000 W as a physical converter clipping limit or assigning thermal breakpoints. The manual describes derating causes on printed p7 / PDF p11. [Official manual](https://en.goodwe.com/Skippower/downloadFileF?id=1928&mid=60)

No curve points were synthesized, fitted or inferred from maximum/European efficiency. No constant 97.6% conversion was substituted.

## 5. RawiBumi mapper and runtime compatibility

### Original evidence versus mapping

`components/ond/parser.py` delegates to `components/panond_raw.py`, retaining source text, order, duplicate keys, indentation, paths, raw values and encoding. Parsing is not engineering interpretation. `components/ond/mapper.py:map_ond` applies `mapping-ledger.yaml` through `components/mapping.py`, retaining unmapped fields. The older OND README understates current curve support; the executable ledger/assembler governs this audit.

The ledger maps `Converter.ModeAffEnum` to profile mode, `VNomEff` to voltage anchors, and `ProfilPIOV1/V2/V3.NPtsEff` and `Point_i` to efficiency source structures. **Only Point_1 through Point_11 are explicitly mapped for each voltage profile.** A larger point count cannot assemble through this ledger without additional mapping support. Pin/Pout pairs use W/W; AC and PV-array power ratings use field-specific kW→W conversions, percentages become fractions, and `PSeuil`/`Night_Loss` are W. Display-unit labels cannot rescale every field globally. PV-array sizing limits are distinct from physical DC/MPPT limits.

`components/ond/semantics.py:_assemble_efficiency_model` accepts only `POutf_PIn`, **exactly three** voltage anchors and three complete profiles, each with integer `NPtsEff>=2`. It consumes active points only, ignoring trailing padding beyond the count. It derives efficiency=Pout/Pin, using zero for zero Pin, and records original assembly inputs, method/version and resulting curves. Unsupported mode, anchor count, missing point/count or negative power causes warnings and no assembled curves. Base `ProfilPIO` is not a substitute; `TCubicProfile` does not invoke a PVsyst compiler. Source encodings, paths and numeric conventions must fit the parser/ledger; successful raw parsing does not ensure mapping or physical validity.

### Candidate, source and revision contracts

`components/candidates.py:build_inverter_candidate` receives candidate/definition/revision/source IDs from the caller, assembles semantics, adds `INVERTER_OND_SEMANTIC_ASSEMBLY_WARNING`, runs validation, derives capabilities and separately checks schema readiness. Source attachment is not manufacturer authentication. `finalize_candidate` requires schema completeness and no error/blocking_error; `auto_validated` does not certify laboratory accuracy or design approval.

`components/source_overlay.py` permits canonical evidence fragments with source IDs/URLs, attribution/license fields, field provenance and explicit priority/conflict records. Manufacturer/model conflicts are rejected; equal-priority conflicting values raise by default; lists such as curves are atomic. This can represent genuinely supplied supplemental tables after an explicit source-preserving conversion. It is not automatic PDF/graph digitization, nor permission to create missing evidence. IDs/revisions and fingerprints must remain bound to their actual sources; identity alone cannot authenticate edits.

`components/validation.py:inverter_capabilities` separates voltage readiness, physical operating-current readiness, basic/MPPT design, yield, efficiency, sizing and derating. Basic design needs identity, MPPT/DC core and operating current, AC power/voltage/frequency/phase, source IDs and absence of relevant errors. Yield readiness recognizes several schema model types; detailed-efficiency capability accepts nonempty one-dimensional or voltage-dependent curves. **These flags are weaker than runtime checks** and cannot independently authorize this simulation. Derating flags likewise do not establish temperature basis.

### Actual runtime requirements and behavior

`engine/inverter/model.py:_runtime_ready` requires `voltage_dependent_curves`, **at least two curves**, positive AC rating/limit and MPPT voltage core. Curve evaluation additionally requires at least two finite, nonnegative Pin/Pout points per curve, strictly increasing Pin after sorting, and finite, strictly increasing voltage anchors after sorting.

`_curve_ac_output_w` linearly interpolates **Pin/Pout**, not efficiency samples. At positive input below the first point it holds the first Pout, then bounds output to [0,Pin]; at nonpositive input it returns zero. Above the last point it holds endpoint efficiency, allowing power to increase until the separate clipping stage. It does not cap output at the last source Pout. `_quadratic_voltage_output_w` clamps voltage to the anchor range, uses the nearest three anchors for quadratic interpolation when available, otherwise linear interpolation, and bounds output to [0,Pin]. Effective efficiency is subsequently clamped to [0,1]. These conversion bounds are distinct from the AC nameplate clipping limit. Multi-tracker conversion evaluates the whole-inverter curve at total DC power and weights efficiencies by tracker power share.

`simulate_voltage_dependent_inverter` accepts active MPP power only inside the MPPT window. Active Voc above the absolute DC maximum fails closed. A binding verified operating-current limit blocks because full IV operating-point solving is required; current is not silently clipped from MPP summaries. Startup uses valid `startup_power_w`, otherwise `minimum_input_power_w`, otherwise zero; conversion activates only when accepted power is **strictly greater** than the threshold. The published 50 V cannot fill a W threshold. Shutdown/hysteresis and a separate startup-voltage state machine are not implemented here.

`_ac_power_limit` uses the maximum AC rating (nominal fallback) without runtime inverter temperature. Supplied temperature requires complete ordered breakpoints and explicit compatible temperature basis; power interpolates linearly between breakpoints and holds the last verified power above the last point. Reaching a supplied absolute-temperature limit fails closed rather than fabricating zero-power behavior. Standby applies to positive raw DC with converter inactive; night applies to raw DC<=0. Each uses threshold fields, then efficiency-model loss fallback, then zero. Net AC subtracts self-consumption and can be negative. Missing-field defaults are repository policies, not verified GoodWe zeros or a complete manufacturer state model.

**Future ingestion answer:** an authentic source OND using the mapped text structure, `POutf_PIn`, three anchors and 2–11 complete points per profile could be ingested without production changes, subject to full validation/schema completion and scientific review of its domain. Other modes, two-anchor ONDs, point counts above 11, different paths/units or missing active points cross the current supported boundary. A valid file in PVsyst is not necessarily supported here. General PVsyst equivalence is not claimed.

### Engineering validation is separate

`validation/engineering/electrical.py` treats explicit false basic/MPPT design flags as INVALID and false basic yield as WARNING. Missing full efficiency data alone need not block electrical design review. Site electrical envelopes, rated-power voltage suitability, source-backed limits, array sizing semantics, connectors/protection and actual revision inputs remain required. No validator was run and no design PASS is claimed.

## 6. Alternative evidence routes

| Route | Sufficiency and supported behavior | Compatibility / readiness / provenance limitations |
|---|---|---|
| Exact manufacturer OND | Best direct candidate if exact identity, conditions and complete profiles are confirmed | Conditional mapped-format compatibility in §5; does not itself prove laboratory accuracy or all design gates. Original bytes/version and permission must be retained. |
| Confirmed PVsyst export | Potentially sufficient if manufacturer origin, exact generation and edit history are verified | Export must satisfy same mapper/runtime requirements; database presence alone is insufficient. Database/export redistribution rights are separate from manufacturer provenance. |
| Original manufacturer table/curve | Potentially sufficient with paired powers, voltage anchors, units, domain and validated conditions | Canonical fragments can represent supported curves; an arbitrary table/plot is not automatically an OND. Digitization/uncertainty would need explicit basis. One voltage curve does not satisfy current runtime; no conversion performed. |
| Lower-fidelity existing contracts | Constant and one-dimensional models exist in schema/capability/resolver contracts | `engine/simulation/models/inverter_resolver.py` can resolve them, but `engine/simulation/canonical.py` rejects non-voltage-dependent models as resolved-but-not-executable; `engine/losses/chain.py` calls the voltage-dependent implementation. No executable alternative is established for this canonical path. Summary efficiencies do not justify constant behavior anyway. |

There is no authorized fidelity reduction or alternative-model implementation. Datasheet-only design intake is distinct from conversion/yield execution and does not cure the missing source profile.

## 7. GoodWe/Jinko relevance

Screening reference only: four Jinko JKM550M-72HL4-V 550 W modules in **4S1P**, 2200 Wp; GoodWe rated AC 2500 W; DC/AC ratio **0.88**, derived as 2200/2500. From the retained PAN values reported in RB-POST3D-05, STC string Vmp=163.60 V and Voc=198.48 V, with series current 13.45 A / Isc 14.03 A. These are arithmetic screening coordinates, not hourly operating points.

Nameplate size makes low and intermediate load performance practically relevant, especially activation and fixed losses; it cannot establish a load histogram, expected yield or absence of clipping. RB-POST3D-03's 533–1427 W range belongs to the earlier numerical fixture and must not be reused as GoodWe operating predictions. Prior illustrative 132–186 V sensitivity is likewise not site climate or a measured voltage distribution.

The manual's nominal-power MPPT range places STC Vmp below its lower bound. This limits a claim of rated-power voltage suitability; it does **not** establish failure at sub-rated power inside the broader MPPT operating window. It reinforces the need for voltage-dependent transfer evidence near actual string operation. Voltage/string screening and conversion completeness remain separate. No string topology or reference design was changed, and no energy/yield result is asserted.

## 8. Manufacturer technical-data request

Draft only; no correspondence sent.

**Subject: GW2500-XS-30 XS G3 — original PVsyst OND and validated conversion data**

Please provide the original, model-specific PVsyst OND for GoodWe GW2500-XS-30 (XS G3, 2500 W single-phase), with document/file version, date, applicable hardware/firmware and market variants, supported PVsyst version and confirmation of manufacturer origin. Please identify whether it is original, exported or modified and provide its revision history.

If no OND is available, please supply original validated DC-input/AC-output power tables in absolute units at identified DC voltages, spanning activation, low load, part load, rated output and clipping. Include voltage anchors and applicable operating domain, units/normalization, measurement/reference conditions and uncertainty, and permitted interpolation/extrapolation. Low-string-voltage behavior is particularly relevant to a preliminary four-module series string around 164 V at STC.

Please clarify input-power startup/activation and shutdown thresholds, voltage conditions, hysteresis and delays; exact night and standby losses and feature-dependent conditions; AC active/apparent/current and clipping restrictions; and temperature derating data with temperature reference/sensor basis, breakpoints, absolute-limit behavior, cooling/installation and altitude restrictions. Please clarify the physical versus array-sizing meaning of the manual's maximum-input-power label and nominal-power MPPT restriction below 213 V.

Please confirm applicability against datasheet EN-V2.1 (2025-07-03) and manual V1.9 (2026-06-29), and give explicit permission and conditions for storing, processing and redistributing the OND/performance data and derived canonical representation in an open-source component library. Attribution and licensing requirements should be stated separately from confirmation of technical authenticity.

## 9. Classified gaps and acceptance impact

| Gap | Classification | Acceptance impact |
|---|---|---|
| Exact-model original OND / confirmed equivalent profile | MISSING | SOURCE_EVIDENCE_UNRESOLVED; acceptable negative audit result, prevents justified curve construction. |
| Complete Pin/Pout voltage/load domain | MISSING | Detailed execution/source-backed full conversion readiness cannot be claimed. |
| Activation W threshold and exact self-consumption | MISSING | Numerical defaults cannot be promoted to manufacturer values. |
| Complete thermal curve/reference basis | AMBIGUOUS | Published derating temperature alone cannot satisfy runtime thermal contract. |
| Maximum-input-power physical meaning / sub-rated voltage performance | AMBIGUOUS | Requires interpretation evidence before canonical mapping or compliance claims. |
| Installed PVsyst exact-model entry/export | MISSING | Accessibility limitation, not demonstrated database absence. |
| Open-source redistribution permission | MISSING | Manufacturer provenance does not grant distribution rights. |

Explicit readiness answers:

1. **Authentic exact-model OND located?** No, within examined accessible evidence.
2. **Manufacturer confirmation established?** Published-document attribution yes; OND/profile confirmation no.
3. **Complete load-dependent efficiency data available?** No.
4. **Does existing code support supplied format?** Supplied PDFs are evidence, not directly ingested OND profiles. Conditional future OND compatibility is defined in §5; no unseen format is declared supported.
5. **What prevents source-backed canonical readiness?** Missing exact-model curves/domain, threshold/loss evidence, unresolved thermal and limit semantics, source confirmation/rights and remaining schema/design evidence. No candidate was assembled to claim actual flags.
6. **Can design validation proceed independently?** Yes, conditionally with legitimate datasheet/manual evidence and project/site/revision inputs, preserving existing gates; no PASS or full execution readiness follows.
7. **Which manufacturer evidence remains required?** The original confirmed OND or equivalent validated profiles, conditions/domain, activation/loss/thermal/control semantics, version applicability and storage/processing/redistribution permission requested in §8.
8. **Smallest justified next action?** Obtain that exact-model technical-data response; §10 contains the sole recommendation.

## 10. Single next action

**Request the exact-model manufacturer evidence and permissions using §8 through GoodWe or an authorized technical representative.** This audit only prepares the request. An evidence deficit does not justify a production implementation task or fabricated component.

## 11. Unsupported claims and search limitations

The search was confined to supplied/repository evidence and the named official public resources and their relevant links. No installed PVsyst database, unrelated user files or Windows installation directories were traversed. PVsyst was not executed; no GUI export or database modification occurred. Dynamic or inaccessible listings may contain resources not visible in the browser extraction. Negative string/filename findings are not exhaustive global searches.

The retained manual was only partially decoded locally; official online text supplied page-level corroboration. No remote-byte hash equivalence, independent laboratory validation, manufacturer correspondence, complete license audit or exhaustive performance-plot inspection is claimed. No third-party curve, summary efficiency, neighboring model, nominal-voltage label or runtime default establishes the missing profile.

Only this Markdown document is created. Original source files, component/weather revisions, B2/ERA5 artifacts, numerical contracts, topology, signed losses and provenance are untouched. No tests, builds, benchmarks, simulations or weather acquisition were executed. **Python regression: SKIPPED by Codex**, per task; orchestrator verification and independent review remain pending. No staging, commit, branch switch, merge, push or history change occurred.
