# ADR 0030 — Phase 3.9H VC2 clipping and grid-residual attribution

Status: accepted as acceptance candidate; exact canonical execution pending external-oracle runtime  
Date: 2026-09-23

## Context

VC2 is the first detailed hourly case with material inverter limiting:

```text
252 modules
14 strings x 18 modules
138.6 kWp
DC/AC ≈ 1.39
DC array resistance = 59 mΩ
```

Detailed PVsyst 8.1.6 source:

```text
Sampel for OpenSimPV_Project_VC2_HourlyRes_0.CSV
SHA-256:
a7dbd60c80bf4c9483f17ccd82aa963a3d11e64150f24db1190bc49184c8687f
```

The raw CSV remains external.

## Decision

### 1. VC2 remains inside every frozen Phase-3.9 acceptance gate

Current acceptance-candidate residuals:

```text
GlobInc                      -0.01464%
GlobEff                      -0.12510%
array nominal                -0.85323%
irradiance effect            +0.32744 pp
temperature effect           +0.24732 pp
DC wiring                    +0.01897 pp
EArrMPP                      -0.23781%
inverter conversion          -0.00311 pp
ordinary clipping            +0.03466 pp
E_Grid                       +0.04696%
specific yield               +0.04696%
PR                           +0.000535 abs
monthly E_Grid RMS            0.17174%
max monthly E_Grid            0.41623%
```

Therefore:

```text
first_nonpassing_stage = null
```

### 2. Final-grid agreement is cancellation-sensitive

The small final residual must not be interpreted as stage-level parity.

Current grid residual:

```text
OpenSIMPV candidate E_Grid  211510.7001 kWh
PVsyst E_Grid               211411.4185 kWh
delta                           +99.2816 kWh
relative                         +0.04696%
```

But the stage contributions are:

```text
EArrMPP delta                    -511.4913 kWh
conversion-loss contribution      +0.2385 kWh
ordinary-clipping contribution   +73.8987 kWh
missing PVsyst ILPmxSH           +536.7011 kWh
other-loss contribution           -0.0655 kWh
------------------------------------------------
expected grid delta               +99.2816 kWh
```

Gross absolute component contribution:

```text
1122.3951 kWh
```

Cancellation ratio:

```text
|final residual| / gross contributions
= 0.08846
```

Therefore the report must explicitly flag cancellation.

### 3. Add a reusable grid-residual decomposition

`PVsystDetailedHourlyAttributionReport v0.1` now includes:

```text
grid_residual_decomposition
```

with:

- observed/reference grid energy;
- EArrMPP contribution;
- inverter conversion-loss contribution;
- ordinary clipping contribution;
- missing PVsyst ILPmxSH contribution;
- remaining EArrMPP-to-grid losses;
- exact algebraic reconciliation;
- gross absolute component magnitude;
- cancellation ratio;
- cancellation flag.

The governing identity is:

```text
dE_grid =
    dEArrMPP
    - dConversionLoss
    - dOrdinaryClipping
    + PVsyst_ILPmxSH
    - dOtherLosses
```

### 4. ILPmxSH remains a named missing model

VC2:

```text
IL_Pmax  = 224.4617 kWh
ILPmxSH  = 536.7011 kWh
IL_Nigh  =   8.7520 kWh
```

OpenSIMPV does not currently model PVsyst ILPmxSH.

It remains a first-class named difference and is never merged into ordinary
hourly clipping.

### 5. Ordinary clipping and PVsyst IL_Pmax are not identical boundaries

VC2 candidate ordinary AC clipping:

```text
150.5630 kWh
47 active intervals
```

PVsyst IL_Pmax:

```text
224.4617 kWh
60 active intervals
```

The relative energy mismatch looks large because the channel itself is small.

However PVsyst IL_Pmax participates in the DC operating-point displacement:

```text
EArrMPP -> EArray
```

while OpenSIMPV currently records AC clipping without fabricating a DC EArray
operating point.

Therefore this difference is attributed under:

```text
KD-EARRAY-DC-FEEDBACK
```

rather than treated as a direct like-for-like inverter defect.

### 6. Inverter-only isolation supports that interpretation

When PVsyst EArrMPP is injected directly into the OpenSIMPV inverter model:

```text
OpenSIMPV conversion loss    2910.7070 kWh
PVsyst IL_Oper               2903.6526 kWh
difference                     +7.0544 kWh
relative                       +0.2430%
```

After using the source ILPmxSH only as an attribution aid:

```text
OpenSIMPV grid aid          211456.6259 kWh
PVsyst E_Grid               211411.4185 kWh
delta                          +45.2074 kWh
relative                        +0.02138%
```

This is not called an exact counterfactual because inverter conversion can
change with DC operating-point displacement.

### 7. Monthly behavior also passes

Direct candidate:

```text
monthly RMS relative error   0.17174%
monthly max absolute error   0.41623%
```

Candidate minus source ILPmxSH as attribution aid:

```text
monthly RMS relative error   0.20802%
monthly max absolute error   0.23779%
```

Both are well inside the frozen:

```text
RMS <= 3%
max <= 5%
```

### 8. Exact canonical qualifier remains

The local analysis environment still does not contain the repository pvlib
runtime.

Therefore the correct status remains:

```text
acceptance_candidate_pass_with_grid_cancellation_pending_exact_canonical_spa_execution
```

No proxy or equation mirror is relabelled as an exact repository NREL-SPA run.

## Consequences

VC2 does not reveal a frozen-gate failure.

It does reveal that:

1. final E_Grid agreement can hide opposing model differences;
2. grid residual decomposition is mandatory from VC2 onward;
3. ILPmxSH becomes quantitatively material;
4. EArray/DC-feedback semantics become active;
5. clipping-channel relative error alone is not a valid parity metric when the
   two products expose different physical boundaries.

The next case is VC4, where both ordinary clipping and ILPmxSH become much more
material.

## Governing rule

```text
No hidden physics.
No hidden resolution.
No hidden loss.
No silent assumption.
No benchmark-revision mixing.
No annual-output tuning.
No cancellation presented as parity.
No ILPmxSH hidden inside ordinary clipping.
No EArray fabricated from AC clipping.
```
