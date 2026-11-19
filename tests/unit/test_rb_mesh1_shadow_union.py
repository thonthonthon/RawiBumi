"""A15/A16 exact-first overlay robustness, bounded evidence and real transport."""
from copy import deepcopy
from dataclasses import replace
from fractions import Fraction as F
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest
import shapely
from shapely.errors import GEOSException
from shapely.geometry import Polygon
from jsonschema import Draft202012Validator

from geometry.shading import beam, prepared, parallel
from geometry.shading.directional import calculate_directional_receiver_visibility
from geometry.shading.snapshot import evaluate_beam_shading_snapshot, BeamSnapshotError, _normalized_timestamp
from geometry.shading.sky import calculate_sky_visibility, SkyDomeResolution
from geometry.shading.ground import calculate_ground_visibility, GroundDomeResolution
from geometry.shading.sky_snapshot import evaluate_sky_shading_snapshot
from geometry.shading.ground_snapshot import evaluate_ground_shading_snapshot
from tests.unit.test_rb_mesh1_acceleration import configuration, exact_payload
from tests.unit.test_rb_mesh1_parallel import isolated_lease_directory

FIXTURE = Path('tests/fixtures/mesh1/shadow_union_28.json')


def fixture():
    return json.loads(FIXTURE.read_text())


def union_args():
    data = fixture()
    polygons = [Polygon(p['exterior'], p['holes']) for p in data['polygons']]
    receiver = Polygon(data['receiver']['exterior'])
    return data, polygons, receiver


def exact_rational_union_area(polygons):
    """Independent vertical arrangement; fixed before comparison in ORACLE_POLICY.

    Exact binary64 inputs as rationals. Every vertex/intersection X divides
    affine cross-section lengths; midpoint integration is exact on each slab.
    Resolution: exact; integration error: zero; conversion allowance: one ULP.
    No GEOS operation is used by this reference.
    """
    edges = []; poly_edges = []; xs = set()
    for polygon in polygons:
        pe = []
        for ring in [polygon['exterior'], *polygon['holes']]:
            vertices = [(F.from_float(float(x)), F.from_float(float(y))) for x, y in ring]
            if vertices[0] != vertices[-1]:
                vertices.append(vertices[0])
            xs.update(x for x, y in vertices)
            pe.extend((a, b) for a, b in zip(vertices, vertices[1:]) if a != b)
        poly_edges.append(pe); edges.extend(pe)
    def cross(a, b): return a[0] * b[1] - a[1] * b[0]
    def sub(a, b): return a[0] - b[0], a[1] - b[1]
    for i, (a, b) in enumerate(edges):
        for c, d in edges[i + 1:]:
            if (max(min(a[0], b[0]), min(c[0], d[0])) > min(max(a[0], b[0]), max(c[0], d[0]))
                    or max(min(a[1], b[1]), min(c[1], d[1])) > min(max(a[1], b[1]), max(c[1], d[1]))):
                continue
            r, s = sub(b, a), sub(d, c); denominator = cross(r, s)
            if denominator:
                t, u = cross(sub(c, a), s) / denominator, cross(sub(c, a), r) / denominator
                if 0 <= t <= 1 and 0 <= u <= 1:
                    xs.add(a[0] + t * r[0])
    area = F(0); ordered = sorted(xs)
    for left, right in zip(ordered, ordered[1:]):
        middle = (left + right) / 2; intervals = []
        for pe in poly_edges:
            ys = sorted(a[1] + (middle - a[0]) * (b[1] - a[1]) / (b[0] - a[0])
                        for a, b in pe if min(a[0], b[0]) < middle < max(a[0], b[0]))
            assert len(ys) % 2 == 0
            intervals.extend(zip(ys[::2], ys[1::2]))
        intervals.sort(); length = F(0); low = high = None
        for a, b in intervals:
            if low is None: low, high = a, b
            elif a <= high: high = max(high, b)
            else: length += high - low; low, high = a, b
        if low is not None: length += high - low
        area += (right - left) * length
    return float(area)


