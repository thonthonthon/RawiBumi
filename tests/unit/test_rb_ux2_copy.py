"""UX2: the engine copy scene command (Duplicate) and its cloned-entity reference audit."""
from copy import deepcopy

import pytest

from apps.api.service import COPY_CLEARED_KEYS
from tests.unit.test_rb_fix_s2_honest_preflight import Project

# Every key a cloned roof/keep-out or obstacle may carry, and how copy treats it. A new key fails this audit until it
# is reviewed: replaced (own IDs), cleared (references to other entities) or kept (values of the copy itself).
REPLACED = {'surface_id', 'obstacle_id', 'scene_object_id'}
CLEARED = set(COPY_CLEARED_KEYS)
KEPT = {'albedo', 'azimuth_deg', 'base_elevation_m', 'boundary_2d', 'edge_dimension_sources', 'geometry_source',
        'locked', 'material', 'metadata', 'name', 'notes', 'selectable', 'shading_receiver', 'slope_deg',
        'surface_type', 'usable_for_pv', 'visible', 'dimensions', 'footprint', 'height_m', 'obstacle_type',
        'receiver_enabled', 'shading_enabled', 'plane', 'elevation_reference'}


def command(ids, dx=30.0, dy=0.0, **extra):
    return {'command': {'schema_name': 'SceneEditorCommand', 'schema_version': '0.1', 'command_id': 'ux2-copy',
                        'command_type': 'copy', 'target_entity_ids': ids, 'parameters': {'dx_m': dx, 'dy_m': dy, **extra}}}


@pytest.fixture
def p(tmp_path):
    project = Project(tmp_path, 18, weather=False, strings=False)
    s = project.service
    s.add_surface_rectangle(project.pid, name='Keepout', origin_x_m=0, origin_y_m=10, width_m=2, height_m=2,
                            base_elevation_m=0, surface_type='exclusion_area', usable_for_pv=False)
    s.add_box_obstacle(project.pid, name='Box', origin_x_m=30, origin_y_m=0, width_m=1, depth_m=1, base_elevation_m=0, height_m=1)
    return project


def post(p, body):
    return p.client.post(p.url + '/scene/commands', json=body)


def by_name(bundle, collection, name):
    return [e for e in bundle['scene'][collection] if e['name'] == name]


def test_roof_copy_is_one_revision_one_history_entry_and_never_copies_fields(p):
    before = p.bundle()
    roof = by_name(before, 'surfaces', 'Exact-count roof')[0]
    response = post(p, command([roof['surface_id']], dx=40))
    assert response.status_code == 200, response.text
    view = response.json()
    after = view['bundle']
    clone = by_name(after, 'surfaces', 'Exact-count roof copy')[0]
    assert clone['surface_id'] not in {s['surface_id'] for s in before['scene']['surfaces']}
    assert clone['scene_object_id'] == 'obj-' + clone['surface_id']
    shifted = [[x + 40, y] for x, y in roof['boundary_2d']['vertices']]
    assert clone['boundary_2d']['vertices'] == shifted
    assert after['scene']['pv_fields'] == before['scene']['pv_fields']
    assert after['scene']['module_instances'] == before['scene']['module_instances']
    assert after['project']['project_revision']['revision_number'] == before['project']['project_revision']['revision_number'] + 1
    assert view['history']['past'][-1]['label'] == 'Duplicate Exact-count roof.'
    entry = view['history']['past'][-1]
    undone = p.client.post(p.url + '/undo', json={'expected_project_revision_id': after['project']['project_revision']['project_revision_id'],
                                                   'expected_entry_id': entry['entry_id']})
    assert undone.status_code == 200, undone.text
    assert not by_name(undone.json()['bundle'], 'surfaces', 'Exact-count roof copy')


