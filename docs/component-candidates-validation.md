# Component candidates and engineering validation v0.1


This layer sits after PAN/OND semantic mapping and before a component revision becomes an
accepted library record.


```text
raw source
  -> lossless parser
  -> semantic mapping
  -> ComponentCandidate
  -> engineering validation
  -> capability flags
  -> review / finalization
  -> immutable component revision
```


## Candidate rule


A candidate may be incomplete.


RawiBumi must not invent zeroes, generic currents, AC ratings, temperature coefficients, or
efficiency curves merely to satisfy the final `ModuleDefinition` or `InverterDefinition`
schema. Missing engineering data remains missing and the candidate records why it is not
schema-ready or simulation-ready.


## Module behavior


The builder translates mapped canonical paths into a nested partial `ModuleDefinition`.
Where Vmp and Imp are both source-backed, it calculates:


```text
pmp_w = vmp_v * imp_a
```


as an explicit **derived** value. The derivation record identifies its inputs and algorithm.
This does not overwrite or reinterpret PAN `PNom`, which remains
`stc.nominal_power_w`.


Module validation currently checks:


- manufacturer and model presence;
- positive width/height and optional mechanical values;
- positive STC electrical values;
- Voc > Vmp;
- Isc >= Imp;
- Pmp consistency with Vmp × Imp using configurable tolerance;
- system-voltage limits >= Voc;
- positive one-diode resistance parameters where present.


The default Pmp consistency tolerance is currently 2% and remains a configurable engineering
default rather than a hidden constant.


## Module capability flags


`layout_ready` requires identity and valid physical dimensions.


`basic_yield_ready` additionally requires the complete V1 STC set, traceable source, complete
temperature coefficients, and no material electrical/limit validation errors.


`detailed_sdm_ready` additionally requires a complete supported PVsyst single-diode
parameter set **and a successful model-validation result**. Merely having parameter names is
not sufficient.


`bifacial_ready` and `detailed_shading_ready` remain false unless the required data is
actually present.


## Inverter behavior


The OND candidate builder now assembles verified AC power/current fields, PV-array sizing
constraints, night loss, temperature-derating breakpoints, and voltage-dependent Pin/Pout
efficiency profiles when those fields are present. It still remains partial when a physical
per-MPPT operating-current limit or other required source datum is not encoded unambiguously.


Validation checks currently include:


- identity;
- phase configuration;
- positive max DC voltage when present;
- MPPT minimum < maximum;
- MPPT maximum <= absolute DC maximum;
- positive MPPT count/current limits;
- MPPT Isc limit >= operating-current limit where both are known;
- positive nominal AC power when known;
- efficiency bounds and curve ordering when an efficiency model exists.


## Inverter capability flags


Inverter capabilities are intentionally **not a single ladder**. Design validation and energy
simulation have different minimum data requirements.


`mppt_voltage_ready` requires identity, max DC voltage, MPPT count, and a valid MPPT voltage
range.


`mppt_current_limit_ready` additionally requires a physical maximum operating current.
`mppt_design_ready` currently follows this stricter current-aware requirement.


`basic_design_ready` additionally requires nominal AC power, AC voltage, nominal frequency,
phase, source traceability, and no relevant design errors.


`basic_yield_ready` does **not** require the physical MPPT current limit. It requires
traceable identity, the MPPT voltage domain, nominal AC power, and an executable efficiency
model. If current limits are missing, current clipping is simply an unavailable refinement
and must be reported as such.


`detailed_efficiency_ready` requires detailed 1-D or voltage-dependent efficiency curves.


`array_sizing_ready` indicates that explicit PV-array sizing constraints are available.


`derating_ready` requires explicit temperature-derating data.


This separation implements progressive fidelity: missing optional constraints reduce the set
of supported checks/models rather than unnecessarily blocking unrelated calculations.


## Multi-source component composition


A component may be assembled from several independent source fragments:


```text
PAN / OND
+ manufacturer datasheet
+ user-entered CSV
+ open database
+ lab/test evidence
        ↓
field-level provenance merge
        ↓
canonical component candidate
        ↓
validation + capability evaluation
```


Each source has an explicit integer priority. Identical values accumulate provenance.
Higher-priority values may refine lower-priority values. Conflicting values at equal priority
are rejected by default. Manufacturer/model identity cannot silently change during a merge.


The user-facing templates live in `components/templates/`. CSV is the normal spreadsheet
entry path; advanced YAML overlays support nested/future canonical fields that do not fit
well in flat tables.


## Finalization


`finalize_candidate()` changes verification state to `auto_validated` only when:


1. the final canonical definition passes its JSON Schema; and
2. no engineering validation finding has severity `error` or `blocking_error`.


Capability flags are deliberately independent of verification state. A component can be
structurally valid yet support only a subset of simulation features.