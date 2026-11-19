"""PERF3 allocation upper counts and conservative admission; no numerical solver changes."""
from copy import deepcopy
from types import SimpleNamespace
import sys

import numpy as np
import pytest

from geometry.shading import compile_shading_geometry, prepare_directional_receiver
from geometry.shading import parallel
from tests.unit.test_rb_mesh1_acceleration import synthetic_scene


def compiled_faces(vertices, *, copies=1):
    return {
        'geometry_payload_sha256': 'a' * 64,
        'receivers': [{'receiver_id': 'r0', 'enabled': True,
                       'source_entity_type': 'surface', 'source_entity_id': 'roof',
                       'vertices_3d': [[0., 0., 0.], [2., 0., 0.], [2., 2., 0.], [0., 2., 0.]],
                       'normal_xyz': [0., 0., 1.], 'area_m2': 4.}],
        'occluders': [{'occluder_id': 'o0', 'shading_enabled': True,
                       'source_entity_type': 'obstacle', 'source_entity_id': 'obstacle',
                       'geometry_type': 'polygon_faces',
                       'faces': [{'face_id': f'f{i}', 'vertices_3d': deepcopy(vertices)} for i in range(copies)]}],
    }


def check_bounds(compiled, ids, self_shading=True):
    config = {'self_shading_enabled': self_shading}
    rows = list(parallel._prepared_allocation_upper_counts(compiled, config, ids))
    assert len(rows) == len(ids)
    for row in rows:
        actual = prepare_directional_receiver(compiled, receiver_id=row['receiver_id'], self_shading_enabled=self_shading)
        assert row['face_upper'] >= len(actual.prepared_faces)
        assert row['vertex_upper'] >= sum(len(face.vertices_3d) for face in actual.prepared_faces)
        structures = sum(sys.getsizeof(face) + sys.getsizeof(vars(face)) + sys.getsizeof(face.vertices_3d)
                         + sum(sys.getsizeof(p) for p in face.vertices_3d) for face in actual.prepared_faces)
        packed = 0 if actual._bounds is None else sum(sys.getsizeof(a) for a in
            [actual._bounds.indices, actual._bounds.vertex_counts, actual._bounds.vertices, actual._bounds.distances])
        assert row['prepared_byte_upper'] >= structures + packed
    return rows


@pytest.mark.parametrize('seed', range(64))
@pytest.mark.parametrize('self_shading', [False, True])
def test_all_seeded_upper_counts_dominate_actual_preparation(seed, self_shading):
    compiled = compile_shading_geometry(synthetic_scene(seed))
    ids = [r['receiver_id'] for r in compiled['receivers'] if r['enabled']]
    check_bounds(compiled, ids, self_shading)


@pytest.mark.parametrize('height,expected', [(-1., 0), (0., 0), (1e-9, 1), (1., 1)])
def test_sourceward_contact_and_exact_tolerance(height, expected):
    c = compiled_faces([[0., 0., height], [1., 0., height], [1., 1., height], [0., 1., height]])
    rows = check_bounds(c, ['r0'])
    assert rows[0]['face_upper'] == expected


def test_crossing_triangle_quads_and_packed_bounds():
    c = compiled_faces([[-1., -1., -1.], [3., -1., 1.], [1., 3., 1.]], copies=80)
    row = check_bounds(c, ['r0'])[0]
    assert row['face_upper'] == 80
    assert row['vertex_upper'] == 320


def test_concave_many_crossings_needs_more_than_n_plus_one():
    ring = [(0., -2.), (8., -2.), (8., 1.), (7., -.5), (6., 1.), (5., -.5),
            (4., 1.), (3., -.5), (2., 1.), (1., -.5), (0., 1.)]
    points = [[1., y, z] for y, z in ring]
    row = check_bounds(compiled_faces(points), ['r0'])[0]
    assert row['vertex_upper'] > len(points) + 1


def test_deduped_vertices_are_overcounted_not_lost():
    points = [[0., 0., 1.], [1., 0., 1.], [1., 0., 1.], [1., 1., 1.], [0., 1., 1.]]
    c = compiled_faces(points)
    row = check_bounds(c, ['r0'])[0]
    actual = prepare_directional_receiver(c, receiver_id='r0', self_shading_enabled=True)
    assert row['vertex_upper'] > len(actual.prepared_faces[0].vertices_3d)


@pytest.mark.parametrize('case', ['disabled', 'own_source', 'module_opt_out'])
def test_disabled_self_and_module_exclusions_match_original(case):
    c = compiled_faces([[0., 0., 1.], [1., 0., 1.], [1., 1., 1.]])
    self_shading = True
    if case == 'disabled':
        c['occluders'][0]['shading_enabled'] = False
    elif case == 'own_source':
        c['occluders'][0].update(source_entity_type='surface', source_entity_id='roof')
    else:
        c['occluders'][0]['source_entity_type'] = 'module_instance'
        self_shading = False
    assert check_bounds(c, ['r0'], self_shading)[0]['face_upper'] == 0


