"""USE4A: canonical metadata commands and a read-only engine-derived systems view."""
from copy import deepcopy
import json
import random
from pathlib import Path
from time import perf_counter

import pytest
from jsonschema import Draft202012Validator

from apps.api.systems_overview import systems_overview
from apps.api.orientation_policy import tolerance_deg
from apps.api.history import SCENE_ENVELOPE
from engine.simulation.execution_groups import module_execution_signature, string_compatibility_keys
from components.design_integration import module_nameplate_w
from geometry.scene import SceneEditorSession
from geometry.pvfield.explicit import create_explicit_field
from tests.unit.test_phase43_pvfield_packing import MODULE, _roof_scene
from tests.unit.test_phase42_scene_editor import _validate_scene
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def fixture_bundle(positions=(0., 3., 64.), tilts=(10., 10.5, 12.)):
    scene = _roof_scene(width=1., height=3.)
    original = scene['surfaces'][-1]
    scene['surfaces'] = []
    scene['pv_fields'] = []
    scene['module_instances'] = []
    for i, (x, tilt) in enumerate(zip(positions, tilts)):
        sid, fid, mid = f's{i}', f'f{i}', f'm{i}'
        roof = deepcopy(original)
        roof.update(surface_id=sid, scene_object_id=f'obj-{sid}', name=f'Roof {i}', group_id=None)
        roof['boundary_2d']['vertices'] = [[x, 0.], [x + 1., 0.], [x + 1., 3.], [x, 3.]]
        scene['surfaces'].append(roof)
        scene['pv_fields'].append({'pv_field_id': fid, 'support_surface_id': sid, 'module_definition_revision_id': MODULE['revision_id'],
                                   'tilt_deg': tilt, 'azimuth_deg': 0.})
        scene['module_instances'].append({'module_instance_id': mid, 'pv_field_id': fid, 'module_definition_revision_id': MODULE['revision_id'], 'enabled': True})
    return {'scene': scene, 'project': {}, 'electrical_design': {}, 'pinned_components': {'modules': {MODULE['revision_id']: MODULE}}}


def stripped(scene):
    result = deepcopy(scene)
    result.pop('buildings', None)
    for key in SCENE_ENVELOPE:
        result.pop(key, None)
    for surface in result['surfaces']:
        surface.pop('group_id', None)
    return json.dumps(result, sort_keys=True)


def test_editor_defaults_rename_upkeep_and_undo_without_geometry_changes():
    bundle = fixture_bundle()
    editor = SceneEditorSession(bundle['scene'])
    before = editor.scene
    editor.group(['s0'], group_id='a')
    assert editor.scene['buildings'] == [{'building_id': 'a', 'name': 'Building 1'}]
    editor.group(['s1'], group_id='b', name='Building 3')
    editor.group(['s2'], group_id='c')
    assert [b['name'] for b in editor.scene['buildings']] == ['Building 1', 'Building 3', 'Building 2']
    editor.group(['s0', 's1'], group_id='a', name='Main')
    assert editor.scene['buildings'] == [{'building_id': 'a', 'name': 'Main'}, {'building_id': 'c', 'name': 'Building 2'}]
    snapshot = editor.scene
    editor.ungroup(['s0', 's1'])
    assert editor.scene['buildings'] == [{'building_id': 'c', 'name': 'Building 2'}]
    assert editor.undo()
    assert editor.scene == snapshot
    assert stripped(editor.scene) == stripped(before)


def test_editor_keeps_obstacle_and_line_support_and_upkeeps_all_members():
    editor = SceneEditorSession(_roof_scene())
    editor.draw_box_obstacle(obstacle_id='o', scene_object_id='obj-o', name='Box', origin_x_m=20, origin_y_m=20,
                             width_m=1, depth_m=1, base_elevation_m=0, height_m=1)
    editor.draw_line(reference_line_id='l', scene_object_id='obj-l', name='Line', vertices=[(0, 0), (1, 1)])
    editor.group(['o', 'l'], group_id='g')
    assert editor.scene['buildings'] == [{'building_id': 'g', 'name': 'Building 1'}]
    editor.ungroup(['o'])
    assert editor.scene['buildings']
    editor.ungroup(['l'])
    assert editor.scene['buildings'] == []


@pytest.mark.parametrize('kwargs', [{'group_id': ''}, {'group_id': ' '}, {'group_id': 'x', 'name': ''},
                                    {'group_id': 'x', 'name': '  '}, {'group_id': 'x', 'name': 'x' * 81}])
