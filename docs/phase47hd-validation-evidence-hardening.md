# OpenSIMPV — Phase 4.7H-D Engineering Validation Evidence Hardening

**Status:** Implementation specification  
**Date:** 2026-09-24  
**Parent:** Phase 4 Engineering Design Environment  
**Predecessor:** Phase 4.7H-C Geometry / Projection / Z Coherence

## 1. Purpose

Phase 4.7H-D hardens the evidence quality behind engineering validation before the Design → Simulation integration phase.

The validator already preferred a validated PVsyst single-diode model and fell back to source-backed temperature coefficients when a detailed model was unavailable. The remaining gap was that both paths could feed hard limits as if they had equal numerical authority.

This phase makes the evidence grade explicit.

## 2. Temperature-model precedence

~~~text
validated PVsyst single-diode
        ↓
documented linear temperature-coefficient fallback
        ↓
INVALID if neither is executable
~~~

The detailed path additionally requires capability_flags.detailed_sdm_ready = true in addition to a validated PVsyst single-diode parameter set.

## 3. Detailed-model evidence

Detailed states carry:

~~~text
evidence_grade = validated_detailed_model
voltage_uncertainty_fraction = 0
current_uncertainty_fraction = 0
~~~

No additional validation guard band is added to the detailed path.

## 4. Linear fallback evidence

The documented fallback remains:

~~~text
Voc(T) from beta_voc
Isc(T) from alpha_isc
Imp(T) ≈ alpha_isc relative behavior
relative beta_vmp ≈ relative gamma_pmp - relative alpha_isc
~~~

The fallback carries evidence_grade = linear_fallback_guarded and explicit uncertainty envelopes.

Default configuration:

~~~text
fallback_voltage_uncertainty_fraction = 0.05
fallback_current_uncertainty_fraction = 0.05
~~~

The values are configurable and serialized. They are not hidden solver constants.

## 5. Evidence basis for the default guard

Executable regression evidence compares the linear fallback against validated detailed PVsyst single-diode behavior for the OpenSIMPV synthetic PAN fixture and manufacturer Jinko PAN fixture at -10 °C, 70 °C, and 1000 W/m².

The regression gate requires maximum endpoint relative error to remain within 5% for Voc, Vmpp, Imp, and Isc.

This supports the current project default guard. It is not a universal claim that all modules or operating conditions have ≤5% fallback error.

## 6. Reference-irradiance boundary

The linear fallback is a temperature-coefficient model. It does not contain validated irradiance-dependent Voc/Vmpp behavior.

Therefore fallback validation is bounded to the module reference irradiance. If another design irradiance is requested and no detailed model is available, MODULE_TEMPERATURE_MODEL_UNAVAILABLE is INVALID.

## 7. String evidence envelopes

For a nominal value x and configured uncertainty u:

~~~text
lower = x × (1 - u)
upper = x × (1 + u)
~~~

String voltage envelopes are summed in series. Series-current envelopes use the limiting module current. Parallel-string current envelopes are summed at MPPT and inverter level.

## 8. Absolute equipment limits

Absolute safety/equipment limits use the conservative upper evidence bound, including inverter maximum DC voltage, module maximum system voltage, MPPT current/Isc limits, and total inverter current/Isc limits.

~~~text
conservative upper evidence > hard maximum
→ INVALID
~~~

The report retains nominal estimate and conservative evidence bound.

## 9. MPPT operating-voltage window

For fallback Vmpp:

~~~text
entire evidence envelope outside MPPT window
→ INVALID

evidence envelope overlaps MPPT boundary
→ WARNING

entire evidence envelope inside MPPT window
→ no boundary finding
~~~

New warning rules:

~~~text
STRING_VMPP_MIN_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW
STRING_VMPP_MAX_TEMP_FALLBACK_UNCERTAINTY_NEAR_MPPT_WINDOW
~~~

## 10. Missing current limits

Existing MPPT missing-limit warnings remain. Phase 4.7H-D adds matching inverter-total warnings:

~~~text
INVERTER_TOTAL_DC_CURRENT_LIMIT_UNAVAILABLE
INVERTER_TOTAL_DC_ISC_LIMIT_UNAVAILABLE
~~~

OpenSIMPV does not fabricate missing limits from adjacent nameplate or sizing fields.

## 11. Rule-set version

~~~text
opensimpv.engineering_validation.v0.2
~~~

## 12. Report metadata

DesignValidationReport metadata now exposes validation_evidence_policy, including the detailed/fallback evidence basis, uncertainty fractions, absolute-limit policy, MPPT-window policy, and reference-irradiance fallback boundary.

## 13. Evidence comparison API

New public helper:

~~~text
compare_temperature_model_paths()
~~~

It executes both the validated detailed path and the documented fallback for a detailed-ready module and returns endpoint relative errors. It is evidence tooling and does not change runtime model selection.

## 14. Explicit exclusions

Phase 4.7H-D does not claim universal 5% fallback accuracy, IEC 61853 validation for every component, PVsyst desktop bit-for-bit equivalence, measured-field uncertainty characterization, probabilistic component-tolerance propagation, manufacturing-bin variation, or sensor uncertainty.

## 15. Exit criterion

Phase 4.7H-D is complete when:

1. detailed and fallback paths carry different evidence grades;
2. fallback uncertainty is explicit, configurable and serialized;
3. fallback is not used for unsupported non-reference-irradiance voltage extrapolation;
4. absolute equipment limits use conservative fallback evidence;
5. MPPT-window overlap under fallback is WARNING rather than false-precision INVALID;
6. missing total inverter current/Isc limits are visible;
7. executable detailed-vs-fallback evidence stays within the configured project guard for accepted reference fixtures;
8. the complete repository validation suite passes deterministically.
