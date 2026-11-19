# ADR 0033 — Engineering validation uses explicit design conditions and visible model downgrade

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4.7 requires cold Voc, temperature-dependent Vmpp, current, Isc and inverter compatibility checks.

The canonical project model does not currently contain a universal site design-temperature source. The module schema contains beta-Voc, alpha-Isc and gamma-Pmp but no independent beta-Vmpp coefficient.

Silently choosing site temperatures or inventing beta-Vmpp would make validation appear more authoritative than the available data supports.

## Decision

1. Phase 4.7 is read-only.
2. Minimum cell temperature, maximum cell temperature and design irradiance are explicit validation inputs.
3. A validated executable PVsyst single-diode model is the preferred temperature-dependent module model.
4. When policy permits and detailed execution is unavailable, a visible linear fallback may use beta-Voc, alpha-Isc and gamma-Pmp.
5. The fallback estimates relative beta-Vmpp as relative gamma-Pmp minus relative alpha-Isc and records this approximation in every report using it.
6. If neither detailed nor fallback calculation is defensible, the affected module temperature model is INVALID rather than guessed.
7. Known absolute voltage/current-limit exceedance is INVALID.
8. Unequal parallel string length and MPPT orientation mismatch are WARNING.
9. DC/AC ratio is INFO unless an explicit project advisory range turns it into WARNING.
10. Missing MPPT current/Isc limit data is WARNING because that check is incomplete, not proof of physical incompatibility.
11. Existing ValidationFinding.severity values remain unchanged for compatibility; Phase 4.7 adds human-facing classification and maps INVALID to blocking_error.
12. Only INVALID findings set blocking_simulation=true.

## Consequences

The validation engine remains conservative about unsupported information without conflating database incompleteness with physical impossibility.

The user can see exactly when a simplified temperature model is used.

Future project/weather integration may generate the explicit design-condition configuration, but it must remain traceable rather than becoming a hidden validator default.
