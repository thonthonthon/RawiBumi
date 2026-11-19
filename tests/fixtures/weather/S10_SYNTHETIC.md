# Fictional S10 weather companions

These are synthetic test inputs, **not ERA5 observations, reconstructed weather,
or interpolated weather**. The accepted four-row fixtures remain unchanged.

`open_meteo_era5_phase60d_uat_padded_s10.json` has 72 hourly Unix labels, UTC
2024-12-31 00:00 through 2025-01-02 23:00. Start with the existing
`open_meteo_era5_phase60d_uat.json` metadata. For each hour, set fictional
temperature 25 °C, relative humidity 70 %, dew point 20 °C, pressure 1000 hPa,
wind 1 m/s, and all three radiation components 0 W/m². At the four original
Unix labels, replace every hourly field with its exact original value. Keep
the original four label/value rows, including their state values, unchanged.
After the existing one-hour label conversion, S10 retains the complete local
January 1 at Asia/Jakarta. Nighttime solar remains zero.

`open_meteo_era5_annual_padded_s10.json` has 8,832 hourly Unix labels, UTC
2024-12-30 00:00 through 2026-01-01 23:00. Use the same fictional constants
above for **every** row, with latitude -6.425, longitude 106.831 and provider
elevation 110 m. Its constants and units match the original annual `payload`
fixture, which remains unchanged. No observed weather is represented. S10
retains 8,784 local hours (2024-12-31 through 2025-12-31), including all 8,760
hours of local 2025. The two neighboring UTC days supply 48 padding labels.

Reproduction recipe: generate each inclusive hourly UTC range with
`pandas.date_range(start, periods=72 or 8832, freq="h")`, convert labels to
integer Unix seconds, and build equal-length arrays with the constants above.
For the day companion only, overwrite rows matching the four original labels
from the accepted UAT fixture. Serialize as UTF-8 JSON with the fixture note.
The S10 tests verify every original day row and the complete label ranges.

These fictional values belong only to offline test fixtures. Production
acquisition never adds, shifts, fills or interpolates a missing interval.
