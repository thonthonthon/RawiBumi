# PAN adapter


This subsystem handles user-supplied PVsyst-style PAN files.


The first implementation layer is deliberately **raw and lossless**:


1. preserve the original source text;
2. preserve line order and duplicate keys;
3. record indentation and hierarchical paths;
4. preserve values as source strings;
5. emit warnings for structurally unusual indentation.


The second layer is a **versioned semantic mapper**:


1. load `mapping-ledger.yaml`;
2. match exact source paths;
3. apply only explicit conversion rules;
4. write an auditable FieldMappingRecord per mapped field;
5. leave unsupported or ambiguous fields untouched;
6. return every unmapped source field.


PAN field names are not canonical RawiBumi fields.


Phase 3.8A adds a third, PAN-specific semantic assembly layer for source structures
that cannot be represented safely as independent scalar mappings. For verified
`UserProfile` / `TCubicProfile` module data it assembles:


- `Absorb` -> canonical module absorptance used by the thermal model;
- `PVObject_IAM` -> canonical tabulated IAM points plus source-profile metadata;
- `PNomTolLow` / `PNomTolUp` -> canonical nameplate tolerance plus the documented
  PVsyst default module-quality adjustment.


The source `TCubicProfile` identity is preserved. RawiBumi executes those points
with its versioned pvlib-backed cubic interpolation path; exact PVsyst cubic
interpolation equivalence is **not** claimed.


References:


- pvlib PAN/OND reader:
  https://github.com/pvlib/pvlib-python/blob/main/pvlib/iotools/panond.py
- pvlib PAN fixture:
  https://github.com/pvlib/pvlib-python/blob/main/tests/data/ET-M772BH550GL.PAN
- PVsyst module parameters:
  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/index.html
- PVsyst PNom/Pmpp distinction:
  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/pv-modules-basic-data/pnom-and-pmppstc-definitions.html


RawiBumi intentionally uses an ordered raw record before mapping because duplicate fields,
source order, and unmapped values are important for auditability and reverse engineering.
## ENG2 readiness and voltage evidence

STC validation and the complete off-STC point/trend checks remain required for
SDM readiness. The sole permitted exception is a failed datasheet beta-Voc
coefficient check when every other check passes. The shared component policy
marks the outer validation aggregate as accepted (`passed: true`, status
`passed`) and records `readiness_tolerances: ["beta_voc_per_c"]`. Ordinary models
carry an empty list. Raw `validation.stc` and `validation.off_stc` records,
including failed checks and residuals, are preserved unchanged. The exception
emits `MODULE_SDM_VOC_TEMPCO_MISMATCH` as a warning with both coefficients and
relative error. Failed STC, points, trends, alpha or gamma still prevent detailed
readiness. Source overlays use the same policy; runtime extraction and resolution
continue to consume its existing aggregate contract.

Energy simulation uses the unchanged SDM. For a tolerated model, engineering
voltage sizing takes the greater of SDM cold Voc and datasheet-linear cold Voc
at the module reference irradiance. Hot Vmp takes the lower of SDM and the
existing datasheet approximation (relative gamma minus relative alpha). The basis
is recorded as `validated_pvsyst_singlediode+datasheet_voc_envelope`; currents,
power and other design fields keep their SDM values. Missing coefficient basis
or reference irradiance is an explicit refusal, never an assumed value. Models
without the tolerance retain their previous numerical design states.
