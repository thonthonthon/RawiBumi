# Decision 0010 — Irradiance completion QC is interval-aware

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Context

Phase 2 originally emitted `WX_IRRADIANCE_DECOMPOSITION_REQUIRED` only when DNI or DHI
columns were completely absent. A weather file with those columns present but partially
missing therefore looked more complete than it actually was.

Phase 3 needs a precise contract for which intervals require irradiance completion.

## Decision

When GHI is present, OpenSIMPV evaluates DNI and DHI independently at each interval.

For each component, QC records:

- `availability`: `complete`, `partial`, or `absent`;
- whether the column is present;
- total missing count and fraction;
- completion count restricted to intervals where GHI is available;
- completion fraction relative to GHI-available intervals;
- example interval-start timestamps.

The decomposition/completion finding records the union of eligible affected intervals.

An interval is eligible for decomposition/completion only when GHI is available. Missing DNI
or DHI at an interval where GHI is also missing does not create a decomposition target; the
missing GHI remains a base-weather QC error.

The finding uses:

```text
WX_IRRADIANCE_DECOMPOSITION_REQUIRED
```

for both fully absent and partially missing DNI/DHI.

The finding context includes:

```text
total_intervals
ghi_available_intervals
intervals_requiring_completion
completion_scope
missing_components
components
```

`completion_scope` is either:

- `full_ghi_available_series`; or
- `partial_intervals`.

Weather import and QC never synthesize DNI or DHI.

## Consequences

- partially missing DNI/DHI can no longer masquerade as complete irradiance input;
- Phase 3 can apply a selected decomposition/completion model only to affected intervals;
- intervals with missing GHI remain blocked instead of being incorrectly treated as
  decomposable;
- the same QC rule handles absent and partially missing components;
- generic optional-variable warnings are not duplicated for DNI/DHI.
