# Installation

RawiBumi runs on Linux (or WSL on Windows) with **Python 3.12** and **Node.js 22**. The PDF report also needs the
Chromium build that Playwright installs (`cd apps/web && npx playwright install chromium`) and the settings in the README's
*Self-hosting* section, which also has a start script.

## 1. Get the code and install
```sh
git clone https://github.com/thonthonthon/RawiBumi.git
cd RawiBumi
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
cd apps/web && npm ci && cd ../..
```
`requirements.lock` pins every Python package with its SHA-256 hash for Python 3.12 on Linux x86_64. Other platforms
need their own validated lock. `npm ci` installs exactly `apps/web/package-lock.json`.

## 2. Run
**For use** (one process, one port):
```sh
cd apps/web && npm run build && cd ../..
.venv/bin/uvicorn apps.api.server:app --host 127.0.0.1 --port 8000
```
Open <http://127.0.0.1:8000>. The API serves the built web app.

**For development** (live reload): run the API as above, and in a second terminal `cd apps/web && npm run dev`, then
open <http://127.0.0.1:5173>. The development server forwards `/api` to port 8000. Never expose it to a network.

## 3. Where your data lives
Projects are saved under `var/projects/` (set `RAWIBUMI_PROJECT_STORE` to move them). Weather, runs, imagery and the
component library sit next to that folder. Back up `var/` to back up your work.

## Upgrading
Saved runs keep their recorded numbers. Rerunning an old project uses the current models and recommended losses, so the
result can change. Runs saved before design fingerprints existed need a rerun before they can produce a report.
