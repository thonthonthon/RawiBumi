# RawiBumi — Phase 6 Pre-Physics Rebaseline: Product Readiness, Weather Acquisition, and User-Test Gate


**Status:** Active Phase-6 implementation anchor  
**Revision:** 0.7  
**Date:** 25 September 2026  
**Baseline:** `main @ 436fbdf33950c7a15d363267ab4700131ae432ce`  
**Parent:** Phase-6 Electrical Shading & High-Fidelity DC Physics Handover


## 1. Purpose


This document re-baselines the implementation sequence entering Development Phase 6.


It does **not** change the Development Phase 6 maturity objective:


```text
geometric shadow
→ local electrical regions
→ substring / submodule IV
→ bypass
→ module IV
→ string IV
→ parallel strings
→ MPPT operating point
→ inverter
```


The re-baseline exists because repository review shows an asymmetry between the scientific/backend maturity and the intended browser product workflow.


The scientific and engineering backend is sufficiently mature to begin Phase-6 electrical physics. The user-facing product is not yet sufficiently integrated for meaningful external user testing.


The implementation sequence is therefore changed so that a minimal browser workflow and coordinate-driven weather acquisition become executable **before** substantial production high-fidelity DC work.


## 2. Verified Pre-Phase-6 State


### 2.1 Mature and reusable


The following foundations are already implemented and should not be reopened without a concrete defect:


- canonical project/site/revision contracts;
- WGS84 site anchor and deterministic local engineering coordinates;
- map-provider abstraction and orthophoto georeferencing contracts;
- canonical 2D scene editing operations and snapping;
- deterministic PV-field packing;
- renderer-neutral 3D scene generation;
- component revision binding;
- canonical String → MPPT → Inverter topology;
- engineering design validation;
- canonical design → SimulationRun integration;
- weather import/normalization/QC/resampling;
- deterministic geometry-aware beam, diffuse-sky, and ground visibility;
- annual geometry-aware SimulationRun execution and Phase-5 closure evidence.


### 2.2 Material product gaps


Repository review at the Phase-5.11 baseline shows:


```text
apps/web
= reserved module boundary, not a runnable browser application


apps/api
= reserved module boundary, not a runnable project API
```


The existing Phase-4 "editor" is therefore primarily a tested engineering-domain/editor kernel rather than the intended graphical browser workspace.


The weather subsystem is also mature as an **ingestion and canonicalization layer**, but not yet as a **coordinate-driven resource acquisition layer**.


Current supported weather inputs include:


- RawiBumi Weather CSV;
- TMY3;
- EPW;
- Meteonorm DAT;
- PVsyst Standard weather CSV;
- explicit probing of unsupported PVsyst internal MET containers.


There is no current Open-Meteo, CAMS, PVGIS, NASA POWER, or other live provider adapter in the repository.


## 3. Maturity Interpretation


The Developmental Phasing Anchor remains valid and should not be rewritten merely because implementation order changes.


However, two different statements must remain distinguishable:


```text
backend tranche closed for current scope
≠
all user-facing evidence for the developmental maturity gate is complete
```


Phase 4/5 backend work remains valid and is not reopened.


The new Phase-6 implementation plan adds the missing product evidence without changing the scientific Phase-6 exit gate.


## 4. Coordinate-First Product Contract


A site coordinate is always part of project engineering state.


The normal browser workflow shall support two equivalent scene contexts:


### 4.1 Map-overlay mode


```text
latitude / longitude
→ map context
→ local metric engineering XY
→ constrained PV CAD overlay
```


The map is contextual, not dimensional authority.


### 4.2 Blank engineering-plane mode


```text
latitude / longitude
→ local metric engineering XY
→ blank grid / true-north reference
→ constrained PV CAD
```


A live map provider is therefore **optional for scene editing**.


This provides a PVsyst-like blank workspace fallback while preserving the same coordinate, solar, weather, and engineering reference system used by the map-overlay workflow.


### 4.3 Required first browser scope


The first user-test browser does not need to reproduce every Phase-4 kernel feature.


It must be sufficient to execute this vertical slice:


```text
Create Project
→ enter/select site coordinate
→ open map overlay OR blank engineering plane
→ create/edit one support surface
→ create simple obstacles
→ place/fill a PV field
→ select a module
→ create string(s)
→ assign MPPT / inverter
→ acquire or import weather
→ validate
→ run existing Phase-5 geometry-aware simulation
→ inspect basic monthly/annual energy and explicit losses
→ save/reopen the project
```


This is the first external-user-test gate.


## 5. Weather Architecture Decision


RawiBumi shall distinguish:


```text
weather acquisition provider
≠
canonical WeatherDataset
≠
weather transformation
≠
simulation model
```


No simulation routine may call an external weather provider directly.


The required chain is:


