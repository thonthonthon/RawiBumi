# Weather Data Foundation v0.1


Phase 2 establishes RawiBumi's canonical meteorological ingestion, timestamp semantics,
quality control, and resolution-conversion layer.


The weather layer is intentionally independent from the later solar-position, irradiance
decomposition, transposition, thermal, and electrical models.


## Supported Phase-2 input paths


- RawiBumi native weather CSV;
- TMY3 through pvlib field parsing with RawiBumi-owned calendar semantics;
- EPW through pvlib's documented reader;
- Meteonorm text DAT weather exports;
- PVsyst documented Standard weather CSV.


PVsyst weather handling is split into an explicit namespace:


```text
weather/pvsyst/
    standard.py   documented Standard weather CSV importer
    probe.py      non-decoding internal .MET classifier
```


Direct decoding of PVsyst internal `.MET` weather payloads remains intentionally deferred.
RawiBumi can now distinguish documented Standard CSV, text `PVObject_=pvMeteo` containers,
binary `.MET` containers, and unrecognized `.MET` candidates without assigning canonical
weather values to undocumented payload fields.


## Canonical time convention


Every canonical weather row is indexed by **interval start**.


The dataset records both:


- source timestamp convention;
- canonical timestamp convention.


Coverage is represented as:


\`\`\`text
start_time = first interval start
end_time   = end of final interval
\`\`\`


and every dataset records:


\`\`\`text
native_resolution_seconds
series_resolution_seconds
\`\`\`


These are deliberately separate.


Example:


\`\`\`text
source TMY3: native 3600 s
resampled simulation weather: 300 s


native_resolution_seconds = 3600
series_resolution_seconds = 300
derived_subhourly = true
\`\`\`


The 5-minute series must not be presented as measured 5-minute weather.


## Canonical time-semantics contract


Weather time interpretation is represented explicitly in:


```text
time_semantics
```


This object is the authoritative Phase-3 contract. The older top-level `timezone`,
`timestamp_convention`, and `source_timestamp_convention` fields remain for v0.1
compatibility and convenient indexing.


The object has three distinct layers:


```text
origin_source
canonical
representative_time
```


### Origin source


`origin_source` records how the original meteorological source represented time:


```text
timezone
utc_offset_hours
timestamp_convention
interval_seconds


reference:
    kind
    offset_minutes
    applied_to_canonical_timestamp
    applied_to_solar_evaluation
```


A provider-declared reference offset is descriptive unless an adapter explicitly states that
it was applied. RawiBumi never assumes that an arbitrary source time-reference field is a
solar-position correction.


### Canonical series


`canonical` describes the current RawiBumi weather series:


```text
timezone
timestamp_convention = interval_start
interval_seconds
```


The interval duration follows the current working series, so it changes when RawiBumi
resamples weather. The origin-source interval duration remains unchanged.


### Representative calculation time


Quasi-steady Phase-3 calculations use:


```text
representative time
    =
canonical interval midpoint
    +
solar_evaluation_offset_minutes
```


The policy is therefore recorded as:


```text
policy = interval_midpoint
```


For ordinary TMY3, EPW, Meteonorm DAT, and unshifted PVsyst weather:


```text
solar_evaluation_offset_minutes = 0
```


A PVsyst declared time shift can leave a within-interval remainder after the whole-step
timestamp shift. Only that residual is carried as a solar-evaluation offset.


Example for a 10-minute PVsyst file with declared +25 min correction:


```text
+20 min → applied to canonical timestamps
 +5 min → solar_evaluation_offset_minutes
