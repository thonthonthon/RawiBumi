# ADR 0027 — Phase 3.9 PVsyst 8.1.6 stage-by-stage attribution

Status: accepted with external acceptance blockers  
Date: 2026-09-23

## Context

Phases 3.8A through 3.8E closed the known internal prerequisites for a
cross-software attribution campaign:

- PAN optical/module-quality semantics reach runtime;
- PVsyst 8.1 transient thermal behavior has a versioned compatibility path;
- PVsyst 8.1 Perez/low-sun behavior has a separate compatibility path;
- solar-aware weather QC is available;
- canonical ProjectRevision + SimulationConfiguration execution produces an
  immutable SimulationRun and persisted result package.

The available PVsyst oracle consists of eight user-supplied PVsyst 8.1.6
reports:

- VC0/VC1 — DC/AC 1.19 hourly/minute;
- VC2/VC3 — DC/AC 1.39 hourly/minute;
- VC4/VC5 — DC/AC 1.58 hourly/minute;
- VC6/VC7 — DC/AC 1.78 hourly/minute.

Pages 4 and 5 of all eight reports were re-checked during Phase 3.9 against the
machine-readable reference targets.

The reports expose monthly/annual balances and the annual loss diagram, but do
not provide the interval Meteonorm 9 weather series or a detailed timestep
result export.

## Primary PVsyst variable semantics

PVsyst documents for grid-connected systems:

- `EArrMPP` is array MPP energy after array losses;
- `EArray` is effective array output and includes inverter operating-point
  displacement;
- `E_Grid` is energy injected into the grid;
- performance ratio is
  `E_Grid / (GlobInc * PNomArray)`.

Primary documentation:

- https://www.pvsyst.com/help/project-design/results/simulation-variables-grid-system.html
- https://www.pvsyst.com/help/project-design/results/performance-ratio-pr.html

## Decision

### 1. Freeze a dedicated Phase-3.9 reference campaign

The report-derived oracle is frozen in:

```text
tests/benchmarks/phase39_pvsyst_v816_attribution.yaml
```

It contains for each VC0..VC7 case:

- source report filename;
- simulation cadence;
- topology/DC loading;
- annual GlobHor, DiffHor, T_Amb, GlobInc, GlobEff, EArray, E_Grid,
  specific yield, and PR;
- monthly EArray and E_Grid;
- annual loss-diagram Array nominal energy;
- irradiance-level effect;
- temperature effect;
- module quality effect;
- mismatch;
- DC wiring;
- EArrMPP;
- inverter conversion;
- clipping;
- zero-reported current/voltage/threshold/night channels;
- inverter output.

The source PDF files remain external and are not redistributed.

### 2. Acceptance thresholds are frozen before same-input OpenSIMPV results

The Phase-3.9 acceptance policy is:

```text
annual horizontal weather:
    relative <= 0.1% OR absolute <= 0.2 kWh/m²

annual POA:
    relative <= 1% OR absolute <= 1.0 kWh/m²

annual effective irradiance:
    relative <= 1% OR absolute <= 1.0 kWh/m²

array nominal energy:
    relative <= 1% OR absolute <= 25 kWh

individual loss-diagram effects:
    absolute difference <= 0.50 percentage point

EArrMPP:
    relative <= 2% OR absolute <= 50 kWh

E_Grid:
    relative <= 3% OR absolute <= 50 kWh

PR:
    absolute difference <= 0.03

specific yield:
    relative <= 3% OR absolute <= 10 kWh/kWp

monthly E_Grid:
    RMS relative error <= 3%
    maximum absolute monthly relative error <= 5%
```

These thresholds may only be loosened through an explicit reviewed decision.
They must not be adjusted after observing a result merely to create agreement.

### 3. Attribution follows the first divergence

Comparison order is:

```text
weather
→ POA transposition
→ IAM/effective irradiance
→ array nominal energy
→ irradiance-level effect
→ temperature effect
→ module quality
→ mismatch
→ DC wiring
→ EArrMPP
→ inverter conversion
→ inverter clipping
→ E_Grid
→ PR
```

A later matching total cannot erase an earlier stage failure.

A failed stage is reported as:

```text
unresolved_requires_evidence
```

until evidence supports one of the established attribution classes.

The comparison engine does not automatically declare a known model difference
to be the cause of a residual.

### 4. OpenSIMPV recreates the PVsyst array-loss sequence explicitly

Phase 3.9 derives an OpenSIMPV loss-diagram analogue from the canonical standard
time series and pinned ModuleDefinition.

For the module section:

```text
GlobEff
→ model STC nominal energy
→ SDM at actual irradiance and 25°C
→ SDM at actual irradiance and actual transient temperature
→ module quality
→ combined module/string mismatch
→ DC wiring
→ array virtual MPP
```

Definitions:

```text
array nominal:
    effective irradiance / 1000
    * model-calculated STC Pmp
    * module count

irradiance-level effect:
    Pmp(actual irradiance, 25°C) / array nominal - 1

temperature effect:
    raw actual-temperature MPP / Pmp(actual irradiance, 25°C) - 1
```

This mirrors the loss-diagram ordering rather than inferring low-light and
temperature effects from a final annual residual.

