# RawiBumi — Phase 6.0D Browser UAT Vertical Slice


**Status:** Closed for Phase-6.0D scope  
**Revision:** 0.4  
**Date:** 25 September 2026  
**Baseline:** main @ fa6b418504604761f65b59ee15cdd2cb4e0c1fd8  
**Parents:** Phase 6.0A product-readiness contract, Phase 6.0B weather acquisition, Phase 6.0C browser shell.


## 1. Objective


Phase 6.0D closes the pre-physics product-readiness sequence by making one representative fixed-tilt PV study executable from the browser without JSON, Python, repository-fixture editing or direct database access.


~~~text
Create Project
→ anchor Site coordinate
→ Map Overlay or Blank Plane
→ create support surface / obstacle
→ select simulation-ready module
→ fill PV field
→ create inverter
→ create strings
→ assign MPPT
→ select one explicit weather source
→ acquire and QC weather
→ validate exact design
→ run existing Phase-5 geometry-aware SimulationRun
→ inspect energy / monthly output / loss ledger / findings
→ save and reopen
~~~


No new PV physics is introduced by this tranche.


## 2. Authority chain


The browser remains orchestration only.


~~~text
browser action
→ FastAPI product command
→ canonical domain object/revision
→ engineering validation
→ canonical SimulationRun
→ persisted canonical result artifacts
→ browser read model
~~~


The browser does not calculate construction geometry, PV packing, string/MPPT topology, weather resource projection, solar position, POA transposition, near-shading physics, module IV behavior, inverter conversion, or loss accounting.


## 3. Weather workflow


The browser exposes the provider/source catalog from Phase 6.0B.


The first available source is:


~~~text
provider_id = open_meteo
source_id   = open_meteo_archive_era5
provider model request = models=era5
~~~


The source-isolation rule remains:


~~~text
provider transport
!= source product
!= source-owned resource-generation method
!= RawiBumi canonical mapping
~~~


The browser does not present Best Match, ERA5-Seamless or cross-source fallback. A live acquisition failure is explicit.


Canonical acquired weather is persisted separately from the project workspace bundle as WeatherDataset metadata JSON, canonical weather-series Parquet, acquisition-manifest JSON, and a content-addressed raw provider response. Simulation consumes the pinned canonical weather revision and never calls a live provider.


## 4. Simulation-ready UAT components


Phase 6.0D adds a synthetic simulation-ready module source:


~~~text
RawiBumi Synthetic SYN-MOD-550-UAT
source format: PAN-compatible synthetic reference
revision: mod-rawibumi-uat-550-r1
~~~


Its detailed single-diode parameters are derived and validated through the existing RawiBumi PAN ingestion/model-validation path.


Phase 6.0D now separates two synthetic inverter roles:


~~~text
inv-rawibumi-ref-150k-r1
    canonical design/editor reference
    explicit mppts[]
    valid design representation
    NOT executable by the current homogeneous Phase-5 worker


inv-rawibumi-uat-150k-r1
    dedicated Gate-A execution reference
    homogeneous mppt_template
    2 identical MPPTs
    3 inputs per MPPT
    voltage-dependent efficiency curves
    executable by the current Phase-5 worker
~~~


The product does not silently flatten explicit `mppts[]` into a template. The
dedicated UAT inverter states the homogeneous runtime assumption directly in its
canonical component definition.


These are regression/UAT assets, not representations of commercial products.


## 5. Immutable simulation launch snapshot


The product workspace is editable state. Simulation requires immutable, internally coherent revisions.


The existing simulation bridge rejects stale project-revision cross-references. Phase 6.0D does not weaken that gate. At launch it creates a simulation-only immutable electrical snapshot:


~~~text
current canonical Scene revision
+ current canonical ElectricalDesignRevision
+ current pinned component revisions
+ selected canonical WeatherDataset revision
        ↓
fresh simulation ProjectRevision ID
+ fresh ElectricalDesignRevision snapshot ID
+ re-bound embedded project_revision_id fields
        ↓
engineering validation
        ↓
SimulationRun
~~~


The editable design is not overwritten. The launch snapshot records the electrical revision it supersedes.


## 6. Engineering validation and execution-readiness gates


Engineering validity and numerical executability are separate contracts.


Before numerical execution the browser flow first evaluates the existing derived
`SimulationExecutionGroupPlan` and the selected component representations.


The current Gate-A execution envelope requires:


~~~text
pinned WeatherDataset revision
+ exactly one homogeneous Phase-5 execution group
+ homogeneous string length / module revision / orientation state
+ inverter represented by mppt_template
+ simulation-ready module SDM
+ supported voltage-dependent inverter efficiency model
~~~


A valid canonical inverter using explicit `mppts[]` remains usable for design,
but the current Phase-5 homogeneous worker does not execute it. The product
therefore returns an explicit execution-readiness finding before launch rather
than allowing the numerical worker to raise a low-level exception.


After execution readiness passes, the browser flow invokes the existing
`validate_engineering_design()` rule set with explicit design conditions.


Blocking engineering or execution-readiness findings stop physics. The product
does not convert them into warnings.


## 7. Phase-5 physics used by UAT


The browser UAT runs the existing geometry-aware fixed-tilt chain:


~~~text
direct beam
    exact polygon beam visibility


sky diffuse
    weighted sky-dome / directional visibility


ground-reflected
    weighted lower-hemisphere visibility
~~~


