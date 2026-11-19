"""Serve controlled browser fixtures against the production frontend (manual runner)."""
import json
from pathlib import Path
import tempfile
import uvicorn
from tests.unit.test_phase69b_browser_launch import setup_project

if __name__ == '__main__':
    root = Path(tempfile.mkdtemp(prefix='rawibumi-closure-browser-'))
    projects = {}
    for name in ('legacy', 'detailed', 'blocked', 'fallback', 'daylight'):
        app, pid, bundle = setup_project(root, dark=name != "daylight")
        if name in ('blocked', 'fallback'):
            bundle['electrical_shading_selections'] = {}
            app.state.project_service.save_bundle(bundle)
        projects[name] = pid
    Path('/tmp/rawibumi-closure-browser.json').write_text(json.dumps({'origin': 'http://127.0.0.1:8769', **projects}))
    uvicorn.run(app, host='127.0.0.1', port=8769)
