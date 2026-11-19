# Decision 0004 — Component capability is progressive, not PAN/OND-complete

**Status:** Accepted for v0.1 implementation  
**Date:** 2026-09-23

## Decision

OpenSIMPV component definitions are canonical and source-format independent.

PAN and OND are supported import adapters, but the presence or absence of a PAN/OND field does
not define the maximum capability of the simulation engine. A component may be assembled from
multiple sources and may contain canonical parameters that PAN/OND cannot represent.

Simulation and engineering capability are evaluated feature-by-feature.

The rule is:

```text
minimum trustworthy inputs -> lower-fidelity calculation
additional trustworthy inputs -> higher-fidelity/refined calculation
missing optional inputs -> unsupported refinement disclosed explicitly
```

Missing optional refinement data must not be replaced with hidden defaults merely to make a
component appear complete.

## Module examples

A module with dimensions, STC points, and temperature coefficients may support a basic yield
calculation without a complete PVsyst single-diode parameter set.

A validated single-diode model can refine electrical behavior.

Bifacial parameters can refine rear-side response.

Internal cell/submodule/bypass topology can refine electrical shading behavior.

Independent measured IV data can strengthen validation evidence without being mandatory for
ordinary layout or basic yield.

## Inverter examples

An inverter with a valid DC/MPPT voltage domain, nominal AC power, and an explicit efficiency
model may support basic energy conversion even when a physical MPPT operating-current limit
is absent.

Adding the operating-current limit enables current-limit design checks and current-clipping
refinement.

Adding detailed efficiency curves refines conversion loss versus DC voltage/load.

Adding temperature derating refines the available AC power limit.

Per-MPPT heterogeneous data may later refine the generic MPPT template.

## Multi-source composition

Canonical component data may be composed from:

- manufacturer PAN/OND;
- manufacturer datasheets/manuals;
- openly redistributable databases;
- laboratory/certification results;
- user-entered CSV/YAML data;
- measured IV/efficiency data.

Each source retains its own provenance, license/redistribution metadata, and source priority.

A higher-priority source may refine a lower-priority field. Equal-priority conflicting values
are not silently resolved. Manufacturer/model identity is protected from accidental merge.

## Consequences

- the canonical schema may grow beyond PAN/OND;
- PAN/OND users are not forced to provide newer optional fields;
- user templates are first-class input formats rather than emergency fallbacks;
- capability flags must state exactly which engineering checks/models are available;
- reports must disclose skipped refinements when relevant to the result;
- no source format is treated as the definition of OpenSIMPV physics.
