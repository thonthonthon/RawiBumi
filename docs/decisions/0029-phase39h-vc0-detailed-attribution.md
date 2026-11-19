# ADR 0029 — Phase 3.9H VC0 detailed hourly attribution

Status: accepted as acceptance candidate; exact canonical execution pending external-oracle runtime  
Date: 2026-09-23

## Context

Phase 3.9H now has a user-supplied PVsyst 8.1.6 detailed hourly oracle for VC0:

```text
Sampel for OpenSimPV_Project_VC0_HourlyRes_0.CSV
SHA-256:
68e1f281d48500585a8f35da90a23e08db354a7b4468b95e0e8f79ff2d40439b
```

The file provides 8760 hourly intervals from the exact PVsyst/Meteonorm-9
simulation snapshot and exposes weather, geometry, POA, IAM, thermal, array,
inverter, and grid stage boundaries.

The raw CSV remains external and is not redistributed.

The current local analysis environment did not contain the project pvlib
dependency. Therefore the final local end-to-end solar stage could not be
truthfully labelled as an exact execution of
`solar_position.nrel_spa.pvlib.v0.1`.

## Decision

### 1. Add a formal external-oracle attribution runner

`validation/attribution/pvsyst_detailed.py` accepts:

```text
PVsystDetailedOutput
+ completed SimulationRun identity
+ OpenSIMPV standard timeseries
+ pinned ModuleDefinition
+ campaign case identity
```

and returns:

```text
PVsystDetailedHourlyAttributionReport v0.1
```

The runner:

- derives reference stage metrics from the detailed CSV itself;
- does not reuse the older PDF totals;
- reuses the frozen Phase-3.9 acceptance tolerances;
- marks same-input hourly comparison as admissible;
- computes interval statistics where both products expose the same stage;
- keeps PVsyst EArray outside the direct DC acceptance mapping;
- keeps `ILPmxSH` separate from ordinary hourly clipping.

### 2. Detailed CSV targets replace report targets for this oracle revision

For `P39-HR1-PVSYST816-20260923`, reference values come from the detailed CSV.

The older PDF benchmark remains historical evidence but is not mixed with this
simulation snapshot.

### 3. PVsyst loss effects use sequential stage boundaries

The detailed reference follows the actual PVsyst loss sequence:

```text
EArrNom
→ subtract GIncLss
→ subtract TempLss
→ subtract ModQual
→ subtract MisLoss
→ subtract OhmLoss
→ EArrMPP
```

Because PVsyst reports module quality as a negative loss for this PAN, subtracting
`ModQual` correctly creates a positive quality gain.

Inverter attribution keeps:

```text
ordinary conversion  = IL_Oper
ordinary clipping    = IL_Pmax
sub-hourly correction = ILPmxSH
final grid            = E_Grid
```

### 4. ILPmxSH is not folded into ordinary clipping

For VC0:

```text
IL_Pmax   = 0.0000 kWh
ILPmxSH   = 49.3015 kWh
```

OpenSIMPV currently models ordinary hourly clipping but does not model PVsyst's
sub-hourly clipping correction.

Therefore `ILPmxSH` remains:

```text
not_implemented_named_difference
```

The quantity:

```text
E_Grid + ILPmxSH
```

may be shown as an attribution aid, but it is not called an exact counterfactual
rerun because inverter conversion can depend on the displaced DC operating point.

### 5. Interval azimuth semantics are explicit

PVsyst solar azimuth is converted from its east-negative / west-positive
convention into the OpenSIMPV canonical convention:

```text
0° North
90° East
180° South
270° West
```

using:

```text
canonical_azimuth = (-PVsyst_AzSol) mod 360
```

Angular comparison is performed only on irradiated intervals to avoid assigning
meaning to night-time azimuth placeholders.

### 6. Stage-isolation findings

The current evidence isolates each major model before evaluating the chained
result.

#### POA with PVsyst solar geometry injected

```text
OpenSIMPV GlobInc   1757.8413167 kWh/m²
PVsyst GlobInc      1758.0986391 kWh/m²
relative difference   -0.01464%
```

Hourly Perez-1990 transposition is therefore essentially aligned when geometry
is held constant.

#### IAM

