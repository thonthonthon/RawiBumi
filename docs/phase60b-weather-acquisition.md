# RawiBumi — Phase 6.0B Weather Acquisition Foundation


**Status:** Implementation tranche  
**Revision:** 0.1  
**Date:** 25 September 2026  
**Baseline:** `main @ 58f3819d0a2b59ae112ae4184d324ad15d155e4d`  
**Parent:** `docs/phase60a-product-readiness-contract.md`  
**Decision:** `docs/decisions/0053-phase6-user-test-weather-provider-boundary.md`


## 1. Objective


Phase 6.0B adds coordinate-driven meteorological acquisition without changing
RawiBumi's canonical simulation-weather authority.


The governing chain is:


```text
Site coordinate
→ explicit meteorological source product
→ provider transport adapter
→ raw provider response
→ source-specific semantic mapping
→ canonical WeatherDataset
→ QC
→ pinned weather revision
→ SimulationRun
```


A simulation never calls a live weather service directly.


## 2. Frozen source-isolation rule


Phase 6.0A remains authoritative:


```text
provider transport
!=
meteorological source product
!=
source-owned resource-generation method
!=
RawiBumi canonical mapping
```


Phase 6.0B does not introduce:


- source blending;
- source averaging;
- cross-source bias correction;
- an RawiBumi meteorological projection model;
- automatic source ranking;
- provider best-match selection;
- silent fallback to another source.


If a selected source is unavailable, acquisition fails explicitly.


## 3. Provider-neutral acquisition API


The implementation adds:


```text
WeatherAcquisitionRequest
WeatherAcquisitionResult
WeatherAcquisitionError
WeatherProviderAdapter
```


A request contains one explicit `source_id`, coordinate, project timezone,
date range, optional elevation and provider cell-selection preference.


An adapter may expose multiple source products in the future, but each
acquisition resolves exactly one source product before network transport.


Unknown source IDs fail closed.


## 4. First live adapter: Open-Meteo Historical Weather


The first implemented transport is:


```text
OpenMeteoHistoricalAdapter
```


The default public endpoint is configurable, allowing a self-hosted or other
authorized Open-Meteo endpoint to be substituted without changing canonical
weather semantics.


### 4.1 Supported source product


Phase 6.0B initially exposes one complete PV-resource source:


```text
source_id:
    open_meteo_archive_era5


provider request:
    models=era5
```


This is intentionally narrower than the complete Open-Meteo model catalog.


### 4.2 Explicitly excluded provider modes


The adapter does not use:


```text
best_match
era5_seamless
implicit/default model selection
```


because those paths can combine or dynamically select multiple upstream
meteorological products.


Their use would violate the Phase-6.0A source-isolation contract unless a later
contract explicitly treats the resulting combined product as its own source
with complete provenance.


### 4.3 ERA5-Land boundary


ERA5-Land is not exposed as a complete PV-resource source in this tranche.


The current Open-Meteo Historical Weather documentation distinguishes ERA5-Land
from ERA5 and indicates that the independent ERA5-Land product does not provide
the complete solar-radiation and wind set required by the standard PV
simulation path.


RawiBumi therefore does not silently supplement an ERA5-Land request with ERA5.


If ERA5-Land is supported later, it remains a separate source product and any
supplement/composition requires an explicit model identity.


## 5. Requested variables


The ERA5 acquisition requests hourly:


```text
temperature_2m
relative_humidity_2m
dew_point_2m
surface_pressure
wind_speed_10m
shortwave_radiation
direct_normal_irradiance
diffuse_radiation
```


RawiBumi requests provider-selectable units close to canonical units:


```text
temperature = Celsius
wind = m/s
time = Unix / UTC
```


Remaining deterministic conversions include:


```text
relative humidity: % → fraction
surface pressure: hPa → Pa when required
```


## 6. Time semantics


Open-Meteo's hourly source has mixed variable semantics.


For the requested solar fields:


```text
source label
= end of preceding-hour mean
```


