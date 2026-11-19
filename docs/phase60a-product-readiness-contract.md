# RawiBumi — Phase 6.0A Product-Readiness Contract


**Status:** Frozen implementation contract  
**Revision:** 0.1  
**Date:** 25 September 2026  
**Baseline:** `main @ 436fbdf33950c7a15d363267ab4700131ae432ce`  
**Parent:** `docs/phase60-pre-physics-rebaseline.md`  
**Decision:** `docs/decisions/0053-phase6-user-test-weather-provider-boundary.md`


## 1. Objective


Phase 6.0A freezes the product-facing contracts required before implementing coordinate-driven weather acquisition and the first runnable browser workflow.


It adds no new PV physics.


The governing sequence after this tranche is:


```text
6.0A  freeze product/weather/browser boundaries
  ↓
6.0B  implement weather acquisition
  ↓
6.0C  implement browser site/scene shell
  ↓
6.0D  run first browser user-test vertical slice on Phase-5 physics
  ↓
6.1+  electrical shading and high-fidelity DC physics
```


The Development Phase 6 maturity objective remains electrical shading and high-fidelity DC physics.


## 2. Frozen Authorities


RawiBumi already has distinct authorities. Phase 6.0A preserves them.


```text
Site
    geographic anchor authority


LocalCoordinateSystem
    engineering spatial authority


Scene
    physical geometry authority


ElectricalDesignRevision
    string / MPPT / inverter connectivity authority


Component revision
    component physical/electrical data authority


WeatherDataset revision
    meteorological time-series authority for one simulation


SimulationConfiguration
    model / loss / fidelity selection authority
```


The browser must not create a second hidden engineering model.


External weather services must not become direct simulation authorities.


## 3. Coordinate-First Project Bootstrap


A normal browser project begins with a site coordinate.


Required project anchor:


```text
latitude
longitude
timezone
optional elevation
true-north reference
LocalCoordinateSystem
```


The site coordinate is required for both initial workspace modes.


### 3.1 Map-overlay workspace


```text
site coordinate
→ map context
→ local engineering XY
→ constrained PV CAD overlay
```


The map supplies context only.


### 3.2 Blank engineering-plane workspace


```text
site coordinate
→ local engineering XY
→ blank metric grid + true north
→ constrained PV CAD
```


A map tile or imagery service is therefore not required to design or simulate a project.


### 3.3 Equivalence invariant


For identical canonical site and scene state:


```text
map-overlay workspace
and
blank engineering-plane workspace
```


must produce identical canonical geometry, electrical state and simulation input identity.


Map viewport, zoom, imagery visibility and other renderer state are not simulation inputs.


## 4. Browser-to-Canonical Boundary


The first browser is an interaction and rendering client over the existing engineering domain.


It shall not reimplement the numerical geometry kernel in TypeScript.


The interaction pattern is:


```text
user gesture / form input
→ explicit browser command
→ canonical engineering operation
→ validated canonical revision
→ renderer projection
```


The browser may hold ephemeral workspace state such as:


- current tool;
- selection;
- map viewport;
- panel state;
- camera;
- layer visibility;
- snap display state.


It must not hold an authoritative shadow copy of:


- surface geometry;
- module coordinates;
- component revision bindings;
- string membership;
- MPPT assignment;
- weather revision;
- simulation model selections.


Save/reopen operates on canonical engineering state, not renderer state.


## 5. Meteorological Source Isolation


### 5.1 Governing rule


For the current architecture, **every meteorological resource source is treated as a separate source product**.


Examples include, without implying equivalence:


```text
Open-Meteo / ERA5
Open-Meteo / ERA5-Land
Open-Meteo / another explicitly selected upstream model
CAMS solar-radiation product
PVGIS product / dataset
NASA POWER product
Meteonorm file
TMY3 file
EPW file
PVsyst Standard weather file
measured user weather
```


The source identity is not erased merely because two products are accessed through the same API transport.


### 5.2 Provider transport is not source identity


The following concepts are separate:


```text
provider / transport
    how RawiBumi obtains data


source product
    the specific meteorological dataset/model/product selected


source-owned projection / reconstruction method
    how that source represents, reconstructs, interpolates,
    downscales, projects or otherwise generates weather at the site


    NOTE: "meteorological projection" here is resource-generation
    semantics, not a cartographic/map coordinate projection.


canonical mapping
    how RawiBumi translates delivered variables, units and timestamps
    into WeatherDataset semantics
```


For example, an Open-Meteo endpoint may expose multiple upstream model products. Those products remain separate `source_id` values even when one adapter performs the HTTP transport.


Phase 6.0B should request an explicit upstream source/model where the provider API supports that choice. A provider-side "best match", automatic model fallback or blended endpoint must not be used when it would erase source-product identity. If a provider necessarily performs dynamic source selection, the resolved source identity must be returned and persisted; unresolved source identity is not equivalent to an explicitly selected source.


### 5.3 Source-owned projection semantics


At this stage:


```text
resource projection authority = source/provider product
```


RawiBumi does **not** apply a common meteorological projection method across sources.


RawiBumi does not presently:


