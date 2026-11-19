# Decision 0012 — PVsyst weather uses an explicit namespace and internal .MET probing is non-decoding

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Context

Phase 2 originally placed the documented PVsyst Standard weather CSV importer under:

```text
weather/met/
```

That package name implied direct support for PVsyst `.MET` objects even though the
implementation only supported the documented CSV interchange format.

Real PVsyst samples also show more than one internal `.MET` container class:

- modern/user-workspace text objects beginning with `PVObject_=pvMeteo`;
- binary/non-text `.MET` containers.

Text containers expose readable structure and metadata but can still contain encoded,
version-dependent weather payloads such as `Day_xxxx` records. Binary containers do not
provide a stable public schema.

## Decision

PVsyst weather support moves to:

```text
weather/pvsyst/
    standard.py
    probe.py
```

`standard.py` is strictly the documented PVsyst Standard weather CSV importer.

`probe.py` classifies PVsyst weather containers without decoding internal meteorological
values.

The controlled probe results are:

- `pvsyst_standard_csv`;
- `pvsyst_internal_met_text`;
- `pvsyst_internal_met_binary`;
- `pvsyst_met_unrecognized`.

## Text .MET probing

A text internal MET is positively identified only from:

```text
PVObject_=pvMeteo
```

The probe may extract structural metadata that does not require interpretation of encoded
weather values:

- PVObject type;
- declared version when present;
- whether encoded `Day_xxxx` records are visible in the probe window;
- counts of visible daily records;
- counts of visible `pvMeteoVar` objects.

The probe does not decode `Day_xxxx` tokens, `WRFactor`, variable storage modes, or any
other internal numerical representation.

## Binary .MET probing

A file with a `.MET` extension and binary/non-text content is classified as
`pvsyst_internal_met_binary`.

This is only a container classification. OpenSIMPV does not infer:

- PVsyst version;
- binary record layout;
- variable identity;
- scale factors;
- timestamps;
- numerical values.

## Negative classification

A generic PVObject signature is not enough to classify weather.

For example:

```text
PVObject_=pvShading
```

in a `.SHD` file must not be classified as meteorological input.

## Import support

Only `pvsyst_standard_csv` is directly importable into canonical weather.

Detected internal MET classes raise an explicit unsupported-format error that identifies the
detected class and, for text objects, the declared version when available.

## Consequences

- package naming no longer conflates documented CSV with internal MET objects;
- text and binary MET containers are distinguishable before import;
- internal structures can be inventoried safely without pretending to understand their
  encoded values;
- future direct MET support can be version-gated behind validated decoders;
- unrelated PVObject files such as SHD scenes are not misrouted into weather ingestion.