def test_editor_refusals_are_atomic(kwargs):
    editor = SceneEditorSession(fixture_bundle()['scene'])
    before = editor.scene
    with pytest.raises(ValueError):
        editor.group(['s0'], **kwargs)
    assert editor.scene == before
    with pytest.raises(ValueError):
        editor.group(['missing'], group_id='x')
    assert editor.scene == before


@pytest.mark.parametrize('gap,cluster_count', [(0., 1), (.9, 1), (1.1, 2)])
def test_suggestions_touching_and_near_roofs(gap, cluster_count):
    bundle = fixture_bundle(positions=(0., 1. + gap), tilts=(0., 0.))
    before = deepcopy(bundle)
    result = systems_overview(bundle)
    assert len(result['suggested_buildings']) == cluster_count
    assert bundle == before


def test_suggestions_use_union_find_not_complete_linkage():
    bundle = fixture_bundle(positions=(0., 1.9, 3.8))
    result = systems_overview(bundle)
    assert result['suggested_buildings'] == [{'name': 'Building 1', 'surface_ids': ['s0', 's1', 's2'], 'matches_confirmed': False}]
    editor = SceneEditorSession(bundle['scene'])
    editor.group(['s0', 's1', 's2'], group_id='g')
    bundle['scene'] = editor.scene
    assert systems_overview(bundle)['suggested_buildings'][0]['matches_confirmed'] is True


def test_distances_include_ungrouped_host_roofs_and_warn_only():
    bundle = fixture_bundle(positions=(0., 4., 65.))
    result = systems_overview(bundle)
    assert [b['building_id'] for b in result['buildings']] == [None, None, None]
    assert [d['distance_m'] for d in result['distances']] == [3., 64., 60.]
    assert [d['over_threshold'] for d in result['distances']] == [False, True, True]
    bundle['project']['distance_warning_m'] = 100.
    assert all(not d['over_threshold'] for d in systems_overview(bundle)['distances'])
    assert all(b['stc_kwp'] == .4 for b in result['buildings'])


@pytest.mark.parametrize('tilts,counts', [((10., 10.5, 12.), [2, 1]), ((10., 10.7, 11.4), [2, 1])])
def test_orientation_groups_are_the_engine_clusters_with_complete_linkage(tilts, counts):
    bundle = fixture_bundle(tilts=tilts)
    scene = bundle['scene']
    strings = [{'string_id': m['module_instance_id'], 'module_instance_ids': [m['module_instance_id']]} for m in scene['module_instances']]
    keys = string_compatibility_keys(scene, strings, orientation_tolerance_deg=tolerance_deg(bundle['electrical_design']))
    expected = {}
    for m in scene['module_instances']:
        expected.setdefault(keys[m['module_instance_id']], []).append(m['pv_field_id'])
    groups = systems_overview(bundle)['orientation_groups']
    assert [g['pv_field_ids'] for g in groups] == list(expected.values())
    assert [g['module_count'] for g in groups] == counts
    assert groups[0]['label'] == '10.0° / 0.0°'
    bundle['electrical_design']['orientation_policy'] = {'normal_angle_tolerance_deg': .1}
    assert len(systems_overview(bundle)['orientation_groups']) == 3


def test_explicit_table_uses_its_own_orientation_and_support():
    bundle = fixture_bundle()
    scene = bundle['scene']
    scene['surfaces'][0]['boundary_2d']['vertices'] = [[0., 0.], [3., 0.], [3., 3.], [0., 3.]]
    field, modules = create_explicit_field(scene, {MODULE['revision_id']: MODULE}, pv_field_id='explicit', name='Explicit',
        tables=[{'table_id': 't', 'anchor_xyz_m': [1.5, 1.5, 20.], 'anchor_convention': 'center', 'tilt_deg': 40., 'azimuth_deg': 90.,
                 'module_definition_revision_id': MODULE['revision_id'], 'modules_across': 1, 'modules_up': 1,
                 'module_orientation': 'portrait', 'module_gap_across_m': .02, 'module_gap_up_m': .02, 'support_surface_id': 's0'}],
        provenance={'source_id': 'synthetic-use4a'})
    scene['pv_fields'].append(field)
    scene['module_instances'].extend(modules)
    group = systems_overview(bundle)['orientation_groups'][-1]
    assert group['label'] == '40.0° / 90.0°'
    assert group['surface_ids'] == ['s0'] and group['module_count'] == 1