def test_captured_28_valid_polygons_and_independent_exact_area_oracle():
    data, polygons, receiver = union_args()
    assert len(polygons) == 28
    assert all(p.is_valid and p.is_simple and p.area > 0 for p in polygons)
    with pytest.raises(GEOSException):
        beam.unary_union(polygons)
    reference = exact_rational_union_area(data['polygons'])
    result, evidence = beam._shadow_union(polygons, receiver,
        receiver_id=data['source_receiver_id'], occluder_ids=data['occluder_ids'], source=data['normalized_sun'])
    assert evidence['quality_flags'] == ['shadow_union_precision_fallback']
    event, = evidence['shadow_union_precision_fallback_events']
    assert event['grid_size_m'] == 1e-10
    assert event['perimeter_m'] == sum(p.length for p in polygons)
    assert event['area_bound_m2'] == event['perimeter_m'] * event['grid_size_m']
    assert abs(result.area - reference) <= event['area_bound_m2'] + math.ulp(reference)
    assert result.difference(receiver).area == 0


def test_exact_success_returns_original_union_without_overlay_or_evidence(monkeypatch):
    polygon = Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
    expected = beam.unary_union([polygon])
    monkeypatch.setattr(beam.shapely, 'union_all', lambda *a, **k: pytest.fail('precision overlay on exact success'))
    # Keep original exact evaluator independent of the patched top-level alias.
    monkeypatch.setattr(beam, 'unary_union', lambda polygons: expected)
    result, evidence = beam._shadow_union([polygon], polygon,
        receiver_id='r', occluder_ids=['o'], source=(0, 0, 1))
    assert result is expected and evidence == {}


@pytest.mark.parametrize('success_at', range(5))
def test_grid_ladder_stops_at_first_success(monkeypatch, success_at):
    data, polygons, receiver = union_args(); calls = []
    def exact(polygons): raise GEOSException('exact failure')
    def precision(polygons, *, grid_size):
        calls.append(grid_size)
        if len(calls) <= success_at: raise GEOSException('precision failure')
        return receiver
    monkeypatch.setattr(beam, 'unary_union', exact)
    monkeypatch.setattr(beam.shapely, 'union_all', precision)
    _, evidence = beam._shadow_union(polygons, receiver, receiver_id='r', occluder_ids=['o'], source=(0, 0, 1))
    assert calls == list(beam.SHADOW_UNION_GRIDS_M[:success_at + 1])
    assert evidence['shadow_union_precision_fallback_events'][0]['grid_size_m'] == calls[-1]


def test_all_steps_fail_chains_original_and_keeps_context(monkeypatch):
    _, polygons, receiver = union_args(); original = GEOSException('original overlay')
    calls = []
    def exact(polygons): raise original
    def precision(polygons, *, grid_size):
        calls.append(grid_size); raise GEOSException('fallback overlay')
    monkeypatch.setattr(beam, 'unary_union', exact)
    monkeypatch.setattr(beam.shapely, 'union_all', precision)
    with pytest.raises(beam.BeamShadowError) as info:
        beam._shadow_union(polygons, receiver, receiver_id='receiver-test', occluder_ids=['obs-b', 'obs-a'], source=(0, 0, 1))
    assert info.value.__cause__ is original
    assert calls == list(beam.SHADOW_UNION_GRIDS_M)
    assert 'receiver-test' in str(info.value) and "['obs-a', 'obs-b']" in str(info.value)
    assert 'timestamp=unavailable' in str(info.value)


def test_non_geos_error_never_retries(monkeypatch):
    _, polygons, receiver = union_args()
    def exact(polygons): raise ValueError('not overlay robustness')
    monkeypatch.setattr(beam, 'unary_union', exact)
    monkeypatch.setattr(beam.shapely, 'union_all', lambda *a, **k: pytest.fail('unexpected retry'))
    with pytest.raises(ValueError, match='not overlay robustness'):
        beam._shadow_union(polygons, receiver, receiver_id='r', occluder_ids=[], source=(0, 0, 1))


