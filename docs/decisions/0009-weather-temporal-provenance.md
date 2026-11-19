# Decision 0009 — Weather cadence and temporal origin are separate provenance dimensions

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Context

A weather file can contain one-minute records without those values being one-minute
measurements.

Examples include:

- provider-generated subhourly weather derived from coarser weather;
- OpenSIMPV disaggregation from hourly input;
- aggregation of a finer imported series into a coarser working series.

Using only `native_resolution_seconds` and `series_resolution_seconds` cannot distinguish
these cases.

## Decision

OpenSIMPV records temporal origin independently from temporal cadence.

The canonical weather dataset may contain:

```text
native_series_origin
series_origin
upstream_generation
```

The controlled origin vocabulary is:

- `measured`;
- `provider_generated`;
- `opensimpv_derived`;
- `unknown`.

`native_series_origin` describes the native series supplied to OpenSIMPV and does not change
when OpenSIMPV later resamples the series.

`series_origin` describes the current working series. Any OpenSIMPV resolution conversion
sets it to `opensimpv_derived`.

`upstream_generation` may record upstream temporal synthesis when supported by evidence:

- provider;
- whether the temporal series is synthetic;
- upstream base resolution;
- generic method identifier;
- evidence class;
- evidence detail.

OpenSIMPV must not infer `measured` merely because a file has fine temporal resolution.

## Meteonorm application

For Meteonorm DAT files with cadence finer than one hour and an accompanying `G_Gh_hr`
hourly-reference column, OpenSIMPV records structural evidence of provider-generated
subhourly data:

```text
native_series_origin = provider_generated
series_origin        = provider_generated

upstream_generation:
  provider: Meteonorm
  synthetic: true
  base_resolution_seconds: 3600
  method: meteonorm_provider_subhourly_generation
  evidence: source_structure
```

The method identifier deliberately does not claim knowledge of Meteonorm's undisclosed
internal algorithm.

Hourly Meteonorm DAT is left as `unknown` unless stronger provenance is supplied.

## OpenSIMPV transformations

Any resolution conversion changes only the working origin:

```text
native origin: provider_generated
        ↓ OpenSIMPV aggregation
native origin: provider_generated
working origin: opensimpv_derived
```

The transformation record also stores input and output series origins.

## Consequences

- a one-minute file cannot masquerade as one-minute measurements;
- provider-generated and OpenSIMPV-generated subhourly series remain distinguishable;
- native provenance survives later aggregation or disaggregation;
- native CSV export/re-import preserves temporal provenance;
- future simulation reports can disclose temporal fidelity without conflating cadence with
  measurement quality.