@pytest.mark.parametrize('seed', range(200))
def test_distinct_state_clustering_equals_per_module_engine_call(seed):
    rng = random.Random(seed)
    count = rng.randint(2, 8)
    bundle = fixture_bundle(positions=tuple(i * 4. for i in range(count)), tilts=(10.,) * count)
    scene = bundle['scene']
    other = deepcopy(MODULE)
    other.update(revision_id='other-r1', model='Other module')
    other['stc']['pmp_w'] = 500.
    bundle['pinned_components']['modules'][other['revision_id']] = other
    bundle['electrical_design']['orientation_policy'] = {'normal_angle_tolerance_deg': rng.choice([0., .1, .5, 1.])}
    scene['module_instances'] = []
    for i, field in enumerate(scene['pv_fields']):
        scene['surfaces'][i]['albedo'] = rng.choice([.2, .2, .4])
        field.update(tilt_deg=rng.choice([0., 10., 10.5, 10.7, 11.4, 12.]), azimuth_deg=rng.choice([0., 90., 359.8]))
        for j in range(rng.randint(2, 8)):
            module = {'module_instance_id': f'm{i}-{j}', 'pv_field_id': f'f{i}', 'enabled': rng.random() > .1,
                      'module_definition_revision_id': rng.choice([MODULE['revision_id'], other['revision_id']])}
            scene['module_instances'].append(module)
    rng.shuffle(scene['module_instances'])
    modules = [m for field in scene['pv_fields'] for m in scene['module_instances'] if m['pv_field_id'] == field['pv_field_id'] and m['enabled']]
    strings = [{'string_id': m['module_instance_id'], 'module_instance_ids': [m['module_instance_id']]} for m in modules]
    keys = string_compatibility_keys(scene, strings, orientation_tolerance_deg=tolerance_deg(bundle['electrical_design']))
    clusters = {}
    for m in modules:
        clusters.setdefault(keys[m['module_instance_id']], []).append(m)
    expected = []
    for members in clusters.values():
        first = members[0]
        field = next(f for f in scene['pv_fields'] if f['pv_field_id'] == first['pv_field_id'])
        mount = field['tables'][0] if field.get('field_kind') == 'explicit_layout' else field
        support = next(s for s in scene['surfaces'] if s['surface_id'] == mount['support_surface_id'])
        signature, _ = module_execution_signature(first, field, support, {'albedo': .2}, '', 1)
        field_ids = list(dict.fromkeys(m['pv_field_id'] for m in members))
        expected.append({'label': f'{signature[3]:.1f}° / {signature[4]:.1f}°', 'pv_field_ids': field_ids,
            'surface_ids': ['s' + fid[1:] for fid in field_ids], 'building_ids': [None], 'module_count': len(members),
            'module_definition_revision_ids': list(dict.fromkeys(m['module_definition_revision_id'] for m in members)),
            'stc_kwp': sum(module_nameplate_w(bundle['pinned_components']['modules'][m['module_definition_revision_id']]) for m in members) / 1000.})
    assert systems_overview(bundle)['orientation_groups'] == expected


def large_overview_bundle():
    bundle = fixture_bundle(positions=(0.,), tilts=(10.,))
    module = bundle['scene']['module_instances'][0]
    bundle['scene']['module_instances'] = [dict(module, module_instance_id=f'm{i}') for i in range(10000)]
    return bundle


def test_10000_module_overview_under_two_seconds(monkeypatch):
    import importlib
    overview_module = importlib.import_module('apps.api.systems_overview')
    calls = []
    def recorded(scene, strings, **kwargs):
        calls.append(len(strings))
        return string_compatibility_keys(scene, strings, **kwargs)
    monkeypatch.setattr(overview_module, 'string_compatibility_keys', recorded)
    bundle = large_overview_bundle()
    started = perf_counter()
    result = systems_overview(bundle)
    elapsed = perf_counter() - started
    assert calls == [1]
    assert result['orientation_groups'][0]['module_count'] == 10000
    assert result['orientation_groups'][0]['stc_kwp'] == 4000.
    assert elapsed < 2., f'10,000-module overview took {elapsed:.3f}s'


def test_same_orientation_different_revisions_carry_model_identifiers():
    bundle = fixture_bundle(positions=(0., 4.), tilts=(10., 10.))
    other = deepcopy(MODULE)
    other.update(revision_id='other-r1', model='Other module')
    bundle['pinned_components']['modules'][other['revision_id']] = other
    bundle['scene']['module_instances'][1]['module_definition_revision_id'] = other['revision_id']
    groups = systems_overview(bundle)['orientation_groups']
    assert [g['label'] for g in groups] == ['10.0° / 0.0°', '10.0° / 0.0°']
    assert [g['module_definition_revision_ids'] for g in groups] == [[MODULE['revision_id']], ['other-r1']]


