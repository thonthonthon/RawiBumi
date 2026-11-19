# Weather quality control


RawiBumi exposes two deterministic QC layers.


## Phase-2 base QC


`run_weather_qc(weather)` covers:


- timestamp integrity;
- cadence and gaps;
- missing values;
- basic non-negative/gross irradiance checks;
- meteorological range checks;
- fraction ranges;
- location sanity;
- interval-aware DNI/DHI completion requirements.


It deliberately does not require the simulation solar-position engine.


## Phase-3 solar-aware QC


`run_solar_aware_weather_qc(weather, solar)` first runs Phase-2 QC and then
adds checks that use the exact `SolarPositionResult` aligned to the canonical
weather intervals.


The versioned policy is:


```text
weather_qc.solar_aware.bsrn_v2_rawibumi.v0.1
```


The solar-aware layer adds:


- BSRN V2 physically possible GHI/DHI/DNI upper limits;
- BSRN V2 GHI versus `DHI + DNI*cos(zenith)` comparison bands;
- BSRN V2 diffuse/global ratio checks;
- conservative RawiBumi night/daylight time-reference warnings;
- optional warning-only clear-sky gross screening when the caller explicitly
  supplies a reference series.


The QC layer never clips, shifts, fills, decomposes, or otherwise repairs the
source weather.


Clear-sky screening is not silently enabled. The caller must provide an
interval-aligned reference so the atmospheric/clear-sky model remains explicit.


See:


- `docs/weather-data-foundation.md`
- `docs/decisions/0010-irradiance-completion-qc.md`
- `docs/decisions/0025-phase38d-solar-aware-weather-qc.md`