# Decision 0011 — Weather time semantics are explicit and separate source reference from solar evaluation

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Context

Weather formats encode time differently:

- TMY3 uses interval-end labels;
- EPW uses a 1..24 hour convention that is normalized to interval starts;
- Meteonorm DAT uses interval-end labels plus a provider `time ref. min` field;
- PVsyst Standard weather uses interval-start labels, can declare a different source time
  reference, and can apply a total time shift whose remainder is used for solar-time
  correction.

Scattering these meanings across `source_metadata` makes Phase 3 vulnerable to double shifts
or format-specific interpretation.

## Decision

Every canonical WeatherDataset carries one authoritative `time_semantics` object with:

```text
origin_source
canonical
representative_time
```

### origin_source

Records the original meteorological source:

- timezone;
- UTC offset when known;
- timestamp convention;
- native interval duration;
- optional source-reference metadata.

Source reference records:

- kind;
- offset in minutes;
- whether the reference was applied to canonical timestamps;
- whether the reference is itself applied to solar evaluation.

A provider-declared reference is never assumed to be a solar correction.

### canonical

Records the current OpenSIMPV series:

- timezone;
- `interval_start` timestamp convention;
- current interval duration.

OpenSIMPV resampling updates only the canonical interval duration. Native source semantics
remain unchanged.

### representative_time

Phase-3 quasi-steady calculations use:

```text
canonical interval midpoint + solar_evaluation_offset_minutes
```

The representative-time policy is fixed as `interval_midpoint` for v0.1.

The solar offset is zero unless a source adapter has explicit evidence that an additional
solar-time correction remains after timestamp normalization.

## Format application

### TMY3

- source convention: interval end;
- source and canonical timezone: source fixed UTC offset;
- source reference: none;
- solar evaluation offset: 0.

### EPW

- source convention: EPW 1..24 interval representation;
- source and canonical timezone: source fixed UTC offset;
- source reference: none;
- solar evaluation offset: 0.

### Meteonorm DAT

- source convention: interval end;
- provider `time ref. min` is retained as
  `origin_source.reference.offset_minutes`;
- that reference is not applied again to canonical timestamps;
- that reference is not applied to solar evaluation;
- solar evaluation offset: 0.

### PVsyst Standard weather

- source convention: interval start;
- source time-reference timezone is recorded separately from site/canonical timezone;
- whole-step declared time shift is applied to canonical timestamps;
- only the within-interval remainder is retained as
  `solar_evaluation_offset_minutes`.

Example:

```text
10 min source interval
declared shift = +25 min

timestamp shift = +20 min
solar evaluation offset = +5 min
```

## Compatibility

The v0.1 top-level fields `timezone`, `timestamp_convention`, and
`source_timestamp_convention` remain present for compatibility and convenient indexing.
`time_semantics` is authoritative for Phase-3 time interpretation.

OpenSIMPV native Weather CSV serializes `time_semantics` so the contract survives
round-trip.

## Consequences

- Phase 3 has one cross-format time interpretation contract;
- source reference metadata cannot be accidentally double-applied;
- PVsyst residual solar-time correction is preserved distinctly from timestamp shifts;
- weather resampling changes the current interval duration without rewriting source history;
- simulations can reproduce the exact representative solar calculation time.
