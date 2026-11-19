# RawiBumi web UI — phase UI-A

This folder (apps/web/ui-a) is a STAGING copy. Nothing in apps/web/src was overwritten.

## Run
- With the engine API (FastAPI on 127.0.0.1:8000): `npm install && npm run dev`
- Without the engine (in-browser mock, for UI review only): `npm run dev:demo`
  Demo numbers are synthetic and labelled "Demo engine" / "Demo data".

## Merge into apps/web
Copy `ui-a/src/` over `apps/web/src/` — types.ts and api.ts are deliberately NOT included here;
keep the existing originals (the new UI only uses a subset of their exports, with identical signatures).
Replaced: App.tsx, main.tsx, styles.css, MapWorkspace.tsx (now always re-centres on site change).
LocalPlan.tsx is no longer imported (superseded by canvas/PlanCanvas.tsx); delete when satisfied.
Replace package.json with ui-a/package.json (adds @fontsource/barlow 5.3.0,
@fontsource/barlow-semi-condensed 5.3.0, scripts dev:demo / build:demo) and add `.env.demo`.
index.html, vite.config.ts and tsconfig.json are unchanged from the originals.

## What is wired vs not
Wired to existing endpoints: create/open project, rectangle surface, move entity, PV field fill,
add inverter, uniform strings, assign strings, weather acquire, readiness, simulate, save,
monthly energy, loss ledger, assumptions.

Every other control carries a hatched **Not wired** badge. Hover shows the endpoint to build.
The full list is `src/pending.ts` (ids: polygonSurface, polygonObstacle, keepout, editVertices,
rotateEntity, scaleEntity, deleteEntity, planeDefinition, undoRedo, moduleEdit, importFile,
imageryConfig, siteEdit, tablePairing, notationApply, stringChecks, orientationPolicy, losses,
loadProfile, zeroExport, timeSeries, exportBundle, view3d).
Unwired edits are kept as local drafts (dashed outlines), listed in Findings, and never enter a run.

## Phases
- UI-A (this): shell, 9-step workflow, 2D editor (free polygons, holes, keep-outs, vertex/rotate/move,
  snapping, measure, underlays), plane/auto-height preview, electrical configurator with MPPT notation,
  simple SLD, meteo/load/zero-export forms, results (monthly, waterfall, heatmap, daily), export spec.
- UI-B: wire endpoints in pending.ts order of value; swap Canvas2D renderer for WebGL behind the same
  component; delta protocol for large projects; control-point picking for imagery.
- UI-C: 3D view from the height model, sun/shadow slider, constraint editing in 3D.
- Later: SaaS/auth, editions gating, report generation, lazy-load maplibre (bundle is 1.4 MB).
