# ADR 0051 — Phase 5.10 validation hierarchy and external-comparison contract

**Status:** Accepted by Phase 5.10 implementation  
**Date:** 2026-09-25

## Context

Phase 5.9 closed the supported annual geometry-aware SimulationRun path. Phase 5.10 must validate the geometric shading chain without turning PVsyst into the definition of OpenSIMPV physics.

The repository already contains:

- analytical beam-shadow microcases;
- controlled synthetic OpenSIMPV annual cases;
- exact/reference and cold/warm reproducibility evidence;
- a frozen PVsyst 8.1.6 VC0–VC5 shaded oracle with exact SHD-derived geometry, channel decomposition, monthly values, annual values and directional signatures.

The raw user-supplied PVsyst CSV/SHD files are intentionally not redistributed.

## Decision

1. Freeze the validation hierarchy:

       A — analytical geometry truth
       B — controlled synthetic OpenSIMPV cases
       C — independent/open implementation where appropriate
       D — external cross-software comparison
       E — regression-only references

2. Analytical geometry truth has priority for the correctness of the direct geometric kernel.

3. Controlled OpenSIMPV cases validate integration, annual execution, persistence and reconciliation.

4. PVsyst VC0–VC5 is an external attribution oracle, not an internal equation definition.

5. Preserve and compare beam, circumsolar, diffuse and albedo channels separately whenever semantics permit.

6. Preserve directional asymmetry. Do not force:

       north == south
       east == west

7. Combined cases are independent cases. Do not construct VC4 or VC5 by summing directional annual losses.

8. A quantitative OpenSIMPV-vs-external residual is allowed only when all of these bases are explicitly matched:

       weather
       scene geometry
       simulation timestep
       solar-time semantics
       pre-shading irradiance
       channel semantics

9. If any comparison basis is unmatched, the validator reports the mismatch and emits no numerical agreement verdict.

10. Do not alter independently validated solar-position, beam, sky or ground equations merely to improve final annual-energy agreement.

11. Phase 5.10 does not implement Phase-6 electrical mismatch and does not interpret geometric residuals as bypass/sub-string loss.

## Consequences

Positive:

- analytical correctness cannot be overridden by cross-software fitting;
- PVsyst residuals can be decomposed rather than hidden behind final annual energy;
- source/convention differences remain visible;
- unmatched comparisons fail closed instead of manufacturing a score;
- VC0–VC5 asymmetry and non-additivity remain evidence.

Trade-offs:

- a frozen aggregate oracle can validate source decomposition and directional evidence but cannot by itself establish matched-input numerical parity for every channel;
- direct quantitative cross-software residuals remain conditional on availability of the original compatible source series or an equivalently reconstructed matched input;
- Phase 5.10 may close its validation-contract boundary without claiming that OpenSIMPV reproduces PVsyst numerically.

## Revisit condition

Revisit when original external time-series sources are made available to an execution environment, when a second independent geometric implementation is adopted, or when Phase 6 introduces electrical shading mismatch.
