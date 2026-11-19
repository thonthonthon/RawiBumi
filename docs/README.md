# RawiBumi Documentation


This directory is the documentation root for RawiBumi.


The v0.1 architecture is governed by six specification families:


1. **System Architecture & Engineering Specification** — product boundary, engineering philosophy, subsystem architecture, deployment model, roadmap, and acceptance criteria.
2. **Canonical Data Model Specification** — authoritative internal engineering entities, revisions, units, provenance, geometry, electrical topology, weather, simulation configuration, results, and validation objects.
3. **Open Component Library Specification** — module/inverter data, provenance, revisions, PAN/OND import, validation, verification, and redistribution boundaries.
4. **Simulation Engine Specification** — timestep semantics, weather processing, solar/irradiance models, shading interfaces, thermal/electrical models, inverter behavior, loss accounting, reproducibility, and validation.
5. **PV Scene Editor & Near-Shading Specification** — constrained parametric PV layout, exact dimensions, scene geometry, editing behavior, and shading workflow.
6. **Validation Benchmark & Reference Cases Specification** — benchmark authority hierarchy, tolerance classes, analytical/numerical reference cases, end-to-end validation, regression policy, and release gates.


The repository structure and implementation should follow these engineering anchors rather than allowing implementation details to redefine the engineering model.


## Machine-readable implementation


The first executable translation of the anchors lives in:


- `schemas/` for cross-domain canonical JSON Schemas;
- `components/schema/` for module and inverter schemas;
- `weather/schema/` for weather schemas;
- `tests/benchmarks/` for benchmark and tolerance registries;
- `tests/reference/` for independent analytical references;
- `tests/fixtures/` for synthetic redistributable inputs;
- `tests/unit/` for executable validation tests.


## Documentation policy


- Specifications are versioned architecture anchors.
- Source-format semantics are documented at adapter boundaries.
- Engineering model choices are named and versioned.
- Important assumptions and approximations remain visible.
- Numerical changes require validation and regression evidence.
- Documentation and implementation should evolve together.




## Phase-2 weather


- weather-data-foundation.md — canonical interval semantics, supported weather adapters,
  weather QC, source provenance, and energy-preserving timestep conversion.
- decisions/0006-weather-time-and-resampling.md — frozen interval-start and progressive
  weather-resolution decision.




## Phase 4 engineering design environment


- [Engineering Design Environment Specification v0.1](engineering-design-environment.md) — Phase-4.0 canonical state boundaries, revision behavior, actual-versus-suggested semantics, workspace separation, validation report, and design-to-simulation interface.
- [ADR 0026 — Phase 4.0 design contracts](decisions/0026-phase40-design-contracts.md) — compatibility mapping for SceneRevision/ElectricalTopologyRevision and the UI-state boundary.


Phase 4.0 intentionally contains no frontend interaction implementation. Phase 4.1 begins only after these contracts pass CI.


- [Site, Map, and Coordinate Foundation v0.1](site-map-coordinate-foundation.md) — Phase 4.1 WGS84/local metric transform, map-provider abstraction, orthophoto georeferencing, scale and measurement semantics.
- [ADR 0027 — Local tangent-plane engineering coordinates](decisions/0027-phase41-local-tangent-map-context.md) — canonical local ENU decision and map-context boundary.


- [2D Constrained Scene Editor Foundation v0.1](2d-constrained-scene-editor.md) — Phase 4.2 deterministic local-metric editing kernel, exact-dimension provenance, snapping, atomic undo/redo, and Scene revision persistence.
- [ADR 0028 — Canonical Scene draft editor kernel](decisions/0028-phase42-canonical-editor-kernel.md) — keeps engineering edits on canonical Scene drafts while selection/snap/history remain workspace state.


- [PV Field and Packing Engine v0.1](pv-field-packing-engine.md) — Phase 4.3 deterministic module footprint resolution, explicit packing commands, setbacks/exclusions, conflict reporting, row/table placement, and reproducibility hash.
- [ADR 0029 — Explicit deterministic PV packing](decisions/0029-phase43-explicit-deterministic-packing.md) — prevents reactive silent repacking and freezes the support-surface 2D packing basis.


- [Height Model and 3D Verification v0.1](height-model-3d-verification.md) — Phase 4.4 deterministic surface planes, obstacle/parapet extrusion, module tilt/physical geometry, height findings, and non-editable GeneratedScene3D output.
- [ADR 0030 — Derived 3D verification authority](decisions/0030-phase44-derived-3d-verification.md) — keeps canonical 2D Scene authoritative and freezes the surface elevation-datum/slope convention.


- [Component-Aware Design Integration v0.1](component-aware-design-integration.md) — Phase 4.5 exact component revision binding, non-mutating revision impact analysis, explicit keep/rebuild actions, and design-facing component snapshots.
- [ADR 0031 — Component revision changes use analyze → explicit apply](decisions/0031-phase45-component-revision-actions.md) — prevents silent geometry/topology redesign when component revisions change.


- [Electrical Topology Editor v0.1](electrical-topology-editor.md) — Phase 4.6 canonical string/MPPT/inverter/PCC authoring, explicit stringing/assignment automation, topology inspection, and electrical revision commit.
- [ADR 0032 — Canonical topology editor](decisions/0032-phase46-canonical-topology-editor.md) — permits disabled unassigned draft strings while keeping simulation/runtime topology stricter.


