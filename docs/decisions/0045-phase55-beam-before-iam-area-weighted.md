# ADR 0045 — Phase-5 beam shading modifies direct POA before IAM and aggregates geometry by receiver area

**Status:** Accepted by Phase 5.5  
**Date:** 2026-09-24

## Context

Phase 5.3 provides analytically validated direct-beam geometric visibility.

Phase 5.4 provides deterministic module receiver snapshots.

The existing numerical PV backend is homogeneous and consumes one irradiance state before module/string/MPPT calculations.

A vertical integration therefore needs to preserve geometric receiver detail while making one explicit lower-fidelity approximation at the existing electrical boundary.

## Decision

1. Insert near-shading after POA transposition and before IAM.
2. Apply geometric beam visibility only to the direct POA beam component.
3. Preserve sky diffuse and ground-reflected POA unchanged.
4. Derive the per-timestep geometry sun vector from canonical solar azimuth and apparent elevation.
5. Evaluate module receiver factors through the existing Phase-5.4 snapshot path.
6. Aggregate module factors to one homogeneous execution-group factor using compiled receiver area weighting.
7. Identify that approximation as beam_visibility.execution_group_area_weighted_mean.v0.1.
8. Record the approximation as a warning-level SimulationAssumption.
9. Preserve the full module receiver factor vector in a separate persisted Parquet dataset.
10. Use unshaded incident POA as the performance-ratio reference denominator.
11. Do not manufacture an electrical shading-energy loss from irradiance loss; keep SummaryResult.shading_energy_loss_wh null for geometry-aware runs.
12. Support only homogeneous_single_group annual execution in Phase 5.5.
13. Keep historical pvsyst_shd_reference configurations blocked and unmodified.
14. Do not implement diffuse/ground obstruction or electrical mismatch in this tranche.

## Consequences

Positive:

- canonical Scene geometry now affects simulated PCC energy;
- direct-beam loss is physically and numerically traceable;
- IAM ordering is explicit;
- diffuse and ground channels cannot be accidentally shaded by the beam factor;
- receiver-level geometry is retained for later Phase-6 physics;
- PR continues to count near shading as a loss;
- historical reference configurations retain their meaning.

Deliberate limitations:

- one homogeneous execution group only;
- one area-weighted beam state enters the current electrical backend;
- no detailed mismatch;
- no diffuse or ground obstruction;
- no annual shading cache acceleration;
- shading electrical-energy loss is not separately counterfactually quantified.

## Revisit condition

The area-weighted electrical approximation should be superseded only when a later electrical-shading runtime consumes spatial module/string irradiance states directly. The module receiver factor dataset should remain reusable as the geometric input to that higher-fidelity model.
