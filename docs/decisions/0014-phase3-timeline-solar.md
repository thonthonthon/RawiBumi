# Decision 0014 — Phase 3 timeline uses interval midpoint plus explicit solar offset and NREL SPA

**Status:** Accepted for Phase 3.1  
**Date:** 2026-09-23

## Context

Phase 2.1 established explicit weather time semantics:

```text
canonical interval_start
current interval_seconds
representative_time.policy = interval_midpoint
solar_evaluation_offset_minutes
```

Phase 3 requires one deterministic interpretation of these fields before irradiance
transposition or electrical calculations begin.

The Simulation Engine specification recommends the pvlib implementation of the NREL SPA
family for V1 solar position and requires canonical azimuth:

```text
0° North
90° East
180° South
270° West
```

## Decision

### Timeline

Every canonical weather interval becomes:

```text
interval_start
interval_end
interval_midpoint
evaluation_time
duration_seconds
```

with:

```text
evaluation_time
    =
interval_midpoint
    +
solar_evaluation_offset_minutes
```

Timeline construction does not resample weather. A requested simulation timestep different
from the current canonical weather cadence is rejected; the caller must execute an explicit
weather transformation first.

The builder also rejects non-monotonic, duplicate, timezone-naive, or cadence-inconsistent
weather series.

### Solar position

The initial supported model is:

```text
solar_position.nrel_spa.pvlib.v0.1
```

implemented with:

```python
pvlib.solarposition.spa_python(
    ...,
    how="numpy",
    numthreads=1,
)
```

The numpy backend and one-thread execution are selected for deterministic reference behavior.

Required outputs are retained separately:

- apparent zenith;
- true zenith;
- apparent elevation;
- true elevation;
- azimuth;
- equation of time;
- exact evaluation timestamp.

### Meteorological inputs to SPA

If complete canonical weather pressure is available, it is used for atmospheric refraction.
Otherwise pressure is derived from site elevation using pvlib's standard-atmosphere relation.

If complete canonical ambient temperature is available, it is used. Otherwise SPA's 12 °C
default is used.

The selected pressure and temperature sources are recorded in the solar-position result
metadata.

### Delta T

The normal engine path leaves `delta_t` to pvlib's SPA calculation and records that policy.
An explicit `delta_t_seconds` can be supplied for a benchmark/reproducibility case.

### Independent numerical reference

`SOL-POS-001` uses the published NREL SPA example from Reda and Andreas,
NREL/TP-560-34302, DOI 10.2172/15003974.

The reference fixture freezes:

```text
2003-10-17 12:30:30 LST-07:00
latitude  = 39.742476°
longitude = -105.1786°
elevation = 1830.14 m
pressure  = 82000 Pa
temperature = 11 °C
delta T   = 67 s

apparent/topocentric zenith = 50.11162°
azimuth                     = 194.34024°
equation of time            = 14.641503 min
```

The fixture is stored in:

```text
tests/benchmarks/solar_position_nrel_spa.yaml
```

## Consequences

- all later irradiance physics receives the exact evaluation time used for solar geometry;
- source time-reference metadata cannot be silently reapplied;
- native hourly and native minute cases use the same timeline semantics;
- PVsyst residual within-interval solar offsets remain supported explicitly;
- solar azimuth is already in the OpenSIMPV canonical compass convention;
- Phase 3.2 can build incidence angle and POA on a stable solar-geometry layer.
