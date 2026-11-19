# RawiBumi web workspace — Phase 6.0D


The Phase-6.0D browser is a React + TypeScript interaction/rendering client over
the canonical RawiBumi Python engineering API.


## Run locally


Terminal 1, from the repository root:


```bash
python -m pip install -r requirements-validation.txt
python -m pip install -r apps/api/requirements.txt
uvicorn apps.api.server:app --reload --host 127.0.0.1 --port 8000
```


Terminal 2:


```bash
cd apps/web
npm install
npm run dev
```


Open `http://127.0.0.1:5173`.


## Frontend toolchain (Phase F, step F0)


How to propose a change is in the repository's `CONTRIBUTING.md`. The design system is in `DESIGN.md` in this folder.


```bash
npm ci                         # pinned dependencies
npm run dev:demo               # in-browser demo engine, no Python needed
npm run verify                 # generated-file checks, boundaries, typecheck, unit tests, build, design gate
npx playwright install chromium && npm run test:e2e   # browser smoke + accessibility (demo build)
npm run test:live              # plan tools against a real API on :8000 (start it first)
```


- **Engine access:** `src/engine/adapter.ts` defines `EngineAdapter`. Screens use `engine` from `src/client.ts`, and the demo adapter must implement every method.
- **Tokens:** `src/ui/tokens.json` is the source. `npm run gen:tokens` writes `src/ui/tokens.css` and the `DESIGN.md` front matter.
- **Schema types:** `npm run gen:types` writes `src/generated/schemas/` from every `*.schema.json` in the repository. `npm run gen:openapi` writes API types from a running API.
- **Quality baselines:** files in `quality/` may only go down. The design detector, axe and the hard-coded colour count are ratchets.
- **Dependencies:** approved packages and versions are in `docs/frontend-dependencies.md` at the repository root.
- **Full detector scan:** `npm run quality` scans source files only. For the rules that need a rendered page (tiny text, low contrast), run `npx impeccable detect http://127.0.0.1:5173` against the dev server.
- **Renderer check (F2, ADR 0010):** in demo mode open `/?synthetic=100000&perf`, pick a project, go to Electrical (Alt+5), then drag the plan with the right mouse button. The readout at top right shows frames per second (target 30 or more), script time per frame and the last pick time (target 16 ms or less). The synthetic layout is a renderer test, never a placement result. If the plan shows a WebGL message, turn on hardware acceleration in the browser.
- **Plan tools (F3, ADR 0012):** V select, M move, R rotate, B rectangle roof, P polygon roof, H hole, O box obstacle, E polygon obstacle, K keep-out, D measure.
- **Imagery (UX1):** the landing site map is larger and can be expanded to most of the window, with "Zoom to point". It has a Streets / Satellite / Hybrid switch; Satellite and Hybrid stay disabled, with "Set up imagery provider", until a bring-your-own-key XYZ provider is set up (template with `{key}`, attribution, terms accepted). That provider and its key live only in this browser's storage. In a project, the Site panel's Imagery section turns on the satellite underlay from that provider, and uploads an image overlay (PNG, JPEG or WebP, up to 10 MB and 8,192 px per side). The overlay is calibrated with the form (m/px across and down, rotation, top-left X/Y, committed on Enter or blur) or on the plan: drag to move, a corner to scale (Shift keeps the aspect ratio), and the round handle to rotate. Each gesture is one undo step. Two-point calibration picks two points and takes the true distance, then locks the overlay. A locked overlay ignores the pointer, and Lock, Unlock and Calibrate are also in the plan menu. Everything is saved in the project's `imagery` section, never in the scene.
- **Project files (DATA1):** the project list has "Import project", and each project has "Export…" (with "Include saved results", ticked by default) and "Backups…" (every save is kept, the newest 20, with Restore). A damaged project is listed as unreadable with its reason and "Restore from backup…". The Export step also offers the project file. The demo hides these controls.
- **Row-to-row shading (RB-4D):** every simulation includes module self-shading. Results notes runs saved before this (no `module_self_shading` on the run) as possibly optimistic for multi-row layouts.
- **Copy and paste (UX3):** Ctrl/Cmd+C (or Copy in the plan menu) copies the selected roof, obstacle or keep-out; Ctrl/Cmd+V pastes it with its centre at the pointer, the menu's Paste at the right-click point, and a paste without a pointer lands beside the original. A roof is pasted with its PV fields (one engine `copy` with `with_pv`), unstrung, in the same project only, as one undo step. The clipboard refers to its source, so a paste copies the source as it is then. Paste explains why it can't run (nothing copied, another project, source deleted). Selected page text keeps the browser's own copy.
- **Vertices (UX3):** a click or right-click on a vertex handle selects it, and the plan and the Inspector share the selection. The Inspector's vertex table highlights the selected vertex, selects one when you click its row, and has a delete button per vertex, disabled with its reason (3 vertices, locked, busy, draft edits pending).
- **Plan menu (UX2):** right-click, Shift+F10 or the Menu key opens a menu for what is under the pointer, or for the selection: Undo and Redo; vertex delete; insert vertex, edge length and reference edge on an edge; properties, zoom, duplicate (one engine `copy`), move, rotate, add hole, lock, hide and delete on an object; module and table deletes; select all, clear selection, zoom to all and the step's tools on empty plan. Disabled items stay visible with their reason. Every item runs the existing action (delete keeps its confirmation). A right-drag still pans. Clicking a vertex handle without dragging selects the vertex; Delete then removes the vertex, and Escape clears it before the object. A selected roof shows its vertex letters (as in the Inspector), the hovered edge, the reference edge, a downhill arrow and its high and low vertices; "Pick on plan" in the Inspector sets the reference edge by clicking it. The plan canvas exposes its view transform read-only as `data-plan-view` for live tests.
  - With a tool active, type a point and press Enter: `x,y`, `@dx,dy` or `d<bearing`.
  - Hold Alt to place a point without snapping, and Shift for 15° steps.
  - Double-click a dimension to type an exact length.
  - Arrow keys nudge by 0.1 m (1 m with Shift).
  - Z zooms to the selection; Z twice zooms to everything.
  - Shift+? lists every key.