- blend multiple sources;
- average multiple sources;
- bias-correct one source against another;
- spatially interpolate several source products into an RawiBumi resource;
- reconstruct one source using the method of another;
- create an RawiBumi ensemble;
- automatically select a scientifically "best" source;
- silently fall back to another source when the selected source is unavailable.


Such capabilities, if ever introduced, require a separate future model family, validation program and provenance contract.


They are deliberately deferred well beyond the initial provider-acquisition work.


### 5.4 What normalization is still allowed


Source isolation does not prohibit canonical semantic normalization.


RawiBumi may deterministically perform and record:


- source field → canonical field mapping;
- unit conversion;
- explicit timestamp-convention normalization;
- timezone normalization;
- calendar normalization where already defined by an importer;
- QC;
- explicitly selected RawiBumi resampling after ingestion;
- later irradiance decomposition when source variables require it.


These are RawiBumi transformations and must remain separately recorded.


They must not be described as reproducing or replacing the source's own meteorological projection method.


### 5.5 No source ranking in the engine


Implementation order is not scientific precedence.


Open-Meteo may be the first live transport adapter implemented in Phase 6.0B, but this does not make an Open-Meteo-exposed source the preferred physical truth.


Likewise, CAMS, PVGIS, NASA POWER, Meteonorm and user files are not assigned a global quality rank by the engine.


The user selects a source product explicitly.


A future comparison UI may present multiple separately simulated source cases without merging them.


## 6. Weather Acquisition Contract


The frozen acquisition chain is:


```text
canonical Site coordinate
        ↓
explicit source-product selection
        ↓
WeatherProviderAdapter transport
        ↓
raw provider payload
+ request manifest
+ source-product identity
+ source-owned method metadata when available
        ↓
source-specific semantic adapter
        ↓
canonical WeatherDataset revision
        ↓
QC
        ↓
optional explicit RawiBumi transformations
        ↓
pinned WeatherDataset revision
        ↓
SimulationRun
```


No simulation function calls a live provider.


### 6.1 Required source identity


A live acquisition must identify, where the source exposes the information:


```text
provider_id
source_id
source_product_name
source_product_version / release if available
adapter_id
adapter_version
requested coordinate
provider-returned coordinate / grid location if reported
requested period
returned coverage
native timestep
source variable names
source time convention
source-owned projection / reconstruction method identifier or note
retrieval timestamp
raw payload SHA-256
canonical mapping version
resulting WeatherDataset revision/hash
```


Unknown source method metadata remains unknown. RawiBumi must not invent it.


### 6.2 Selected-source failure behavior


If the selected source cannot satisfy the acquisition request:


```text
selected source unavailable
→ explicit acquisition failure/finding
→ user may retry or choose another source
```


Not:


```text
selected source unavailable
→ silently substitute another source
```


### 6.3 Reproducibility


A completed simulation pins the resulting WeatherDataset revision.


Re-running that simulation does not re-query the live provider.


A fresh provider retrieval is a new acquisition event and may produce a new WeatherDataset revision.


## 7. Deterministic Testing Contract


Blocking CI must not depend on provider availability or mutable upstream data.


For each implemented live adapter:


```text
frozen raw provider response
+ frozen request manifest
        ↓
adapter
        ↓
deterministic canonical WeatherDataset
        ↓
expected canonical hash / semantic assertions
```


Optional live smoke tests may detect:


- provider outage;
- endpoint incompatibility;
- schema drift;
- authentication/configuration problems.


Live smoke tests do not define numerical reference truth.


## 8. First Browser User-Test Contract


The first user-test vertical slice must support:


```text
Create Project
→ enter/select coordinate
→ choose Map Overlay or Blank Plane
→ create/edit support surface
→ create simple obstacle(s)
→ select module revision
→ create/fill PV field
→ create string(s)
→ assign MPPT and inverter
→ select one meteorological source OR import one weather file
→ validate design
→ run existing Phase-5 geometry-aware simulation
→ inspect basic monthly/annual energy and explicit loss outputs
→ save project
→ reopen project
→ reproduce canonical design state
```


External user testing must not require:


- JSON editing;
- Python scripting;
- repository fixture editing;
- direct database manipulation.


## 9. Phase 6.0A Non-Goals


Phase 6.0A does not implement:


- live weather retrieval;
- source blending;
- RawiBumi meteorological projection;
- meteorological bias correction;
- weather ensemble generation;
- automatic weather-source ranking;
- production browser rendering;
- new scene physics;
- electrical shading;
- bypass solving;
- string IV aggregation.


## 10. Phase 6.0A Acceptance Gate


Phase 6.0A is complete when the repository freezes all of the following:


- coordinate-first project bootstrap;
- map-overlay / blank-plane equivalence;
- browser → canonical command boundary;
- weather provider transport versus source-product identity;
- separate source-owned projection semantics;
- no source blending/ranking/automatic fallback;
- acquisition provenance and immutable snapshot identity;
- deterministic provider-test strategy;
- first browser user-test acceptance flow;
- Phase-6 versus Phase-7 product boundary.


Machine-readable contract schemas accompany this document for:


- `SiteWorkspaceBootstrap`;
- `WeatherSourceAcquisitionManifest`.


After this gate, Phase 6.0B and 6.0C may proceed without reopening these boundaries unless implementation reveals a concrete contradiction.