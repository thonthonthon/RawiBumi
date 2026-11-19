# Inverter conversion and clipping


Phase 3.6 activates the detailed runtime model:


```text
inverter.voltage_dependent_efficiency.v0.1
```


for canonical inverter definitions with voltage-dependent DC-input/AC-output curves.


The runtime chain is:


```text
MPPT MPP states
    ↓
MPPT voltage-window acceptance
    ↓
startup / minimum-input threshold
    ↓
voltage-dependent conversion efficiency
    ↓
temperature-resolved AC power ceiling when explicitly configured
    ↓
AC clipping
    ↓
night / standby self-consumption
```


## Efficiency interpolation


The canonical OND representation stores multiple Pin/Pout curves at DC-voltage anchors.


Phase 3.6 uses a versioned and bounded execution policy:


```text
power interpolation:
    bounded_linear_pin_pout_v0.1


power above highest curve point:
    hold_endpoint_efficiency


voltage interpolation:
    bounded_quadratic_v0.1
```


The source Huawei OND uses `TCubicProfile`. The exact proprietary/interior PVsyst cubic
algorithm is not independently frozen in RawiBumi yet. The runtime therefore does not claim
bit-identical interpolation. This difference remains visible for Phase-3.9 attribution
instead of being silently tuned.


For multiple independent MPPTs, the efficiency curves are treated as whole-inverter transfer
curves. RawiBumi evaluates inverter-wide efficiency at total accepted DC power for each
tracker voltage, then power-weights those voltage-dependent efficiencies by tracker DC share.
It does not apply inverter fixed/part-load losses once per MPPT.


## Voltage limits


Each tracker is checked against its canonical MPPT operating window.


Power outside the MPPT voltage window is retained as:


```text
dc_voltage_threshold_loss_w
```


and does not reach the converter.


If active-string/MPPT open-circuit voltage exceeds the inverter absolute DC voltage limit,
simulation is blocked as a physically invalid configuration.


## Current limits


A current limit is used only when an independently verified canonical MPPT operating-current
limit exists.


Phase 3.6 has only MPP summary points, not full string IV curves. Therefore if a verified
current limit would bind, simulation stops and requires a future full-IV operating-point
solver. RawiBumi does not approximate the shifted operating point by simply clipping
current at Vmp.


For the Huawei Phase-3 reference, the per-MPPT operating-current limit remains unknown, so
no current clipping is fabricated from the OND contractual array-current field.


## Startup threshold


The runtime uses explicit `startup_power_w` when available, otherwise
`minimum_input_power_w`.


DC power below the threshold is reported separately as:


```text
dc_power_threshold_loss_w
```


rather than conversion inefficiency.


## AC power limit and clipping


The base power ceiling is:


```text
max_ac_power_w
```


when available, otherwise nominal AC power.


Conversion and clipping remain separate:


```text
conversion loss
    = DC to converter - unclipped AC


clipping loss
    = unclipped AC - allowed AC output
```


For the Huawei reference:


```text
PNom = 100 kW
PMax = 110 kW
```


so the default clipping ceiling is 110 kW when no resolved inverter-temperature series is
supplied.


## Temperature-dependent power limit


Temperature derating is applied only when the runtime temperature basis is explicitly
resolved.


The Huawei breakpoints are preserved as:


```text
30 °C → 110 kW
40 °C → 100 kW
60 °C →  36 kW
62 °C → absolute temperature limit
```


Between verified power points, RawiBumi uses linear interpolation.


Above the last verified power point but below the absolute temperature limit, the last
verified power limit is held. At or beyond the absolute limit, Phase 3.6 blocks because the
source does not define a verified post-limit power curve. It does not invent a zero-power
endpoint.


## Self-consumption


Night and standby consumption are explicit power channels.


The runtime exposes both:


```text
ac_available_w
ac_net_output_w
```


where `ac_net_output_w` may be negative at night because the inverter can consume power.
Grid/PCC treatment remains a later AC-stage responsibility.


## Outputs


The result preserves:


```text
DC MPP available
DC accepted by MPPT voltage window
voltage-threshold loss
power-threshold loss
DC to converter
conversion efficiency
conversion loss
unclipped AC
AC power limit
clipping loss
AC available
night consumption
standby consumption
net inverter AC output
converter-active flag
clipping flag
```


These channels are intentionally separate so Phase 3.7 can integrate and reconcile them
without reverse-engineering aggregate losses.

INV1 adds the explicitly selected `inverter.voltage_dependent_efficiency.v0.2`
model with policy `adjacent_envelope_clamped_quadratic_v0.2`. It evaluates the
existing nearest-three Lagrange polynomial, then bounds each voltage result to
its two adjacent anchor outputs. A composite convex-envelope guard removes
floating-point overshoot after MPPT power weighting. The Pin/Pout interpolation,
two-anchor branch, voltage endpoint clamp, pooling, thresholds, clipping and
night consumption are unchanged. Four-plus-anchor nearest-three stencil switches
retain their legacy discontinuity; OND imports provide exactly three anchors.

Direct calls and automatic engine resolution retain v0.1 by default. Browser
configurations explicitly select v0.2 for the next run. The new run and
reproducibility manifest identify the selected model and voltage policy; legacy
payloads gain no fields. Imported definitions and old run snapshots stay pinned.
PVsyst documents quadratic interpolation across three voltage curves; the
adjacent-envelope bound is a RawiBumi policy and does not claim reference-tool
numerical parity.
