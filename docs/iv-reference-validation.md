# Independent IV reference validation v0.1


This layer lets RawiBumi validate an existing canonical module electrical model against
external operating-point measurements instead of validating only against the PAN values used
to construct that model.


## Engineering purpose


The validation chain is intentionally separated from parameter fitting:


```text
PAN / canonical model
  -> validated PVsyst SDM


independent or external IV dataset
  -> canonical IVReferenceDataset
  -> dataset QA
  -> evaluate existing model at the same G/T conditions
  -> compare Isc / Voc / Imp / Vmp / Pmp
  -> optionally compare the full IV curve
  -> qualification + residual report
```


The validator does **not** refit the PAN-derived model to the validation dataset. Doing so
would contaminate the validation evidence with the same data used for calibration.


pvlib 0.15.2 includes a separate
`fit_pvsyst_iec61853_sandia_2025()` routine for estimating a PVsyst model from IEC 61853-1
matrix measurements. RawiBumi may expose that later as a distinct model-creation workflow,
but it is deliberately not called by this validation path.


## Canonical dataset


`IVReferenceDataset` stores source-format-independent points with:


- effective irradiance [W/m²];
- cell temperature [°C];
- Isc [A];
- Voc [V];
- Imp [A];
- Vmp [V];
- Pmp [W];
- optional full forward-quadrant voltage/current samples;
- optional measurement uncertainty;
- source/provenance metadata.


The canonical JSON format can represent IEC 61853-style matrices, laboratory IV sweeps,
field IV measurements, manufacturer matrices, or synthetic regression data.


A simple CSV importer is provided for summary-only matrices with these required columns:


```text
point_id
effective_irradiance_w_m2
cell_temperature_c
isc_a
voc_v
imp_a
vmp_v
pmp_w
```


Full curves use the canonical JSON representation in v0.1.


## Dataset QA


Before comparing model residuals, each reference point is checked for:


- finite positive Isc/Voc/Imp/Vmp/Pmp;
- Voc > Vmp;
- Isc >= Imp;
- Pmp consistency with Vmp × Imp;
- finite voltage/current samples for optional IV curves;
- minimum curve sample count;
- duplicate measured voltages are retained and reported as QA warnings rather than silently
  deduplicated, because repeated voltage samples can result from instrument resolution or
  sweep sampling.


Materially invalid reference data fails the affected validation point instead of being
silently cleaned.


## Summary-point comparison


The existing PVsyst SDM is evaluated at each reference point using the dataset's effective
irradiance and cell temperature. The current provisional RawiBumi tolerances are:


- Isc: 3%;
- Voc: 2%;
- Imp: 3%;
- Vmp: 3%;
- Pmp: 3%.


These are engineering defaults, not normative IEC 61853 pass/fail limits. They are explicit
and configurable and should eventually be replaced or supplemented by uncertainty-aware
criteria for laboratory datasets.


## Full IV curve comparison


When a reference point contains an IV curve, RawiBumi evaluates the model current at the
same measured voltages using `pvlib.pvsystem.i_from_v()`.


The current curve metric is:


```text
current_nrmse = RMSE(I_model - I_reference) / Isc_reference
```


with a provisional 3% acceptance threshold and a default minimum of five curve samples.


The result stores every measured/modelled current pair, RMSE, normalized RMSE, and maximum
absolute current error.


## Evidence qualification


Passing numerical tolerances is separate from evidence provenance.


The validator classifies a result as:


- `independent_reference_validation` — a distinct IEC 61853/laboratory/field source;
- `external_reference_validation` — a distinct datasheet matrix;
- `same_source_validation` — the validation source is also a model source;
- `synthetic_regression` — executable regression data only;
- `unqualified` — provenance is insufficient to claim independence.


Only a passed `independent_reference_validation` can set
`capability_flags.independent_iv_validated = true`.


Synthetic fixtures in this repository therefore test the software but do not create evidence
claims about a real module.


## Standards and implementation references


IEC 61853-1 describes PV-module performance measurement and power rating across multiple
irradiance and temperature conditions:


https://webstore.iec.ch/en/publication/6035


pvlib single-diode documentation:


https://pvlib-python.readthedocs.io/en/stable/user_guide/modeling_topics/singlediode.html


pvlib PVsyst IEC 61853 fitting implementation:


https://github.com/pvlib/pvlib-python/blob/v0.15.2/pvlib/ivtools/sdm/pvsyst.py


The fitting implementation is a technical reference only for this validation workflow; the
validator compares the existing model and does not fit against the validation data.




## Real measurement ingestion and source integrity


The v0.1 ingestion layer now accepts raw bytes, not only already-decoded text, so the exact
uploaded source can be fingerprinted before any parsing or normalization.


Each ingested source file can carry:


- original filename and media type;
- byte size;
- SHA-256 of the exact source bytes;
- source URL and immutable Git blob SHA when applicable;
- SPDX license identifier and license URL;
- attribution text.


The simple matrix CSV importer also recognizes optional absolute uncertainty columns:


```text
irradiance_uncertainty_w_m2
cell_temperature_uncertainty_c
isc_uncertainty_a
voc_uncertainty_v
imp_uncertainty_a
vmp_uncertainty_v
pmp_uncertainty_w
uncertainty_confidence_fraction
uncertainty_coverage_factor
```


Uncertainty does **not** silently relax model-validation tolerances. The default policy is
`report_only`: uncertainty-normalized residuals are recorded while the normal RawiBumi
engineering tolerance remains authoritative. An explicit `expand_tolerance` policy can use
reported uncertainty as an acceptance envelope when the dataset declares a known
`uncertainty_basis`; that behavior and multiplier are stored in validation configuration.


## Legacy pvlib/PVLIB measured-IV importer


RawiBumi includes an adapter for the legacy measured-IV text format used by
pvlib/PVLIB MATLAB's PVsyst parameter-estimation regression data. The importer preserves:


- Isc, Imp, Vmp, Voc;
- POA and effective irradiance separately;
- cell temperature;
- every voltage/current sample;
- source curve index;
- header temperature coefficients and series-cell count.


Pmp is not present as a source field in that format, so it is explicitly derived as
`Imp × Vmp` and the transformation is recorded in dataset ingestion metadata.


## Redistributable real measured fixture


The repository now contains a 12-curve subset for the **Mitsubishi PV-UE125MF5N** from
pvlib-python v0.15.2. Sandia report SAND2015-8598 describes the underlying example as
outdoor measured IV curves from Albuquerque, New Mexico. The report states that cell
temperature was estimated from three thermocouples on the module backsheet and effective
irradiance was measured in the module plane with a silicon reference cell.


The upstream pvlib source file is BSD-3-Clause licensed. RawiBumi retains the license and
attribution beside the redistributed subset and records the upstream Git blob SHA, SHA-256,
and the exact source-index mapping.


Fixture location:


```text
tests/fixtures/iv_reference/real/
  mitsubishi_pv_ue125mf5n_sandia_subset.csv
  dataset-manifest.json
  README.md
  LICENSE-pvlib-BSD-3-Clause.txt
```


This dataset is **real measurement evidence**, but the regression model distributed with
pvlib was fitted from the same measurement campaign. Therefore the executable same-campaign
comparison is deliberately classified as `same_source_validation`, not as independent
Level-7 evidence. A model derived from an unrelated PAN/datasheet/campaign will be required
before these curves can support an `independent_reference_validation` claim.