def test_keepout_and_obstacle_copies_use_the_obstacle_path(p):
    bundle = p.bundle()
    keepout = by_name(bundle, 'surfaces', 'Keepout')[0]
    box = by_name(bundle, 'obstacles', 'Box')[0]
    k = post(p, command([keepout['surface_id']], dx=3))
    assert k.status_code == 200, k.text
    assert by_name(k.json()['bundle'], 'surfaces', 'Keepout copy')[0]['surface_type'] == 'exclusion_area'
    o = post(p, command([box['obstacle_id']], dx=2))
    assert o.status_code == 200, o.text
    copy = by_name(o.json()['bundle'], 'obstacles', 'Box copy')[0]
    assert copy['obstacle_id'] != box['obstacle_id'] and copy['height_m'] == box['height_m']


def test_obstacle_copy_onto_modules_is_a_conflict_not_a_silent_overlap(p):
    # At roof height (the roof is at 6.1 m), so a copy over the array really meets the modules.
    p.service.add_box_obstacle(p.pid, name='Vent', origin_x_m=30, origin_y_m=0, width_m=1, depth_m=1, base_elevation_m=6.1, height_m=1)
    box = by_name(p.bundle(), 'obstacles', 'Vent')[0]
    saved = p.path.read_bytes()
    response = post(p, command([box['obstacle_id']], dx=-25, dy=1))
    assert response.status_code == 422, response.text
    assert response.json()['detail']['conflicts']
    assert p.path.read_bytes() == saved
    dry = post(p, {**command([box['obstacle_id']], dx=-25, dy=1), 'dry_run': True})
    assert dry.status_code in (200, 422)
    assert p.path.read_bytes() == saved
    applied = post(p, {**command([box['obstacle_id']], dx=-25, dy=1), 'on_module_conflict': 'remove_modules'})
    assert applied.status_code == 200, applied.text
    assert len(applied.json()['bundle']['scene']['module_instances']) < 18


def test_reference_audit_and_cleared_links(p):
    raw = p.bundle()
    roof = by_name(raw, 'surfaces', 'Exact-count roof')[0]
    keepout = by_name(raw, 'surfaces', 'Keepout')[0]
    keepout['group_id'] = 'group-a'
    keepout['parent_surface_id'] = roof['surface_id']
    by_name(raw, 'obstacles', 'Box')[0]['group_id'] = 'group-a'
    p.service.save_bundle(raw, history_mode='neutral')
    for collection, name in (('surfaces', 'Keepout'), ('obstacles', 'Box'), ('surfaces', 'Exact-count roof')):
        source = by_name(p.bundle(), collection, name)[0]
        source_id = source.get('surface_id') or source['obstacle_id']
        response = post(p, command([source_id], dx=50))
        assert response.status_code == 200, response.text
        bundle = response.json()['bundle']
        clone = by_name(bundle, collection, name + ' copy')[-1]
        assert set(clone) <= REPLACED | CLEARED | KEPT, set(clone) - (REPLACED | CLEARED | KEPT)
        for key in CLEARED & set(clone):
            assert clone[key] is None
        assert by_name(bundle, collection, name)[0] == source
    assert by_name(p.bundle(), 'surfaces', 'Keepout')[0]['group_id'] == 'group-a'


def test_refusals_leave_the_project_unchanged(p):
    raw = p.bundle()
    mesh = deepcopy(by_name(raw, 'obstacles', 'Box')[0])
    mesh.update(obstacle_id='obstacle-mesh', scene_object_id='obj-obstacle-mesh', name='Mesh', obstacle_type='imported_mesh')
    raw['scene']['obstacles'].append(mesh)
    p.service.save_bundle(raw, history_mode='neutral')
    roof = by_name(p.bundle(), 'surfaces', 'Exact-count roof')[0]['surface_id']
    saved = p.path.read_bytes()
    cases = [
        command(['obstacle-mesh']),
        command([roof], extra_key=1),
        command([roof, 'obstacle-mesh']),
        command([]),
        {'command': {**command([roof])['command'], 'parameters': {'dx_m': 'NaN', 'dy_m': 0}}},
        command([roof], dx=1e9),
    ]
    for body in cases:
        response = post(p, body)
        assert response.status_code == 422, (body, response.text)
        assert p.path.read_bytes() == saved
    assert 'read-only' in post(p, command(['obstacle-mesh'])).json()['detail']
