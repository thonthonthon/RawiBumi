# Detailed PV module electrical runtime

Phase 3.4 connects the validated canonical PVsyst single-diode parameter set to the
time-series simulation engine.

Current detailed model:

```text
module.pvsyst_singlediode.v6
```

The runtime shares the same PVsyst-v6 diode-parameter mapping used by PAN/component
validation. Runtime execution therefore cannot silently reinterpret validated PAN fields.

Inputs per interval:

```text
effective irradiance [W/m²]
cell temperature [°C]
validated PVsyst parameter set
module area [m²]
```

Outputs per module:

```text
Isc
Voc
Imp
Vmp
Pmp
external module efficiency
efficiency on effective-irradiance basis
active/inactive state
Pmp = Vmp × Imp reconciliation residual
```

The electrical model is driven by **effective irradiance after IAM**.

The external efficiency needed by the PVsyst thermal equation is defined separately on the
incident-POA basis:

```text
eta_m = Pmp / (POA_incident × module_area)
```

This distinction is deliberate. The optical engine may reduce effective irradiance below
incident POA, while the thermal balance still uses incident POA together with module
absorption.

Intervals below the explicit active-irradiance threshold return a zero IV/power state rather
than asking the diode solver to interpret darkness.

## Thermal/electrical coupling

The PVsyst heat balance contains `eta_m`, but `eta_m` itself depends on module
temperature. Phase 3.4 therefore provides a deterministic fixed-point solver.

For the original steady-state thermal path:

```text
initial eta
    ↓
steady-state thermal model → TSS
    ↓
single-diode model → Pmp
    ↓
eta = Pmp / (POA_incident × area)
    ↓
repeat until TSS and eta converge
```

Phase 3.8B extends the same coupling boundary for the PVsyst 8.1 compatibility
model:

```text
initial eta
    ↓
steady-state thermal model → TSS
    ↓
PVsyst 8.1 adapted Prilliman inertia → TArray(interval average)
    ↓
single-diode model at TArray → Pmp
    ↓
eta = Pmp / (POA_incident × area)
    ↓
repeat until TArray and eta converge
```

The transient model therefore does not post-process electrical results after the
fact. Thermal inertia is inside the temperature/efficiency fixed point, and the
electrical model sees the transient interval-average temperature. The underlying
steady-state temperature remains available for diagnostics.

The starting efficiency is only a numerical initial state. It is not retained as a physical
assumption.

The solver records:

- convergence tolerances;
- maximum iteration count;
- relaxation factor;
- iterations used;
- final temperature residual;
- final efficiency residual;
- selected thermal and electrical model IDs;
- transient/base steady-state model identity when applicable;
- module unit mass and its source when applicable.

A non-converged result is an error; the engine does not silently accept the last iterate.

## Component model trust

`extract_validated_pvsyst_parameter_set()` only returns a detailed model whose component
validation has passed. A caller may still provide a raw complete parameter dictionary
directly for diagnostics/tests, but normal simulation orchestration should consume the
validated component model selected by the existing resolver.

String, MPPT, mismatch, wiring, inverter, and clipping behavior remain outside this layer.
