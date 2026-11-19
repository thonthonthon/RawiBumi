# ADR 0037 — Engineering limit decisions are evidence-graded

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4.7 introduced deterministic engineering validation using either a validated PVsyst single-diode model or a documented linear temperature-coefficient fallback.

The fallback is approximate, especially for Vmpp and Imp. Treating fallback values as exact at hard or operational boundaries could create false precision. The validator also warned when MPPT current limits were unavailable but did not consistently warn when total inverter current limits were missing.

## Decision

1. Engineering validation rule-set version becomes opensimpv.engineering_validation.v0.2.
2. Detailed PVsyst evidence requires both a validated parameter set and detailed_sdm_ready=true.
3. Detailed evidence receives no additional guard band.
4. Linear fallback receives explicit configurable voltage/current uncertainty fractions.
5. Default fallback voltage uncertainty is 5%.
6. Default fallback current uncertainty is 5%.
7. The defaults are regression-anchored to accepted synthetic and manufacturer PAN fixtures at -10 °C, 70 °C and reference irradiance; they are not represented as universal physical bounds.
8. Linear fallback is permitted only at module reference irradiance because it lacks validated irradiance-dependent voltage behavior.
9. Absolute equipment maxima use the conservative upper evidence bound and may produce INVALID.
10. MPPT operating-voltage windows produce INVALID only when the full evidence interval is outside; fallback interval overlap produces WARNING.
11. Missing MPPT current/Isc limits remain WARNING.
12. Missing total inverter DC current/Isc limits also become WARNING.
13. Missing limits are never inferred from adjacent component fields.
14. Reports expose nominal estimates, conservative bounds and evidence grade where those affect the decision.
15. Validation remains read-only.

## Consequences

A fallback-based hard rejection is conservative and traceable rather than pretending the approximation is exact.

Operational MPPT-window decisions near a fallback uncertainty boundary remain visible without becoming an unjustified blocking result.

Component-library incompleteness is surfaced consistently at both MPPT and inverter-total levels.
