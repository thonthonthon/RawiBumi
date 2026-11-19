# Decision 0008 — Meteonorm DAT uses explicit interval-end labels and preserved time reference

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Context

Meteonorm text DAT weather exports may be hourly or subhourly and use the same tabular
structure. The file header carries:

- latitude and longitude;
- elevation;
- fixed timezone offset;
- a separate time-reference value in minutes.

The weather rows use month/day/day-of-year plus hour/minute labels and do not necessarily
carry a meteorological year.

## Decision

OpenSIMPV infers Meteonorm DAT source cadence from consecutive source labels.

The source labels are interpreted as interval ends. The canonical timestamp is:

```text
canonical interval start
    =
Meteonorm source label
    -
inferred source interval duration
```

The header's `time ref. min` value is preserved in source metadata and is not applied as an
additional timestamp shift during import.

The source day-of-year field must agree with month/day.

Yearless calendars use deterministic scaffolding:

- 2001 for ordinary 365-day sequences;
- 2000 if February 29 is explicitly present.

The anchor year is calendar scaffolding only and is not meteorological provenance.

## Canonical variables

The v0.1 Meteonorm DAT adapter maps only source fields whose semantics are sufficiently clear
for the canonical weather layer:

- `G_Gh` → GHI;
- `G_Dh` → DHI;
- `G_Bn` → DNI;
- `Ta` → ambient temperature;
- `FF` → wind speed;
- `Td` → dew-point temperature.

Other source columns remain discoverable through source metadata and the immutable source-file
provenance until their semantics are intentionally modeled.

## Consequences

- hourly, 15-minute, 10-minute, and 1-minute DAT files use one importer;
- source cadence is never inferred from filenames;
- `24:00` is normalized deterministically;
- the time-reference field cannot accidentally cause a double timestamp shift;
- provider-generated subhourly series remain native to the imported file cadence, while later
  provenance work can separately describe how the provider generated those values.
