# RawiBumi — Engineering Validation Engine v0.1


**Status:** Phase 4.7 implementation specification  
**Date:** 2026-09-24  
**Parent:** Engineering Design Environment Specification v0.1


## 1. Purpose


Phase 4.7 determines whether a canonical PV electrical design is electrically compatible under explicit design conditions.


The validator consumes:


~~~text
SceneRevision
ElectricalDesignRevision
exact component revisions
EngineeringValidationConfiguration
~~~


and produces:


~~~text
DesignValidationReport
~~~


The validator is read-only.


## 2. Governing Policy


The Phase-4 handoff rule is retained:


~~~text
physically impossible
or explicitly unsupported
→ normally block simulation


non-optimal but physically valid
→ normally remains simulatable
~~~


The human-facing classifications are:


~~~text
INFO
RECOMMENDATION
WARNING
INVALID
~~~


For compatibility with the Phase-4.0 canonical finding schema, INVALID is serialized as:


~~~text
classification = INVALID
severity       = blocking_error
~~~


No previously frozen severity field is renamed.


## 3. Explicit Design Conditions


Temperature/current checks shall not silently invent site design conditions.


EngineeringValidationConfiguration therefore requires:


~~~text
minimum_cell_temperature_c
maximum_cell_temperature_c
design_irradiance_w_m2
~~~


Optional policy:


~~~text
orientation_tolerance_deg
dc_ac_ratio_warning_min
dc_ac_ratio_warning_max
temperature_model_policy
~~~


No default minimum or maximum design temperature is embedded in the validator.


## 4. Module Temperature Model


### 4.1 Preferred path


If an exact module revision contains a validated PVsyst single-diode model executable by the Phase-3 engine, Phase 4.7 evaluates it at:


~~~text
configured design irradiance
minimum cell temperature
maximum cell temperature
~~~


and resolves:


~~~text
Voc
Vmpp
Imp
Isc
~~~


### 4.2 Linear fallback


If a validated detailed model is unavailable and policy permits fallback, the validator may use canonical temperature coefficients only when their basis is explicitly:


~~~text
absolute
or
relative
~~~


Required coefficients:


~~~text
alpha_isc_per_c
beta_voc_per_c
gamma_pmp_per_c
~~~


Voc is directly corrected from beta_voc.


Isc is corrected from alpha_isc and scaled to the configured design irradiance.


Because v0.1 component schema does not contain an independent Vmpp temperature coefficient, the fallback explicitly approximates:


~~~text
relative beta_vmp
≈
relative gamma_pmp
-
relative alpha_isc
~~~


and approximates Imp temperature response from relative alpha-Isc behavior.


Every use of this fallback emits:


~~~text
MODULE_TEMPERATURE_MODEL_DOWNGRADED
→ WARNING
~~~


The report records the exact fallback basis.


### 4.3 No defensible model


If neither detailed execution nor the documented coefficient fallback is available:


~~~text
MODULE_TEMPERATURE_MODEL_UNAVAILABLE
→ INVALID
~~~


Values are not guessed.


## 5. Cold Voc


For every enabled StringCircuit, module Voc values at the configured minimum cell temperature are summed in series.


Checks:


~~~text
string Voc cold
≤ inverter absolute max DC voltage


string Voc cold
≤ lowest known module max-system-voltage rating in that string
~~~


Violation:


~~~text
INVALID
~~~


## 6. Vmpp Temperature Window


For each enabled string, Vmpp is evaluated at:


~~~text
minimum configured cell temperature
maximum configured cell temperature
~~~


Both endpoints are compared to the exact target MPPT operating-voltage window from the bound inverter revision.


Outside the MPPT window:


~~~text
INVALID
~~~


The validator does not replace the actual topology or change string length.


## 7. String Operating Current and Isc


For each enabled string, the design-condition current state includes:


~~~text
Imp at maximum configured cell temperature
Isc at maximum configured cell temperature
~~~


For a series string, current is constrained by the lowest-current module in the string.


A per-string informational finding makes the computed design current inspectable.


