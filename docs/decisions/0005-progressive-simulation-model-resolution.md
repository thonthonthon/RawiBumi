# Decision 0005 — Resolve the highest justified simulation model explicitly

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Decision

Before numerical simulation, OpenSIMPV shall resolve canonical component data into explicit
named simulation-model contracts.

Automatic resolution selects the highest-fidelity registered model whose required data and
validation evidence are present.

Optional refinement data are resolved independently.

## Rules

1. External file completeness does not define simulation capability.
2. Missing optional refinement data must not block unrelated lower-fidelity calculation.
3. Missing data must not be fabricated to make a higher-fidelity model appear available.
4. Explicit user/model requirements must not be silently relaxed.
5. Every fallback, missing refinement, unsupported model, and blocking condition must be
   serialized in an assumption/limitation ledger.
6. Simulation runs must retain the resolved component revision and selected model ID.
7. A component model may be preserved in canonical data before OpenSIMPV has an executable
   contract for it; preservation is not the same as implementation support.

## Initial model ordering

Module:

```text
validated PVsyst single diode
    >
explicit STC + temperature-coefficient fallback
```

Inverter:

```text
voltage-dependent efficiency curves
    >
one-dimensional efficiency curve
    >
explicit constant efficiency
```

This ordering may grow through versioned registry entries. Adding a new model must not change
historical simulation meaning without a new model/version identifier.

## Refinement examples

The following are independent of the primary inverter conversion-model selection:

- physical MPPT current limiting;
- temperature-dependent power derating;
- night self-consumption;
- startup threshold.

Therefore a missing physical MPPT current limit may prevent current-clipping analysis while
still permitting voltage/efficiency-based energy conversion.

## Consequences

- Phase-3 simulation code consumes resolved model contracts rather than directly guessing
  from arbitrary component fields.
- Reports can state exactly what was and was not modeled.
- A richer manufacturer/user/open source can improve a component without invalidating a
  lower-fidelity simulation path.
- PAN/OND remain useful adapters without becoming the ceiling of OpenSIMPV physics.
