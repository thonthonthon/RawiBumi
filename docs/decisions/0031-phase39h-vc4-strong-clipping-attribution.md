# ADR 0031 — Phase 3.9H VC4 strong-clipping attribution

Status: accepted as acceptance candidate; exact canonical execution pending external-oracle runtime  
Date: 2026-09-23

## Context

VC4 raises the controlled-family DC loading to:

```text
288 modules
16 strings x 18 modules
158.4 kWp
DC/AC ≈ 1.58
array resistance = 52 mΩ
string mismatch = 0.05%
```

Detailed PVsyst 8.1.6 source:

```text
Sampel for OpenSimPV_Project_VC4_HourlyRes_0.CSV
SHA-256:
b5814bd641ffcf8f8df541b5c51389bba820b3f21e4dbb54e7b7fd84cdc46143
```

The source is part of the same controlled hourly family as VC0/VC2: timestamp,
weather, solar geometry, POA and optical columns are identical.

## Decision

### 1. VC4 remains inside every frozen acceptance gate

The acceptance-candidate residuals remain bounded:

```text
GlobInc                      -0.01464%
GlobEff                      -0.12510%
array nominal                -0.85325%
irradiance effect            +0.32744 pp
temperature effect           +0.24732 pp
total mismatch               +0.00100 pp
DC wiring                    +0.01232 pp
EArrMPP                      -0.24352%
inverter conversion          -0.02816 pp
ordinary clipping            +0.25340 pp
E_Grid                       +0.83610%
specific yield               +0.83610%
PR                           +0.007226 abs
monthly grid sensitivity RMS  0.89233%
monthly grid sensitivity max  1.35128%
```

Therefore:

```text
first_nonpassing_stage = null
```

### 2. The dominant missing grid-side model is now ILPmxSH

PVsyst VC4:

```text
IL_Pmax = 3898.8000 kWh
ILPmxSH = 2013.2653 kWh
```

The raw candidate final-grid residual is:

```text
+1977.5115 kWh
+0.83610%
```

Its stage decomposition is:

```text
EArrMPP contribution                  -598.2899 kWh
conversion-loss contribution           -61.1082 kWh
ordinary-clipping contribution        +623.2671 kWh
missing PVsyst ILPmxSH               +2013.2653 kWh
other-loss contribution                +0.3773 kWh
----------------------------------------------------
grid residual                         +1977.5115 kWh
```

ILPmxSH accounts for about 61% of the gross absolute stage contributions.

VC4 therefore differs from VC2:

- VC2 final agreement was strongly cancellation-sensitive.
- VC4's raw grid difference is no longer near zero.
- The largest named missing model is now directly visible as ILPmxSH.

### 3. Source-ILPmxSH subtraction is only an attribution aid

Using the candidate interval clipping envelope:

```text
candidate E_Grid                     238494.6220 kWh
minus source ILPmxSH                  2013.2653 kWh
-----------------------------------------------
attribution-aid grid                 236481.3567 kWh

PVsyst E_Grid                        236517.1105 kWh
difference                              -35.7538 kWh
relative                                -0.01512%
```

Monthly sensitivity after the same attribution aid:

```text
RMS relative error      0.09986%
maximum absolute error  0.16882%
```

This is strong evidence that the unresolved high-loading grid discrepancy is
primarily the sub-hourly clipping correction boundary.

It is not called an exact counterfactual because inverter efficiency and DC
operating point can move under sub-hourly clipping.

### 4. EArrMPP-to-EArray feedback is now quantitatively dominant

PVsyst:

```text
EArrMPP - EArray
= 5911.9480 kWh
```

and:

```text
IL_Pmax + ILPmxSH
= 5912.0653 kWh
```

Difference:

```text
-0.1173 kWh
```

Therefore, at VC4 loading, the PVsyst DC operating-point displacement is almost
entirely accounted for by the two clipping channels.

This validates keeping:

```text
KD-EARRAY-DC-FEEDBACK
```

as an architectural model boundary rather than fabricating a DC EArray from
OpenSIMPV's AC clipping result.

### 5. Electrical isolation remains close before the clipping boundary

Using PVsyst GlobEff and TArray while executing OpenSIMPV's PAN SDM, quality,
mismatch and exact I²R chain:

```text
OpenSIMPV EArrMPP  245445.7523 kWh
PVsyst EArrMPP     245685.8895 kWh
difference             -0.09774%
```

Thus the strong high-loading residual is not caused by a large new array-model
failure.

### 6. Inverter-only isolation

Feeding PVsyst EArrMPP directly into the OpenSIMPV inverter transfer curve:

```text
OpenSIMPV conversion loss  3317.4802 kWh
PVsyst IL_Oper             3248.0224 kWh
difference                    +2.1385%
```

The absolute difference is about 69.46 kWh.

OpenSIMPV AC clipping under the same virtual MPP input:

```text
3452.5524 kWh
```

PVsyst IL_Pmax:

```text
3898.8000 kWh
```

Again these clipping channels are not treated as identical physical boundaries.

After source ILPmxSH is applied only as an attribution aid, the grid difference
is:

```text
+376.7290 kWh
+0.15928%
```

This remains small compared with total annual energy and supports the conclusion
that conversion is secondary to the clipping/DC-feedback boundary.

### 7. Monthly full-chain values are explicitly a sensitivity envelope

The local analysis environment still lacks the repository pvlib runtime.

The exact annual full-chain EArrMPP candidate is therefore distributed over the
electrical-isolation interval shape using one uniform factor before the inverter
run.

This is labelled:

```text
monthly_grid_sensitivity
```

and is not substituted for an exact canonical NREL-SPA execution.

## Consequences

VC4 does not create a new failing frozen stage.

It establishes that, at DC/AC ≈1.58:

1. ILPmxSH is a first-order model difference;
2. EArray/DC operating-point feedback is materially active;
3. ordinary AC clipping and PVsyst IL_Pmax cannot be compared as if they were
   identical channels;
4. final-grid attribution must preserve sub-hourly correction separately;
5. high-loading PVsyst validation cannot rely on final annual E_Grid alone.

The next case is VC6, where clipping becomes stronger again.

## Governing rule

```text
No hidden physics.
No hidden resolution.
No hidden loss.
No silent assumption.
No benchmark-revision mixing.
No annual-output tuning.
No ILPmxSH hidden inside ordinary clipping.
No EArray fabricated from AC clipping.
No sensitivity envelope relabelled as canonical execution.
```