- [Engineering Validation Engine v0.1](engineering-validation-engine.md) — Phase 4.7 temperature-corrected voltage/current validation, MPPT/inverter limits, DC/AC policy, orientation/string-length warnings, and deterministic DesignValidationReport generation.
- [ADR 0033 — Explicit validation conditions and visible model downgrade](decisions/0033-phase47-explicit-validation-conditions.md) — requires explicit design temperatures/irradiance and forbids hidden Vmpp-temperature assumptions.


- [Phase 4.7H-A Module Identity and Topology Impact Hardening](phase47ha-module-identity-topology-impact.md) — placement-derived generated module identity, legacy-ID continuity for equivalent rebuilds, deterministic layout delta, and stale string-membership reporting.
- [ADR 0034 — Generated module identity follows placement](decisions/0034-phase47ha-module-identity-topology-impact.md) — separates packing lineage from canonical ModuleInstance identity and forbids silent topology reinterpretation during rebuild.


- [Phase 4.7H-B Manual Module and Vertex Editing](phase47hb-manual-module-vertex-editing.md) — explicit identity-preserving module movement/rotation, snapped vertex editing, conflict visibility, save/reload invariance, and generated-rebuild identity collision protection.
- [ADR 0035 — Manual edits preserve identity](decisions/0035-phase47hb-manual-edit-identity.md) — separates engineer-authored object movement from generated replacement semantics.


- [Phase 4.7H-C 2D ↔ 3D Geometry / Projection / Z Coherence](phase47hc-geometry-projection-z-coherence.md) — freezes horizontal-plan Scene geometry, tilted-module plan projection, canonical module center Z, legacy footprint migration, and 2D/3D consistency.
- [ADR 0036 — Horizontal-plan PV geometry semantics](decisions/0036-phase47hc-horizontal-plan-geometry.md) — keeps one canonical XY editing frame and separates projected 2-D footprint from physical 3-D module dimensions.


- [Phase 4.7H-D Engineering Validation Evidence Hardening](phase47hd-validation-evidence-hardening.md) — evidence grades, guarded linear fallback, reference-irradiance boundary, conservative absolute-limit checks, and missing inverter-limit visibility.
- [ADR 0037 — Evidence-graded engineering validation](decisions/0037-phase47hd-evidence-graded-validation.md) — freezes the distinction between detailed model evidence and approximate fallback evidence at engineering limits.


- [Phase 4.8 Design → Simulation Integration](phase48-design-simulation-integration.md) — ProjectRevision/configuration bridge, exact validation gate, component/weather pinning, UI independence, and direct-canonical equivalence.
- [ADR 0038 — ProjectRevision remains the Design → Simulation pinning boundary](decisions/0038-phase48-project-revision-simulation-boundary.md) — prevents an editor-specific physics model and keeps validation evidence derived.


- [Phase 4.9A Unshaded Reference Matrix](phase49a-unshaded-reference-matrix.md) — freezes nine PVsyst 8.1.6 hourly oracles spanning two/multi-orientation, loading-ratio and multi-inverter cases, with explicit unresolved design metadata and VC4/VC8 scaling isolation.
- [Phase 4.9B Shaded Reference / Geometry Matrix](phase49b-shaded-reference-geometry.md) — freezes six PVsyst CSV+SHD shading cases with exact non-symmetric scene geometry, annual/monthly shading targets, directional temporal signatures, source fingerprints, and corrected IL_Pmin attribution semantics.
- [Phase 4.9C Canonical Reference Project Roundtrip](phase49c-reference-project-roundtrip.md) — reconstructs R1–R5, freezes the canonical design-state save/reopen contract, proves deterministic revalidation/rerun where supported, and closes Phase 4 for the current scope without flattening unsupported physics.
- [ADR 0039 — Canonical design-state package is the Phase-4 save/reopen boundary](decisions/0039-phase49c-design-state-package.md) — persists revision-pinned engineering state with integrity hashes while keeping UI workspace state outside physics.

## Reproducible development install

`requirements.lock` pins the complete validated Python 3.12 / Linux x86_64 environment,
including test tools, with wheel SHA-256 hashes. From the repository root:

```sh
python3.12 -m venv /tmp/rawibumi-venv
/tmp/rawibumi-venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
cd apps/web
npm ci
```

The lock was resolved with the installed pip 26.2.1:
`pip lock -r apps/api/requirements.txt -r requirements-validation.txt -r /tmp/rb-r1/installed-pins.txt --output /tmp/rb-r1/pylock.toml`.
The additional pins were the existing environment's installed versions; the lock retains
those versions and the resolved wheels' hashes. Other Python/platform combinations need
a separately validated lock. Chromium and Node remain prerequisites for PDF/browser tests.
The requirement inputs declare the direct imports and the parallel validation tools
at the versions already pinned in the lock.

Archive imports now mark saved run records as imported, and Results and the shared report
label them accordingly. Earlier imports cannot be distinguished from locally computed runs.
The marker does not alter immutable run packages or their recorded numbers.


## Upgrading

Saved runs keep their recorded numbers. A rerun uses the current models and recommended
losses. Projects saved before 2026-11-03 had none of these losses, so rerunning can change
the result substantially: REL1 measured −10.5 % for a project saved on 29 October.
Runs saved before 2026-11-08 have no design fingerprint; rerun them to produce a report.

For Meteonorm or PVsyst weather, export the hourly data as TMY3 or "PVsyst Standard" CSV
and import that file. PVsyst `.MET` files are not read.