## 8. Per-MPPT Current


Parallel strings assigned to an MPPT are summed.


Checks:


~~~text
Σ string Imp
≤ MPPT max operating current


Σ string Isc
≤ MPPT max short-circuit current
~~~


Known hard-limit exceedance:


~~~text
INVALID
~~~


If the exact inverter revision does not provide one of these limits:


~~~text
WARNING
~~~


because that particular compatibility check is incomplete.


## 9. Total Inverter Input Current


Across all enabled strings connected to the inverter:


~~~text
Σ string Imp
≤ inverter max DC current


Σ string Isc
≤ inverter max DC short-circuit current
~~~


Known hard-limit exceedance:


~~~text
INVALID
~~~


## 10. DC/AC Ratio


Connected STC DC power is calculated from the unique enabled strings connected to each inverter:


~~~text
DC/AC ratio
=
connected module STC Pmp
/
inverter nominal AC power
~~~


The ratio itself is:


~~~text
INFO
~~~


No universal warning threshold is hard-coded.


If a project explicitly configures:


~~~text
dc_ac_ratio_warning_min
dc_ac_ratio_warning_max
~~~


an out-of-range ratio becomes:


~~~text
WARNING
~~~


not INVALID.


## 11. Unequal String Length


Parallel strings on the same MPPT with different module counts produce:


~~~text
MPPT_UNEQUAL_STRING_LENGTH
→ WARNING
~~~


This does not automatically block simulation because unequal lengths are a design-quality/topology issue rather than universally physically impossible.


Runtime model limitations may still impose stricter execution scope separately.


## 12. Orientation Mismatch


Modules/strings sharing one MPPT are compared by field tilt and azimuth.


A configurable angular tolerance is used.


Mismatch:


~~~text
MPPT_ORIENTATION_MISMATCH
→ WARNING
~~~


The editor does not automatically separate or reassign strings.


## 13. Component and Model Capability


Exact component revisions remain authoritative.


Examples:


~~~text
missing bound component revision
→ INVALID


explicit inverter basic_design_ready=false
→ INVALID


explicit inverter mppt_design_ready=false
→ INVALID


detailed module model missing but linear fallback available
→ WARNING


basic simulation capability explicitly unavailable
→ WARNING
~~~


This separates electrical impossibility from simulation-model quality.


## 14. Structural Preconditions


Phase 4.7 performs a minimum structural precheck before electrical arithmetic:


~~~text
enabled string has resolvable MPPT
string↔MPPT assignment is reciprocal
referenced module exists and is enabled
module belongs to only one enabled string
module has a valid PVField
module revision matches its parent PVField revision
MPPT index exists on exact inverter revision
~~~


Structural contradictions are:


~~~text
INVALID
~~~


Phase 4.6 remains the topology-authoring layer.


## 15. Determinism


For identical:


~~~text
Scene
ElectricalDesign
component revisions
validation configuration
report ID
generated_at
~~~


the validation report and finding ordering are identical.


Finding IDs are assigned only after deterministic sorting.


## 16. Report Semantics


DesignValidationReport remains the Phase-4.0 canonical envelope.


Status:


~~~text
no findings
→ valid


non-blocking findings only
→ valid_with_findings


one or more INVALID findings
→ invalid
~~~


blocking_simulation=true only when at least one finding maps to legacy blocking_error.


Metadata records:


~~~text
classification counts
exact validation configuration
design_mutated=false
temperature-model precedence
linear fallback assumption
~~~


## 17. Explicit Exclusions


Phase 4.7 does not:


- resize strings;
- reassign MPPTs;
- replace components;
- repack PV fields;
- modify validation inputs;
- derive site design temperatures from weather automatically;
- perform code-specific conductor/fuse sizing;
- perform full MV protection coordination.


Those require separate design or standards layers.


## 18. Exit Criterion


Phase 4.7 is complete when a user can determine, from the canonical report alone, whether the configured PV string/inverter design is electrically compatible under explicit design conditions, including temperature-corrected voltage and current constraints, without an external sizing spreadsheet.