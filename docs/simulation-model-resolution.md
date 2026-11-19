# Simulation Model Resolution & Progressive Fidelity v0.1


Phase 1 defines how RawiBumi converts canonical component data into an explicit simulation
model selection.


The resolver does not perform annual energy simulation yet. Its responsibility is narrower
and foundational:


```text
canonical component revision
        ↓
engineering validation
        ↓
eligible registered models
        ↓
highest justified model
        ↓
optional refinement availability
        ↓
assumption / limitation ledger
        ↓
resolved simulation-model contract
```


This layer prevents three failure modes:


1. treating PAN/OND completeness as the definition of simulation capability;
2. silently inventing parameters when optional refinement data are missing;
3. silently falling back from an explicitly requested model.


## Core rule


```text
minimum trustworthy inputs
    -> lower-fidelity calculation


additional trustworthy inputs
    -> additional checks and/or higher-fidelity model


missing optional refinement
    -> explicit limitation, not fabricated data
```


The result is deterministic for a fixed component revision and resolver version.


## Module model resolution


Phase 1 registers two module model contracts.


### 1. `module.pvsyst_singlediode.v6`


Priority/fidelity rank: 300.


Eligibility requires a canonical `pvsyst_singlediode` model whose stored validation result
has `passed=true`.


The resolver therefore does not select detailed single-diode behavior merely because the
parameter names are present.


### 2. `module.stc_tempco_linear.v0.1`


Priority/fidelity rank: 100.


This is the explicit lower-fidelity fallback when trustworthy STC electrical points and
temperature coefficients exist but a validated detailed SDM is unavailable.


Required canonical data include:


- Pmp, Voc, Isc, Vmp, Imp;
- reference irradiance;
- reference cell temperature;
- alpha Isc;
- beta Voc;
- gamma Pmp;
- an interpretable coefficient basis: `absolute` or `relative`;
- source traceability.


The model contract intentionally does not claim detailed IV behavior.


If a component also contains an unsupported model entry such as a future/custom model, the
resolver may still select the valid basic fallback. The unsupported entry is recorded as a
warning rather than blocking unrelated calculation.


## Inverter model resolution


Phase 1 registers three conversion contracts.


### 1. `inverter.voltage_dependent_efficiency.v0.1`


Priority/fidelity rank: 300.


Selected when the canonical inverter contains explicit voltage-dependent efficiency curves.


The manufacturer Huawei OND fixture resolves to this model.


### 2. `inverter.one_dimensional_efficiency.v0.1`


Priority/fidelity rank: 200.


Selected when a verified single load-dependent efficiency curve is supplied.


### 3. `inverter.constant_efficiency.v0.1`


Priority/fidelity rank: 100.


Selected when an explicit constant efficiency is supplied.


This is a deliberate basic fallback and is reported as such.


Inverter conversion resolution also requires:


- a valid maximum DC voltage;
- an MPPT voltage domain;
- at least one MPPT or MPPT template;
- nominal AC active power;
- source traceability.


Physical MPPT operating-current data are **not** mandatory for basic voltage/efficiency-based
energy conversion.


## Independent refinements


Refinements are resolved separately from the primary conversion model.


### MPPT current limit


When a physical maximum operating-current value exists for the MPPT template or every
individual MPPT:


```text
mppt_current_limit -> enabled
```


If absent:


```text
energy conversion may proceed
current clipping refinement unavailable
current-limit design check unavailable
```


The resolver explicitly warns not to infer the value from contractual PV-array current
fields.


### Temperature derating


A temperature derating refinement is available when its power/temperature breakpoints are
present.


If the component stores `temperature_basis=unknown`, the data are retained as available but
the resolver emits a warning that the simulation configuration must choose the runtime
temperature basis before applying them.


### Night loss


A source-backed nonnegative `night_loss_w` enables the night-loss refinement.


When missing, the resolver does not silently set it to zero. It records that no component
night-loss term is justified and leaves a future explicit simulation override possible.


### Startup threshold


A source-backed minimum-input-power or startup-power threshold enables low-power startup
refinement.


