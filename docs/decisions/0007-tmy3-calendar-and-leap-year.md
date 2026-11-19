# Decision 0007 — TMY3 calendar and leap-year normalization

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Context

TMY3 is an interchange structure, not proof that a file represents one synthetic 365-day
typical year.

Real-world TMY3-style exports may contain:

- a complete actual year;
- a leap-year actual year with 8,784 hourly records;
- a partial time series;
- a chronological multi-year series;
- a conventional TMY assembled from source months belonging to different years.

pvlib is retained as OpenSIMPV's TMY3 field and station-metadata parser, but its normal TMY
calendar normalization intentionally advances leap-day labels for typical-year use. Applying
that behavior blindly to an actual leap-year file causes February 29 timestamps to collide
with March 1.

## Decision

OpenSIMPV owns canonical TMY3 timestamp construction.

The source `Date (MM/DD/YYYY)` and `Time (HH:MM)` columns are parsed directly. TMY3
timestamps are treated as interval-end labels. `24:00` is interpreted as next-day
`00:00`, after which one source interval is subtracted to obtain the canonical interval
start.

Calendar classification is explicit:

- `actual_year`: one complete regular source year, preserving its actual year and leap day;
- `partial_time_series`: an incomplete single-year sequence, preserving source dates;
- `multi_year_time_series`: a regular chronological sequence spanning source years;
- `typical_year`: mixed source years that do not form a chronological hourly calendar.

For `typical_year`, month/day/time are mapped onto deterministic calendar scaffolding:

- anchor year 2001 for ordinary non-leap calendars;
- anchor year 2000 when the source explicitly contains February 29.

The anchor year is not a meteorological provenance claim. Original source years are retained
separately.

## Metadata

The weather dataset records:

- `calendar_type`;
- `leap_year_handling`;
- `source_metadata.calendar_classification`;
- `source_metadata.source_years`;
- `source_metadata.calendar_anchor_year` when applicable.

## Consequences

- actual leap years retain all 8,784 unique hourly intervals;
- February 29 is never silently shifted into March 1 for actual-year data;
- `24:00` behavior is deterministic at month and year boundaries;
- mixed-year TMY files remain representable as one regular canonical year;
- pvlib field mappings remain available without making pvlib's DatetimeIndex authoritative;
- timestamp behavior becomes reproducible across library versions.
