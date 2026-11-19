# Architecture

| Folder | Holds |
|---|---|
| `apps/api` | The FastAPI service: projects, scene and electrical commands, history (undo), imports, studies, reports. |
| `apps/web` | The React browser app (plan, 3D and SLD views, the ten steps), its demo mode, and the report renderer. |
| `engine` | The simulation: irradiance and transposition, optics, module (single-diode), inverter, losses, the hourly run. |
| `geometry` | Scene model and editing, PV-field packing, 3D, and near-shading geometry. |
| `shading` | Beam, diffuse and albedo shading, and electrical shading. |
| `electrical` | Strings, MPPTs, topology editing, DC and AC wiring. |
| `components` | PAN and OND parsing and mapping, candidates, IV reference checks. |
| `weather` | Importers (TMY3, EPW, Meteonorm, PVsyst CSV, RawiBumi CSV), providers, quality checks. |
| `reporting` | Charts, the protected PDF export, templates. |
| `validation` | Engineering checks, the PVsyst benchmark tooling, attribution. |
| `schemas` | JSON schemas of the canonical data model. |

Principles: the engineer decides (automation suggests and checks, never silently overrides); every run is tied to
immutable project, component, weather and model revisions; external formats are adapters into RawiBumi's own data model.