- **PV layout (F4, ADR 0013):** the Fill zone panel (B5) previews the engine's fill live, with the module count in portrait and in landscape, before Apply.
  - In the plan, click a module to select it, and drag it to move its table.
  - Delete removes the selected modules; Shift+Delete removes their tables.
  - Every edit pins its table, and a re-fill keeps pinned tables, showing what it adds and removes.
  - One fill is one undo step.
  - The golden case is a 12 × 8 m roof with the "2 × 1 m golden-case module", 2 rows per table, 5 cm gaps, a 1 m aisle and a 40 cm setback: 30 portrait, 25 landscape.
  - Against the real engine, the preview needs proposal 0003. A one-row-per-table fill already goes through `POST /pv-fields`.
- **Electrical (F5, ADR 0014; S14a):** the tools are S string path, A assign brush, L lasso, X split, J join, R reverse, M move module and W swap modules.
  - `[` and `]` step the target MPPT; 1–9 pick an MPPT within the inverter.
  - String path: click or drag modules in wiring order, then Enter. Backspace removes the last module; Esc cancels.
  - Move module: click a strung module (a ring marks it), then the module whose place it takes; Shift+click puts it just after. Delete takes the picked module out of its string. Swap modules: click two strung modules. Esc drops a pick.
  - Uniform strings: row by row, or serpentine (every other row of a field reversed).
  - The task panel has the topology tree (inverter → MPPT → string, with voltage bars and live-check icons), the selection actions (string the selection, assign, unassign, delete, Replicate pattern) and a notation editor per inverter. The notation editor shows a diff against the engine and has Apply and Discard.
  - The string table sits under the stage.
  - Each gesture is one engine command and one undo step.
  - Against the real engine, row-by-row uniform strings and Assign unassigned go through `POST /strings` and `POST /assignments`; split, join, reverse, move, swap, serpentine strings, notation Apply, Replicate pattern, the orientation rule and pairing go through `POST /electrical/commands`.
  - Orientation rule (S14b): the tolerance (at most 1°, between module normals) and a per-MPPT override with a reason are saved in the design and undoable. Within the tolerance the simulation runs the strings as one group; beyond it an override silences the warning, but the run stays blocked.
  - Pairing chips save the inverter's paired fields (advisory). Notation Apply draws from them, or from every field when none are paired. Replicate pattern works on explicit tables; on generated fields the button explains why it's unavailable.
  - Live checks come from the engine with every project view (`topology_checks`, S14a): the design validation at the readiness design temperatures, shown per string, never enforced. The demo uses its own illustrative STC rule.
- **SLD (F6, ADR 0015):** the SLD view is generated from the assignment.
  - Clicking a string, MPPT or inverter selects its modules; Shift adds, Enter works from the keyboard, Escape clears, and double-click opens the plan. A selection made on the plan or in the string table shows in the SLD, full or partial.
  - **Symbol sheet** lists the 14 in-house symbols with their terminals. The SLD draws them with the same component.
