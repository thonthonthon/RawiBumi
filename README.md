# RawiBumi

RawiBumi is a free, self-hostable, browser-based tool to design and simulate grid-connected rooftop PV systems: site,
roof geometry, module layout, stringing and inverters, weather, an hourly yearly simulation with near shading, results
and a report. Every model choice and loss is visible and editable; nothing is a black box.

*Bahasa Indonesia: lihat [wiki](docs/wiki/Home-ID.md) dan panduan di dalam aplikasi (`/manual/id.html`).*

> **Status: beta.** RawiBumi works end to end, from an empty project to a report, and its engine has been checked
> against an independent audit and against PVsyst on real projects. The user interface is still being reworked; see
> [Known work in progress](#known-work-in-progress). Review every result before you rely on it.

## What it does

| Step | What you do |
|---|---|
| 1 Project & site | Name, coordinates, time zone, elevation, address; installation type; an optional calibrated background image. |
| 2 Components | Pick modules and inverters from the library, or import PAN and OND files. |
| 3 Scene | Draw roofs (rectangles, polygons, holes), obstacles with heights and keep-out zones; set each roof's plane. |
| 4 PV layout | Fill roofs with modules: orientation, mounting, tilt, azimuth, gaps, tables, setbacks, row pitch, alignment. |
| 5 Systems | Group buildings, size inverters, fill each MPPT's string table by hand or with Suggest. |
| 6 Electrical | Draw string paths; assign, split, join, reverse and swap strings; live voltage and current checks. |
| 7 Weather | Get a weather year for the site or import one. |
| 8 Losses & grid | Set losses, optics and thermal, load profile, zero export and shading accuracy. |
| 9 Simulate | Preflight checks, then an hourly simulation of the year with near shading. |
| 10 Results | Energy, specific yield, performance ratio, loss diagram, inverter and MPPT tables, P50–P95. |
| 11 Report & export | A report (HTML or PDF), a 10-column hourly CSV, and the project file. |

The full manual, in English and Indonesian, is built into the app (the **Manual** link at the top, or `/manual/`).

### What the results are based on

- The standard hourly path implements its cited methods (Perez transposition, single-diode module model from PAN
  data, PVsyst-style Uc/Uv thermal model, IAM, inverter efficiency curves from OND data); an independent audit checked it.
- Against PVsyst 8 on two real shaded projects, annual grid energy agrees within −0.06 % and −0.30 %. PVsyst is a
  benchmark, not the truth: agreement shows the same conventions, not field accuracy.
- The energy ledger must reconcile in every hour of every run, or the run fails. Two identical runs give identical
  numbers.
- What the engine does **not** claim (no comparison with measured plants yet, no far-horizon shading, hourly only,
  and more) is listed in the wiki page [Engine methods and limits](docs/wiki/Engine-methods-and-limits.md).

## Install

RawiBumi runs on **Linux x86_64** or **Windows through WSL 2** (Ubuntu 24.04 tested). macOS is not tested.

You need:
- **Python 3.12** (`python3.12`, with the `venv` module),
- **Node.js 22** and npm,
- Git,
- about 2 GB of disk for dependencies, and 8 GB of RAM or more for large roofs.

```sh
git clone https://github.com/thonthonthon/RawiBumi.git
cd RawiBumi

# Python engine and API (every package is pinned with its hash)
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock

# Web app
cd apps/web
npm ci
npm run build
cd ../..
```

`requirements.lock` is validated for Python 3.12 on Linux x86_64. Other platforms need their own lock; open an issue if
you need one.

### Optional: the PDF report

The HTML report works out of the box. The PDF report is rendered by a headless Chromium that Playwright installs:

```sh
cd apps/web && npx playwright install chromium && cd ../..
```

and is switched on by the settings in [Self-hosting](#self-hosting) below.

## Run it on your own computer

```sh
.venv/bin/uvicorn apps.api.server:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. One process serves both the API and the built web app. Stop it with Ctrl+C; your
projects stay on disk.

To try the interface without the engine, `cd apps/web && npm run dev:demo` runs a demo with built-in sample data at
<http://127.0.0.1:5173>.

## Self-hosting

RawiBumi has **no user accounts** in this edition: anyone who can open the address can see and change every project.
Run it for yourself or a trusted team, and keep it off the open internet unless something in front of it controls who
gets in (a VPN, or a reverse proxy with sign-in).

A small start script, saved as `run.sh` next to the repository:

```sh
#!/bin/sh
cd "$(dirname "$0")"
export RAWIBUMI_DEPLOYMENT_EDITION=community_self_hosted
export RAWIBUMI_PROJECT_STORE="$PWD/var/projects"            # where projects live (this is the default)
# PDF report (after `npx playwright install chromium`):
export RAWIBUMI_PDF_NODE="$(command -v node)"
export RAWIBUMI_PDF_RUNTIME_ROOT="$PWD/apps/web"
export RAWIBUMI_PDF_CHROMIUM_EXECUTABLE="$(ls -d "$HOME"/.cache/ms-playwright/chromium-*/chrome-linux64/chrome | sort | tail -1)"
exec .venv/bin/uvicorn apps.api.server:app --host 127.0.0.1 --port 8000
```

### Settings

| Variable | Default | Meaning |
|---|---|---|
| `RAWIBUMI_DEPLOYMENT_EDITION` | unset | `community_self_hosted` enables the PDF report when its renderer is configured. |
| `RAWIBUMI_PROJECT_STORE` | `var/projects` | Folder for projects. Weather, runs, imagery and the component library sit next to it. |
| `RAWIBUMI_PDF_NODE`, `RAWIBUMI_PDF_RUNTIME_ROOT`, `RAWIBUMI_PDF_CHROMIUM_EXECUTABLE` | unset | Absolute paths to Node, `apps/web`, and the Chromium binary, for the PDF report. |
| `RAWIBUMI_COMMUNITY_NATIVE_PDF_ENABLED` | unset | `0` turns the PDF off even when configured. |
| `RAWIBUMI_PDF_MEMORY_LIMIT_MIB` | about 1,657 | Memory cap for the PDF renderer, 768–2,048 MiB. |
| `RAWIBUMI_SHADING_MAX_WORKERS` | `12` | Processes used for near-shading calculations. Lower it on small machines. |
| `RAWIBUMI_SIMULATE_WAIT_SECONDS` | unset | Behind a proxy that cuts long requests (for example 100 s), set this below the limit, for example `80`: a longer run then answers with a job the app polls until it ends. |
| `RAWIBUMI_UNDO_HISTORY_STEPS` | `10` | Undo steps kept per project while the server runs. |

### Behind a reverse proxy

Keep RawiBumi on `127.0.0.1` and let the proxy (nginx, Caddy, a tunnel) handle HTTPS and sign-in. Allow uploads of at
least 50 MB (weather files are capped at 50 MiB), and set `RAWIBUMI_SIMULATE_WAIT_SECONDS` if the proxy has a
request time limit.

### Your data and backups

Everything lives in `var/` (or next to `RAWIBUMI_PROJECT_STORE`). Back up that folder to back up your work; copy it back
to restore. Nothing is sent anywhere except the online services you use from the app:

| Service | Used for | When |
|---|---|---|
| [Open-Meteo](https://open-meteo.com) (ERA5 archive) | A weather year for the site | When you acquire a weather year in Meteo |
| [Nominatim](https://nominatim.openstreetmap.org) (OpenStreetMap) | Finding an address | When you search an address |
| [OpenFreeMap](https://openfreemap.org) | The background map | While the map is shown |

Imported weather, PAN and OND files stay on your computer.

### Upgrading

```sh
git pull
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
cd apps/web && npm ci && npm run build && cd ../..
```

Then restart. Saved runs keep their recorded numbers. Rerunning an old project uses the current models, so the result
can change. Back up `var/` before upgrading.

## Known work in progress

The engine is ahead of the interface. Known limits of this beta:

- **Drawing in 3D:** the stage is one window with Top, Front, Back, Left, Right, Isometric and "Perpendicular to face"
  views. Every drawing and editing tool works in Top; the other views select, move and raise objects. Editing in the
  other views comes next, one tool at a time.
- **Buildings made of several roofs** do not yet move and rotate as one group around a shared reference point; each
  roof, obstacle and keep-out has its own (nine-point) reference point. On the canvas, resize handles still follow
  the map axes; typed sizes in the Inspector follow the object's own axes.
- **One user at a time:** there are no accounts, and undo history lasts only while the server runs.
- **Platforms:** the Python lock covers Linux x86_64 only; on Windows use WSL 2.

How the calculation works, step by step, with its methods, libraries and quirks:
[How RawiBumi works](docs/wiki/How-RawiBumi-works.md). Engineering limits are listed in
[Engine methods and limits](docs/wiki/Engine-methods-and-limits.md). Please report what you find as an issue: the
project, what you expected, and what happened.

## Develop

```sh
cd apps/web && npm run dev          # web app with live reload at http://127.0.0.1:5173 (API on port 8000)
.venv/bin/python -m pytest -q        # Python tests
cd apps/web && npm test              # web unit tests
cd apps/web && npm run test:e2e      # browser tests (after `npx playwright install chromium`)
```

The development server forwards `/api` to port 8000; never expose it to a network. How the code is organised:
[Architecture](docs/wiki/Architecture.md). How to propose a change: [CONTRIBUTING.md](CONTRIBUTING.md); contributions need the
[Contributor License Agreement](CLA.md). Security
issues: [SECURITY.md](SECURITY.md).

## Copyright and licence

Copyright © 2026 Sulthon.

RawiBumi is free software: you can redistribute it and modify it under the terms of the
[GNU Affero General Public License, version 3](LICENSE). If you run a modified version as a network service, the AGPL
requires you to offer its source code to the service's users.

A hosted RawiBumi service, when offered, is operated by Total Surya Energi (TSE). Third-party components and their
licences are listed in `apps/web/THIRD_PARTY_NOTICES.md` and `requirements.lock`.
