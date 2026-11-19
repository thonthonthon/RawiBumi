# ADR 0023 — Phase 3.8B PVsyst 8.1 transient thermal compatibility

Status: accepted for Phase 3.8B  
Date: 2026-09-23

## Context

PVsyst 8.1.0 changed the simulation temperature model. The previous OpenSIMPV
Phase-3 path used only the steady-state PVsyst heat balance:

```text
TSS = Tamb + alpha * G * (1 - eta) / (Uc + Uv * WS)
```

That model remains physically coherent and useful, but it is no longer the complete
thermal target for a PVsyst 8.1.6 cross-software comparison.

PVsyst 8.1 applies an adaptation of the Prilliman transient thermal model to both
hourly and sub-hourly simulations. Its documentation describes two stages:

```text
external conditions + electrical efficiency
  -> steady-state PV array temperature TArrSS
  -> adapted Prilliman thermal inertia
  -> interval-average PV array temperature TArray
```

The second temperature is the operating temperature used by the module electrical
model.

## Decision

### 1. Preserve the existing steady-state model

The existing model ID remains:

```text
thermal.pvsyst.pvlib.v0.1
```

Its numerical behavior is not silently changed. Existing OpenSIMPV simulations can
therefore remain reproducible.

### 2. Add a separate PVsyst 8.1 compatibility model

The new model ID is:

```text
thermal.pvsyst81.prilliman_adapted.v0.1
```

It first executes the existing steady-state model and retains that result explicitly
as the `TArrSS`-equivalent state.

It then applies the documented PVsyst 8.1 relaxation-rate equation:

```text
P = 0.0046 + 0.00046*WS - 0.00023*mu - 0.000016*WS*mu
```

where:

- `P` is in 1/s;
- `WS` is weather wind speed in m/s;
- `mu` is module unit mass in kg/m².

### 3. Resolve module unit mass canonically

The preferred runtime source is:

```text
ModuleDefinition.mechanical.mass_kg
/
(ModuleDefinition.mechanical.width_m * ModuleDefinition.mechanical.height_m)
```

The area is one-sided module area.

For the Jinko reference fixture:

```text
mass = 28.0 kg
area = 1.134 * 2.278 = 2.583252 m²
unit mass = 10.839050932700333 kg/m²
```

The PVsyst documented fallback is reproduced:

```text
missing mass             -> 11.0 kg/m²
unit mass >= 20 kg/m²    -> 11.0 kg/m²
```

The selected mass source is recorded in thermal metadata.

### 4. Wind is required independently of Uv

The steady-state model needs wind only when `Uv != 0`.

The transient model is different: wind also appears in the Prilliman relaxation
rate. Therefore `thermal.pvsyst81.prilliman_adapted.v0.1` requires a complete
weather wind-speed series even when `Uv = 0`.

The engine shall fail explicitly rather than silently assuming zero wind.

### 5. History cutoff

The documented maximum relaxation time is:

```text
tau_max = 1 / (0.0046 - 0.00023*mu)
```

and the history cutoff is:

```text
cutoff = 3 * tau_max
```

Older steady-state samples outside the cutoff do not contribute to the Prilliman
weighted history.

### 6. Interval-average temperature

PVsyst simulations operate on interval-average states rather than reporting only an
instantaneous end-of-step temperature.

OpenSIMPV analytically integrates the exponential transition over each interval:

```text
T(t) = T0 + (T1 - T0) * (1 - exp(-P*t))

Tavg =
T0 + (T1 - T0) *
[1 - (1 - exp(-P*dt)) / (P*dt)]
```

The formula above is the exact analytical integral of the exponential transition
shown as Eq. (3) in the current PVsyst documentation. The expression currently
rendered as Eq. (4) on the PVsyst help page is algebraically inconsistent with
Eq. (3) when interpreted literally. OpenSIMPV therefore uses the analytical
integral of Eq. (3), records this basis in model metadata, and leaves literal
PVsyst 8.1.6 numerical equivalence to Phase 3.9 rather than silently adopting an
internally inconsistent printed expression.