```text
Site coordinate
→ WeatherProviderAdapter
→ raw provider response + request manifest
→ semantic mapping
→ canonical WeatherDataset revision
→ QC
→ optional canonical transformation/resampling
→ immutable weather revision
→ SimulationRun
```


### 5.1 Provider transport versus meteorological source


Open-Meteo is the first planned live **transport adapter** because it is open source, supports coordinate-based retrieval and can be self-hosted.


This implementation order is not scientific precedence.


A provider transport and a meteorological source product are different identities.


For example, multiple upstream products exposed through one Open-Meteo API remain separate source products in RawiBumi. They are not collapsed into one generic `open_meteo` resource identity.


Open-Meteo is **not** the canonical weather model and shall not become a single mandatory dependency.


A self-hosted Open-Meteo service may later be deployed as a sidecar/service. Initial integration remains an adapter against its documented API.


### 5.2 Separate-source rule


For the current architecture, every meteorological source product is treated separately.


Examples include, without implying equivalence or ranking:


- Open-Meteo / ERA5;
- Open-Meteo / ERA5-Land;
- another explicitly selected Open-Meteo upstream product;
- CAMS solar-radiation products;
- PVGIS products/datasets;
- NASA POWER products;
- Meteonorm files;
- TMY3 files;
- EPW files;
- PVsyst Standard weather files;
- measured user weather.


Each source retains its own source-defined meteorological projection, reconstruction, interpolation, downscaling or generation semantics.


RawiBumi may normalize fields, units and timestamps into the canonical WeatherDataset, but it does not currently replace source resource-generation semantics with one common RawiBumi meteorological projection.


There is therefore no engine-level source hierarchy, blending, averaging, bias correction, ensemble construction or silent fallback between weather sources in Phase 6.0B.


If the selected source is unavailable, acquisition fails explicitly and the user may choose another source.


An RawiBumi-owned meteorological projection/model family may be considered much later, with separate validation and provenance.


### 5.3 User-supplied weather remains first-class


Provider acquisition does not replace:


- TMY3;
- EPW;
- Meteonorm;
- PVsyst Standard weather CSV;
- RawiBumi native CSV;
- future measured weather.


A project may be fully reproducible offline from a pinned imported WeatherDataset revision.


### 5.4 Provenance requirements


Every provider acquisition must preserve at least:


```text
provider_id
adapter_version
request endpoint family
requested coordinate
provider-selected coordinate/grid cell if reported
requested elevation
provider/source-product identifier
source-product version/release where available
source-owned projection/reconstruction method metadata where available
variable names and semantics
native timestep
time convention
coverage period
retrieval timestamp
raw response SHA-256
license / attribution requirement
provider transformation notes
canonical mapping version
canonical WeatherDataset revision/hash
```


Where provider results are generated or derived products, that state must remain visible.


### 5.5 Deterministic CI rule


Blocking CI shall not depend on a live external API.


Provider tests are split into:


```text
adapter contract tests
→ frozen raw-response fixtures
→ deterministic canonical WeatherDataset hashes


optional live smoke tests
→ non-authoritative provider availability / schema drift checks
```


A live provider response is never silently substituted for a pinned weather revision during simulation replay.


## 6. Revised Phase-6 Implementation Tranches


The **Development Phase 6 maturity objective remains unchanged**.


Only the implementation tranches are revised.


### Phase 6.0A — Rebaseline and Product-Readiness Contracts


Frozen by:


- `docs/phase60a-product-readiness-contract.md`;
- `docs/decisions/0053-phase6-user-test-weather-provider-boundary.md`;
- `weather/schema/weather-source-acquisition-manifest.schema.json`;
- `apps/web/schema/site-workspace-bootstrap.schema.json`.


The tranche freezes:


- coordinate-first browser bootstrap;
- map/blank workspace equivalence;
- weather-provider transport versus meteorological source-product identity;
- separate source-owned meteorological projection semantics;
- no source blending/ranking/silent fallback;
- provider/source provenance and snapshot identity;
- browser → canonical model boundary;
- user-test acceptance flow;
- distinction between browser/product readiness and Phase-6 electrical-physics maturity.


**Exit:** contract boundary frozen; no production electrical-shading kernel started.


### Phase 6.0B — Weather Acquisition Foundation


**Status: CLOSED.** See `docs/phase60b-weather-acquisition.md`.


Implemented:


- `WeatherProviderAdapter` transport interface;
- Open-Meteo transport adapter first;
- explicit source-product selection beneath that transport;
- raw-response persistence/hashing;
- canonical normalization through the existing weather layer;
- provider + source-product + source-method provenance;
- explicit selected-source failure behavior with no silent cross-source fallback;
- frozen provider/source fixtures.


Additional provider adapters such as CAMS, PVGIS or NASA POWER may then be added independently. Their outputs remain distinct WeatherDataset revisions and are not merged into a common resource projection.


