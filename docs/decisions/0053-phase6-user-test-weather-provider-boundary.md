# ADR 0053 — Phase-6 User-Test and Weather-Provider Boundary

**Status:** Accepted  
**Date:** 25 September 2026

## Context

At the Phase-5.11 baseline, OpenSIMPV has a mature canonical engineering and geometry-aware simulation backend, but the intended browser workflow is not yet runnable. The repository's web/API application directories remain reserved boundaries.

The weather layer can import and normalize several engineering formats, but there is no coordinate-driven provider acquisition path.

Beginning production high-fidelity electrical shading immediately would increase scientific depth while delaying the first representative user test of the intended product.

## Decision

1. Preserve the Development Phase 6 maturity objective: electrical shading and high-fidelity DC physics.
2. Add Phase-6 pre-physics enabling tranches for:
   - coordinate-driven weather acquisition;
   - a minimal browser site/scene workflow;
   - an end-to-end user-test slice using the existing Phase-5 engine.
3. Require site latitude/longitude for both browser workspace modes:
   - map overlay;
   - blank local engineering plane.
4. Keep local metric engineering geometry authoritative. Map imagery remains contextual.
5. Introduce a provider-neutral `WeatherProviderAdapter` transport boundary.
6. Implement Open-Meteo first as a live transport adapter and optional future self-hosted service, but do not assign Open-Meteo scientific precedence.
7. Treat every meteorological source product as separate. Multiple upstream products exposed through one provider/API remain separate source identities.
8. Preserve each source product's own meteorological projection/reconstruction/interpolation/downscaling/generation semantics. OpenSIMPV does not apply a common resource-projection method at this stage.
9. Do not blend, average, bias-correct, ensemble, rank, or silently fall back between meteorological source products.
10. Retain user-supplied weather imports as first-class inputs.
11. Normalize each selected source response into its own versioned canonical `WeatherDataset` before simulation while preserving source-product and source-method provenance.
12. Persist request semantics, raw-response hash, provider/source identity, source-method metadata where available, canonical mapping version, and resulting dataset identity.
13. Never require live external provider access for deterministic blocking CI; use frozen response fixtures.
14. Require an early browser user-test gate before substantial production detailed-DC work.
15. Use analytical cases as primary electrical validation truth. Use PVMismatch where compatible as independent open-source electrical evidence and PVsyst as secondary cross-software evidence.

## Consequences

### Positive

- The first external user test occurs before another large backend-only development cycle.
- Weather acquisition becomes coordinate-driven without making OpenSIMPV dependent on one provider or one meteorological source product.
- Different source products can be compared without erasing their different resource-generation semantics.
- Self-hosted/offline operation remains possible through pinned weather files/datasets.
- Map availability does not block engineering work.
- Phase-6 electrical physics remains architecturally clean and can reuse the existing geometry/electrical authorities.
- Provider outages or schema drift do not invalidate historical simulations.
- Validation is less dependent on PVsyst-derived fixtures.

### Costs

- Phase-6 implementation begins with product-enabling work that is not itself new electrical physics.
- A browser/API shell must be built earlier than previously planned.
- Weather-provider provenance and adapter testing add schema and maintenance work.
- Supporting more than one provider/source product adds mapping and operational complexity.
- OpenSIMPV cannot yet create a harmonized multi-source resource; comparison remains source-by-source by design.

## Rejected alternatives

### Start high-fidelity DC first and defer GUI to Phase 7

Rejected because the intended product cannot be meaningfully user-tested and browser/canonical integration risk would remain hidden until after substantial solver work.

### Make Open-Meteo the canonical weather subsystem

Rejected because Open-Meteo is an acquisition/processing service over multiple upstream datasets. Canonical OpenSIMPV weather semantics and reproducibility must remain independent of provider implementation.

### Require a live map for all projects

Rejected because map imagery is context, not engineering authority. A coordinate-anchored blank local plane is a valid engineering workflow.

### Require live weather APIs in CI

Rejected because provider availability and mutable upstream data would make deterministic regression dependent on external state.

### Apply one OpenSIMPV meteorological projection method to all sources

Rejected for the current roadmap because the source products use different resource-generation semantics and evidence bases. OpenSIMPV will preserve those differences. Any future OpenSIMPV-owned meteorological projection, blending, bias-correction or ensemble model requires a new explicit model family, provenance contract and validation program.

### Automatically fall back from one weather source to another

Rejected because it would change the physical resource basis without an explicit engineering decision. Source unavailability produces an explicit acquisition failure; the user may then select another source.
