# Weather calendar windows

Open-Meteo acquisitions interpret `start_date..end_date` as inclusive calendar
dates in the site's timezone. The UTC provider request is padded by one day on
both sides, with its end capped at today's UTC date. After the existing
preceding-hour-label conversion and timezone conversion, only existing interval
starts inside the local window are retained. Variables, units, state alignment
and the source interval convention are unchanged.

The window is `[first real instant of start, first real instant of end + 1)`:

- An ordinary date starts at local midnight.
- A repeated midnight uses its earlier occurrence. Havana 2023-11-05 includes
  both physical occurrences of 00:00 and has 25 hourly rows.
- A skipped midnight uses the first valid local time. São Paulo 2018-11-04
  starts at 01:00 and has 23 hourly rows. Boundaries are not rounded to a whole
  hour; Kathmandu 1986-01-01 starts at 00:15.
- Consecutive days share the same resolved boundary, with no overlap or gap.
- A wholly skipped requested window, such as Pacific/Apia 2011-12-30, is refused
  with a clear HTTP 422 before provider transport. A wider window containing
  real days remains usable.

This rule resolves **window bounds only**. Source timestamps are never shifted
or deduplicated by the boundary resolution. Retention always tests canonical
interval starts; no sub-hourly data or partial intervals are manufactured.
UTC-hourly data can appear at local :30 or :45 in fractional-offset timezones;
QC preserves that source cadence rather than imposing local whole-hour labels.

The dataset period contains the resolved local start and exclusive end as ISO
timestamps with offsets. A distinct `timezone_normalization` transformation,
algorithm `local_window_trim` version `0.1`, records the original requested dates,
resolved bounds, padded UTC dates, before/after row counts and rows dropped at
each end. The padded raw response remains byte-identical in the snapshot store,
with its SHA-256 provenance anchor unchanged. Schemas and the original source
timestamp convention are unchanged.

For S10-trimmed datasets only, missing leading/trailing intervals produce
`WX_TIME_GAPS` errors with exact counts and examples, including an empty retained
window. Existing internal-gap and other QC checks remain in force. Missing
weather is never fabricated, filled, shifted or interpolated. Other importers
retain their default period/QC behavior; old pinned weather is not rewritten.

The fictional offline companions are documented in
[`tests/fixtures/weather/S10_SYNTHETIC.md`](../tests/fixtures/weather/S10_SYNTHETIC.md).
