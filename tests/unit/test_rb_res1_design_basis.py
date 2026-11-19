"""RES1: each run records the design it simulated; the view exposes the current design's fingerprint."""
from copy import deepcopy
import json
import re

import pytest

import apps.api.study as study_module
from apps.api.history import design_fingerprint, projection
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def view(p):
    return p.client.get(p.url).json()


def fence(v):
    return {'expected_project_revision_id': v['bundle']['project']['project_revision']['project_revision_id'],
            'expected_entry_id': v['history']['past'][-1]['entry_id']}


def simulate(p):
    response = p.client.post(p.url + '/simulate', json={})
    assert response.status_code == 200, response.text
    return response.json()


def _s17_projection(bundle):
    """The S17 implementation before RES1, kept verbatim as the byte reference for the undo fence."""
    from apps.api.history import SCENE_ENVELOPE, ELECTRICAL_ENVELOPE, OPTIONAL_KEYS
    state = {key: bundle[key] for key in OPTIONAL_KEYS if key in bundle}
    state['project'] = {key: value for key, value in bundle['project'].items() if key != 'project_revision'}
    state['scene'] = {key: value for key, value in bundle['scene'].items() if key not in SCENE_ENVELOPE}
    state['electrical_design'] = {key: value for key, value in bundle['electrical_design'].items() if key not in ELECTRICAL_ENVELOPE}
    state['site_workspace_bootstrap'] = {key: value for key, value in bundle['site_workspace_bootstrap'].items() if key != 'workspace_context'}
    return json.dumps(state, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


@pytest.fixture
def project(tmp_path):
    return Project(tmp_path, 18)


def test_projection_bytes_are_unchanged_for_the_s17_fence(project):
    p = project
    p.client.patch(p.url + '/losses', json={'overrides': {'lid_fraction': 0.02}})
    p.client.patch(p.url + '/shading-accuracy', json={'overrides': {'level': 'high'}})
    bundle = p.bundle()
    assert projection(bundle) == _s17_projection(bundle)


def test_fingerprint_is_canonical_stable_and_excludes_only_project_labels(project):
    p = project
    bundle = p.bundle()
    value = design_fingerprint(bundle)
    assert re.fullmatch(r'sha256:[0-9a-f]{64}', value)
    reordered = json.loads(json.dumps(bundle, sort_keys=True))
    reordered['scene'] = dict(reversed(list(reordered['scene'].items())))
    assert design_fingerprint(reordered) == value == design_fingerprint(p.bundle())
    labelled = deepcopy(bundle)
    labelled['project']['name'] = 'Renamed'
    labelled['project']['description'] = 'New description'
    labelled['project']['project_revision'] = {**labelled['project']['project_revision'], 'project_revision_id': 'other'}
    labelled['scene']['revision_id'] = 'other-scene-revision'
    labelled['site_workspace_bootstrap']['workspace_context'] = {'anything': True}
    labelled['simulation_runs'] = [{'simulation_run_id': 'unrelated'}]
    assert design_fingerprint(labelled) == value
    for change in (
        lambda b: b['scene']['surfaces'][0].__setitem__('name', 'Renamed roof'),
        lambda b: b['project']['site'].__setitem__('latitude_deg', -6.3),
        lambda b: b['project']['site'].__setitem__('name', 'Other site'),
        lambda b: b.__setitem__('weather_selection', None),
        lambda b: b['electrical_design']['strings'].pop(),
        lambda b: b.__setitem__('loss_settings', {**b.get('loss_settings', {}), 'overrides': {'lid_fraction': 0.03}}),
        lambda b: b.__setitem__('shading_accuracy', {'overrides': {'level': 'high'}}),
        lambda b: b['pinned_components']['modules'].clear(),
    ):
        changed = deepcopy(bundle)
        change(changed)
        assert design_fingerprint(changed) != value
    broken = deepcopy(bundle)
    broken['scene']['surfaces'][0]['base_elevation_m'] = float('nan')
    with pytest.raises(ValueError):
        design_fingerprint(broken)


def test_run_records_its_design_and_undo_back_matches_again(project):
    p = project
    run = simulate(p)
    current = view(p)
    assert run['design_fingerprint'] == current['design_fingerprint'] == design_fingerprint(p.bundle())
    stored = json.loads(p.path.read_text())
    assert 'design_fingerprint' not in stored
    assert stored['simulation_runs'][-1]['design_fingerprint'] == run['design_fingerprint']
    renamed = p.service.update_project(p.pid, name='Only a label')
    assert renamed['design_fingerprint'] == run['design_fingerprint']
    edited = p.client.patch(p.url + '/losses', json={'overrides': {'lid_fraction': 0.02}})
    assert edited.status_code == 200
    assert edited.json()['design_fingerprint'] != run['design_fingerprint']
    undone = p.client.post(p.url + '/undo', json=fence(edited.json()))
    assert undone.status_code == 200, undone.text
    assert undone.json()['design_fingerprint'] == run['design_fingerprint']
    assert undone.json()['bundle']['simulation_runs'][-1]['design_fingerprint'] == run['design_fingerprint']


def test_fingerprint_comes_from_the_launch_snapshot_not_the_merge(project, monkeypatch):
    p = project
    launch = design_fingerprint(p.bundle())
    original = study_module.run_validated_design_simulation

    def edit_during_run(*args, **kwargs):
        p.service.add_surface_rectangle(p.pid, name='Added while running', origin_x_m=40, origin_y_m=0, width_m=4,
            height_m=3, base_elevation_m=3, surface_type='flat_roof', usable_for_pv=True)
        return original(*args, **kwargs)

    monkeypatch.setattr(study_module, 'run_validated_design_simulation', edit_during_run)
    run = simulate(p)
    after = view(p)
    assert run['design_fingerprint'] == launch
    assert after['design_fingerprint'] != launch
    assert after['bundle']['simulation_runs'][-1]['design_fingerprint'] == launch


def test_legacy_runs_are_not_backfilled(project):
    p = project
    raw = p.bundle()
    raw['simulation_runs'] = [{'simulation_run_id': 'legacy', 'status': 'completed', 'project_revision_id': 'legacy-r1',
                               'scene_revision_id': 'legacy-scene', 'electrical_revision_id': 'legacy-electrical',
                               'weather_dataset_revision_id': 'legacy-weather'}]
    p.service.save_bundle(raw, history_mode='neutral')
    assert 'design_fingerprint' not in view(p)['bundle']['simulation_runs'][0]
    assert 'design_fingerprint' not in p.bundle()['simulation_runs'][0]
