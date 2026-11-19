"""ENG1 regressions: synthetic variants only, with disposable HTTP stores."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from apps.api.component_library import ComponentLibraryStore, IMPORTER_VERSION, definition_readiness
from apps.api.execution_readiness import phase5_inverter_definition_readiness
from apps.api.server import create_app
from components.candidates import build_inverter_candidate
from components.ond import map_ond, parse_ond_bytes
from components.validation import inverter_capabilities, validate_inverter

ROOT = Path(__file__).resolve().parents[2]
OND = (ROOT / 'tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND').read_bytes()
PAN = (ROOT / 'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN').read_bytes()
MODES = ('POutf_PIn', 'Efficiencyf_POut', 'Efficf_POut', 'Efficf_PIn', 'Efficiencyf_PIn')


def candidate(raw=OND):
    return build_inverter_candidate(map_ond(parse_ond_bytes(raw)), candidate_id='eng1',
        inverter_definition_id='eng1-inverter', revision_id='eng1-inverter-r1', source_id='eng1-synthetic-source')


def mode_bytes(mode):
    return OND.replace(b'ModeAffEnum=POutf_PIn', b'ModeAffEnum=' + mode.encode())


@pytest.fixture
def http(tmp_path):
    app = create_app(store_root=tmp_path / 'projects', library_root=tmp_path / 'component-library')
    with TestClient(app) as client:
        yield app, client, tmp_path / 'component-library'


def upload(client, raw, filename='synthetic.ond', dry=False):
    return client.post('/api/component-library/imports', params={'filename': filename, 'dry_run': dry},
        content=raw, headers={'Content-Type': 'application/octet-stream'})


def commit(client, raw, filename='synthetic.ond'):
    response = upload(client, raw, filename)
    assert response.status_code == 200, response.text
    return response.json()['entry']


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('mode', MODES)
def test_mode_changes_only_display_not_curves_capabilities_or_phase5_readiness(mode):
    baseline = candidate()
    actual = candidate(mode_bytes(mode))
    assert actual['definition_schema_ready']
    assert actual['canonical_data']['efficiency_model'] == baseline['canonical_data']['efficiency_model']
    assert actual['capability_flags'] == baseline['capability_flags']
    assert phase5_inverter_definition_readiness(actual['canonical_data']) == phase5_inverter_definition_readiness(baseline['canonical_data'])
    assert not [f for f in actual['validation_findings'] if f['rule_id'] == 'INVERTER_OND_SEMANTIC_ASSEMBLY_WARNING']


def test_unknown_mode_stays_refused_without_inventing_a_curve():
    actual = candidate(mode_bytes('Foo_Bar'))
    assert not actual['canonical_data']['efficiency_model'].get('curves')
    assert actual['capability_flags']['basic_yield_ready'] is False
    assert any(f['rule_id'] == 'INVERTER_OND_SEMANTIC_ASSEMBLY_WARNING' and "profile_mode='Foo_Bar'" in f['message']
               for f in actual['validation_findings'])


@pytest.mark.parametrize('pair', ['2831.2,3000.0', '0,1', '-1,0', '3000,-1', 'nan,0', 'inf,1'])
def test_bad_point_refuses_assembly_and_names_voltage_and_point_without_clipping(pair):
    head, tail = OND.split(b'ProfilPIOV1=TCubicProfile', 1)
    # The fixture's v1 Point_2 is 3000.0,2831.2; change this point alone.
    assert b'Point_2=3000.0,2831.2' in tail
    raw = head + b'ProfilPIOV1=TCubicProfile' + tail.replace(b'Point_2=3000.0,2831.2', b'Point_2=' + pair.encode(), 1)
    actual = candidate(raw)
    assert not actual['canonical_data']['efficiency_model'].get('curves')
    warnings = [f for f in actual['validation_findings'] if f['rule_id'] == 'INVERTER_OND_SEMANTIC_ASSEMBLY_WARNING']
    assert any('v1 (200.0 V) Point_2' in f['message'] and 'PIn >= POut >= 0' in f['message'] for f in warnings)
    mapped = map_ond(parse_ond_bytes(raw)).values_by_canonical_path
    assert mapped['ond_efficiency_source.profiles.v1.point_2']['ac_power_w'] == float(pair.split(',')[1])


def test_zero_origin_is_valid_but_missing_frequency_is_a_warning_not_a_default():
    head, tail = OND.split(b'ProfilPIOV1=TCubicProfile', 1)
    actual = candidate(head + b'ProfilPIOV1=TCubicProfile' + tail.replace(b'Point_1=500.0,0.0', b'Point_1=0,0', 1))
    assert actual['canonical_data']['efficiency_model']['curves'][0]['points'][0] == {
        'dc_power_w': 0.0, 'ac_power_w': 0.0, 'efficiency_fraction': 0.0}
    assert actual['canonical_data']['ac_limits'].get('nominal_frequency_hz') is None
    warning = next(f for f in actual['validation_findings'] if f['rule_id'] == 'INVERTER_AC_FREQUENCY_NOT_SPECIFIED')
    assert warning['severity'] == 'warning' and warning['category'] == 'ac'
    assert warning['message'] == ('The inverter file does not state its nominal AC frequency. It is not needed for the energy '
                                'simulation; check grid compatibility (50 Hz in Indonesia) against the datasheet.')
    assert not actual['capability_flags']['mppt_design_ready']
    assert not actual['capability_flags']['basic_design_ready']


def test_frequency_is_not_needed_for_design_but_other_ac_and_mppt_inputs_still_are():
    data = candidate()['canonical_data']
    data['mppt_template']['max_operating_current_a'] = 26.0  # Synthetic test-only datasheet overlay.
    without = inverter_capabilities(data, validate_inverter(data))
    assert without['basic_design_ready'] and without['mppt_design_ready']
    with_frequency = deepcopy(data)
    with_frequency['ac_limits']['nominal_frequency_hz'] = 50.0
    assert inverter_capabilities(with_frequency, validate_inverter(with_frequency)) == without
    assert not any(f['rule_id'] == 'INVERTER_AC_FREQUENCY_NOT_SPECIFIED' for f in validate_inverter(with_frequency))
    assert with_frequency['ac_limits']['nominal_frequency_hz'] == 50.0
    for group, key in [('ac_limits', 'nominal_ac_power_w'), ('ac_limits', 'nominal_ac_voltage_v'),
                       ('mppt_template', 'max_operating_current_a')]:
        broken = deepcopy(data)
        broken[group].pop(key)
        assert not inverter_capabilities(broken, validate_inverter(broken))['basic_design_ready']
    broken = deepcopy(data)
    broken.pop('phase_configuration')
    assert not inverter_capabilities(broken, validate_inverter(broken))['basic_design_ready']


@pytest.mark.parametrize('euro,maximum,metric,value', [('0.00','98.97','maximum',.9897),
    ('98.82','0.00','european',.9882), ('0.00','0.00',None,None)])
def test_zero_summary_is_null_in_canonical_mapping_and_preview(http, euro, maximum, metric, value):
    _, client, root = http
    raw = OND.replace(b'EfficEuro=98.82', b'EfficEuro=' + euro.encode()).replace(b'EfficMax=98.97', b'EfficMax=' + maximum.encode())
    mapping = map_ond(parse_ond_bytes(raw))
    for key, original in [('european_efficiency_fraction', euro), ('max_efficiency_fraction', maximum)]:
        path = 'efficiency_model.reference_metrics.' + key
        record = next(r for r in mapping.mapped_fields if r['canonical_path'] == path)
        expected = None if original == '0.00' else float(original) / 100
        assert mapping.values_by_canonical_path[path] == record['canonical_value'] == expected
        assert record['source_value'] == original
    # Per-voltage fields remain raw and unchanged, rather than supplying fabricated summary values.
    assert [f for f in mapping.unmapped_fields if f['key'] in ('EfficEuroV','EfficMaxV')] == [
        f for f in map_ond(parse_ond_bytes(OND)).unmapped_fields if f['key'] in ('EfficEuroV','EfficMaxV')]
    response = upload(client, raw, dry=True)
    assert response.status_code == 200, response.text
    assert response.json()['parameters']['efficiency_metric'] == metric
    assert response.json()['parameters']['efficiency_fraction'] == value
    assert not root.exists()


def synthetic_current_fixture(app, root, rid):
    """Test-only canonical overlay, representing the later S12a2 input, never an OND mapping."""
    path = root / 'inverters' / f'{rid}.json'
    entry = json.loads(path.read_text())
    data = entry['definition']
    data['mppt_template']['max_operating_current_a'] = 26.0
    data['source_ids'].append('src-eng1-synthetic-current-overlay')
    findings = validate_inverter(data)
    data['capability_flags'] = inverter_capabilities(data, findings)
    entry['library']['findings'] = findings
    entry['library']['readiness'] = definition_readiness('inverters', data)
    path.write_text(json.dumps(entry))
    app.state.project_service.refresh_catalog()
    return data


def executable_project(app, client, module_id, inverter_id):
    response = client.post('/api/projects', json={'name':'ENG1 synthetic study','latitude_deg':-6.2,
        'longitude_deg':106.8,'elevation_m':25,'timezone':'Asia/Jakarta'})
    assert response.status_code == 201
    pid = response.json()['bundle']['project']['project_id']
    url = f'/api/projects/{pid}'
    response = client.post(url+'/surfaces/rectangle', json={'name':'Roof','width_m':1+18*1.154-.01,'height_m':3.45,'base_elevation_m':6.1})
    assert response.status_code == 200
    sid = response.json()['bundle']['scene']['surfaces'][0]['surface_id']
    for endpoint, body in [('/pv-fields', {'name':'Array','support_surface_id':sid,'module_definition_revision_id':module_id,
        'tilt_deg':10,'row_pitch_m':3.2,'perimeter_setback_m':.5}),
        ('/inverters', {'name':'Inverter','inverter_definition_revision_id':inverter_id}), ('/strings', {'string_length':18})]:
        response = client.post(url+endpoint, json=body)
        assert response.status_code == 200, response.text
    iid = response.json()['bundle']['electrical_design']['inverter_instances'][0]['inverter_instance_id']
    assert client.post(url+'/assignments', json={'inverter_instance_id':iid}).status_code == 200
    app.state.study_service.acquire_weather(pid,source_id='open_meteo_archive_era5',start_date='2025-01-01',end_date='2025-01-01',
        raw_response=(ROOT/'tests/fixtures/weather/open_meteo_era5_phase60d_uat_padded_s10.json').read_bytes())
    return url


def completed(client, url):
    ready = client.get(url+'/execution-readiness')
    assert ready.status_code == 200 and ready.json()['ready'], ready.text
    assert not any(f['rule_id'] in ('INVERTER_BASIC_DESIGN_READY_FALSE','INVERTER_MPPT_DESIGN_READY_FALSE') for f in ready.json()['findings'])
    response = client.post(url+'/simulate', json={})
    assert response.status_code == 200, response.text
    assert response.json()['status'] in ('completed','completed_with_warnings')
    assert response.json()['model_manifest']['near_shading_runtime']['electrical_shading_scope'] == 'not_modeled'


def test_new_display_mode_library_huawei_simulates_with_synthetic_current_and_no_frequency(http):
    app, client, root = http
    module = commit(client, PAN, 'module.pan')
    inverter = commit(client, mode_bytes('Efficiencyf_POut'))
    assert not inverter['simulation_ready']
    data = synthetic_current_fixture(app, root, inverter['revision_id'])
    assert data['ac_limits'].get('nominal_frequency_hz') is None
    assert data['capability_flags']['basic_design_ready'] and data['capability_flags']['mppt_design_ready']
    url = executable_project(app, client, module['revision_id'], inverter['revision_id'])
    completed(client, url)
    pinned = client.get(url).json()['bundle']['pinned_components']['inverters'][inverter['revision_id']]
    assert pinned['ac_limits'].get('nominal_frequency_hz') is None
    assert pinned['mppt_template']['max_operating_current_a'] == 26.0


def legacy_entry(root, rid, kind, version):
    path = root / kind / f'{rid}.json'
    entry = json.loads(path.read_text())
    if version is None:
        entry['library'].pop('importer_version')
    else:
        entry['library']['importer_version'] = version
    path.write_text(json.dumps(entry, ensure_ascii=False, indent=2) + '\n')
    return path


@pytest.mark.parametrize('raw,filename,kind', [(PAN,'module.pan','modules'),(OND,'inverter.ond','inverters')])
@pytest.mark.parametrize('old_version', [None,1])
def test_remap_versions_preview_hide_only_old_revision_and_duplicate(http, raw, filename, kind, old_version):
    _, client, root = http
    first = commit(client, raw, filename)
    rid = first['revision_id']
    path = legacy_entry(root, rid, kind, old_version)
    original = path.read_bytes()
    before = tree(root)
    preview = upload(client, raw, filename, dry=True).json()
    assert preview['revision_id'] == rid[:-1]+'2'
    assert preview['remapped_from'] == rid and preview['duplicate_of'] is None
    assert tree(root) == before
    remap = upload(client, raw, filename).json()
    assert remap['created'] and remap['entry']['revision_id'] == preview['revision_id']
    assert remap['entry']['remapped_from'] == rid
    expected = json.loads(original)
    expected['library']['hidden'] = True
    assert path.read_bytes() == (json.dumps(expected, ensure_ascii=False, indent=2)+'\n').encode()
    second_path = root / kind / f"{remap['entry']['revision_id']}.json"
    second = json.loads(second_path.read_text())
    assert second['library']['importer_version'] == IMPORTER_VERSION == 8
    assert second['library']['remapped_from'] == rid
    assert second['definition'][('module_definition_id' if kind=='modules' else 'inverter_definition_id')] == expected['library']['definition_id']
    after = tree(root)
    duplicate = upload(client, raw, filename).json()
    assert not duplicate['created'] and duplicate['entry']['duplicate_of'] == second['definition']['revision_id']
    assert tree(root) == after
    assert client.post(f'/api/component-library/{rid}/unhide').status_code == 200
    assert not json.loads(path.read_text())['library']['hidden']


def test_remap_preserves_project_pinned_to_old_module_and_simulation(http):
    app, client, root = http
    module = commit(client, PAN, 'module.pan')
    rid = module['revision_id']
    legacy_entry(root, rid, 'modules', None)
    url = executable_project(app, client, rid, 'inv-rawibumi-uat-150k-r1')
    completed(client, url)
    before = client.get(url).json()['bundle']
    old_pins = deepcopy(before['pinned_components'])
    commit(client, PAN, 'module.pan')
    assert client.get(url).json()['bundle'] == before
    assert client.get(url).json()['bundle']['pinned_components'] == old_pins
    assert rid not in [m['revision_id'] for m in client.get('/api/catalog').json()['modules']]
    completed(client, url)
    assert client.get(url).json()['bundle']['pinned_components'] == old_pins


def test_concurrent_legacy_reimports_create_one_new_revision_and_hidden_duplicates_write_nothing(tmp_path):
    store = ComponentLibraryStore(tmp_path/'library')
    rid = store.import_bytes('module.pan', PAN)['entry']['revision_id']
    legacy_entry(store.root, rid, 'modules', None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _:store.import_bytes('module.pan', PAN), range(2)))
    assert sorted(r['created'] for r in results) == [False, True]
    assert len(store.entries(include_hidden=True)) == 2
    new_id = results[0]['entry']['revision_id']
    store.set_hidden(new_id, True)
    before = tree(store.root)
    assert store.import_bytes('module.pan', PAN)['entry']['duplicate_of'] == new_id
    assert tree(store.root) == before


def test_failed_auto_hide_does_not_leave_a_committed_replacement(http, monkeypatch):
    app, client, root = http
    first = commit(client, PAN, 'module.pan')
    path = legacy_entry(root, first['revision_id'], 'modules', None)
    before = tree(root)
    atomic = app.state.project_service.library._atomic
    def fail_old_entry(target, data):
        if target == path:
            raise OSError('synthetic hide failure')
        return atomic(target, data)
    monkeypatch.setattr(app.state.project_service.library, '_atomic', fail_old_entry)
    response = upload(client, PAN, 'module.pan')
    assert response.status_code == 503
    assert tree(root) == before