```text
OpenSIMPV GlobEff   1749.9012673 kWh/m²
PVsyst GlobEff      1752.0930667 kWh/m²
relative difference   -0.12510%
```

This remains consistent with the named PAN TCubic/diffuse-IAM execution
difference. Exact PVsyst TCubic equivalence is not claimed.

#### Transient thermal

Using PVsyst optical inputs:

```text
mean bias      +0.06281 °C
MAE             0.06292 °C
RMSE            0.08616 °C
max abs         0.61079 °C
```

The current Phase-3.8B thermal implementation is not a material VC0 divergence.

#### Module single-diode model

Using PVsyst `GlobEff` and `TArray`:

```text
OpenSIMPV raw pre-quality  188415.7027 kWh
PVsyst raw pre-quality     188623.1357 kWh
relative difference            -0.10997%
```

The PAN-derived module SDM is closely aligned.

### 7. VC0 frozen-tolerance evidence

With PVsyst solar geometry supplied only as a stage-isolation control, all
frozen Phase-3.9 annual/monthly thresholds pass.

Selected results:

```text
GlobInc relative difference       -0.01464%
GlobEff relative difference       -0.12510%
array nominal relative difference -0.85323%
irradiance effect delta           +0.32744 percentage point
temperature effect delta          +0.24732 percentage point
EArrMPP relative difference       -0.24023%
E_Grid relative difference        -0.21713%
monthly E_Grid RMS relative error  0.21571%
max monthly absolute rel error     0.26728%
PR absolute delta                  0.001763
```

No frozen acceptance metric fails.

Therefore:

```text
first_nonpassing_stage = null
```

### 8. Independent solar-geometry sensitivity envelope

A separate high-accuracy Meeus/NOAA equation mirror was used only as a
sensitivity check because it is not the canonical NREL-SPA implementation.

On irradiated intervals, its geometry differs from the PVsyst oracle by roughly:

```text
GHI-weighted abs elevation difference ≈ 0.0594°
GHI-weighted abs azimuth difference   ≈ 0.1677°
```

The resulting full-chain sensitivity still passes every frozen threshold:

```text
GlobInc difference          -0.07227%
GlobEff difference          -0.18004%
array nominal difference    -0.90778%
EArrMPP difference          -0.29781%
E_Grid difference           -0.27808%
monthly E_Grid RMS error     0.31633%
max monthly relative error   0.60154%
```

This makes the candidate result robust to the observed small solar-geometry
difference, but it is not substituted for the canonical NREL-SPA execution.

## Classification

The VC0 state is:

```text
same-input oracle                       CLOSED
detailed interval attribution tooling   CLOSED
frozen threshold evidence               PASS
first nonpassing stage                  NONE
bit-for-bit parity claim                NOT MADE
exact canonical external-oracle run     PENDING
```

Machine-readable evidence is frozen in:

```text
tests/benchmarks/phase39_vc0_attribution_evidence_20260923.yaml
```

with status:

```text
acceptance_candidate_pass_pending_exact_canonical_spa_execution
```

This wording is deliberate. It records the engineering result without claiming
that the local equation mirror was the repository's exact pvlib execution.

## Consequences

Positive:

- the previously external hourly-data blocker is closed;
- no major defect is visible in Perez, thermal, module SDM, array losses, or
  inverter conversion for VC0;
- every frozen acceptance threshold passes in the current evidence envelope;
- residuals remain decomposed rather than tuned away;
- the exact runner is now available for execution wherever the user-supplied CSV
  and project dependencies coexist.

Remaining work:

1. execute the new detailed-hourly runner with the external VC0 CSV using the
   normal OpenSIMPV dependency environment;
2. if that exact canonical result remains within the already frozen tolerances,
   promote VC0 from `acceptance_candidate_pass` to `pass`;
3. proceed to VC2, then VC4 and VC6, where clipping and ILPmxSH become material;
4. keep minute acceptance separate until the verified PVsyst 8.1 sub-hourly
   Perez production coefficients are available.

## Governing rule

```text
No hidden physics.
No hidden resolution.
No hidden loss.
No silent assumption.
No benchmark-revision mixing.
No annual-output tuning.
No proxy relabelled as canonical execution.
No ILPmxSH hidden inside ordinary clipping.
```
