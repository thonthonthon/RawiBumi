# ADR 0059 — Phase-6.4 Level-1 Module-Equivalent Electrical State

**Status:** Accepted  
**Date:** 27 September 2026

## Context

Phase 6.3 provides spatially resolved local irradiance while deliberately stopping
before electrical interaction. The next fidelity step must exercise the new
geometry-to-electrical vertical path without prematurely introducing substring,
bypass, nonuniform module-IV, string-IV, or MPPT physics.

The Phase-6.1 fidelity contract also requires Level 1 to remain usable without an
internal `ModuleTopologyDefinition` when a validated whole-module electrical model
exists.

## Decision

1. Level 1 means one validated whole-module electrical state per module per interval.
2. The canonical Level-1 route is topology-independent and consumes one exact
   module-plane geometry-only `ShadingResult`.
3. The irradiance collapse is explicit: channel-specific unshaded POA is multiplied
   by geometric visibility, then by explicit optical modifiers, then summed into one
   module-equivalent effective irradiance.
4. Level-1 execution requires trusted `ResolvedComponentModel` evidence selecting the
   exact validated `module.pvsyst_singlediode.v6` model for the exact module revision.
   Raw capability booleans are not execution authority.
5. Existing whole-module SDM code is reused; Phase 6.4 does not create another module
   electrical model.
6. An existing Phase-6.3 regional state may be collapsed to Level 1 only when its
   `ElectricalRegionMap` covers the complete module receiver. The collapse is weighted
   by physical region area. Missing area fails closed rather than being silently
   renormalized away.
7. Use of the regional adapter does not make topology a Level-1 prerequisite.
8. Level-1 internal nonuniformity scope is `collapsed_uniform_equivalent`; bypass is
   `not_modeled`.
9. Geometric irradiance remains upstream and is not re-booked as electrical mismatch.
   Electrical mismatch, bypass interaction and MPPT operating-point attribution remain
   explicitly `not_modeled` at Level 1.
10. Level-1 outputs carry deterministic scientific and physical identities so the same
    scientific inputs reproduce the same result independent of execution plumbing.
11. The project API may expose a non-persisted diagnostic Level-1 module snapshot, but
    that endpoint does not become Scene or ElectricalDesign authority.

## Consequences

- Level 1 can remove project/execution-group homogenization at the module-state level
  without overstating partial-shading fidelity.
- Modules with validated whole-module SDM data remain useful even when no detailed
  topology exists.
- Phase-6.3 regional work can feed Level 1 when complete, but cannot silently bias a
  result through partial-area averaging.
- Loss accounting remains compatible with the later Level-2/3 counterfactual ledger.
- The first true internal electrical interaction remains Phase 6.5, where substring IV
  and bypass-device behavior will be solved explicitly.