def query_maps():
    data = fixture(); compiled = data['compiled_geometry']; rid = data['source_receiver_id']
    fast = prepared.prepare_directional_receiver(compiled, receiver_id=rid, self_shading_enabled=True)
    # Force the certified broad phase even on this intentionally small fixture.
    fast = replace(fast, _bounds=prepared._build_bound_state(fast))
    return data, compiled, rid, fast, replace(fast, _bounds=None)


def test_reference_direct_prepared_and_directional_agree_with_fallback():
    data, compiled, rid, fast, reference = query_maps()
    kwargs = dict(sun_vector_xyz=data['normalized_sun'])
    frozen = prepared.calculate_prepared_direct_beam_shadow(reference, **kwargs)
    accelerated = prepared.calculate_prepared_direct_beam_shadow(fast, **kwargs)
    direct = beam.calculate_direct_beam_shadow(compiled, receiver_id=rid, self_shading_enabled=True, **kwargs)
    assert frozen == accelerated == direct
    assert frozen['shadow_union_precision_fallback_events'][0]['grid_size_m'] == 1e-10
    directional = calculate_directional_receiver_visibility(compiled, receiver_id=rid,
        self_shading_enabled=True, source_direction_xyz=data['normalized_sun'])
    assert directional['shadow_union_precision_fallback_events'] == frozen['shadow_union_precision_fallback_events']
    assert directional['shaded_area_m2'] == frozen['shaded_area_m2']
    for name, payload in [('beam-shadow-query-result', direct), ('directional-visibility-query-result', directional)]:
        Draft202012Validator(json.loads(Path(f'geometry/shading/{name}.schema.json').read_text())).validate(payload)


@pytest.mark.parametrize('workers', [1, 2, 12])
def test_real_pool_snapshot_matches_reference_and_saved_evidence(workers, isolated_lease_directory):
    data, compiled, rid, fast, reference = query_maps(); config = configuration()
    kwargs = dict(shading_configuration=config, receiver_ids=[rid], sun_vector_xyz=data['raw_sun'], timestamp=data['timestamp'])
    expected = evaluate_beam_shading_snapshot(compiled, prepared_queries={rid: reference}, **kwargs).shading_result
    serial = evaluate_beam_shading_snapshot(compiled, prepared_queries={rid: fast}, **kwargs).shading_result
    exact_payload(serial, expected, label='fallback serial')
    lease = parallel._MachineLease(); assert lease.acquire()
    pool = parallel.ExactReceiverPool(compiled, config, [rid], workers, lease)
    carrier = parallel.PreparedReceiverMap(SimpleNamespace(receiver_ids=(rid,), prepared_query=lambda _: fast), pool)
    try:
        actual = evaluate_beam_shading_snapshot(compiled, prepared_queries=carrier, **kwargs).shading_result
        exact_payload(actual, expected, label=f'fallback pool {workers}')
    finally:
        pool.close()
    record, = actual['inline_records']; event, = record['shadow_union_precision_fallback_events']
    assert 'shadow_union_precision_fallback' in record['quality_flags']
    assert event['timestamp'] == record['timestamp'] and event['channel'] == 'beam'
    totals = beam._fallback_totals(record['shadow_union_precision_fallback_events'])['shadow_union_precision_fallback']
    assert totals['count'] == 1 and totals['grid_size_m_histogram'] == {'1e-10': 1}
    Draft202012Validator(json.loads(Path('geometry/shading/shading-result.schema.json').read_text())).validate(actual)


def test_snapshot_exhaustion_includes_actual_timestamp(monkeypatch):
    data, compiled, rid, fast, _ = query_maps()
    def fail(polygons): raise GEOSException('exhausted')
    monkeypatch.setattr(beam, 'unary_union', fail)
    monkeypatch.setattr(beam.shapely, 'union_all', lambda *a, **k: fail(a[0]))
    with pytest.raises(BeamSnapshotError) as info:
        evaluate_beam_shading_snapshot(compiled, prepared_queries={rid: fast}, shading_configuration=configuration(),
            receiver_ids=[rid], sun_vector_xyz=data['raw_sun'], timestamp=data['timestamp'])
    assert _normalized_timestamp(data['timestamp']) in str(info.value) and rid in str(info.value)