```


By contrast, Meteonorm's provider `time ref. min` value is preserved under
`origin_source.reference` and is not applied again to either canonical timestamps or solar
evaluation after interval-end normalization.


The complete time-semantics object is preserved by RawiBumi native Weather CSV export and
re-import.


## Temporal provenance and fidelity


Resolution and provenance are separate concepts.


`native_resolution_seconds` records the cadence of the series supplied to RawiBumi.
It does **not** claim that the values were physically measured at that cadence.


Every canonical weather dataset may therefore record:


\`\`\`text
native_series_origin
series_origin
upstream_generation
\`\`\`


The controlled series-origin vocabulary is:


- `measured`: the source explicitly establishes that the native values are measurements;
- `provider_generated`: the supplied series cadence/values were generated upstream by a
  provider or upstream tool;
- `opensimpv_derived`: the current working series was produced by an RawiBumi
  transformation;
- `unknown`: the available evidence does not establish one of the above.


`native_series_origin` describes the imported/native series and is preserved across later
RawiBumi transformations.


`series_origin` describes the current working series. Any RawiBumi resolution conversion
changes this value to `opensimpv_derived` while retaining the native origin.


Example:


\`\`\`text
Meteonorm 1-minute DAT
native_resolution_seconds = 60
native_series_origin       = provider_generated
series_origin              = provider_generated


RawiBumi aggregate to 15 min
native_resolution_seconds = 60
series_resolution_seconds = 900
native_series_origin       = provider_generated
series_origin              = opensimpv_derived
\`\`\`


When upstream generation is evidenced, `upstream_generation` can record:


\`\`\`text
provider
synthetic
base_resolution_seconds
method
evidence
evidence_detail
\`\`\`


These fields describe temporal-series provenance only. They do not imply that the underlying
meteorological climate record is fabricated, and RawiBumi does not invent an exact upstream
algorithm when the source does not disclose one.


The native RawiBumi Weather CSV preserves these fields so provenance survives export and
re-import.


## TMY3 normalization


TMY3 irradiation is defined over the 60 minutes preceding its timestamp. The source therefore
uses interval-end labels, including the conventional `24:00` representation for midnight.


RawiBumi owns TMY3 calendar/timestamp interpretation rather than accepting pvlib's normalized
DatetimeIndex. pvlib remains the field and station-metadata parser.


The raw `Date (MM/DD/YYYY)` and `Time (HH:MM)` labels are parsed directly:


\`\`\`text
source interval-end label
        ↓
24:00 normalized to next-day 00:00
        ↓
source calendar classified
        ↓
subtract 3600 s
        ↓
canonical interval-start timestamp
\`\`\`


Calendar handling is explicit:


- a complete single source year is retained as `actual_year`, including February 29;
- an incomplete single-year sequence is retained as `partial_time_series`;
- a genuinely chronological multi-year sequence is retained as `multi_year_time_series`;
- mixed source years that form a TMY calendar are normalized to a deterministic
  `typical_year` anchor while the original source years remain in provenance.


The normal typical-year anchor is 2001. If the source explicitly contains February 29, the
anchor is 2000 so the date remains representable. This anchor is calendar scaffolding, not a
claim that the meteorological data belong to that year.


For a one-hour interval:


\`\`\`text
Wh/m2 over one hour
        =
numeric average W/m2 over that hour
\`\`\`


The numeric irradiance value is therefore unchanged, but quantity interpretation, calendar
classification, source years, optional anchor year, and timestamp normalization are recorded
explicitly.


TMY3 temperature, wind, humidity, pressure, albedo, dew point, and precipitable water are
preserved where present.


## Meteonorm DAT normalization


RawiBumi supports the text Meteonorm DAT structure represented by yearless climate exports
with a site line, location/time metadata line, and tabular weather columns such as:


\`\`\`text
m dm dy h mi G_Gh ... G_Dh ... G_Bn Ta FF ... Td
\`\`\`


The source cadence is inferred from consecutive timestamps rather than from the filename.
One-minute, 10-minute, 15-minute, and hourly files therefore use the same importer.


Meteonorm coordinate text may contain both an explicit numeric sign and a hemisphere token.
When the numeric value is negative, that explicit sign is authoritative (for example
`-6.425 [deg N]` remains -6.425°). For positive/unsigned values, S/W tokens apply the
negative sign. This rule is regression-tested against the Phase-3 Home reference format.


Meteonorm DAT labels the end of each weather interval. RawiBumi converts these labels to
canonical interval starts by subtracting exactly the inferred source cadence:


\`\`\`text
Meteonorm interval-end label
        ↓ subtract inferred interval duration
RawiBumi interval-start timestamp
\`\`\`


The source header also carries a separate time-reference value, for example:


\`\`\`text
-30 [time ref. min]
\`\`\`


This value is preserved as `source_metadata.source_time_reference_minutes` and is **not**
applied as a second timestamp shift during import. It remains available for later
solar-geometry interpretation.


Meteonorm DAT files in this interchange structure have month/day/day-of-year fields but no
meteorological year. RawiBumi therefore uses deterministic calendar scaffolding:


- anchor year 2001 for a normal 365-day calendar;
- anchor year 2000 if February 29 is explicitly present.


The anchor is not a claim about the meteorological year. The dataset records
`calendar_type=typical_year` and identifies whether the supplied sequence is a complete
yearless typical year or a partial yearless series.


The Phase-2 canonical mapping is:


\`\`\`text
G_Gh → ghi_w_m2
G_Dh → dhi_w_m2
G_Bn → dni_w_m2
Ta   → ambient_temperature_c
FF   → wind_speed_m_s
Td   → dew_point_temperature_c
\`\`\`


Other source columns remain discoverable in source metadata and are retained in the original
source file provenance rather than being assigned unverified canonical semantics.


For subhourly Meteonorm DAT files, the presence of a subhourly `G_Gh` series together with
the `G_Gh_hr` hourly-reference column is treated as structural evidence that the supplied
subhourly cadence is provider-generated from an hourly basis. In that case RawiBumi records:


\`\`\`text
native_series_origin = provider_generated


upstream_generation:
    provider = Meteonorm
    synthetic = true
    base_resolution_seconds = 3600
    method = meteonorm_provider_subhourly_generation
    evidence = source_structure
\`\`\`


The method identifier is intentionally generic: it records that Meteonorm generated the
subhourly series, not a claim about an undisclosed internal algorithm.


Hourly Meteonorm DAT input is not automatically labeled measured or generated when the file
itself does not establish that distinction; its series origin remains `unknown`.


## EPW normalization


pvlib converts EPW's 1..24 hour convention to a 0..23 local-standard-time index. RawiBumi
uses that normalized index as interval start.


EPW irradiation fields are interval energy in Wh/m2 for one-hour records and are converted to
canonical interval-average W/m2.


Additional supported variables include:


- dry-bulb ambient temperature;
- wind speed;
- atmospheric pressure;
- relative humidity;
- albedo;
- dew-point temperature;
- precipitable water;
- aerosol optical depth.


## PVsyst Standard weather CSV


RawiBumi implements the documented PVsyst Standard weather CSV format.


The official format specifies:


- site/country/source header fields;
- time step;
- latitude/longitude/altitude;
- time zone;
- interval-start timestamps;
- GHI or GPI plus ambient temperature;
- optional DHI, DNI, wind, RH, precipitable water, Linke turbidity, AOD.


RawiBumi supports GHI-based horizontal weather directly. A GPI-only file can be ingested and
preserved, but it is not considered ready for the normal horizontal-irradiance simulation
pipeline until an explicit retro-transposition model is implemented.


### PVsyst internal .MET probing


Internal `.MET` containers are **detectable but not importable** in Phase 2.1.


The non-decoding probe returns a structured classification:


```text
pvsyst_standard_csv
pvsyst_internal_met_text
pvsyst_internal_met_binary
pvsyst_met_unrecognized
```


For a text `PVObject_=pvMeteo` object, the probe may safely expose structural metadata such
as:


```text
object_type
version
has_encoded_daily_payload
encoded_day_record_count_in_probe_window
meteo_variable_object_count_in_probe_window
```


These fields describe the container structure only. `Day_xxxx` tokens and other encoded
meteorological payloads are **not decoded or assigned engineering semantics**.


Binary `.MET` detection is container-level only. A `.MET` file with NUL/non-text bytes is
classified as `pvsyst_internal_met_binary`; RawiBumi does not infer a binary schema,
PVsyst version, variable layout, or numerical meaning.


The probe also deliberately rejects unrelated PVObject containers as weather. For example,
`PVObject_=pvShading` in a `.SHD` file is not classified as a meteorological source.


The documented PVsyst Standard weather CSV remains the supported interchange path for direct
canonical weather import.


### PVsyst time shifts


PVsyst may declare time correction through hour/time-shift metadata.


For v0.1 RawiBumi follows the PVsyst 8.1 concept:


\`\`\`text
declared total shift
      ↓
whole interval timestamp shift
      +
remaining within-interval solar time shift
\`\`\`


The whole-step shift is applied to canonical timestamps.


The remaining offset is preserved as:


\`\`\`text
source_metadata.solar_time_shift_minutes
\`\`\`


It is not yet applied to sun position because solar geometry belongs to Phase 3.


## RawiBumi native weather CSV


The native format uses metadata lines:


\`\`\`text
# timezone=Asia/Jakarta
# native_resolution_seconds=3600
# series_resolution_seconds=3600
# timestamp_convention=interval_start
\`\`\`


followed by canonical columns such as:


\`\`\`text
timestamp
ghi_w_m2
dni_w_m2
dhi_w_m2
ambient_temperature_c
wind_speed_m_s
pressure_pa
albedo
relative_humidity_fraction
\`\`\`


Blank/missing values remain missing. They are never silently replaced with zero.


An exporter is included so canonical weather can be round-tripped through this format.


## Quality control


Phase-2 QC checks data properties that do not require solar geometry:


- timezone-aware timestamps;
- monotonic ordering;
- duplicate timestamps;
- expected cadence;
- gaps and overlapping/irregular intervals;
- missing GHI;
- missing ambient temperature;
- missing values;
- negative irradiance;
- gross irradiance screening;
- DHI materially above GHI;
- gross ambient-temperature screening;
- negative/gross wind-speed screening;
- pressure screening;
- albedo and RH fractions;
- geographic coordinate ranges.


If the GHI field is present but DNI and/or DHI are absent **or partially missing**, the
dataset remains usable as a Phase-3 input when the required base variables themselves pass
QC, but it receives:


\`\`\`text
WX_IRRADIANCE_DECOMPOSITION_REQUIRED
\`\`\`


The finding is interval-aware. It records, for each of DNI and DHI:


\`\`\`text
availability = complete | partial | absent
column_present
missing_count
missing_fraction
completion_count
completion_fraction_of_ghi_available
example timestamps
\`\`\`


It also records the union of intervals requiring completion and whether completion applies to
the full GHI-available series or only partial intervals.


Only intervals with usable GHI are counted as eligible for decomposition/completion. If GHI
is itself missing at an interval, that interval remains a base-weather QC error rather than
being misclassified as something irradiance decomposition can repair.


Phase 3 must select and record an explicit decomposition/completion model and apply it only to
the affected eligible intervals. Weather import and QC never synthesize DNI or DHI.


The Phase-2 QC function deliberately does **not** test solar-geometry-dependent
relationships, so weather ingestion remains independent from the simulation engine.


Phase 3.8D adds a separate solar-aware QC layer that consumes the aligned
\`SolarPositionResult\` used by simulation. It now checks:


\`\`\`text
BSRN physically possible GHI/DHI/DNI limits
GHI versus DHI + DNI*cos(true zenith)
DHI/GHI comparison bands
material irradiance with the Sun well below the horizon
near-zero GHI in established daylight
optional clear-sky gross exceedance when an explicit reference is supplied
\`\`\`


The solar-aware layer never repairs the weather. It emits findings only.
Clear-sky screening remains opt-in and no atmospheric climatology is selected silently.


See \`docs/decisions/0025-phase38d-solar-aware-weather-qc.md\`.


## Resolution conversion


Phase 2 provides deterministic integer-ratio resampling.


### Hourly to sub-hourly


The v0.1 algorithm is:


\`\`\`text
interval_mean_hold
\`\`\`


Every source interval mean is copied into its child intervals.


This does not invent sub-hourly cloud structure.


For irradiance it preserves source-interval energy exactly:


\`\`\`text
sum(G * dt)_before = sum(G * dt)_after
\`\`\`


The transformation is explicitly labeled synthetic.


A future clear-sky-normalized disaggregation model may shape irradiance within each source
interval, but it must have its own named/versioned model and preserve interval energy.


### Aggregation


Complete equal-duration child intervals are aggregated using arithmetic interval means.


For irradiance, energy preservation is checked programmatically.


Non-integer resolution ratios and incomplete terminal groups are rejected rather than silently
interpolated or truncated.


## Provenance


Every imported raw file can record:


- filename;
- byte size;
- SHA-256;
- source URL;
- attribution;
- license fields.


Every deterministic normalization/resampling operation appends a transformation record with
algorithm name, version, and parameters.


This allows a future SimulationRun to identify:


\`\`\`text
original weather file
        ↓
import adapter
        ↓
timestamp normalization
        ↓
unit conversion
        ↓
QC status
        ↓
resolution conversion
        ↓
simulation weather revision
\`\`\`


## Phase boundary


Phase 2 does not perform irradiance decomposition, solar position, POA transposition, clear
sky comparison, module temperature, or PV power calculation.


Those begin in Phase 3.


The Phase-3 engine should consume only weather that has:


- canonical interval semantics;
- explicit source provenance;
- a QC report;
- explicit transformation history.




---


## Phase 6.0B coordinate-driven acquisition extension


Phase 6.0B adds a provider-acquisition layer above the Phase-2 import/canonical
foundation.


The simulation-weather authority does not change.


```text
coordinate + explicit source product
→ WeatherProviderAdapter
→ raw provider snapshot
→ source-specific mapping
→ canonical WeatherDataset
→ existing QC / transformations
→ SimulationRun
```


The first implemented live transport is Open-Meteo Historical Weather with the
explicit source ID `open_meteo_archive_era5` mapped to `models=era5`.


Provider default/best-match and seamless multi-source modes are not used.


Every future provider/source adapter must preserve its own source identity and
source-owned resource-generation semantics. RawiBumi does not currently blend,
rank, bias-correct, or project meteorological sources into one common weather
resource.


See `docs/phase60b-weather-acquisition.md`.