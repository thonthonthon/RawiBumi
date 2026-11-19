# Decision 0020 — Phase 3.7 uses ordered signed loss channels and explicit interval energy

**Status:** Accepted for Phase 3.7  
**Date:** 2026-09-23

## Context

The Simulation Engine specification requires every material loss to belong to one stage and
one reference basis, and requires monthly/annual energy plus explicit reconciliation.

Phase 3.6 already exposes inverter threshold, conversion, clipping, and self-consumption
channels. The Phase-3 PVsyst reference additionally configures:

```text
module quality loss fraction = -0.75%
module mismatch loss fraction = 2.00%
string mismatch loss fraction = 0 or 0.05%
DC wiring reference loss = 1.50% at STC
per-case global array resistance
```

The PVsyst reports also distinguish `Array virtual energy at MPP`, `EArray`, and grid
energy.

## Decision

### Loss application order

The Phase-3 electrical loss chain is:

```text
raw array MPP
→ module quality
→ module mismatch
→ string mismatch
→ DC wiring
→ array virtual MPP
→ MPPT voltage threshold
→ inverter power threshold
→ inverter conversion
→ inverter clipping
→ inverter self-consumption
→ PCC identity boundary
```

No channel is applied twice.

### Signed module-quality convention

The configuration field remains a signed loss fraction:

```text
positive = loss
negative = gain
```

Therefore `-0.0075` produces a 0.75% gain.

### Aggregate mismatch boundary

Module and string mismatch are currently explicit MPP power-fraction models.

They are sequential:

```text
P_after = P_before × (1 - loss_fraction)
```

They do not claim detailed IV mismatch fidelity.

### DC wiring

The runtime model is:

```text
P_loss = I_array² R_array
ΔV = I_array R_array
```

The per-case PVsyst global array resistance is the runtime parameter.

The 1.50% source field is used only as an STC reference/check. Applying both resistance I²R
and a 1.50% multiplier would double-count the same wiring loss.

The global equivalent-resistance model requires active MPPTs to share a common pre-wire MPP
voltage. Heterogeneous trackers require per-circuit resistance data.

The quality/mismatch MPP factors preserve tracker Vmp and map their power effect onto Imp
before the wiring calculation. Voc and Isc are not redefined by these aggregate MPP
factors.

### Inverter input

The inverter receives the **post-array-loss MPPT state**.

This ensures array quality/mismatch/wiring alter inverter input power and voltage before
efficiency, threshold, and clipping evaluation.

### Loss ledger

Every stage is represented as:

```text
downstream = upstream - signed_loss
```

and has an interval residual.

A negative signed loss is an explicit gain.

The full electrical ledger must reconcile both per interval and annually.

### PCC boundary

For Phase 3.7:

```text
P_PCC = inverter.ac_net_output
```

This is an identity boundary because downstream AC wiring, transformer, availability,
curtailment, and plant auxiliaries have not yet been introduced into the Phase-3 benchmark
runtime.

The metadata explicitly states this limitation.

### Interval energy

Energy integration requires explicit canonical duration:

```text
E_Wh = P_W × Δt_s / 3600
```

Irradiance exposure uses the corresponding:

```text
H_Wh/m² = G_W/m² × Δt_s / 3600
```

Timestamp spacing is not used to infer the final interval duration.

### Monthly and annual aggregation

Monthly energy groups by canonical local interval-start month.

Annual energy is the sum of the interval-integrated series, not a multiplication of average
power by nominal annual hours.

### KPIs

```text
Yf = E_PCC / installed DC kWp
Yr = incident POA kWh/m² / 1 kW/m²
PR = Yf / Yr
```

Incident POA is the PR irradiance basis for the Phase-3 PVsyst comparison.

### PVsyst EArray

OpenSIMPV does not equate `array_virtual_mpp` with PVsyst `EArray`.

PVsyst can alter the DC operating point when inverter limiting binds. Phase 3.6 represents
that loss explicitly as AC clipping without a full DC feedback solve.

Until that operating-point feedback is implemented or independently reconstructed, direct
PVsyst `EArray` mapping remains deferred.

No AC-to-DC back-calculation is introduced merely to force agreement.

## Validation

Phase 3.7 regressions cover:

- signed module-quality gain semantics;
- sequential module and string mismatch;
- exact global (I^2R) loss and voltage drop;
- rejection of heterogeneous tracker voltages for global resistance;
- explicit interval-duration energy integration;
- monthly boundary grouping;
- specific yield/reference yield/PR equations;
- integrated array-loss → inverter → PCC chain;
- interval and annual ledger reconciliation;
- post-array-loss inverter input;
- consistency of all four Phase-3 array resistances with the source 1.50% STC reference.

## Consequences

- array losses now affect inverter operating conditions rather than only reports;
- the electrical chain is auditable from raw array MPP through net AC;
- gains and losses cannot disappear into a generic system-loss factor;
- interval duration semantics are explicit and resolution-independent;
- Phase 3.8 can focus on temporal-resolution execution rather than redefining energy
  integration;
- Phase 3.9 can compare PVsyst totals while keeping the unresolved `EArray`/DC clipping
  feedback boundary visible.
