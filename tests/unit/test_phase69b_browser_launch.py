"""Browser launch envelopes through real HTTP and persisted canonical dispatch."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient
from apps.api.server import create_app
from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
from tests.integration.test_phase69a_closure import _declare

ROOT = Path(__file__).resolve().parents[2]
REQUEST = {'electrical_shading_configuration': {'requested_fidelity': 'level_2_bypass_substring', 'fallback_policy': 'fail_closed'}}


def setup_project(tmp_path, dark=False):
    app = create_app(store_root=tmp_path / 'projects')
    service, study = app.state.project_service, app.state.study_service
    bundle = service.create_project(name='Browser detailed', latitude_deg=-6.2, longitude_deg=106.8,
        elevation_m=25., timezone_name='Asia/Jakarta', workspace_mode='map_overlay')
    pid = bundle['project']['project_id']
    _, _, store, scene, electrical = _canonical_fixture()
    store = _declare(store, 'separate_from_parameterization')
    bundle.update(store.detailed_electrical_inputs.replay())
    for surface in scene['surfaces']:
        surface.setdefault('name', 'Detailed test roof')
    bundle['scene'], bundle['electrical_design'] = scene, electrical
    bundle['pinned_components']['inverters'] = {k: v for k, v in store.component_revisions.items() if v['schema_name'] == 'InverterDefinition'}
    for inverter in bundle['pinned_components']['inverters'].values():
        inverter['capability_flags'].update(basic_design_ready=True, mppt_design_ready=True)
        inverter['mppt_template'].update(min_operating_voltage_v=0.01, count=1)
    weather = next(iter(store.weather_revisions.values())).copy()
    # All dark gives a fast actual producer run and real not-applicable summary.
    if dark:
        weather.series.loc[:, ['ghi_w_m2', 'dni_w_m2', 'dhi_w_m2']] = 0.
    bundle['weather_selection'] = study.weather.save(pid, weather)
    service.save_bundle(bundle)
    return app, pid, bundle


def test_blocked_detailed_request_never_executes(tmp_path, monkeypatch):
    app, pid, bundle = setup_project(tmp_path)
    bundle['electrical_shading_selections'] = {}
    app.state.project_service.save_bundle(bundle)
    def forbidden(*args, **kwargs):
        raise AssertionError('blocked preflight executed physics')
    monkeypatch.setattr('apps.api.study.run_validated_design_simulation', forbidden)
    client = TestClient(app)
    ready = client.get(f'/api/projects/{pid}/execution-readiness', params=REQUEST['electrical_shading_configuration']).json()
    assert not ready['ready'] and ready['findings']
    assert ready['execution_class'] == 'blocked_detailed_inputs'
    assert client.post(f'/api/projects/{pid}/simulate', json=REQUEST).status_code == 422
    assert client.get(f'/api/projects/{pid}/runs').json() == []


def test_browser_detailed_dark_persisted_reopen_render_and_tamper(tmp_path, monkeypatch):
    app, pid, bundle = setup_project(tmp_path, dark=True)
    client = TestClient(app)
    ready = client.get(f'/api/projects/{pid}/execution-readiness', params=REQUEST['electrical_shading_configuration'])
    assert ready.status_code == 200, ready.text
    assert ready.json()['execution_class'] == 'ready_detailed', ready.text
    response = client.post(f'/api/projects/{pid}/simulate', json=REQUEST)
    assert response.status_code == 200, response.text
    record = response.json()
    detail = record['detailed_electrical_shading']
    assert record['status'] in {'completed', 'completed_with_warnings'}, record['validation_findings']
    identity = detail['execution_identity']
    assert identity['requested_fidelity'] == identity['resolved_fidelity'] == 'level_2_bypass_substring'
    assert not identity['fallback_applied']
    run_id = record['simulation_run_id']
    directory = app.state.study_service.run_root / pid / run_id
    context = json.loads((directory / 'detailed-execution-context.json').read_text())
    assert context['inputs']['simulation_configuration']['shading_configuration']['electrical_shading_configuration']['requested_fidelity'] == REQUEST['electrical_shading_configuration']['requested_fidelity']
    assert context['selection_snapshot']['payload']['electrical_shading_selections'] == bundle['electrical_shading_selections']
    def forbidden(*args, **kwargs):
        raise AssertionError('reopen must not recompute')
    monkeypatch.setattr('apps.api.study.run_validated_design_simulation', forbidden)
    monkeypatch.setattr('engine.simulation.attribution_energy.aggregate_persisted_attribution', forbidden)
    reopened = TestClient(create_app(store_root=tmp_path / 'projects'))
    assert reopened.get(f'/api/projects/{pid}/runs/{run_id}/result').json()['detailed_electrical_shading'] == detail
    assert reopened.get(f'/api/projects/{pid}').json()['bundle']['simulation_runs'][-1]['detailed_electrical_shading'] == detail
    channels = detail['attribution_energy_summary']['periods'][0]['channels']
    assert all(c['completeness'] == 'not_applicable' for c in channels.values())
    cases = tmp_path / 'browser-dark.json'
    cases.write_text(json.dumps({'dark': detail}))
    rendered = subprocess.run(['node', 'tests/detailed-results.mjs', str(cases)], cwd=ROOT / 'apps/web', capture_output=True, text=True)
    assert rendered.returncode == 0, rendered.stdout + rendered.stderr
    path = directory / 'detailed-execution-context.json'
    path.write_text('{}')
    assert reopened.get(f'/api/projects/{pid}/runs/{run_id}/result').status_code == 422


def test_policy_mismatch_is_integrity_block_even_when_fallback_allowed(tmp_path):
    app, pid, _ = setup_project(tmp_path)
    request = deepcopy(REQUEST)
    request['electrical_shading_configuration']['fallback_policy'] = 'explicit_lower_fidelity'
    client = TestClient(app)
    ready = client.get(f'/api/projects/{pid}/execution-readiness', params=request['electrical_shading_configuration']).json()
    assert not ready['ready']
    assert 'request does not match frozen selection' in ready['findings'][0]['message']
    assert client.post(f'/api/projects/{pid}/simulate', json=request).status_code == 422


def test_explicit_allowed_fallback_records_identity_and_reason(tmp_path):
    app, pid, bundle = setup_project(tmp_path, dark=True)
    bundle['electrical_shading_selections'] = {}
    app.state.project_service.save_bundle(bundle)
    request = deepcopy(REQUEST)
    request['electrical_shading_configuration']['fallback_policy'] = 'explicit_lower_fidelity'
    client = TestClient(app)
    ready = client.get(f'/api/projects/{pid}/execution-readiness', params=request['electrical_shading_configuration']).json()
    assert ready['ready'] and ready['execution_class'] == 'explicit_fallback_available', ready
    response = client.post(f'/api/projects/{pid}/simulate', json=request)
    assert response.status_code == 200, response.text
    record = response.json()
    identity = record['detailed_electrical_shading']['execution_identity']
    assert record['status'] in {'completed', 'completed_with_warnings'}, record
    assert identity['requested_fidelity'] == 'level_2_bypass_substring'
    assert identity['resolved_fidelity'] == 'level_0_geometric_only'
    assert identity['fallback_applied'] and identity['fallback_reason']
    assert record['detailed_electrical_shading']['attribution_energy_summary'] is None


def test_invalid_launch_contract_never_silently_uses_legacy(tmp_path):
    app, pid, _ = setup_project(tmp_path)
    client = TestClient(app)
    assert client.post(f'/api/projects/{pid}/simulate', json={'electrical_shading_configuration': {'requested_fidelity': 'invented'}}).status_code == 422
    assert client.get(f'/api/projects/{pid}/runs').json() == []



def test_missing_weather_detailed_readiness_is_actionable(tmp_path):
    app, pid, bundle = setup_project(tmp_path)
    bundle['weather_selection'] = None
    app.state.project_service.save_bundle(bundle)
    response = TestClient(app).get(f'/api/projects/{pid}/execution-readiness', params=REQUEST['electrical_shading_configuration'])
    assert response.status_code == 200
    assert not response.json()['ready']
    assert response.json()['findings'][0]['rule_id'] == 'EXECUTION_WEATHER_REVISION_REQUIRED'
