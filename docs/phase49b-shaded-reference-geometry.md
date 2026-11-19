# OpenSIMPV — Phase 4.9B Shaded Reference / Geometry Matrix

**Status:** External shaded-oracle and geometry tranche  
**Date:** 2026-09-24  
**Parent:** Phase 4.9 Reference Projects and UX Hardening  
**Source software:** PVsyst 8.1.6

## 1. Scope

Phase 4.9B freezes six user-supplied PVsyst shaded hourly exports together with their corresponding SHD scenes.

The cases are:

| Case | User label |
|---|---|
| VC0 | north |
| VC1 | south |
| VC2 | east |
| VC3 | west |
| VC4 | east-west |
| VC5 | north-south |

The labels identify the intended shading case. They are **not** symmetry claims.

This tranche does not implement the OpenSIMPV Phase-5 shading solver. It freezes source geometry, source shading behavior and provenance so later canonical reconstruction and Phase-5 geometry validation have an external oracle.

## 2. Controlled baseline

All six cases use:

- one inverter;
- 216 × JKM550M-72HL4-V modules;
- 118.8 kWp DC;
- 12 PV tables;
- 18 portrait modules per table;
- module dimensions 1.134 × 2.278 m;
- 20° field tilt;
- 0° field azimuth;
- 0.020 m module spacing;
- the same site and weather source;
- 8,760 hourly rows.

The following critical pre-shading series are exactly identical across all six CSVs:

`date, HSol, AzSol, AngInc, AngProf, GlobHor, DiffHor, BeamHor, T_Amb, WindVel, GlobInc, BeamInc, CircInc, DifSInc, Alb_Inc`.

Annual `GlobInc` is therefore common:

```text
1758.0986391 kWh/m²
```

The six files contain the same 107 channel names. VC0 uses a different column order from VC1–VC5, which is retained as a parser-order regression: PVsyst ingestion must be field-name based rather than positional.

## 3. SHD geometry

The SHD files resolve geometry that the previous aggregate unshaded CSV set could not recover.

Common PV table X origins:

```text
0 m
23 m
```

VC0, VC2, VC3 and VC4 use table Y origins:

```text
-21, -18, -15, -12, -9, -6 m
```

VC1 and VC5 use:

```text
8, 11, 14, 17, 20, 23 m
```

Obstacle geometry is frozen exactly from the SHD files:

| Case | Obstacle origin(s) [m] | Size XYZ [m] |
|---|---|---|
| VC0 north | (-8.256538, -5.000000, 0) | 40 × 10 × 5 |
| VC1 south | (-8.256538, -5.000000, 0) | 40 × 10 × 5 |
| VC2 east | (35.794541, -24.427654, 0) | 10 × 20 × 5 |
| VC3 west | (-21.702076, -24.427654, 0) | 10 × 20 × 5 |
| VC4 east-west | (-21.702076, -24.427654, 0); (35.024096, -24.141728, 0) | 10 × 20 × 5 each |
| VC5 north-south | (-8.256538, -5.000000, 0); (-8.242630, 24.358715, 0) | 40 × 10 × 5 each |

The geometry demonstrates why north/south and east/west must not be interpreted as mirrored pairs. In VC0/VC1 the obstacle is unchanged while the PV table field is translated. East/west obstacle positions are also not exact mirror coordinates.

## 4. Annual shading oracle

| Case | Shading loss kWh/m² | Fraction of GlobInc | EGrid kWh |
|---|---:|---:|---:|
| VC0 north | 165.2601076 | 9.3999% | 165674.0187 |
| VC1 south | 73.1104655 | 4.1585% | 174666.5388 |
| VC2 east | 77.8276791 | 4.4268% | 174094.5553 |
| VC3 west | 90.7345854 | 5.1609% | 172875.0182 |
| VC4 east-west | 133.4087328 | 7.5882% | 168576.9789 |
| VC5 north-south | 176.8839615 | 10.0611% | 164467.1335 |

Each case also freezes the separate beam, circumsolar, diffuse and albedo shading-loss channels plus monthly shading loss and monthly grid energy.

The four shading components reconcile to total PVsyst `ShdLoss` within source rounding.

## 5. Directional hourly evidence

For the directional check, Phase 4.9B integrates beam + circumsolar shading loss over two local-clock windows:

```text
morning   06:00–11:59
afternoon 12:00–17:59
```

VC2 east:

```text
morning   25.3049903 kWh/m²
afternoon  2.6566938 kWh/m²
```

VC3 west:

```text
morning    2.6667887 kWh/m²
afternoon 34.4876896 kWh/m²
```

This establishes the expected temporal directionality while deliberately avoiding any claim that east and west are magnitude-symmetric.

## 6. Combined cases are not additive

The two-obstacle cases are retained as independent source oracles.

```text
VC4 east-west shading loss
= 133.4087328 kWh/m²

VC2 + VC3
= 168.5622645 kWh/m²
```

and:

```text
VC5 north-south shading loss
= 176.8839615 kWh/m²

VC0 + VC1
= 238.3705731 kWh/m²
```

OpenSIMPV must not construct combined shading by summing independent directional annual losses.

## 7. PVsyst IL_Pmin reconciliation correction

The shaded matrix exposes nonzero `IL_Pmin`, which revealed an error in the existing attribution balance.

PVsyst `EArray` is the PV-array power at the inverter-imposed DC operating point. `IL_Pmin` is an inverter low-power loss after that boundary.

Therefore:

```text
EArrMPP - EArray
```

may include:

```text
IL_Vmin
IL_Pmax
ILPmxSH
IL_Vmax
IL_Imax
```

but **not** `IL_Pmin`.

`IL_Pmin` remains included in total `InvLoss`.

With the corrected boundary, the maximum observed DC operating-point residual is below 0.001 kW across VC0–VC5. The broader external source family uses a 0.01 kW reconciliation tolerance because source rounding produces up to 0.0097 kW residual in other balance identities. The global parser default is not relaxed.

## 8. Provenance boundary

The raw CSV and SHD files remain external user-supplied references and are not redistributed.

The repository freezes:

- source filename;
- SHA-256;
- byte size;
- exact SHD-derived table/obstacle geometry;
- common design baseline;
- annual shading components;
- monthly shading and grid targets;
- directional hourly signatures;
- source balance residuals;
- column-set/order fingerprints.

Geometry is taken from SHD, not reverse-engineered from hourly output.

## 9. Phase boundary

Phase 4.9B provides a geometry-aware external reference package.

It does **not** claim:

- OpenSIMPV geometric beam shading is implemented;
- diffuse sky obstruction is implemented;
- ground-view obstruction is implemented;
- electrical mismatch from shade is implemented;
- PVsyst shading factors define OpenSIMPV's future equations.

Those belong to Phase 5 and later fidelity work.

For Phase 4.9, these cases support reference-project reconstruction, exact geometry serialization, save/reload identity, design provenance and future shading validation.