def test_mixed_face_sizes_and_empty_scene_remain_conservative():
    c = compiled_faces([[0., 0., 1.], [1., 0., 1.], [1., 1., 1.]])
    c['occluders'][0]['faces'].append({'face_id': 'quad', 'vertices_3d':
        [[0., 0., 2.], [1., 0., 2.], [1., 1., 2.], [0., 1., 2.]]})
    assert check_bounds(c, ['r0'])[0]['vertex_upper'] == 7
    c['occluders'] = []
    assert check_bounds(c, ['r0'])[0]['face_upper'] == 0


def test_non_native_and_unresolved_metadata_do_not_claim_allocation_credit():
    c = compiled_faces([[0., 0., 1.], [1., 0., 1.], [1., 1., 1.]])
    c['occluders'][0]['faces'][0]['vertices_3d'][0][0] = np.float64(0.)
    with pytest.raises(parallel._AdmissionEstimateUnavailable):
        list(parallel._prepared_allocation_upper_counts(c, {'self_shading_enabled': True}, ['r0']))
    with pytest.raises(parallel._AdmissionEstimateUnavailable):
        list(parallel._prepared_allocation_upper_counts({}, {'self_shading_enabled': True}, ['missing']))


def test_admission_policy_constants_are_fixed():
    assert parallel._LATE_PARENT_ALLOWANCE_BYTES == 1536 * 1024**2
    assert (parallel._PREPARED_MARGIN_NUMERATOR, parallel._PREPARED_MARGIN_DENOMINATOR) == (5, 4)
    assert parallel._WORKER_BASE_BYTES == 96 * 1024**2
    assert parallel._WORKER_SCRATCH_MIN_BYTES == 8 * 1024**2
    assert parallel._WORKER_SCRATCH_BYTES_PER_FACE == 2048
    assert parallel.RESERVATION_BYTES == 6 * 1024**3


def native_empty_receivers():
    c = compiled_faces([[0., 0., 1.], [1., 0., 1.], [1., 1., 1.]])
    c['occluders'] = []
    r = c['receivers'][0]
    c['receivers'] = [dict(deepcopy(r), receiver_id=f'r{i}', source_entity_id=f'roof{i}') for i in range(256)]
    return c, [r['receiver_id'] for r in c['receivers']]


def test_small_machine_selects_serial_before_lease(monkeypatch):
    c, ids = native_empty_receivers()
    monkeypatch.delenv('PYTEST_XDIST_WORKER', raising=False)
    monkeypatch.delenv('RAWIBUMI_SHADING_WORKER', raising=False)
    monkeypatch.setattr(parallel, '_worker_limit', lambda: 12)
    monkeypatch.setattr(parallel, '_available_memory', lambda: 2 * 1024**3)
    monkeypatch.setattr(parallel, '_rss', lambda pid: 64 * 1024**2)
    def forbidden(*args, **kwargs):
        raise AssertionError('serial admission must not take a machine lease')
    monkeypatch.setattr(parallel._MachineLease, 'acquire', forbidden)
    pool, telemetry = parallel.create_receiver_pool(c, {'self_shading_enabled': True}, ids)
    assert pool is None and telemetry['reason'] == 'memory_reservation_unavailable'
    assert telemetry['late_parent_allowance_bytes'] == 1536 * 1024**2


def test_admission_selects_largest_fitting_existing_worker_count(monkeypatch):
    c, ids = native_empty_receivers()
    monkeypatch.delenv('PYTEST_XDIST_WORKER', raising=False)
    monkeypatch.delenv('RAWIBUMI_SHADING_WORKER', raising=False)
    monkeypatch.setattr(parallel, '_worker_limit', lambda: 12)
    monkeypatch.setattr(parallel, '_available_memory', lambda: 4 * 1024**3)
    monkeypatch.setattr(parallel, '_rss', lambda pid: 64 * 1024**2)
    captured = {}
    class Lease:
        def __init__(self, reservation): self.reservation_bytes = reservation
        def acquire(self): return True
    class Pool:
        def __init__(self, compiled, config, receivers, workers, lease):
            captured.update(workers=workers, reservation=lease.reservation_bytes)
            self.telemetry = {'mode': 'parallel', 'workers': workers}
    monkeypatch.setattr(parallel, '_MachineLease', Lease)
    monkeypatch.setattr(parallel, 'ExactReceiverPool', Pool)
    pool, telemetry = parallel.create_receiver_pool(c, {'self_shading_enabled': True}, ids)
    assert pool is not None and 2 <= captured['workers'] < 12
    base, per_worker, _ = parallel._receiver_allocation_estimate(c, {'self_shading_enabled': True}, ids, 64 * 1024**2)
    assert base + captured['workers'] * per_worker <= captured['reservation']
    assert base + (captured['workers'] + 1) * per_worker > captured['reservation']


def test_existing_hard_guard_remains_fatal(monkeypatch):
    pool = object.__new__(parallel.ExactReceiverPool)
    pool.lease = SimpleNamespace(reservation_bytes=100)
    pool.children = []
    pool.telemetry = {'peak_job_rss_bytes': 0}
    monkeypatch.setattr(parallel, '_rss', lambda pid: 101)
    with pytest.raises(parallel.ExactReceiverPoolError, match='exceeded its memory reservation'):
        pool._check_resources()
    assert pool.telemetry['peak_job_rss_bytes'] == 101
