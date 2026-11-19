# Decision 0019 — Phase 3.6 separates inverter conversion, threshold losses, clipping, and self-consumption

**Status:** Accepted for Phase 3.6  
**Date:** 2026-09-23

## Context

Phase 3.5 produces independent MPPT MPP states.

The Huawei SUN2000-100KTL-M1 reference OND provides:

```text
MPPT window: 200..1000 V
absolute DC voltage: 1100 V
minimum input power: 500 W

PNom AC: 100 kW
PMax AC: 110 kW

efficiency curves:
    200 V
    650 V
    1000 V

night loss: 2 W

temperature power points:
    30 °C → PMax
    40 °C → PNom
    60 °C → 36 kW
    62 °C → absolute limit
```

The same OND does not establish a verified per-MPPT operating-current limit in the current
canonical record.

The Simulation Engine specification requires conversion inefficiency and clipping to remain
separate, with startup thresholds, MPPT voltage windows, and self-consumption explicit.

## Decision

### Runtime model

The detailed model ID is:

```text
inverter.voltage_dependent_efficiency.v0.1
```

and consumes the canonical voltage-dependent Pin/Pout curves selected by the existing
progressive model resolver.

### Efficiency interpolation

The Phase-3.6 execution policy is explicitly versioned:

```text
power:
    bounded linear interpolation of Pin/Pout source points

above highest source Pin:
    hold endpoint efficiency

voltage:
    bounded quadratic interpolation across voltage-anchor curves
```

The Huawei OND source profile class is `TCubicProfile`, but the exact PVsyst internal cubic
algorithm has not been independently frozen. OpenSIMPV therefore does not claim exact PVsyst
curve interpolation in this phase.

Any Phase-3.9 residual attributable to this interpolation policy must be reported rather than
removed by undocumented tuning.

### Multiple MPPTs

The OND efficiency curves describe whole-inverter conversion.

For total accepted DC power `Pdc`, each active tracker voltage is used to evaluate the
whole-inverter transfer curve at `Pdc`.

The resulting voltage-dependent efficiencies are weighted by each tracker's DC-power share.

This prevents applying inverter part-load/fixed-loss behavior independently to each MPPT.

### MPPT voltage threshold

Power at an active tracker whose MPP voltage lies outside its verified MPPT window is removed
before converter efficiency and is reported as:

```text
dc_voltage_threshold_loss_w
```

Active open-circuit voltage above the absolute inverter DC voltage is a blocking invalid
condition.

### MPPT current limit

Current limiting is applied only if a verified physical MPPT operating-current limit exists.

Because Phase 3.5/3.6 retain MPP summary points rather than full string IV curves, a binding
current limit cannot be solved correctly by merely replacing current with `Imax` at the old
Vmp.

Therefore:

```text
verified limit exists and does not bind → simulation proceeds
verified limit binds               → block; full IV solver required
limit unavailable                  → do not fabricate current clipping
```

This is especially relevant to the Huawei reference, whose OND contractual PV-array current
field is explicitly not treated as the physical MPPT operating-current limit.

### Startup / minimum-power threshold

The runtime uses `startup_power_w` when present, otherwise
`minimum_input_power_w`.

Below this threshold:

```text
AC conversion = 0
DC threshold loss = accepted DC power
```

This is separate from conversion inefficiency.

### Conversion and clipping

For accepted DC power:

```text
AC_unclipped = efficiency_model(Pdc, Vdc)
conversion_loss = Pdc - AC_unclipped
```

Then:

```text
AC_available = min(AC_unclipped, AC_power_limit)
clipping_loss = AC_unclipped - AC_available
```

For the Huawei reference without an explicitly resolved inverter-temperature series:

```text
AC_power_limit = 110 kW
```

Nominal 100 kW remains a separate nameplate/rating quantity and is not silently substituted
for the verified 110 kW maximum-power ceiling.

### Temperature derating

Temperature-dependent clipping limits are optional runtime refinement.

They require an explicit runtime temperature basis because the canonical Huawei OND
derating basis is currently `unknown`.

When enabled:

```text
30 °C → 110 kW
40 °C → 100 kW
60 °C → 36 kW
```

with linear interpolation between points.

Above 60 °C but below 62 °C, 36 kW is held because it is the last verified power point.

At or above the 62 °C absolute limit, simulation blocks. The source does not justify
inventing a zero-power point at 62 °C.

### Night and standby consumption

Night and standby consumption are explicit AC-side channels.

```text
ac_net_output
    =
ac_available
- night_consumption
- standby_consumption
```

Negative inverter AC output at night is allowed as a representation of self-consumption.
Grid/PCC import/export semantics are handled later.

## Validation

Phase 3.6 regressions cover:

- exact Huawei 60 kW / 650 V OND transfer-curve point;
- endpoint-efficiency behavior above the highest efficiency-curve power;
- separation of conversion loss and clipping;
- multiple-MPPT efficiency without duplicating inverter fixed losses;
- 500 W startup threshold;
- MPPT voltage-window loss;
- 2 W night consumption;
- unknown-current-limit semantics;
- blocking when a verified current limit would bind;
- explicit temperature-basis requirement;
- 30/40/60 °C power-limit interpolation;
- blocking at the absolute temperature limit;
- blocking above absolute DC voltage;
- explicit interpolation metadata.

## Consequences

- Phase 3 now reaches net inverter AC power;
- conversion inefficiency and clipping are non-overlapping;
- nominal and maximum AC power remain distinct;
- unknown Huawei MPPT current capability is not fabricated;
- temperature derating cannot be applied using an undocumented temperature basis;
- Phase 3.7 can integrate loss channels directly;
- Phase 3.9 can attribute PVsyst disagreement to a specific inverter interpolation or
  operating-rule boundary instead of tuning aggregate annual energy.
