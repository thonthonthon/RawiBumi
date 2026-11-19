# OpenSIMPV — Phase 5.10 Analytical and External Validation Matrix v0.1

**Status:** Phase 5.10 implementation and validation anchor  
**Date:** 25 September 2026  
**Base:** Phase 5.9 merged main `84cebda1f0f98067597fff2d390bd841dd7ef118`  
**Shading physics change:** none  
**Electrical shading:** Phase-6 mismatch/bypass behavior remains outside scope

## 1. Objective

Phase 5.10 validates the Phase-5 geometric shading chain by decomposition rather than by final-energy fitting.

Validation order:

    A analytical geometry truth
    -> B controlled synthetic OpenSIMPV
    -> C independent/open implementation where appropriate
    -> D PVsyst cross-software evidence
    -> E regression-only references

PVsyst remains a reference, not the definition of OpenSIMPV equations.

## 2. Analytical truth

The existing Phase-5.3 direct-beam microcases remain the primary geometry oracle.

They cover:

- no occluder;
- full block;
- exact 50% rectangular overlap;
- diagonal 50% overlap;
- overlapping-shadow union;
- rotated receiver;
- tilted receiver;
- low solar altitude;
- occluder behind receiver;
- boundary touch;
- sun below horizon;
- self-intersection exclusion.

Phase 5.10 registers these as Authority A rather than duplicating or weakening their tolerances.

## 3. Controlled OpenSIMPV evidence

Phase 5.8H and 5.9 provide Authority B integration evidence:

- full beam + sky + ground none/exact physical parity;
- cold/warm exact reproducibility;
- bounded receiver-factor persistence;
- R1 full-year clear/no-loss regression;
- R4 full-year nontrivial geometry-aware execution;
- explicit annual geometric near-shading PCC counterfactual.

These cases validate the complete supported annual chain independently of PVsyst fitting.

## 4. Frozen PVsyst VC0–VC5 oracle

The Phase-4.9B oracle is retained as Authority D.

Cases:

    VC0 north
    VC1 south
    VC2 east
    VC3 west
    VC4 east-west
    VC5 north-south

The repository retains:

- source filename, SHA-256 and byte size;
- exact SHD-derived geometry;
- common pre-shading-series identity;
- beam shading loss;
- circumsolar shading loss;
- diffuse shading loss;
- albedo shading loss;
- monthly shading loss;
- annual shading loss;
- grid energy;
- directional hourly signatures.

The raw user-supplied source files remain external and are not redistributed.

## 5. New comparison contract

Added:

    validation/shading/phase510.py

The external comparator requires explicit compatibility declarations for:

    weather
    scene_geometry
    simulation_timestep
    solar_time_semantics
    pre_shading_irradiance
    channel_semantics

If any declaration is false:

    status = not_quantitatively_comparable
    residuals = {}

This prevents a comparison using different weather/transposition bases from being reported as physical model agreement.

If all bases are matched, the comparator emits decomposed signed and relative residuals only. It intentionally does not produce a winner, fit score or instruction to tune OpenSIMPV.

## 6. Source-side PVsyst reconciliation

The Phase-5.10 gate independently rechecks that the four frozen PVsyst shading channels:

    beam
    + circumsolar
    + diffuse
    + albedo

reconcile to the frozen total shading loss within source-rounding tolerance.

This is a source-oracle integrity check, not an OpenSIMPV parity claim.

## 7. Directional evidence

The external oracle preserves:

    VC2 east:
        morning beam+circumsolar loss
        >
        afternoon beam+circumsolar loss

    VC3 west:
        afternoon beam+circumsolar loss
        >
        morning beam+circumsolar loss

The signs are preserved as evidence.

The magnitudes are not forced to symmetry.

## 8. Combined-obstacle evidence

The validator explicitly preserves:

    VC4 != VC2 + VC3
    VC5 != VC0 + VC1

The combined cases remain independent geometric/source cases.

No production code is allowed to synthesize a combined annual shading result by adding independent directional losses.

## 9. Current external-validation boundary

The frozen repository oracle is sufficient to validate:

- source-channel reconciliation;
- source provenance;
- exact stored geometry;
- directional signatures;
- combined-case non-additivity;
- the comparison/attribution contract.

It is not sufficient by itself to claim a fully matched OpenSIMPV-vs-PVsyst numerical residual matrix because the original detailed source time series are intentionally not redistributed in the repository.

Therefore Phase 5.10 makes no claim that OpenSIMPV numerically reproduces PVsyst VC0–VC5 annual losses.

That claim is deliberately blocked unless matched weather, timestep, solar-time semantics, pre-shading irradiance and channel semantics are available.

## 10. CI gate

Normal validation adds:

    python tools/validate_phase510.py

The tool fails when:

- the frozen oracle identity changes unexpectedly;
- VC0–VC5 are incomplete;
- channel decomposition does not reconcile within source rounding;
- east/west directional evidence is lost;
- VC4/VC5 non-additivity evidence is lost.

Unit tests also prove that unmatched cross-software comparison bases fail closed.

## 11. Acceptance disposition

Phase-5.10 validation-contract boundary:

    analytical hierarchy frozen
    PASS

    analytical beam truth retained
    PASS

    controlled annual OpenSIMPV evidence retained
    PASS

    VC0–VC5 source oracle integrity
    PASS

    separate beam/circumsolar/diffuse/albedo channels
    PASS

    directional asymmetry preserved
    PASS

    combined-case non-additivity preserved
    PASS

    matched-input requirement for quantitative residuals
    PASS

    unmatched-input comparison fails closed
    PASS

    no shading-physics tuning
    PASS

    no Phase-6 electrical mismatch
    PASS

Direct matched-input OpenSIMPV-vs-PVsyst numerical parity:

    NOT CLAIMED FROM THE REDISTRIBUTABLE REPOSITORY ORACLE ALONE

This is an explicit evidence boundary, not an unexplained residual.

## 12. Phase 5.11 handoff

Phase 5.11 should freeze the complete Phase-5 maturity boundary and regression family.

Closure hardening should preserve:

- analytical shadow microcases;
- R1 annual unobstructed case;
- R4 annual obstacle-rich case;
- multiple receiver orientations where supported;
- VC0–VC5 external attribution oracle;
- save/reload/compile/run reproducibility;
- compiled geometry identity;
- shading-result identity;
- annual output deterministic tolerance;
- benchmark evidence for compile, beam, sky, annual shading, cache and memory behavior.

Do not broaden Phase 5.11 into Phase-6 electrical shading.