def test_schema_existing_scene_unchanged_and_new_buildings_validate():
    scene = _roof_scene()
    before = json.dumps(scene, sort_keys=True)
    _validate_scene(scene)
    assert json.dumps(scene, sort_keys=True) == before and 'buildings' not in scene
    scene['buildings'] = [{'building_id': 'a', 'name': 'Building 1'}]
    _validate_scene(scene)
    scene['buildings'][0]['extra'] = 1
    from jsonschema import ValidationError
    with pytest.raises(ValidationError):
        _validate_scene(scene)


def command(p, kind, ids, parameters):
    return p.client.post(p.url + '/scene/commands', json={'command': {'schema_name': 'SceneEditorCommand', 'schema_version': '0.1',
        'command_id': 'use4a-command', 'command_type': kind, 'target_entity_ids': ids, 'parameters': parameters}})


def test_api_overview_threshold_commands_and_history(tmp_path):
    p = Project(tmp_path, weather=False)
    before = p.bundle()
    sid = before['scene']['surfaces'][0]['surface_id']
    result = p.client.get(p.url + '/systems/overview')
    assert result.status_code == 200, result.text
    assert result.json()['schema_name'] == 'SystemsOverview' and result.json()['threshold_m'] == 50.
    assert p.bundle() == before
    grouped = command(p, 'group', [sid], {'group_id': 'g', 'name': 'Main'})
    assert grouped.status_code == 200, grouped.text
    after = p.bundle()
    assert stripped(after['scene']) == stripped(before['scene'])
    assert after['electrical_design']['strings'] == before['electrical_design']['strings']
    assert after['scene']['buildings'] == [{'building_id': 'g', 'name': 'Main'}]
    view = grouped.json()
    undo = p.client.post(p.url + '/undo', json={'expected_project_revision_id': after['workspace_state']['active_project_revision_id'],
        'expected_entry_id': view['history']['past'][-1]['entry_id']})
    assert undo.status_code == 200, undo.text
    assert p.bundle()['scene']['surfaces'][0].get('group_id') is None
    assert 'buildings' not in p.bundle()['scene']
    assert command(p, 'group', [sid], {'group_id': 'g', 'name': 'Main'}).status_code == 200
    assert command(p, 'group', [sid], {'group_id': 'g', 'name': 'Renamed'}).status_code == 200
    assert command(p, 'ungroup', [sid], {}).status_code == 200
    assert p.bundle()['scene']['buildings'] == []
    response = p.client.patch(p.url, json={'distance_warning_m': 100.})
    assert response.status_code == 200, response.text
    assert p.bundle()['project']['distance_warning_m'] == 100.
    assert p.client.get(p.url + '/systems/overview').json()['threshold_m'] == 100.
    for value in (-1, 10001, None):
        assert p.client.patch(p.url, json={'distance_warning_m': value}).status_code == 422
    assert p.client.get('/api/projects/missing/systems/overview').status_code == 404


def test_api_requires_name_and_surfaces_only(tmp_path):
    p = Project(tmp_path, weather=False)
    sid = p.bundle()['scene']['surfaces'][0]['surface_id']
    response = command(p, 'group', [sid], {'group_id': 'new'})
    assert response.status_code == 422 and response.json()['detail'] == 'a new building requires a name'
    for ids, params in [(['unknown'], {'group_id': 'x', 'name': 'A'}), ([sid], {'group_id': ' ', 'name': 'A'}),
                        ([sid], {'group_id': 'x', 'name': ' '}), ([], {'group_id': 'x', 'name': 'A'})]:
        assert command(p, 'group', ids, params).status_code == 422
    # Place non-surface entities directly in the temporary bundle; route target lookup still uses the real editor.
    b = p.bundle()
    editor = SceneEditorSession(b['scene'])
    editor.draw_box_obstacle(obstacle_id='obstacle', scene_object_id='obj-o', name='Box', origin_x_m=100, origin_y_m=100,
        width_m=1, depth_m=1, base_elevation_m=0, height_m=1)
    editor.draw_line(reference_line_id='line', scene_object_id='obj-l', name='Line', vertices=[(0, 0), (1, 1)])
    b['scene'] = editor.scene
    p.service.store.save(b)
    for entity in ('obstacle', 'line'):
        for kind in ('group', 'ungroup'):
            r = command(p, kind, [entity], {'group_id': 'g', 'name': 'Main'} if kind == 'group' else {})
            assert r.status_code == 422 and 'surfaces only' in r.text