The interval-average `Tavg` is exposed as:

```text
cell_temperature_c
module_temperature_c
```

and is supplied to the single-diode electrical model.

The underlying steady-state values remain available as:

```text
steady_state_cell_temperature_c
steady_state_module_temperature_c
```

### 7. Thermal inertia remains inside the electrical-efficiency fixed point

The correct integrated chain is:

```text
eta guess
  -> steady-state heat balance
  -> transient thermal inertia
  -> interval-average module temperature
  -> PVsyst single-diode model
  -> operating efficiency
  -> repeat
```

The transient model is not an output-only smoothing pass.

### 8. Hourly cutoff edge is explicit, not hidden

For ordinary module unit mass, `3*tau_max` may be shorter than one hour. PVsyst
8.1 nevertheless applies its transient model to hourly simulations, and PVsyst
8.1.1 removed an obsolete error associated with a cutoff shorter than the time
step.

The public documentation does not fully expose the internal sample-selection rule
for this boundary case.

OpenSIMPV therefore uses the following versioned compatibility policy:

```text
if cutoff < one simulation interval:
    retain the immediately preceding steady-state sample
```

This prevents the hourly transient model from degenerating into an undefined empty
history. The policy is recorded in metadata as:

```text
always_include_immediate_previous_steady_state_sample
```

This is an inference needed to construct a runnable compatibility model. It is
**not** presented as independently verified PVsyst internals and must be tested in
Phase 3.9.

### 9. Initialization is explicit

At the first available interval, the Prilliman boundary state is initialized from
the first steady-state temperature.

This choice is recorded as:

```text
initialization_policy = first_steady_state_boundary
```

Any material warm-up/first-interval sensitivity found in Phase 3.9 shall be
attributed rather than hidden by annual-only tuning.

## Sources

Primary documentation used for the compatibility contract:

- PVsyst documentation, "Transient Thermal Model".
- PVsyst documentation, "Steady state thermal model".
- PVsyst 8.1 release notes: 8.1.0 introduction of transient thermal modeling for
  hourly and sub-hourly simulations.
- PVsyst 8.1.1 release note removing the obsolete
  "Cutoff Time is <= than the time step duration" error.
- PVsyst 8.1.4 release note for the large-module-mass thermal correction.

The implementation does not depend on a reverse-engineered PVsyst binary.

## Consequences

Positive:

- PVsyst 8.1.6 comparison no longer contains the known steady-state-versus-transient
  model mismatch;
- hourly and sub-hourly simulations use the same named transient model;
- component mass already imported from PAN becomes simulation-relevant;
- `TArrSS`-equivalent and transient temperatures remain simultaneously auditable;
- the model is inside the existing electrical/thermal fixed point;
- legacy steady-state OpenSIMPV runs remain reproducible.

Limitations:

- the currently rendered PVsyst Eq. (4) is algebraically inconsistent with its
  documented exponential transition Eq. (3); OpenSIMPV uses the exact integral
  of Eq. (3) and leaves numerical parity to Phase 3.9;
- exact PVsyst internal handling when the history cutoff is shorter than one time
  step is not publicly specified;
- exact PVsyst first-record initialization is not independently established;
- Phase 3.8B does not address PVsyst 8.1 sub-hourly Perez coefficients;
- agreement with PVsyst 8.1.6 must still be measured stage-by-stage in Phase 3.9.

## Regression requirements

The Phase 3.8B gate requires tests proving:

1. the documented relaxation-rate equation is reproduced;
2. wind changes the relaxation rate independently of `Uv`;
3. missing wind blocks the transient model;
4. missing or invalid module unit mass uses the 11 kg/m² PVsyst fallback;
5. a one-minute steady-state temperature step is delayed and smoothed;
6. the hourly cutoff-under-timestep path remains defined and its policy is recorded;
7. steady-state temperatures remain visible alongside transient temperatures;
8. the transient temperature participates in the module electrical-efficiency fixed point;
9. the Jinko PAN fixture yields approximately 10.83905 kg/m² unit mass;
10. the existing steady-state thermal model remains available under its original ID.
