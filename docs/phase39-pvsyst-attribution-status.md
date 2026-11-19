# Phase 3.9 — PVsyst 8.1.6 attribution status

Snapshot: 2026-09-23

## Status

```text
attribution framework          READY
reference reports              VERIFIED
hourly acceptance              BLOCKED — exact PVsyst/Meteonorm 9 interval weather missing
minute acceptance              BLOCKED — exact weather + verified PVsyst 8.1 Perez table missing
interval RMSE/MAE attribution  BLOCKED — detailed PVsyst timestep result export missing
```

This is an external oracle/data boundary, not an instruction to substitute a
different weather family or tune OpenSIMPV to annual PVsyst energy.

## What is already frozen

The campaign is defined in:

```text
tests/benchmarks/phase39_pvsyst_v816_attribution.yaml
```

and covers PVsyst 8.1.6 cases VC0..VC7.

The supplied report pages containing monthly/annual balances and loss diagrams
were re-checked when Phase 3.9 was created.

The comparison order is:

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

Acceptance tolerances are frozen before same-input OpenSIMPV results are
available. A later change to them requires an explicit reviewed decision.

## Required hourly oracle

To make VC0/VC2/VC4/VC6 admissible acceptance cases, obtain the exact interval
weather used by the PVsyst simulations.

Minimum required hourly weather inputs:

```text
timestamp / simulation interval
GlobHor
DiffHor
T_Amb
WindVel
```

Where the PVsyst output facility can expose the direct/beam component used by
the simulation, include it as well.

The export must retain:

```text
PVsyst project/variant identity
simulation timestep
timezone/time convention
calendar/year
site coordinates
weather source identity
```

Do not substitute the standalone Meteonorm 8.2 Home DAT files. They are a
different controlled benchmark family.

## Recommended detailed PVsyst output export

PVsyst's detailed output-file facility should be configured before simulation
and exported at the simulation timestep.

For the first attribution case, VC0, request as many of the following
PVsyst-native variables as the available output list exposes:

### Weather and geometry

```text
GlobHor
DiffHor
T_Amb
WindVel
HSol
AzSol
AngInc
```

### Irradiance / optical chain

```text
GlobInc
GlobEff
```

### Thermal / array state

```text
TArray
UArray / Uarray
IArray / Iarray
PArray where exposed
EArrMPP / corresponding interval quantity where exposed
EArray
```

### Inverter / grid

```text
inverter input/output power or energy
inverter efficiency/conversion-loss channel
over-power/clipping-loss channel
input-current-limit channel
voltage-limit channels
threshold channels
night consumption
E_Grid
```

PVsyst variable labels can differ by output context/version. Preserve the
native column names in the source export and map them semantically afterward.

## Recommended acquisition sequence

Start with:

```text
VC0 — hourly, DC/AC 1.19
```

Why VC0 first:

- hourly Perez compatibility is executable;
- clipping is reported as zero;
- the electrical chain is therefore simpler to attribute;
- it isolates weather → POA → IAM → thermal → module → ordinary inverter
  conversion before testing clipping feedback.

After VC0:

```text
VC2 → VC4 → VC6
```

This increases DC/AC loading and therefore clipping progressively.

Only after the hourly path is attributed should the minute sequence be treated
as an acceptance campaign:

```text
VC1 → VC3 → VC5 → VC7
```

because exact minute transposition still has the separate PVsyst 8.1 production
Perez coefficient dependency.

## Current minute blocker

Phase 3.8C established a timestep-specific 8×6 Perez coefficient contract.

OpenSIMPV will not silently substitute:

- hourly Perez-1990;
- Perez-Driesse;
- the earlier EUPVSEC prototype one-minute table;
- coefficients interpolated from another timestep.

Therefore a minute run may be useful diagnostically, but it remains
`not_admissible` as exact PVsyst 8.1.6 transposition evidence until a verified
production coefficient table is available.

## EArrMPP versus EArray

These are deliberately not treated as the same quantity.

