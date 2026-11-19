# Engineering validation

Phase 4.7 evaluates an exact canonical Scene + ElectricalDesign + component-revision set under explicit design conditions.

Core API:

- validate_engineering_design()
- ENGINEERING_RULE_SET_ID
- ModuleDesignState

The validator is read-only. It does not alter Scene, ElectricalDesign, component definitions, strings, MPPT assignments, or simulation configuration.

Required design-condition inputs are explicit:

~~~text
minimum_cell_temperature_c
maximum_cell_temperature_c
design_irradiance_w_m2
~~~

Optional policy inputs:

~~~text
orientation_tolerance_deg
dc_ac_ratio_warning_min
dc_ac_ratio_warning_max
temperature_model_policy
~~~

Temperature-model precedence:

~~~text
validated PVsyst single-diode model
        ↓
documented linear coefficient fallback
        ↓
INVALID if neither is executable
~~~

The linear fallback is visible in the report and uses:

~~~text
Voc(T) from beta_voc
Isc(T) from alpha_isc
Imp(T) ≈ alpha_isc relative behavior
relative beta_vmp ≈ relative gamma_pmp - relative alpha_isc
~~~

This is an approximation, not a hidden replacement for a detailed IV model.

Human-facing finding classes:

~~~text
INFO
RECOMMENDATION
WARNING
INVALID
~~~

Canonical compatibility mapping:

~~~text
INFO           -> severity=info
RECOMMENDATION -> severity=recommendation
WARNING        -> severity=warning
INVALID        -> severity=blocking_error
~~~


## Phase 4.7H-D evidence hardening

The engineering rule set is now:

~~~text
opensimpv.engineering_validation.v0.2
~~~

Detailed PVsyst single-diode evidence requires both a validated parameter set and `detailed_sdm_ready=true`.

The linear coefficient fallback is explicitly guarded:

~~~text
fallback_voltage_uncertainty_fraction = 0.05
fallback_current_uncertainty_fraction = 0.05
~~~

These are configurable project policy guards. The current defaults are regression-anchored to the accepted synthetic and manufacturer PAN fixtures; they are not asserted as universal module uncertainty bounds.

The fallback is limited to module reference irradiance because temperature coefficients do not provide validated irradiance-dependent Voc/Vmpp behavior.

Decision policy:

~~~text
absolute equipment maximum
→ compare conservative upper evidence
→ INVALID if exceeded

MPPT operating window
→ full evidence interval outside = INVALID
→ fallback interval crossing boundary = WARNING
~~~

Missing total inverter current and Isc limits are now surfaced as warnings, consistent with existing MPPT missing-limit behavior.
