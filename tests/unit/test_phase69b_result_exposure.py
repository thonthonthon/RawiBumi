"""API projection and actual React rendering from authoritative compact summaries."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from apps.api.detailed_results import detailed_result_fields, hydrate_run_records
from apps.api.server import create_app
from engine.simulation.attribution_energy import aggregate_persisted_attribution
from tests.unit.test_phase69b_attribution_energy import _source, _powers
from tests.integration.test_phase69b_dc_attribution import completed

ROOT = Path(__file__).resolve().parents[2]


def test_verified_api_projection_reopen_and_tamper(tmp_path, completed, monkeypatch):
    original = completed[-1]
    app = create_app(store_root=tmp_path / 'projects')
    service = app.state.project_service
    bundle = service.create_project(name='Attribution exposure', latitude_deg=-6.2,
        longitude_deg=106.8, elevation_m=25., timezone_name='Asia/Jakarta', workspace_mode='map_overlay')
    project_id = bundle['project']['project_id']
    run_id = original.simulation_run['simulation_run_id']
    directory = app.state.study_service.run_root / project_id / run_id
    shutil.copytree(original.artifact_directory, directory)
    def forbidden(*args, **kwargs):
        raise AssertionError('presentation cannot execute counterfactual physics or energy aggregation')
    monkeypatch.setattr('engine.simulation.detailed_attribution.execute_detailed_dc_attribution', forbidden)
    monkeypatch.setattr('engine.simulation.attribution_energy.aggregate_persisted_attribution', forbidden)
    monkeypatch.setattr('engine.simulation.attribution_energy._assemble', forbidden)
    monkeypatch.setattr('engine.simulation.attribution_energy._from_source', forbidden)
    monkeypatch.setattr('engine.simulation.artifacts.verify_run_package', forbidden)
    persisted = json.loads((directory / 'detailed-dc-attribution-energy-summary.json').read_text())['payload']
    client = TestClient(app)
    response = client.get(f'/api/projects/{project_id}/runs/{run_id}/result')
    assert response.status_code == 200, response.text
    detail = response.json()['detailed_electrical_shading']
    assert detail['attribution_energy_summary'] == persisted
    assert detail['package_manifest_sha256'] == json.loads((directory / 'run-package-manifest.json').read_text())['manifest_payload_sha256']
    assert detail['execution_identity']['requested_fidelity'] == 'level_2_bypass_substring'
    assert detail['execution_identity']['runtime_support_result'] == 'pcc_complete'
    assert detail['selected_mppt_result']['status'] == 'available'
    assert detail['dc_attribution_result']['status'] == 'available'
    assert detail['diagnostic_artifacts']['artifacts'] == []
    assert response.json()['summary_result'] == original.summary_result
    record = {**deepcopy(original.simulation_run), 'scene_revision_id': 'scene-test',
              'electrical_revision_id': 'electrical-test', 'weather_dataset_revision_id': 'weather-test',
              'summary_result': deepcopy(original.summary_result), 'detailed_electrical_shading': detail}
    bundle['simulation_runs'] = [record]
    service.save_bundle(bundle)
    reopened = create_app(store_root=tmp_path / 'projects')
    reopened_client = TestClient(reopened)
    assert reopened_client.get(f'/api/projects/{project_id}/runs').json()[0]['detailed_electrical_shading'] == detail
    assert reopened_client.get(f'/api/projects/{project_id}').json()['bundle']['simulation_runs'][0]['detailed_electrical_shading'] == detail
    path = directory / 'detailed-dc-attribution-energy-summary.json'
    tampered = json.loads(path.read_text())
    tampered['payload']['periods'][0]['channels']['regional_mismatch']['observed_signed_energy_wh'] += 1
    path.write_text(json.dumps(tampered))
    assert reopened_client.get(f'/api/projects/{project_id}/runs/{run_id}/result').status_code == 422
    assert reopened_client.get(f'/api/projects/{project_id}/runs').status_code == 422
    assert reopened_client.get(f'/api/projects/{project_id}').status_code == 422
    # Refreshing the outer file manifest still cannot bypass compact identity.
    from engine.simulation.artifacts import _build_run_package_manifest
    (directory / 'run-package-manifest.json').write_text(json.dumps(_build_run_package_manifest(directory, simulation_run_id=run_id)))
    assert reopened_client.get(f'/api/projects/{project_id}/runs/{run_id}/result').status_code == 422


def test_legacy_records_not_given_attribution(tmp_path):
    records = [{'simulation_run_id': 'old', 'status': 'completed', 'summary_result': {'shading_energy_loss_wh': 7}}]
    records.append({'simulation_run_id': 'old-null', 'status': 'completed', 'detailed_electrical_shading': None})
    assert hydrate_run_records(records, tmp_path, 'legacy') == records


def test_render_signed_coverage_and_backend_periods(tmp_path):
    base = _powers()
    small = dict(base, U=90.00033148579314)
    missing = dict(base, N=None)
    all_missing = {**{k: None for k in base}, "T": 80.}
    cases = {
        'signed': [('2026-01-31T23:55:00+07:00', 600, small, []), ('2026-02-01T00:05:00+07:00', 900, base, [])],
        'partial': [('2026-01-31T23:55:00+07:00', 600, base, []), ('2026-02-01T00:05:00+07:00', 900, missing, ['reverse_domain_unavailable'])],
        'unavailable': [('2026-01-31T23:55:00+07:00', 600, all_missing, ['reverse_domain_unavailable'])],
        'dark': [('2026-01-31T23:55:00+07:00', 600, None, [])],
    }
    output = {}
    # Small scientific term must be visible in the run-total row, not only audit.
    cases['signed'][1] = ('2026-02-01T00:05:00+07:00', 900, small, [])
    for name, specs in cases.items():
        subdir = tmp_path / name
        subdir.mkdir()
        summary = aggregate_persisted_attribution(_source(subdir, specs)).replay()
        reference = {'status': 'available', 'artifact': 'compact.json', 'sha256': 'abc', 'model_id': None, 'unavailable_reason_codes': []}
        output[name] = {'execution_identity': {'requested_fidelity': 'level_2_bypass_substring', 'resolved_fidelity': 'level_2_bypass_substring', 'runtime_support_result': 'pcc_complete', 'limitations': ['bounded reverse domain'], 'failure_reasons': [], 'fallback_reason': None},
            'selected_mppt_result': reference, 'dc_attribution_result': reference, 'attribution_energy_result': reference,
            'attribution_energy_summary': summary, 'diagnostic_artifacts': {'status': 'not_requested_or_not_produced', 'artifacts': []}}
    fixture = tmp_path / 'render.json'
    fixture.write_text(json.dumps(output))
    process = subprocess.run(['node', 'tests/detailed-results.mjs', str(fixture)], cwd=ROOT/'apps/web', capture_output=True, text=True)
    assert process.returncode == 0, process.stdout + process.stderr


def test_diagnostics_exposed_only_as_references(tmp_path, completed):
    from engine.simulation.artifacts import _build_run_package_manifest
    actual = completed[-1]
    directory = tmp_path / actual.simulation_run['simulation_run_id']
    shutil.copytree(actual.artifact_directory, directory)
    # Emulate the existing opt-in physical diagnostic persistence using the
    # exact in-memory diagnostic result from the completed physical execution.
    (directory / 'detailed-mppt-result.json').write_text(json.dumps(actual.detailed_backend_result.record()))
    manifest = _build_run_package_manifest(directory, simulation_run_id=actual.simulation_run['simulation_run_id'])
    (directory / 'run-package-manifest.json').write_text(json.dumps(manifest))
    fields = detailed_result_fields(directory)['detailed_electrical_shading']
    assert fields['diagnostic_artifacts'] == {'status': 'available', 'artifacts': ['detailed-mppt-result.json']}
    assert 'curves' not in json.dumps(fields)
    assert fields['attribution_energy_summary'] == json.loads((directory / 'detailed-dc-attribution-energy-summary.json').read_text())['payload']