**Exit:** a latitude/longitude plus one explicitly selected source product can produce a pinned, validated canonical WeatherDataset without manual file preparation, while file import remains available.


### Phase 6.0C — Browser Site / Scene Shell


**Status: CLOSED.** See `docs/phase60c-browser-site-scene-shell.md`.


Implemented the first runnable `apps/web` and minimal project API surface.


Required behavior:


- create/open project;
- enter coordinates or select location on map;
- MapLibre-backed provider-agnostic map context;
- blank local engineering grid fallback;
- true-north/local-coordinate indication;
- render/edit the existing canonical scene;
- simple surface/obstacle/PV-field workflow;
- component selection;
- basic string/MPPT/inverter workflow;
- save/reopen.


Do not rebuild the geometry kernel in TypeScript. The browser is an interaction/rendering layer over canonical engineering commands/contracts.


### Phase 6.0D — User-Test Vertical Slice on Existing Physics


**Status: CLOSED.** See `docs/phase60d-browser-uat-vertical-slice.md`.


Gate A is closed. The native browser-authored project now passes execution-readiness
preflight, engineering validation, the existing Phase-5 geometry-aware SimulationRun,
result persistence, and save/reopen identity checks.


Implemented:


- browser weather-source discovery and explicit coordinate-driven acquisition;
- canonical WeatherDataset persistence and project pinning;
- exact-design engineering validation before execution;
- existing Phase-5 geometry-aware SimulationRun through the product API;
- persisted canonical run artifacts and compact project run history;
- browser energy/monthly/PR/loss/finding inspection;
- native RawiBumi UAT project independent of PVsyst-derived geometry;
- deterministic provider-shaped UAT weather fixture for network-free blocking CI;
- save/reopen preservation of weather and run identity.


The supported UAT envelope remains fixed-tilt and homogeneous inside the existing Phase-5 execution scope. Detailed electrical shading/mismatch is not approximated here.


Original gate wiring:


```text
browser project
→ site coordinate
→ map/blank CAD
→ component/topology
→ provider-acquired OR imported weather
→ validation
→ existing Phase-5 geometry-aware SimulationRun
→ basic results/loss view
```


Create a native RawiBumi acceptance project independent of PVsyst-derived test geometry.


**Gate A — User-Test Ready:**


A PV engineer can complete a small fixed-tilt study in the browser without editing JSON, Python fixtures, or repository code.


This gate occurs **before** high-fidelity electrical-shading production work.


---


### Phase 6.1 — Electrical Shading Contract & Canonical Boundary


**Status: CLOSED — DRIVE WORKING BASELINE; GITHUB SYNCHRONIZATION PENDING.** See `docs/phase61-electrical-shading-contract.md`.


This is the former Phase 6.0 electrical tranche.


Freeze:


- fidelity semantics;
- ModuleTopologyDefinition;
- module local-coordinate convention;
- physical/electrical region taxonomy;
- region-to-substring mapping;
- local electrical irradiance state;
- IV representation;
- bypass model taxonomy;
- module/string/MPPT IV contracts;
- loss-accounting boundary;
- scientific versus execution identity;
- provenance/fallback behavior.


### Phase 6.2 — Canonical Module Topology & Capability Resolution


**Status: IN PROGRESS — topology library + catalog + project/API selection persistence.** See
`docs/phase62-canonical-module-topology-capability.md`.


Implement production topology-library integration against the Phase-6.1 contract:
revision storage/binding, source ingestion, validated reference topologies,
region/cell-parameterization capability evidence, product-facing capability
resolution, and explicit lower-fidelity selection.


Do not infer detailed topology or region electrical parameters from cell count,
bypass-diode count, or whole-module SDM parameters alone.


### Phase 6.3 — Derived Electrical Regions & Local Irradiance


**Status: IN PROGRESS — deterministic region-map and three-channel local-irradiance foundation implemented.** See
`docs/phase63-derived-electrical-regions-local-irradiance.md`.


Derive a deterministic ElectricalRegionMap from existing module geometry plus ModuleTopologyDefinition.


Compute region-level local irradiance while preserving beam, diffuse, and ground channels.


### Phase 6.4 — Level-1 Module-Level Electrical Shading


**Status: IN PROGRESS — topology-independent module-equivalent Level-1 reference path implemented.** See
`docs/phase64-level1-module-electrical-shading.md` and
`docs/phase64-milestone-measuring-stick.md`.


Exercise the complete new vertical data path with one validated whole-module SDM state
per module before introducing bypass complexity. Level 1 does not require module
topology. Existing Phase-6.3 regional irradiance may feed an optional area-weighted
collapse only when it covers the complete module receiver. Electrical mismatch, bypass
and MPPT interaction remain explicitly unmodeled in this tranche.