Current acceptance mapping:

```text
PVsyst EArrMPP  ↔ OpenSIMPV array_virtual_mpp
PVsyst E_Grid   ↔ OpenSIMPV PCC/grid energy
```

Current non-mapping:

```text
PVsyst EArray   ↔ no exact current OpenSIMPV equivalent
```

Reason: PVsyst EArray includes inverter operating-point displacement. The
current OpenSIMPV inverter chain does not back-propagate inverter limiting into
a synthetic DC operating point.

The report-derived displacement reference:

```text
EArrMPP - EArray
```

is retained for attribution, but OpenSIMPV does not manufacture this loss by
back-converting AC clipping.

## Acceptance interpretation

A result may be:

```text
pass
fail
not_admissible
not_executed
```

`not_admissible` is materially different from `fail`.

For example, an OpenSIMPV simulation using Meteonorm 8.2 could numerically
match PVsyst annual E_Grid by coincidence. It would still be
`not_admissible` because the input weather is not the same source series.

Likewise, a minute run without verified PVsyst 8.1 production Perez
coefficients cannot establish exact transposition parity even if annual energy
matches.

## Relevant decision

See:

```text
docs/decisions/0027-phase39-pvsyst-v816-attribution.md
```


## 2026-09-23 detailed hourly oracle update

Four PVsyst 8.1.6 detailed hourly outputs are now available externally for
VC0/VC2/VC4/VC6 and are fingerprinted by
`tests/benchmarks/phase39_hourly_detailed_oracle_20260923.yaml`.

This closes the previous **hourly same-input weather availability** blocker when
the external CSV is supplied to a validation run.

The files expose 8760 hourly intervals and identify
`Home_MN90_SYN_1MIN.MET` as the upstream Meteonorm-9 one-minute weather file.
PVsyst's documented time convention (interval-start label, interval-midpoint
solar geometry) matches the OpenSIMPV canonical time contract.

A new explicit difference is now visible: hourly PVsyst runs from this
sub-hourly MET apply `ILPmxSH`, the sub-hourly clipping correction. OpenSIMPV
does not yet model that correction. The detailed oracle therefore separates:

```text
ordinary hourly clipping      IL_Pmax
sub-hourly clipping correction ILPmxSH
```

rather than combining them.

The detailed CSVs are later simulation snapshots than the earlier PDFs and have
different POA/DC/grid totals. They form a new oracle revision
`P39-HR1-PVSYST816-20260923`; report and CSV metrics must not be mixed.


## VC0 detailed attribution candidate

The detailed VC0 oracle has now been processed through stage-isolation and the
frozen Phase-3.9 tolerance policy.

Current classification:

```text
VC0 same-input detailed oracle            available
VC0 detailed attribution runner           implemented
VC0 frozen-tolerance evidence             pass
VC0 first nonpassing stage                none
VC0 exact canonical NREL-SPA execution    pending external-oracle runtime
```

The evidence is deliberately labelled
`acceptance_candidate_pass_pending_exact_canonical_spa_execution`, because the
local analysis environment used for the evidence envelope did not contain
pvlib. A high-accuracy independent solar-geometry proxy and a PVsyst-geometry
stage-isolation run both remain within every frozen tolerance, but neither is
mislabelled as the exact canonical NREL-SPA execution.

The largest current stage signatures remain within acceptance:

```text
array nominal energy    -0.8532%
irradiance effect       +0.3274 percentage point
temperature effect      +0.2473 percentage point
EArrMPP                 -0.2402%
E_Grid                  -0.2171%
monthly E_Grid RMS       0.2157%
```

PVsyst `ILPmxSH = 49.3015 kWh` remains an explicit named difference, separate
from VC0 ordinary hourly clipping `IL_Pmax = 0`.

See:

- `docs/decisions/0029-phase39h-vc0-detailed-attribution.md`
- `tests/benchmarks/phase39_vc0_attribution_evidence_20260923.yaml`
- `validation/attribution/pvsyst_detailed.py`