### 5. EArrMPP is the DC acceptance mapping

PVsyst `EArrMPP` maps to:

```text
OpenSIMPV net_dc_power_w / array_virtual_mpp
```

after module quality, mismatch, and DC wiring.

This is an explicit acceptance target.

### 6. EArray is not a current acceptance target

PVsyst documents that `EArray` includes inverter operating-point displacement.

The current OpenSIMPV inverter model keeps:

```text
array virtual MPP
→ threshold eligibility
→ conversion
→ AC clipping
```

without back-propagating clipping/operating limits into a synthetic DC array
operating point.

Therefore Phase 3.9 does not compare OpenSIMPV `array_virtual_mpp` to PVsyst
`EArray`.

Instead each report records:

```text
DC operating displacement reference
    = EArrMPP - EArray
```

as an excluded reference metric.

This difference may be implemented in a later explicit DC/inverter coupling
model. It must not be faked by back-converting AC clipping.

### 7. Report-level comparison and interval comparison are separate

The current PVsyst source set supports:

- annual stage metrics;
- monthly EArray/E_Grid;
- annual loss diagram.

It does not support direct interval RMSE/MAE because no detailed timestep
PVsyst output is available.

Interval attribution becomes available only when a detailed PVsyst timestep
export is supplied.

### 8. Same-input weather is a hard acceptance precondition

The reports identify:

```text
Meteonorm 9.0 dll, Sat=100% - Synthetic
```

but do not include the interval weather series.

The standalone Meteonorm 8.2 files in the benchmark family are not the same
weather source and are not accepted as substitutes.

Therefore:

```text
different weather family
→ diagnostics may be calculated
→ acceptance status = not_admissible
```

A close annual total from a different weather family is not PVsyst parity
evidence.

### 9. Minute acceptance has an additional Perez precondition

For 60-second PVsyst 8.1.6 cases, exact transposition acceptance additionally
requires a timestep-matched coefficient set verified as the PVsyst 8.1
production Perez table.

Until that exists:

```text
minute acceptance = blocked_external_model_data
```

even if the Meteonorm 9 minute weather series is later obtained.

### 10. Current campaign readiness

At the time of this decision:

#### Hourly VC0/VC2/VC4/VC6

Blocked by:

```text
PVSYST_METEONORM9_INTERVAL_WEATHER_NOT_ALIGNED
```

If the exact hourly PVsyst/Meteonorm 9 weather series is exported, the hourly
cases become admissible for annual/monthly acceptance immediately.

#### Minute VC1/VC3/VC5/VC7

Blocked by:

```text
PVSYST_METEONORM9_INTERVAL_WEATHER_NOT_ALIGNED
PVSYST81_SUBHOURLY_PEREZ_COEFFICIENTS_UNVERIFIED
```

### 11. Known differences remain candidates, not automatic explanations

The attribution report carries the applicable known-difference ledger:

- sub-hourly Perez production coefficients;
- PAN IAM TCubic execution difference;
- OND inverter TCubic execution approximation;
- transient-thermal history edge semantics;
- EArray DC operating-point feedback.

These are possible explanations only after the earliest failed stage and the
available evidence point to them.

## New attribution API

Phase 3.9 adds:

```text
load_pvsyst_attribution_campaign(...)
validate_pvsyst_reference_campaign(...)
assess_pvsyst_case_readiness(...)
extract_opensimpv_attribution_metrics(...)
build_pvsyst_attribution_report(...)
```

The output contract is:

```text
PVsystAttributionReport v0.1
```

## Consequences

Positive:

- acceptance thresholds are frozen before observing same-input OpenSIMPV
  results;
- PVsyst report values have one versioned machine-readable source;
- OpenSIMPV can recreate the meaningful PVsyst loss-diagram stages without
  tuning annual output;
- different weather families cannot accidentally become acceptance evidence;
- EArrMPP and EArray semantics are no longer conflated;
- known model differences are visible without being used as automatic excuses;
- future PVsyst weather/timestep exports can be inserted into the same
  attribution framework without redesigning the comparison logic.

Current limitation:

- no exact same-weather PVsyst/OpenSIMPV annual acceptance result can be claimed
  from the supplied reports alone;
- exact minute transposition acceptance additionally remains blocked by the
  unavailable verified PVsyst 8.1 production Perez coefficients;
- interval RMSE/MAE attribution awaits detailed PVsyst timestep output.

## Regression requirements

Phase 3.9 framework is accepted when tests prove:

1. all eight report-derived references are internally consistent;
2. hourly and minute controlled families share their respective report-level
   weather/optical inputs across DC loading cases;
3. report clipping increases with DC/AC ratio;
4. hourly readiness is blocked without same interval weather;
5. hourly readiness becomes annual/monthly acceptance-ready when same weather
   is available;
6. minute readiness requires both same weather and verified Perez coefficients;
7. a synthetic exact observation passes the frozen thresholds;
8. an earliest-stage failure is reported without an invented causal claim;
9. different weather remains not-admissible even if totals match;
10. EArray is excluded from current acceptance mapping;
11. OpenSIMPV metric extraction reconstructs a signed loss-diagram sequence;
12. the attribution report validates against JSON Schema;
13. full repository CI passes.
