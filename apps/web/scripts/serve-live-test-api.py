"""Test-only API launcher. Never use this reduced catalogue for production.

The checkout lacks module-uat-550.pan. If absent, exclude that UAT component
and its dependent topology from this process's catalogue. All geometry,
electrical commands, validation and HTTP routes remain the real engine's.
Projects are isolated under the F8 delivery's tmp/live-projects directory.
"""
from pathlib import Path
import argparse
import sys

stage = Path(__file__).resolve().parents[3]
repo = next(p for p in (stage, *stage.parents) if (p / "geometry").is_dir())
sys.path.insert(0, str(repo))
sys.dont_write_bytecode = True
import apps.api.catalog as catalog

if not (catalog.REFERENCE_ROOT / "module-uat-550.pan").is_file():
    def test_catalog():
        module = catalog._load_json("module-ref-650.json")
        inverters = [catalog._load_json(n) for n in ("inverter-ref-150k.json", "inverter-uat-150k.json")]
        return {"modules": {module["revision_id"]: module},
                "inverters": {i["revision_id"]: i for i in inverters},
                "module_topologies": {}, "electrical_parameterization_evidence": {}, "sources": {}}
    catalog.load_reference_catalog = test_catalog
    print("TEST ONLY: excluding missing UAT PAN component and its dependent topology", flush=True)

from apps.api.server import create_app
import uvicorn

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run(create_app(store_root=stage / "tmp" / "live-projects"), host="127.0.0.1", port=args.port, timeout_keep_alive=75)

