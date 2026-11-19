# Decision 0001 — Keep module PNom separate from Pmpp

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-22

## Decision

OpenSIMPV stores module commercial/nameplate nominal power separately from the actual or
modeled maximum-power-point power at reference conditions.

Canonical STC fields therefore include:

- `nominal_power_w` — commercial/nameplate rating;
- `vmp_v` and `imp_a` — manufacturer reference MPP coordinates;
- `pmp_w` — actual/model/reference maximum-power value used by the selected canonical model.

A PAN `PNom` field maps to `stc.nominal_power_w`, **not** directly to
`stc.pmp_w`.

## Reason

PVsyst explicitly distinguishes the module nameplate `Pnom` from the product
`Impp × Vmpp` and from the modeled P-V maximum. Treating these as one field would lose
engineering meaning and can affect installed-power and performance-ratio semantics.

Reference:
https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/pv-modules-basic-data/pnom-and-pmppstc-definitions.html

## Consequences

- PAN import preserves `PNom` as nominal power.
- A later component builder may calculate or validate `pmp_w` using the selected electrical
  model and the supplied reference points, but that calculation must be explicit.
- Validation should compare `nominal_power_w`, `vmp_v × imp_a`, and modeled Pmpp rather
  than assuming equality.
