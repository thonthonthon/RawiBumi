# RawiBumi — Phase 6.0C Browser Site / Scene Shell


**Status:** Closed for Phase-6.0C scope  
**Revision:** 0.2  
**Date:** 25 September 2026  
**Baseline:** `main @ c7ae69c2312c4c1aa5085749687b8af12db0dee5`  
**Parent:** `docs/phase60a-product-readiness-contract.md`


## 1. Objective


Phase 6.0C makes the existing engineering backend directly usable through the
first runnable browser product shell.


It does not add new PV physics.


The browser is an interaction and rendering client over canonical RawiBumi
engineering authorities.


```text
browser gesture / engineering form
→ HTTP command
→ existing Python domain kernel
→ canonical revision
→ persisted project workspace bundle
→ derived browser read model
→ Map or Blank Plane rendering
```


No construction-geometry or electrical-topology algorithm is reimplemented in
TypeScript.


## 2. Canonical authorities


The product shell preserves the Phase-6.0A authority split:


```text
Project / Site
    geographic anchor


LocalCoordinateSystem
    engineering coordinate authority


Scene
    surface / obstacle / PV-module geometry authority


Component revisions
    module dimensions and inverter data authority


ElectricalDesignRevision
    String → MPPT → Inverter topology authority


DesignWorkspaceState
    browser-only selection / viewport / display state
```


The new `ProjectWorkspaceBundle` is only a persistence envelope around these
objects.


It is not a new simulation model.


## 3. Runtime architecture


### 3.1 API


The first API runtime uses FastAPI.


Primary orchestration lives in:


```text
apps/api/service.py
apps/api/server.py
apps/api/project_store.py
apps/api/catalog.py
```


The API delegates engineering calculations to:


```text
LocalCoordinateSystem
SceneEditorSession
PVFieldPackingSession
ElectricalTopologyEditorSession
```


### 3.2 Browser


The first browser uses:


```text
React
TypeScript
Vite
MapLibre GL JS
```


The browser renders only read models returned by the API.


## 4. Coordinate-first project creation


A browser project requires:


- project name;
- WGS84 latitude;
- WGS84 longitude;
- IANA timezone;
- optional elevation;
- initial workspace mode.


Coordinates may be:


- entered numerically; or
- selected from the map coordinate picker.


Project creation constructs the canonical:


```text
Site
+
LocalCoordinateSystem
+
empty Scene
+
empty ElectricalDesignRevision
```


with true north as the engineering reference.


## 5. Equivalent workspace modes


### 5.1 Map overlay


The map path is:


```text
canonical Scene local XY
→ LocalCoordinateSystem.local_to_geographic()
→ derived GeoJSON
→ MapLibre renderer
→ contextual base map
```


Map pixels and Web-Mercator distances are never used as construction geometry.


The default development context style is configurable through:


```text
VITE_MAP_STYLE_URL
```


with OpenFreeMap Liberty used when no override is supplied.


The provider/style choice is not canonical engineering state.


### 5.2 Blank engineering plane


The blank path is:


```text
canonical Scene local XY
→ local metric read model
→ SVG engineering plane
```


The renderer shows:


- metric grid;
- X East;
- Y North;
- true-north arrow;
- surfaces;
- obstacles;
- modules.


No map service is required.


### 5.3 Identity invariant


Switching:


```text
Map Overlay
↔
Blank Engineering Plane
```


may modify only workspace/rendering state.


It must not change:


- Project engineering state;
- Scene revision or hash;
- ElectricalDesignRevision or hash;
- component bindings.


This invariant is regression-tested.


## 6. Geometry workflow


Phase 6.0C exposes a deliberately constrained first editor workflow.


### 6.1 Support surface


The browser supplies exact parameters for a rectangular support surface:


- local X;
- local Y;
- width;
- height;
- base elevation;
- surface type.


The API executes `SceneEditorSession.draw_rectangle()`.


### 6.2 Obstacle


The first obstacle primitive is a box with:


- local X/Y;
- width;
- depth;
- base elevation;
- height.


The API executes `SceneEditorSession.draw_box_obstacle()`.


The underlying canonical editor already supports additional primitives; they
are not all exposed in the first product shell.


### 6.3 Existing-scene edit


The browser also exposes an explicit move operation for existing support
surfaces:


```text
selected surface + ΔX + ΔY
→ SceneEditorSession.move()
→ new canonical Scene revision
```


The service fails closed when the surface already supports a PV field. Moving
a populated support surface without an explicit layout-impact/rebuild decision
would leave dependent module placement ambiguous, so that behavior is deferred
rather than guessed.


## 7. PV-field workflow


The browser selects:


- support surface;
- module revision;
- orientation;
- azimuth;
- tilt;
- module gaps;
- row pitch;
- mounting height;
- perimeter setback;
- obstacle setback.


The API executes:


```text
PVFieldPackingSession.create_field()
→ explicit fill_area()
```


Module coordinates are therefore produced by the existing deterministic
packing kernel.


The browser never calculates module placement.


## 8. Reference component bootstrap


The repository previously provided import mechanisms and schemas but no small
redistributable component set suitable for an out-of-box browser test.


Phase 6.0C adds two explicitly synthetic components:


```text
RawiBumi Reference REF-MOD-650
RawiBumi Reference REF-INV-150K
```


They are:


- synthetic;
- redistributable;
- clearly labeled as non-vendor data;
- intended for product-shell testing only.


When selected, their immutable revisions are pinned into the project workspace
bundle.


They do not replace the Open Component Library or PAN/OND/user imports.


## 9. Electrical workflow


The browser exposes three explicit operations.


### 9.1 Add inverter


```text
selected inverter revision
→ ElectricalTopologyEditorSession.add_inverter()
→ canonical MPPT instances
→ PCC connection
```


### 9.2 Create strings


The user selects string length.


```text
enabled unstrung modules
→ explicit create_strings()
→ row-major deterministic grouping
→ draft unassigned strings
```


Unassigned disabled strings are a valid draft state and are reported as
`draft`, not structural errors.


### 9.3 Assign MPPT


```text
unassigned strings
→ explicit assign_strings()
→ balanced MPPT allocation
→ enabled assigned strings
```


The browser does not silently string or assign modules merely because a PV
field exists.


## 10. Persistence and reopen


The first self-hosted store is a filesystem JSON store.


Writes use:


```text
temporary file
→ flush
→ fsync
→ atomic replace
```


The default local path is:


```text
var/projects/
```


and can be overridden with:


```text
RAWIBUMI_PROJECT_STORE
```


The persisted envelope contains:


- Project;
- Scene;
- ElectricalDesignRevision;
- pinned component revisions;
- SiteWorkspaceBootstrap;
- DesignWorkspaceState.


Save/reopen regression tests require identical canonical Scene and Electrical
hashes.


## 11. Browser workflow available after 6.0C


The first runnable shell supports:


```text
Create Project
→ enter/pick coordinate
→ Map Overlay OR Blank Plane
→ add support surface
→ add box obstacle
→ select module
→ create/fill PV field
→ add inverter
→ create strings
→ assign strings to MPPTs
→ inspect topology
→ inspect canonical hashes
→ save
→ return to project list
→ reopen
```


## 12. Validation


Phase 6.0C adds regression coverage for:


- reference component schema validity;
- coordinate-first project creation;
- canonical surface/obstacle commands;
- canonical existing-surface move and dependency guard;
- deterministic PV packing through the existing kernel;
- inverter/string/MPPT topology through the existing kernel;
- project bundle schema;
- derived GeoJSON from canonical local geometry;
- map/blank engineering-identity equivalence;
- canonical hash stability across save/reopen;
- API health/catalog/create/list/reopen flow;
- TypeScript production build.


Existing Phase-5 numerical validation remains in the same blocking workflow.


## 13. Non-goals


Phase 6.0C deliberately does not yet implement:


- weather-source selection UI;
- weather-file upload UI;
- SimulationRun execution from the browser;
- results/loss dashboards;
- direct drag/vertex CAD interaction;
- all existing Scene primitive tools;
- 3-D browser inspection;
- authentication/authorization;
- multi-user concurrency;
- database-backed project persistence;
- background job queues;
- production hosting configuration.


Weather → simulation → results is Phase 6.0D.


Direct-manipulation CAD capabilities may be incrementally exposed after the
first vertical user-test flow; they must continue to call canonical domain
commands rather than creating a client-side engineering authority.


## 14. Exit criterion


Phase 6.0C closure requires:


1. the API integration tests pass;
2. the browser production build passes;
3. a project can be created with a coordinate;
4. map and blank modes render the same canonical scene;
5. a simple support surface, obstacle and PV field can be created;
6. an existing support surface can be edited through a canonical Scene command
   before dependent PV layout exists, and unsafe dependent edits fail closed;
7. module dimensions come from a pinned component revision;
8. inverter/string/MPPT topology can be created explicitly;
9. project save/reopen preserves canonical identities;
10. no existing Phase-5 regression or benchmark is broken.


Phase 6.0D may then wire weather selection/import, existing Phase-5
SimulationRun execution and basic energy/loss results into this shell.




## 15. Closure evidence


Phase 6.0C is closed for the defined scope.


Closure evidence includes:


- the first runnable `apps/web` React/TypeScript/MapLibre workspace;
- the first runnable `apps/api` FastAPI project surface;
- canonical Scene and electrical mutations executed by existing Python domain kernels;
- map-overlay and blank-plane identity-equivalence regression coverage;
- save/reopen canonical hash regression coverage;
- browser production build as a blocking CI step;
- existing Phase-5 numerical regression and benchmark suite retained in the same blocking workflow.


Weather selection/import, SimulationRun execution, validation UX, and basic
energy/loss results remain intentionally unclaimed here and are the Phase-6.0D
vertical-slice scope.




## 14. Map-context resilience hardening


The map renderer is explicitly non-authoritative.


The default development context currently uses the configurable MapLibre style:


```text
https://tiles.openfreemap.org/styles/liberty
```


The style URL remains replaceable through `VITE_MAP_STYLE_URL`; a self-hosted
style can therefore be used without changing canonical project geometry.


The browser keeps the latest canonical Scene GeoJSON in a renderer ref so a
late map-style load cannot install stale engineering geometry.


Map style/tile errors are non-blocking. The browser reports that contextual map
data is unavailable and directs the engineer to Blank Plane mode. Project,
Scene, ElectricalDesignRevision and local metric geometry remain usable without
a live map service.


This preserves the Phase-6.0A invariant:


```text
map availability
!=
engineering-workspace availability
```