## VC2 detailed attribution candidate

VC2 now passes every frozen Phase-3.9 acceptance metric, but its final-grid
agreement is explicitly classified as cancellation-sensitive.

```text
VC2 frozen-tolerance evidence             pass
VC2 first nonpassing stage                none
VC2 grid cancellation                     detected
VC2 ILPmxSH                               536.7011 kWh
VC2 exact canonical NREL-SPA execution    pending external-oracle runtime
```

Direct E_Grid relative error is only +0.04696%, but the decomposition contains
a -511.49 kWh EArrMPP residual opposed by the absent +536.70 kWh PVsyst
sub-hourly clipping correction plus a +73.90 kWh ordinary-clipping contribution.

Therefore final-energy agreement is not presented as stage-level parity.

The detailed attribution report now includes a general
`grid_residual_decomposition` object and a cancellation ratio.

See:

- `docs/decisions/0030-phase39h-vc2-clipping-and-grid-cancellation.md`
- `tests/benchmarks/phase39_vc2_attribution_evidence_20260923.yaml`


## VC4 detailed attribution candidate

VC4 remains inside every frozen Phase-3.9 tolerance while materially activating
both clipping-resolution and DC-feedback boundaries.

```text
VC4 frozen-tolerance evidence             pass
VC4 first nonpassing stage                none
VC4 IL_Pmax                               3898.8000 kWh
VC4 ILPmxSH                               2013.2653 kWh
VC4 EArrMPP-EArray displacement           5911.9480 kWh
VC4 exact canonical NREL-SPA execution    pending external-oracle runtime
```

The raw candidate E_Grid residual is +0.8361%. Removing source ILPmxSH only as
an attribution aid reduces the annual residual to about -0.0151%, with monthly
sensitivity RMS about 0.0999%.

The PVsyst displacement identity is now especially informative:

```text
EArrMPP - EArray       5911.9480 kWh
IL_Pmax + ILPmxSH      5912.0653 kWh
difference               -0.1173 kWh
```

This confirms that the EArray/DC-feedback boundary is a real physical/accounting
difference at high loading, not a negligible naming issue.

See:

- `docs/decisions/0031-phase39h-vc4-strong-clipping-attribution.md`
- `tests/benchmarks/phase39_vc4_attribution_evidence_20260923.yaml`

## VC6 detailed attribution candidate and hourly ladder closure

VC6 completes the controlled hourly loading ladder and remains inside every frozen Phase-3.9H tolerance.

- VC6 frozen-tolerance evidence: pass
- VC6 first nonpassing stage: none
- VC6 ordinary clipping delta: +0.3994 percentage point
- VC6 clipping gate: ±0.5000 percentage point
- VC6 IL_Pmax: 13261.5364 kWh
- VC6 ILPmxSH: 3824.6276 kWh
- VC6 EArrMPP-EArray displacement: 17086.2240 kWh
- VC6 exact canonical NREL-SPA execution: pending external-oracle runtime

Source ILPmxSH is again the largest individual grid-side missing-model contribution. Subtracting it only as an attribution aid reduces the annual grid residual from +1.598% to +0.103%.

The high-loading displacement identity remains nearly exact:

EArrMPP - EArray = 17086.2240 kWh
IL_Pmax + ILPmxSH = 17086.1640 kWh
difference = 0.0600 kWh

The complete hourly candidate ladder is now:

- VC0 ~1.19 DC/AC: PASS
- VC2 ~1.39 DC/AC: PASS
- VC4 ~1.58 DC/AC: PASS
- VC6 ~1.78 DC/AC: PASS

No frozen case has a first nonpassing stage. The campaign remains qualified as acceptance-candidate evidence until the external CSVs are executed through the repository's exact NREL-SPA runtime.

See:

- docs/decisions/0032-phase39h-vc6-hourly-stress-and-ladder-closure.md
- tests/benchmarks/phase39_vc6_attribution_evidence_20260923.yaml
