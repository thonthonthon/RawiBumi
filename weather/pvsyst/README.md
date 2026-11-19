# PVsyst weather adapters


This namespace separates two different PVsyst weather interfaces:


- `standard.py` implements the documented **PVsyst Standard weather CSV** interchange
  format and is directly importable into canonical RawiBumi weather.
- `probe.py` classifies internal `.MET` containers without decoding their meteorological
  payload.


The probe distinguishes:


```text
pvsyst_standard_csv
pvsyst_internal_met_text
pvsyst_internal_met_binary
pvsyst_met_unrecognized
```


Modern user-workspace text `.MET` samples can expose readable `PVObject_=pvMeteo`
metadata while still containing version-dependent encoded weather payloads. Binary/internal
`.MET` containers are classified separately. Neither internal class is decoded in Phase 2.1.


See `docs/weather-data-foundation.md` and ADR 0012.