The browser configuration uses module receiver granularity, exact cache policy, full compiled module polygons with 1×1 receiver resolution, and electrical_shading_method = null. No occluder chord-tolerance approximation is requested because the current Phase-5 reference geometry kernels explicitly execute the full compiled polygons.


Geometry therefore affects irradiance before the existing homogeneous electrical worker. This tranche does not claim detailed electrical mismatch/bypass shading; that remains Phase 6.1+.


## 8. Result surface


The browser exposes a deliberately small auditable subset of the existing SummaryResult:


- executed-period energy;
- annual energy when coverage is a complete year;
- specific yield;
- performance ratio;
- peak AC power;
- monthly energy;
- named electrical loss ledger;
- shading-energy-loss field when actually available;
- validation failures when a run cannot proceed.


No browser-specific yield formula is introduced. The full canonical run package remains persisted by the existing simulation artifact layer.


## 9. Native RawiBumi UAT reference


The acceptance regression is authored through the product service, not loaded from a PVsyst-derived Scene.


~~~text
new RawiBumi Project
→ WGS84 site coordinate
→ rectangular roof
→ box obstacle
→ synthetic RawiBumi simulation-ready module
→ canonical PV packing
→ synthetic RawiBumi inverter
→ canonical strings / MPPT assignment
→ synthetic Open-Meteo-shaped deterministic UAT response
→ explicit ERA5 adapter/mapping path
→ canonical weather revision
→ engineering validation
→ Phase-5 SimulationRun
~~~


The weather fixture is frozen only to keep blocking CI deterministic. It is a synthetic provider-shaped response designed to exercise the explicit ERA5 adapter, canonical mapping, weather persistence and solar-aware execution path. It is **not** claimed to be an actual ERA5 observation, climatological reference, or scientific validation dataset.


Its irradiance components are deliberately internally consistent for the UAT execution gate; scientific weather-source validation remains separate from this product-integration regression.


## 10. Deterministic CI


Blocking CI does not require live Open-Meteo, a map tile server, proprietary PAN/OND files, PVsyst desktop, or external databases.


The 6.0D regression verifies that the web application builds, explicit weather-source identity survives acquisition, no RawiBumi resource projection is applied, canonical weather can be persisted/reloaded, a browser-authored project reaches the existing SimulationRun, run artifacts are persisted, project reopen retains weather selection/run history, and existing Phase-5 benchmark/validation gates remain green.


## 11. User acceptance gate


Gate A is satisfied when a PV engineer can complete the supported study from the browser with no source-code interaction.


The supported 6.0D UAT envelope is intentionally narrow:


~~~text
fixed tilt
one homogeneous executable orientation/group
one supported inverter topology
explicit string/MPPT assignment
one explicit weather source
Phase-5 geometry-aware shading
~~~


Unsupported physics must fail explicitly rather than being silently flattened.


The browser is ready for engineering usability feedback after this gate, but this is not yet the complete V1 product.


## 12. Non-goals


Phase 6.0D does not implement detailed electrical shading/mismatch, bypass diode operation, combined module/string IV curves, MPPT local/global optimum behavior under mismatch, multiple weather-source combination, TMY synthesis, full weather-file upload UI, generic 3D CAD, multi-user/server authorization, production reporting templates, or advanced result analytics.


## 13. Exit criterion


Phase 6.0D is closed when:


1. the native product-level UAT regression reaches a completed canonical SimulationRun;
2. browser TypeScript/Vite build passes;
3. all schema/unit/integration tests pass;
4. retained Phase-5 benchmark/validation gates remain green;
5. weather/source and run identities survive save/reopen;
6. unsupported conditions remain fail-closed;
7. the exact tested PR head is merged.


After closure:


~~~text
6.0A  product/weather/browser contracts       CLOSED
6.0B  coordinate-driven weather acquisition   CLOSED
6.0C  browser site / scene shell              CLOSED
6.0D  browser UAT vertical slice              CLOSED
6.1   electrical shading contract             NEXT
~~~




## 14. Closure evidence


Phase 6.0D closure follows the complete validation workflow. Earlier failed UAT
runs exposed and corrected two integration contract mismatches:


1. an unsupported geometric chord-tolerance request was removed in favor of the
   already-executable full compiled polygon contract;
2. an explicit-`mppts[]` design inverter reached a worker that only executes
   homogeneous `mppt_template`; this is now blocked by preflight and the UAT uses
   a dedicated homogeneous-template inverter.


Closure is defined by the exact PR-head validation workflow.


The final UAT path must demonstrate, without live external services in blocking CI:


~~~text
browser-authored canonical project
→ explicit source-product weather acquisition through the Phase-6.0B adapter
→ persisted WeatherDataset revision
→ exact-design engineering validation
→ executable Phase-5 geometry-aware shading configuration
→ canonical SimulationRun
→ persisted SummaryResult / timeseries artifacts
→ browser/API result read model
→ project reopen with weather/run identity intact
~~~


The UAT provider fixture is an integration fixture, not meteorological truth. The
Phase-5 execution-scope guard remains active; unsupported geometric resolution,
heterogeneous electrical execution, or future detailed-mismatch requests must
still fail closed.


The corrected implementation passed the complete browser build, Python regression
suite, and retained Phase-5.8 / 5.8H / 5.9 / 5.10 / 5.11 validation gates before
closure. The final PR head is required to remain green through merge.


Gate A is therefore closed. The next tranche is Phase 6.1 — Electrical Shading
Contract & Canonical Boundary.