### Phase 6.5 — Substring / Bypass Reference Kernel


Implement a slow transparent reference solver and analytical bypass-transition fixtures.


### Phase 6.6 — Nonuniform Module IV Assembly


Assemble protected substrings/branches into complete module IV/PV curves.


### Phase 6.7 — General Series String IV


Support non-identical module curves in series while preserving canonical electrical order.


### Phase 6.8 — Parallel Strings & MPPT Operating Point


Combine mismatched string curves at common voltage and separate:


```text
physical combined P-V curve
from
tracker/control assumption
```


The initial reference tracker may use ideal global MPP if explicitly identified.


### Phase 6.9 — Detailed SimulationRun Integration & Loss Ledger


Integrate region irradiance → detailed DC → inverter → PCC.


Keep separate counterfactuals for:


- geometric irradiance reduction;
- electrical mismatch/bypass interaction;
- MPPT interaction.


**Gate B — Detailed-Physics Browser Test:**


The same browser acceptance project can switch fidelity and expose detailed-shading status, limitations, and loss effects without changing canonical design geometry.


### Phase 6.10 — Annual Acceleration & Bounded Persistence


Only after reference correctness:


- affected-region filtering;
- state/curve caching;
- bounded artifacts;
- deterministic equivalence checks;
- performance telemetry.


### Phase 6.11 — Analytical / Independent / Cross-Software Validation


Validation hierarchy:


```text
analytical truth
→ controlled RawiBumi synthetic cases
→ independent open implementation
→ cross-software comparison
→ annual end-to-end attribution
```


Recommended independent electrical reference:


- PVMismatch for compatible cell/module/string/bypass cases.


pvlib may be used for sub-equation/reference checks, but it is not independent evidence where RawiBumi uses the same pvlib implementation internally.


PVsyst remains useful cross-software evidence, not the definition of correctness.


### Phase 6.12 — Closure Hardening & User Acceptance


Freeze:


- no-mismatch regression;
- module mismatch family;
- bypass family;
- string mismatch family;
- parallel/MPPT mismatch family;
- save/reload/reproducibility;
- provider-weather snapshot reproducibility;
- map and blank-workspace equivalence;
- browser end-to-end reference project;
- annual deterministic identity;
- performance evidence;
- Phase-7 handoff.


Only then claim:


```text
────── PV PHYSICS WORKFLOW STABLE ──────
```


## 7. Phase-7 Boundary After This Rebaseline


Phase 7 remains useful and should not be absorbed into Phase 6.


Phase 6 now proves that the intended product surface can exercise the scientific engine.


Phase 7 still owns **product completeness and coherence**, including broader workflow refinement, report generation, complete result exploration, onboarding, error UX, long-running job UX, and the requirement that a normal grid-connected study has no missing core product capability.


Therefore:


```text
Phase 6
= validated PV physics + testable browser vertical slice


Phase 7
= coherent grid-connected V1 product
```


## 8. Immediate Next Action


Phase 6.0A, Phase 6.0B, Phase 6.0C, and Phase 6.0D are closed.


Gate A is closed using the deliberately narrow existing Phase-5 execution envelope:


~~~text
browser-authored project
→ pinned explicit weather source
→ homogeneous execution-plan preflight
→ simulation-ready module
→ homogeneous mppt_template inverter
→ engineering validation
→ existing Phase-5 geometry-aware SimulationRun
→ persisted results
→ save/reopen identity
~~~


The browser now distinguishes canonical design validity from numerical execution
readiness. Valid but currently unsupported explicit-`mppts[]` inverter definitions
remain design-usable and are blocked before Run rather than silently flattened.


Phase 6.1 is **CLOSED for the Drive working baseline**. The electrical-shading
fidelity, topology, region, IV, provenance, fallback, loss-accounting, and
scientific/execution identity boundaries are frozen without activating a production
mismatch solver. Drive-local closure evidence is recorded in
`docs/phase61-electrical-shading-contract.md`, ADR 0055, and
`docs/phase61-closure-handover.md`.


Phase 6.2 is now **IN PROGRESS** in the Drive working repository. The first
production-integration slice adds exact-revision topology indexing/selection,
canonical SourceRecord resolution for topology/parameterization provenance, an
explicit RawiBumi-owned reference topology, and product-facing capability
orchestration over the frozen Phase-6.1 validators/resolver. It does not add a
production mismatch solver.


Continue Phase 6.2 with user/local topology/evidence ingestion, full-stack API tests,
and the minimal browser capability/selection surface.


GitHub remains a transport/synchronization target: PR #74 is draft/open/unmerged.
When GitHub Actions is available again, synchronize the Drive closure-only
documentation changes, run both required workflows on the exact synchronized head,
and merge only that green head. Do not reopen the frozen Phase-6.1 architecture
during synchronization unless a concrete defect is found.