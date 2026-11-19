# How RawiBumi works

*Bahasa Indonesia: [Cara kerja RawiBumi](How-RawiBumi-works-ID).*

This page explains what happens between your design and the numbers in Results: the calculation chain, the methods
behind each step, the libraries RawiBumi stands on, how it was checked, what works and what does not yet, and the
quirks worth knowing. For the claims the evidence does and does not support, see
[Engine methods and limits](Engine-methods-and-limits).

## The calculation chain, hour by hour

Every run simulates a year (or the period of the weather file) at the weather file's time step, usually one hour.
Each step records which model it used, so the run's audit shows exactly what was done.

| # | Step | Method | Notes |
|---|---|---|---|
| 1 | Timeline | Each interval is represented by its mid-point (or the file's stated convention) | Time zones without daylight saving only |
| 2 | Sun position | NREL Solar Position Algorithm (SPA), via pvlib | Uses the site's elevation, pressure and temperature when available |
| 3 | Missing irradiance | When the file lacks DNI or DHI: Erbs, DISC or DIRINT decomposition (pvlib) | The completed values are flagged in the quality check |
| 4 | Plane of array | Perez anisotropic transposition (hourly), keeping beam, circumsolar, isotropic sky, horizon and ground-reflected parts separate; Perez–Driesse, Hay–Davies and isotropic are also available | Ground reflection is Lambertian with one albedo (default 0.2) |
| 5 | Near shading | The 3-D scene (roofs, obstacles, the modules themselves) is meshed; the beam is traced from each receiver towards the sun; sky diffuse is weighted over a sky dome (standard accuracy: 48 azimuth sectors × 12 elevation bands); the horizon band and the ground view are separate channels | Shading is applied per channel, before the angle losses |
| 6 | Angle of incidence (IAM) | The module's own IAM table from its PAN file when present; otherwise the Fresnel/physical model (n = 1.526, K = 4, L = 0.002) | Diffuse IAM factors are integrated over the sky, horizon and ground |
| 7 | Soiling | A monthly fraction (default 3 % every month) applied to the optical result | Editable per month |
| 8 | Cell temperature | PVsyst-style steady-state heat balance (`Uc`, `Uv`, absorptance), via pvlib; default semi-integrated mounting `Uc = 20`, `Uv = 0` W/m²K | The module efficiency used in the heat balance is solved by a short fixed-point iteration |
| 9 | Module electrical | The PVsyst single-diode model (version 6 parameter mapping) from the module's PAN data, driven by the effective irradiance after IAM and the cell temperature | Every module in a string is assumed to see the same irradiance and temperature (see limits) |
| 10 | Strings and MPPTs | Modules in series, strings in parallel, operating at the MPPT's maximum power point within its voltage window | Strings outside the window or over the cold-voltage limit block the run as design errors |
| 11 | Array losses | LID (from the module file, else a generic value by technology), module quality (from the PAN tolerance), module mismatch and string mismatch (recommended values by string length and count), degradation (year 1 = half a year of the annual rate) | Each circuit (MPPT) is handled independently |
| 12 | DC wiring | Ohmic loss per circuit from a fraction at STC (default 1.5 %), applied as I²R at the operating current | |
| 13 | Inverter | The inverter's OND efficiency curves, voltage dependent; MPPT current and power limits; DC power and voltage thresholds; AC power limit (clipping); night and standby consumption | |
| 14 | AC side | AC wiring per inverter (quadratic in power), optional transformer (iron and copper loss), unavailability, plant AC wiring, optional zero-export limit | Off or zero unless you set them |
| 15 | Results | Energy at the point of connection, specific yield, performance ratio (IEC 61724 style: energy ÷ kWp ÷ plane-of-array irradiation), loss diagram, monthly and hourly series, inverter and MPPT tables | Every loss is in an energy ledger that must reconcile each hour, or the run fails |
| 16 | P50–P95 | An uncertainty ledger — year-to-year solar variability, solar-resource bias, residual model error, component and availability terms, with their correlations — combined into exceedance values | Simplified method: the run's year is treated as the annual mean; the terms and their sources are listed with the result |

### Options beyond the standard path
- **Mixed orientations:** an inverter may serve fields with different tilts or azimuths; the result is reported per
  orientation group.
- **Detailed electrical shading (level 2, bypass substrings):** for shaded arrays, an optional path models the
  mismatch inside strings at bypass-diode level. It is slower and uses pinned selections; the standard path does not
  model electrical mismatch under uneven shade.

## How it was checked
- The standard hourly path: a whole-engine physics review by a separate AI reviewer that recomputed each stage (internal, 2026; details not published).
- Results checked internally against PVsyst 8 on two real shaded projects, with close agreement on annual and monthly energy (details not published: they are client projects). PVsyst is a benchmark, not the truth.
- The module model was checked internally against datasheet STC power on a set of real PAN files (details not published).
- Reproducibility: two identical runs give identical numbers.
- About 8,300 Python tests and 1,600 browser unit tests, plus browser end-to-end tests against the real engine.
- Not yet: comparison with measured plant data.

The design notes, decision records and validation reports behind the engine are indexed in
[the engineering documentation](https://github.com/thonthonthon/RawiBumi/blob/main/docs/README.md).

## What RawiBumi stands on
**Engine (Python 3.12):**

| Library | Used for |
|---|---|
| pvlib | Solar position, decomposition, transposition, IAM and thermal building blocks |
| NumPy, pandas, SciPy | Arrays, time series, solvers |
| Shapely | 2-D geometry (roofs, holes, keep-outs, packing) |
| PyArrow | Saving hourly results (Parquet) |
| h5py, lxml, PyYAML | Reading weather and component formats, mapping ledgers |
| FastAPI, Starlette, Uvicorn, Pydantic | The local web API and its request validation |
| jsonschema | Validating saved projects against their schemas |
| pikepdf | Protecting and checking the PDF report |
| pytest, pytest-xdist | Tests |

**Web app (TypeScript, React):**

| Library | Used for |
|---|---|
| React, Zustand | The interface and its state |
| three.js | The 3-D view |
| MapLibre GL | The background map |
| ECharts, uPlot | Charts |
| TanStack Table and Virtual | Large tables |
| React Aria Components, cmdk | Accessible controls, the command palette |
| i18next | English and Indonesian |
| Vite, Vitest, Playwright | Build and tests |

The exact versions are pinned in `requirements.lock` (with hashes) and `apps/web/package-lock.json`; third-party
licences are in `apps/web/THIRD_PARTY_NOTICES.md`.

## What works, and what does not yet
**Works end to end:** site and map, roofs and obstacles, PV layout fill, component import (PAN/OND), systems and
inverter sizing, stringing (suggested or by hand), weather (ERA5 download or file import), losses, the hourly
simulation with near shading, results, report (HTML and PDF), the 10-column CSV and the project file, undo and
backups, one window with Top/Front/Back/Left/Right/Isometric/face views, and a nine-point reference point per
roof, obstacle and keep-out (position from the origin, orientation, own-axis sizes).

**Not yet (being worked on):** see the README's "Known work in progress": editing tools work in the Top view only
(the other views select, move and raise); a building made of several roofs does not yet move as one group around a
shared reference point; canvas resize handles still follow the map axes. Engine limits (no measured-plant comparison, no far horizon, hourly only, no daylight
saving time zones, no reactive power) are on [Engine methods and limits](Engine-methods-and-limits).

## Quirks worth knowing
- **ERA5 sunshine reads high in the cloudy tropics.** A year downloaded from ERA5 (Open-Meteo) can be 10–15 % above
  station-based data in places such as Jakarta. Compare with a local dataset before relying on the yield.
- **Performance ratio depends on what you switch on.** LID, AC wiring, transformer and unavailability are 0 or off by
  default except LID on new projects; a run with them off reads a few points higher than a typical PVsyst report.
- **Loss defaults are versioned.** New projects use the current defaults (automatic LID); older projects keep the
  earlier defaults (LID 0 %) until you press "Use the current defaults" in Losses & grid. Saved runs never change.
- **Undo lasts while the server runs** (10 steps per project). Restarting the server clears it; backups do not.
- **One user at a time.** There are no accounts; two people editing the same project at once overwrite each other's
  unsaved steps.
- **Re-stringing an inverter frees its old strings.** Applying a new MPPT layout (Systems or Electrical) removes the
  inverter's strings the new layout does not keep, and their modules become free for the new strings.
- **Delete asks first and names the object.** Check the name in the dialog before confirming.
- **Long runs behind a proxy.** A proxy that cuts long requests (for example 100 s) needs
  `RAWIBUMI_SIMULATE_WAIT_SECONDS`; the app then polls the run instead of waiting on one request.
- **The PDF report needs its settings** (see the README's Self-hosting section); without them only the HTML report
  is offered.
- **Platforms:** the Python lock is for Linux x86_64; on Windows use WSL 2.
