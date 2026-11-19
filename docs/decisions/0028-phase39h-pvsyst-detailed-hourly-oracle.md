# ADR 0028 — Phase 3.9H PVsyst detailed hourly oracle

Status: accepted  
Date: 2026-09-23

## Context

Four user-supplied PVsyst 8.1.6 detailed-output CSV files are now available for
VC0, VC2, VC4, and VC6.

Each file contains 8760 hourly intervals and identifies the same upstream weather:

```text
Home_MN90_SYN_1MIN.MET
Home; Meteonorm 9.0 dll, Sat=100%; Synthetic
```

The detailed outputs expose weather, solar geometry, transposition, IAM,
temperature, array losses, virtual MPP, inverter losses, and grid output.

These files are later simulation executions than the previously supplied PDF
reports. Their annual POA/DC/grid totals differ from those PDF snapshots, so the
two source families must not be merged into one benchmark identity.

## Decision

### 1. Create a separate detailed-hourly oracle revision

The detailed source family is versioned as:

```text
P39-HR1-PVSYST816-20260923
```

The raw user-supplied CSV files remain external. OpenSIMPV stores their SHA-256
identities and frozen aggregate fingerprints in:

```text
tests/benchmarks/phase39_hourly_detailed_oracle_20260923.yaml
```

### 2. Treat CSV timestamps as interval starts

PVsyst documents that an hourly timestamp denotes the beginning of the interval
and that solar geometry is evaluated at the middle of the interval.

This matches the OpenSIMPV canonical convention:

```text
timestamp = interval_start
representative solar time = interval_midpoint
```

No timestamp shift is introduced.

### 3. Horizontal weather is the same-input execution boundary

Canonical weather imported from the detailed oracle uses:

```text
GlobHor -> ghi_w_m2
DiffHor -> dhi_w_m2
T_Amb   -> ambient_temperature_c
WindVel -> wind_speed_m_s
```

DNI is intentionally not copied or reconstructed from PVsyst solar geometry.

OpenSIMPV derives the missing DNI from GHI/DHI using its own solar geometry.
This preserves the ability to observe solar-position/transposition differences
rather than importing a PVsyst-derived direct-normal series that could hide
them.

### 4. Underlying MET resolution and exported resolution stay distinct

The detailed output series is hourly:

```text
series resolution = 3600 s
```

The source metadata identifies a one-minute MET:

```text
upstream weather resolution = 60 s
```

The canonical weather adapter records both. It does not call the hourly CSV a
native one-minute series.

### 5. Common inputs are controlled across VC0/VC2/VC4/VC6

Weather, solar geometry, POA, and IAM/effective-irradiance columns were checked
across all four uploaded files and are identical.

A deterministic logical hash is frozen:

```text
894a678a78de755352a5acb2d3433466c473ba221ad888412611d256f91e0ea4
```

Therefore the four detailed cases constitute a controlled DC-loading family.

### 6. PDF reports and detailed CSVs are different simulation snapshots

The PDF simulations were produced around 11:50–11:59.

The detailed CSV simulations were produced around 20:03–20:06.

For example VC0:

```text
PDF E_Grid      181376 kWh
CSV E_Grid      181795.8099 kWh
```

The detailed CSVs also produce different annual GlobInc/GlobEff values.

Therefore:

```text
PDF report campaign = historical report-level oracle
P39-HR1 CSV family  = detailed timestep oracle
```

No comparison may use weather/POA from one family and E_Grid from the other.

### 7. Sub-hourly clipping correction is first-class

PVsyst documents that an hourly simulation using a sub-hourly MET automatically
applies sub-hourly clipping correction.

The corresponding detailed-output variable is:

```text
ILPmxSH
```

VC0 exports ILPmxSH directly.

VC2, VC4, and VC6 omitted that column from the selected output fields, but the
value is exactly recoverable from PVsyst's inverter-loss identity:

```text
ILPmxSH =
    InvLoss
    - IL_Oper
    - IL_Pmin
    - IL_Vmin
    - IL_Pmax
    - IL_Vmax
    - IL_Imax
    - IL_Nigh
```

VC0 directly validates this inference path to sub-watt-level CSV rounding.

Annual correction values for P39-HR1 are:

```text
VC0    49.3015 kWh  direct
VC2   536.7011 kWh  inferred
VC4  2013.2653 kWh  inferred
VC6  3824.6276 kWh  inferred
```

This correction must remain separate from ordinary hourly `IL_Pmax`.

### 8. PVsyst interval identities are validation gates

The detailed oracle parser checks:

```text
EArrMPP =
    EArrNom
    - GIncLss
    - TempLss
    - ModQual
    - MisLoss
    - OhmLoss

InvLoss = EArrMPP - EOutInv

EArrMPP - EArray =
    IL_Pmin + IL_Vmin + IL_Pmax + ILPmxSH + IL_Vmax + IL_Imax

E_Grid = EOutInv
```

within explicit CSV rounding tolerance.

### 9. Economics are outside the physics attribution scope

No economic variable is required by Phase 3.9H.

The uploaded exports are therefore sufficiently complete for the physical
hourly attribution campaign.

## Consequences

Positive:

- the previous same-input hourly weather blocker is closed when one of these
  external source files is supplied to the attribution run;
- timestamp semantics are no longer uncertain;
- Stage A through the detailed electrical chain can be compared interval by
  interval;
- the controlled DC-loading family is proven by one logical input hash;
- sub-hourly clipping correction is explicitly visible rather than being folded
  into generic clipping;
- the older PDF benchmark remains reproducible without being silently replaced.

Remaining limitation:

- OpenSIMPV does not currently implement PVsyst's ILPmxSH correction model.
  Therefore final high-loading E_Grid parity must attribute that channel
  separately unless the model is explicitly implemented from independent
  source data/evidence.
- minute PVsyst acceptance still has the separate production-Perez coefficient
  blocker established in Phase 3.8C.

## New implementation

```text
validation/attribution/pvsyst_output.py
```

provides:

- PVsyst detailed-output parsing;
- source fingerprinting;
- interval/balance validation;
- ILPmxSH direct/inferred resolution;
- hourly oracle aggregation;
- canonical weather adaptation;
- controlled-input logical hashing.
