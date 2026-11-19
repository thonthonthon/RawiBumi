# PV module thermal modeling


RawiBumi keeps the steady-state PVsyst heat balance and the PVsyst 8.1
transient-temperature compatibility path as separate named models.


## Steady-state model


```text
thermal.pvsyst.pvlib.v0.1
```


uses `pvlib.temperature.pvsyst_cell`:


```text
TSS = Ta + alpha * G * (1 - eta_m) / (Uc + Uv * WS)
```


where:


- `G` is incident POA global before IAM;
- `alpha` is module absorptance;
- `eta_m` is external module efficiency;
- `Uc` and `Uv` are the thermal loss coefficients;
- `WS` is wind speed.


The module-efficiency term can be a scalar or interval series. In the integrated
runner it is solved together with the detailed electrical model rather than being
frozen at STC efficiency.


## PVsyst 8.1 transient compatibility model


```text
thermal.pvsyst81.prilliman_adapted.v0.1
```


first computes the same steady-state temperature and then applies the documented
PVsyst 8.1 adaptation of the Prilliman thermal-inertia model.


For each interval, the relaxation rate is:


```text
P = 0.0046 + 0.00046*WS - 0.00023*mu - 0.000016*WS*mu  [1/s]
```


where `mu` is module unit mass in kg/m². The normal source is:


```text
module mechanical mass / one-sided module area
```


PVsyst's documented fallback is reproduced:


- missing mass -> 11.0 kg/m²;
- unit mass >= 20 kg/m² -> 11.0 kg/m².


The history cutoff is:


```text
tau_max = 1 / (0.0046 - 0.00023*mu)
cutoff  = 3 * tau_max
```


The model forms exponentially weighted Prilliman boundary temperatures from
previous steady-state temperatures. RawiBumi then analytically averages the
documented exponential transition over the simulation interval:


```text
Tavg = T0 + (T1 - T0) *
       [1 - (1 - exp(-P*dt)) / (P*dt)]
```


This expression is the exact analytical integral of the exponential transition
shown as Eq. (3) in the current PVsyst documentation. The Eq. (4) expression
currently rendered on the PVsyst help page is algebraically inconsistent with
Eq. (3) when read literally. RawiBumi therefore does not encode the rendered
Eq. (4) verbatim; the discrepancy is retained as an explicit Phase 3.9
compatibility check rather than resolved silently.




`Tavg` is the temperature supplied to the electrical model. The corresponding
steady-state temperature is retained in the result as
`steady_state_cell_temperature_c` for attribution and diagnostics.


### Wind semantics


The transient model requires a complete wind-speed series even when `Uv = 0`.
That is not contradictory: `Uv` controls steady-state convective loss, while
wind also appears independently in the PVsyst 8.1 thermal-inertia relaxation rate.


### Hourly cutoff edge


For a typical module, `3*tau_max` can be shorter than a 60-minute simulation
step. PVsyst 8.1 nevertheless applies the transient model to hourly simulations.
RawiBumi therefore always retains the immediately preceding steady-state sample
when the cutoff would otherwise contain no history.


This is an explicit compatibility policy, not a claim that PVsyst's internal edge
handling has been reverse-engineered. Phase 3.9 must attribute/verify this detail
against PVsyst 8.1.6.


### Initialization


The first transient boundary is initialized from the first available steady-state
temperature. Initialization is recorded in result metadata and remains visible to
the validation campaign.


Both thermal models expose named model IDs and diagnostics. The steady-state path
is retained as a valid RawiBumi model rather than silently changing historical
simulation semantics.