For several meteorological state fields:


```text
source label
= instantaneous state at label
```


RawiBumi therefore records the source convention as mixed instead of falsely
describing the complete payload as interval-start or interval-end.


Canonical indexing is:


```text
provider Unix UTC label
→ subtract 1 hour
→ canonical interval start
→ convert to project timezone
```


No state-variable interpolation is invented.


Per-variable metadata records:


```text
source_variable
source_temporal_semantics
canonical_alignment
```


This allows a future temporal-model improvement without losing what the source
actually supplied.


## 7. Spatial/resource semantics


The acquisition manifest freezes:


```text
projection_authority = source_product
rawibumi_resource_projection_applied = false
```


Here "projection" means meteorological resource generation, interpolation,
downscaling or reconstruction, not map/cartographic projection.


The request preserves:


- requested WGS84 coordinate;
- optional requested elevation;
- provider cell-selection setting;
- provider-returned coordinate/elevation when reported;
- provider model parameter;
- source method note.


Provider-returned coordinates never become CAD geometry authority.


## 8. Raw-response snapshots


Phase 6.0B adds a reference content-addressed filesystem snapshot store.


Identity:


```text
SHA-256(raw bytes)
```


Logical reference:


```text
weather-snapshot://sha256/<digest>
```


Snapshots are immutable by content identity.


The canonical WeatherDataset also receives a deterministic SHA-256 over
canonical metadata and normalized series.


A completed simulation can therefore distinguish:


```text
raw provider payload identity
from
canonical WeatherDataset identity
```


## 9. QC and failure behavior


Provider acquisition does not bypass existing weather QC.


The sequence is:


```text
provider parse
→ canonical mapping
→ Phase-2 weather QC
→ qc_passed | qc_warning | failed
```


Malformed units, cadence, timestamps, response structure, API errors and unknown
source IDs raise explicit `WeatherAcquisitionError` findings.


No error path automatically requests another source.


## 10. Deterministic CI


Blocking CI uses:


```text
frozen Open-Meteo-style ERA5 JSON fixture
→ explicit adapter
→ canonical WeatherDataset
→ schema validation
→ QC
→ stable canonical hash
```


CI does not depend on live Open-Meteo availability.


The fixture validates:


- explicit `models=era5`;
- absence of best-match/seamless selection;
- unit normalization;
- mixed source-time provenance;
- raw response SHA-256;
- content-addressed storage;
- WeatherDataset schema;
- WeatherSourceAcquisitionManifest schema;
- deterministic replay;
- fail-closed unsupported-source behavior.


## 11. Implemented files


```text
weather/providers/base.py
weather/providers/open_meteo.py
weather/providers/snapshot_store.py
weather/providers/__init__.py
weather/providers/README.md


tests/fixtures/weather/open_meteo_era5_hourly.json
tests/unit/test_phase60b_weather_acquisition.py
```


The existing `weather` package exports the acquisition API.


## 12. Non-goals


Phase 6.0B does not implement:


- TMY generation from ERA5;
- climate-normal-year synthesis;
- provider comparison scoring;
- source ensemble generation;
- RawiBumi meteorological downscaling;
- source-to-source correction;
- CAMS/PVGIS/NASA POWER adapters;
- live-provider-dependent CI;
- browser weather selection UI.


Those remain independent follow-on capabilities.


## 13. Exit criterion


Phase 6.0B is closed when all of the following pass:


1. a WGS84 coordinate plus explicit `open_meteo_archive_era5` source can be
   translated into one deterministic request;
2. the response becomes a canonical, QC-evaluated WeatherDataset;
3. source identity and source-owned meteorological resource semantics are
   preserved;
4. raw bytes and canonical output both have reproducible identity;
5. replay requires no network call;
6. unsupported sources fail closed;
7. all existing regression/benchmark tests remain green.


At that point Phase 6.0C may consume the acquisition API from the browser/API
product shell without changing the simulation engine.