## Explicit user/model requests


Automatic resolution chooses the highest-fidelity eligible registered model.


However, an explicit request is authoritative.


If the user/configuration requests:


```text
module.pvsyst_singlediode.v6
```


for a component that only supports the STC/temperature-coefficient fallback, RawiBumi does
not silently substitute the fallback. Resolution becomes `blocked`.


The same applies to explicit inverter models and required refinements.


Example:


```text
required refinement = mppt_current_limit
Huawei OND only      = no physical operating-current value
result                = blocked
```


Adding the Huawei datasheet overlay with the 26 A operating-current limit resolves the same
requirement without modifying the OND evidence.


## Resolved component object


Each module/inverter resolver emits a `ResolvedComponentModel`:


```text
resolution_id
component type
component definition/revision IDs
status
requested model
selected model
enabled refinements
unavailable refinements
assumption ledger
warnings
source IDs
capability snapshot
```


The selected model records:


```text
model_id
model_family
fidelity_rank
source model type
implementation status
component model version
parameter source path
validation status
```


This object is intended to be stored with each immutable simulation run.


Phase 6.1 also consumes the module `ResolvedComponentModel` as the trusted
detailed-SDM capability handoff for electrical shading. The shading resolver does
not authorize detailed-SDM fidelity from a raw ModuleDefinition capability flag
and does not re-run component validation. For Level 1+ it requires an exact
module-revision match and a resolved selected model of
`module.pvsyst_singlediode.v6` whose implementation contract and stored model
validation are both accepted; the capability snapshot must agree with that
resolved model state.


## Assumption ledger


All material resolution choices are serialized as `SimulationAssumption` records.


Kinds currently include:


- `model_selection`;
- `fallback`;
- `missing_refinement`;
- `unsupported_model`;
- `explicit_requirement`;
- `limitation`.


Each record contains:


- statement;
- basis;
- severity;
- relevant canonical source paths;
- affected simulation behavior.


This is the beginning of the simulation assumption/limitation ledger that will later appear in
engineering reports.


## Combined system resolution


`resolve_simulation_models()` resolves a module and inverter together.


The combined result is `resolved` only if both components are resolved and all explicitly
required refinements are available.


No geometry, weather, irradiance, thermal, or shading model is selected in Phase 1. Those are
later phases.


## Registered vs unsupported future component models


The canonical component schemas already allow model types that do not yet have a frozen
Phase-1 execution contract.


For example an imported component may contain:


```text
sandia
pvwatts
custom
desoto_singlediode
cec_sam
```


Their presence must not be discarded, but RawiBumi does not claim executable support until
the corresponding parameter contract and implementation are defined and tested.


Where a lower-fidelity registered fallback exists, calculation can continue with a warning.


Where no registered executable model is justified, resolution is blocked.


## Current reference cases


The unit suite covers:


- validated synthetic PAN -> detailed PVsyst SDM;
- basic user CSV module -> STC/temperature-coefficient fallback;
- explicit unavailable module-model request -> blocked;
- real Jinko manufacturer PAN -> selection follows actual SDM validation evidence;
- Huawei OND -> detailed voltage-dependent efficiency model;
- Huawei OND without 26 A current limit -> basic yield allowed, current clipping unavailable;
- Huawei OND + manufacturer datasheet overlay -> current-limit refinement enabled;
- user CSV inverter with explicit constant efficiency -> lower-fidelity conversion fallback;
- explicitly required unavailable current refinement -> blocked;
- inverter without executable efficiency model -> blocked;
- combined module/inverter model resolution;
- JSON Schema validation of the serialized resolution records.


## Phase boundary


Phase 1 froze **selection contracts** independently of numerical execution.


Phase 2 implemented weather ingestion/QC.


Phase 3 now consumes these resolution contracts. Phase 3.8E persists the exact
`SimulationModelResolution` and its assumption ledger inside each canonical
`SimulationRun`.


A model may be correctly resolved by the registry yet still be outside the numerical
implementation scope of the current kernel. Phase 3.8E treats that as an explicit blocking
execution-scope finding rather than silently choosing another model.