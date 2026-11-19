# Decision 0003 — Do not treat OND IMaxDC as physical MPPT operating current

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Decision

OND `IMaxDC` is not automatically mapped to
`mppt_template.max_operating_current_a`.

OpenSIMPV currently stores a positive `IMaxDC` only as a PV-array sizing/current constraint
under `array_sizing_limits.max_pv_current_a`.

## Evidence

The manufacturer-supplied Huawei SUN2000-100KTL-M1 OND contains:

```text
IDCMax=0.0
IMaxDC=40.0
NbMPPT=10
```

Huawei's own datasheet separately specifies:

```text
Max. Current per MPPT = 26 A
Max. Short Circuit Current per MPPT = 40 A
```

Therefore treating `IMaxDC=40 A` as the physical 26 A operating-current limit would be
demonstrably wrong for this fixture.

PVsyst documentation also separates contractual PV-array current constraints from physical
MPPT current limiting.

## Consequences

- the Huawei OND-only candidate remains not `mppt_design_ready`;
- lower-fidelity energy conversion may still be simulated because voltage range, AC power,
  and detailed efficiency curves are available;
- physical MPPT current clipping cannot yet be simulated from this OND alone;
- the 40 A source value remains available for sizing/contractual checks;
- a manufacturer-datasheet overlay may later add the 26 A value with separate provenance;
- no generic division or reinterpretation of OND current values is permitted.