def test_diffuse_queries_and_snapshots_preserve_conditional_events(monkeypatch):
    data, compiled, rid, _, _ = query_maps()
    compiled = deepcopy(compiled)
    receiver = compiled['receivers'][0]
    center, normal = receiver['center_xyz'], receiver['normal_xyz']
    cover = deepcopy(compiled['occluders'][0])
    cover['occluder_id'] = 'synthetic-front-cover'
    cover['faces'] = [{
        'face_id': 'cover', 'normal_xyz': normal,
        'vertices_3d': [[center[k] + 100 * (point[k] - center[k]) + .001 * normal[k]
                         for k in range(3)] for point in receiver['vertices_3d']],
    }]
    compiled['occluders'].append(cover)
    fast = prepared.prepare_directional_receiver(compiled, receiver_id=rid, self_shading_enabled=True)
    def fail(polygons): raise GEOSException('force fallback for diffuse propagation')
    monkeypatch.setattr(beam, 'unary_union', fail)
    for channel, query_fn, snapshot_fn, resolution, schema in (
        ('sky', calculate_sky_visibility, evaluate_sky_shading_snapshot, SkyDomeResolution(4, 1, 4, 1, 10.), 'sky-visibility-query-result'),
        ('ground', calculate_ground_visibility, evaluate_ground_shading_snapshot, GroundDomeResolution(12, 12), 'ground-visibility-query-result'),
    ):
        result = query_fn(compiled, receiver_id=rid, self_shading_enabled=True, resolution=resolution, prepared_query=fast)
        assert result['shadow_union_precision_fallback_events']
        Draft202012Validator(json.loads(Path(f'geometry/shading/{schema}.schema.json').read_text())).validate(result)
        actual = snapshot_fn(compiled, shading_configuration=configuration(), receiver_ids=[rid], prepared_queries={rid: fast}).shading_result
        record, = actual['inline_records']
        assert 'shadow_union_precision_fallback' in record['quality_flags']
        assert all(e['timestamp'] is None for e in record['shadow_union_precision_fallback_events'])
        Draft202012Validator(json.loads(Path('geometry/shading/shading-result.schema.json').read_text())).validate(actual)