- **Results and report (F7, ADR 0016):**
  - Results show the run's key figures, S10's result checks (pass, not available, fail), monthly bars, the loss waterfall and the 52 × 24 heatmap with its coverage (ECharts), and daily profiles (uPlot).
  - Demo data is stamped. Against the real engine (S15), monthly losses, meteo and PR, the 52-week heatmap and daily profiles come from the run's stored series (`GET .../timeseries`). Curtailment and load wait for S19. Each run lists the readiness warnings it was launched with ("not recorded" for older runs).
  - Export → numerical files: CSV and/or Parquet, plus the full deliverable (on by default): a monthly table, the summary, findings and the run record, with SHA-256 hashes in the manifest.
  - kWp everywhere is the DC nameplate: the datasheet nominal power, else STC Pmp (D14).
  - Annual energy exceedance (UNC1): Results shows the engine's P50–P95 for a completed annual run, with P99 marked not qualified, plus the basis and the "model-based, assumption-based" label.
    - The ledger editor offers U1's six categories, with their double-count guidance and no numbers. Each term needs a σ (percent of the mean, or kWh), a source and a justification, plus a correlation basis.
    - Saving is one undo step.
    - The HTML report shows the same block in its KPI chapter, and the ledger in its Assumptions chapter. The demo mirrors the rules, stamped synthetic.
  - Export → **Report**: preview the HTML report, download it as one self-contained file, print to PDF (A4). The plan figure is drawn by the plan's own renderer and the SLD by the SLD component. A blocking rule failure stops the report.
  - **Design basis (RES1):** a run whose design fingerprint differs from the current design shows "These results are from an earlier design. Run again to update." A run saved before design tracking shows a neutral note instead. Either way Results shows only figures saved with the run (capacity from `execution_breakdown` or the run's resolved loss settings, otherwise "—"), never current capacity, topology or orientation. The HTML report refuses such a run, because its plan and strings are drawn from the current design. The demo computes the same fingerprint field set with FNV-1a (demo only).


## Workspace modes


### Map overlay


MapLibre renders a configurable contextual map style plus GeoJSON projected
from the canonical local Scene through the project's LocalCoordinateSystem.


The default development style is:


```text
https://tiles.openfreemap.org/styles/liberty
```


Override with `VITE_MAP_STYLE_URL`.


### Site address lookup (F7.1)


The Site panel looks the site address up from the coordinates, for the report
cover. The default service is OpenStreetMap Nominatim:


```text
https://nominatim.openstreetmap.org/reverse
```


Its usage policy allows at most one request per second and requires the credit
"© OpenStreetMap contributors"; it is not for heavy use. RawiBumi looks up once
per project and coordinate and never after the user edits the address.
Set `VITE_GEOCODER_URL` (with `{lat}`, `{lon}`, `{lang}`),
`VITE_GEOCODER_ATTRIBUTION` and `VITE_GEOCODER_LABEL` to use another service with
Nominatim's JSON format, or `VITE_GEOCODER=off` to remove the lookup. Users can
also switch it off per browser. The address is kept in the browser until the
engine stores it (proposal 0006).


### Blank engineering plane


The same canonical local Scene is rendered directly in local metric XY with a
visible grid and true-north reference. No map service is required.


Switching modes changes only workspace/rendering state. Canonical Project,
Scene and ElectricalDesignRevision identities do not change.


## Editing boundary


The browser does not implement construction geometry, PV packing or electrical
topology algorithms.


Forms submit explicit engineering parameters to the API, which delegates to:


- `SceneEditorSession`;
- `PVFieldPackingSession`;
- `ElectricalTopologyEditorSession`.


The returned canonical state is then rendered.

Since F3 the plan snaps and applies exact edits in the browser, so the cursor
responds at pointer speed. These are ports of the engine's own `SnapEngine` and
`geometry2d` functions, held to them by fixture tests (ADR 0012). The result is
committed through the engine's routes where one exists. Otherwise it stays a
marked local draft.


## Current 6.0D scope


- create/open project;
- coordinate input and map coordinate picker;
- map-overlay / blank-plane toggle;
- rectangular support surfaces;
- box obstacles;
- deterministic PV-field fill;
- reference component selection;
- inverter creation;
- explicit string creation;
- explicit MPPT assignment;
- canonical identity display;
- explicit weather-source discovery/acquisition;
- pinned canonical weather revision and QC status;
- engineering validation before execution;
- existing Phase-5 geometry-aware SimulationRun;
- monthly energy, PR, peak AC and named loss-ledger inspection;
- explicit failed-run findings;
- save/reopen with weather selection and run history.


The browser remains inside the Phase-5 execution boundary for this tranche.
Detailed electrical shading/mismatch, bypass behavior and nonuniform module/string
IV aggregation begin in Phase 6.1+ rather than being approximated in the UI.
Session undo/redo uses the existing toolbar and Ctrl/Cmd+Z, Ctrl/Cmd+Shift+Z or
Ctrl/Cmd+Y. Native undo in text fields is unchanged. An Inspector name is committed
once on Enter/blur as a local edit. Local drafts and real design commands share the
server-reported step limit; demo history remains 100 steps. Reload or switching
projects clears the client stack. Expired, evicted or stale history shows “Undo
history is no longer available”; it never retries an edit. Saved runs are preserved.
See the API README for resource settings; saved runs show their design basis (RES1).