def test_run_counts_static_events_once_and_aggregates_groups(tmp_path, monkeypatch):
    from tests.unit.test_phase49c_reference_projects import _reference
    from tests.unit.test_rb_mesh1_tables import _convert_design_to_explicit
    from apps.api.study import _phase5_configuration, _validation_configuration
    from validation.engineering import validate_engineering_design
    from engine.simulation import build_design_revision_store, run_validated_design_simulation
    from engine.simulation import geometry_aware
    from engine.simulation.artifacts import verify_run_package
    from geometry.shading.cache import GLOBAL_EXACT_STATIC_SHADING_CACHE
    r = _reference('R5')
    scene, electrical = _convert_design_to_explicit(r['scene'], r['electrical'], r['components'])
    # R5's coplanar arrays alone produce no unions. A raised synthetic cover
    # exercises real beam/static unions without contacting any module.
    from geometry.scene.mesh import make_mesh_obstacle
    scene['obstacles'].append(make_mesh_obstacle(
        obstacle_id='union-evidence-cover', scene_object_id='obj-union-cover',
        name='Synthetic union evidence cover',
        mesh={'vertices_m': [[-100, -100, 50], [100, -100, 50],
                             [100, 100, 50], [-100, 100, 50]], 'faces': [[0, 1, 2, 3]]},
        provenance={'source_id': 'synthetic-union-evidence'},
    ))
    config = _phase5_configuration(r['project_revision'], configuration_id='union-run-evidence')
    config['shading_configuration']['self_shading_enabled'] = True
    report = validate_engineering_design(scene, electrical,
        project_revision_id=r['project_revision']['project_revision_id'], component_revisions=r['components'],
        configuration=_validation_configuration(), design_validation_report_id='union-run-evidence', generated_at='2026-11-04T00:00:00Z')
    assert not report['blocking_simulation']
    def force(polygons): raise GEOSException('exercise run-level fallback evidence')
    monkeypatch.setattr(beam, 'unary_union', force)
    GLOBAL_EXACT_STATIC_SHADING_CACHE.clear()
    observed = []
    for name in ('evaluate_beam_shading_snapshot', 'evaluate_sky_shading_snapshot', 'evaluate_ground_shading_snapshot'):
        original = getattr(geometry_aware, name)
        def observe(*args, _original=original, **kwargs):
            result = _original(*args, **kwargs)
            observed.extend(event for record in result.shading_result['inline_records']
                for event in record.get('shadow_union_precision_fallback_events', []))
            return result
        monkeypatch.setattr(geometry_aware, name, observe)
    result = run_validated_design_simulation(r['project_revision'], config,
        revision_store=build_design_revision_store(scene, electrical, r['weather'], r['components']),
        design_validation_report=report, output_directory=tmp_path,
        simulation_run_id='union-evidence', engine_version='mesh1-test', executed_at='2026-11-04T00:00:00Z')
    assert result.backend_result is not None, result.simulation_run
    verify_run_package(result.artifact_directory)
    runtime = result.backend_result.metadata['shading_runtime']
    evidence = runtime['shadow_union_precision_fallback']
    groups = runtime['execution_groups']
    assert len(groups) == 2
    assert evidence['count'] == len(observed) > 0
    assert evidence['count'] == sum(g['shadow_union_precision_fallback']['count'] for g in groups.values())
    assert sum(evidence['grid_size_m_histogram'].values()) == evidence['count']
    assert evidence['max_area_bound_m2'] == max(e['area_bound_m2'] for e in observed)
    static = [e for e in evidence['events'] if e['channel'] != 'beam']
    assert static and all(e['timestamp'] is None for e in static)
    saved = (result.artifact_directory / 'reproducibility-manifest.json').read_text()
    assert 'shadow_union_precision_fallback' in saved


def test_detailed_region_snapshot_keeps_events_and_flags(monkeypatch):
    from shading.electrical import local_irradiance as local
    from shading.electrical import derive_electrical_region_map
    from tests.unit.test_phase63_electrical_regions import _topology
    data = fixture(); compiled = data['compiled_geometry']
    topology = _topology()
    topology['module_definition_revision_id'] = compiled['receivers'][0]['metadata']['module_definition_revision_id']
    mapped = derive_electrical_region_map(compiled, topology,
        module_instance_id=compiled['receivers'][0]['module_instance_id'])
    def query(*args, receiver_id, **kwargs):
        return {
            'status': 'evaluated', 'beam_visibility_factor': .5,
            'sky_visibility_factor': .6, 'horizon_visibility_factor': .7,
            'ground_visibility_factor': .8,
            'shadow_union_precision_fallback_events': [{
                'receiver_id': receiver_id, 'occluder_ids': ['synthetic'],
                'source_direction_xyz': [0., 0., 1.], 'grid_size_m': 1e-10,
                'perimeter_m': 2., 'area_bound_m2': 2e-10,
            }],
        }
    monkeypatch.setattr(local, 'calculate_direct_beam_shadow', query)
    monkeypatch.setattr(local, 'calculate_sky_visibility', query)
    monkeypatch.setattr(local, 'calculate_ground_visibility', query)
    result = local.evaluate_electrical_region_visibility(compiled, mapped,
        sun_vector_xyz=[0, 0, 1], self_shading_enabled=True,
        sky_resolution=SkyDomeResolution(4, 1, 4, 1, 10.),
        ground_resolution=GroundDomeResolution(4, 1), timestamp=data['timestamp'])
    for record in result['inline_records']:
        assert record['quality_flags'] == ['shadow_union_precision_fallback']
        assert len(record['shadow_union_precision_fallback_events']) == 3
        assert record['shadow_union_precision_fallback_events'][0]['timestamp'] == record['timestamp']
