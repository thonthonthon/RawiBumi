"""S12a2: synthetic public-fixture variants, disposable stores, real HTTP and runs."""
from tests.unit._availability import missing_commit
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

from fastapi.testclient import TestClient
import numpy as np
import pytest

from apps.api.server import create_app
from components.candidates import build_inverter_candidate
from components.ond import map_ond, parse_ond_bytes
from components.ond.semantics import assemble_inverter_semantics, SINGLE_PROFILE_WARNING
from engine.inverter.model import evaluate_voltage_dependent_conversion, _curve_ac_output_w

ROOT = Path(__file__).resolve().parents[2]
OND = (ROOT/'tests/fixtures/panond/manufacturer/Huawei_Sun2000_100KTL_M1.OND').read_bytes()
PAN = (ROOT/'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN').read_bytes()
CURRENT = 'mppt_template.max_operating_current_a'
SOURCE = {'document': 'Fictional test-only datasheet', 'page_or_section': 'Table 1', 'url': 'https://example.com/synthetic'}


def single_bytes():
    # Retain public scalar inputs, synthesize one ProfilPIO from the V2 source pairs.
    text = OND.decode()
    before, profiles = text.split('  ProfilPIO=TCubicProfile', 1)
    _, v2 = profiles.split('  ProfilPIOV2=TCubicProfile', 1)
    v2 = v2.split('  ProfilPIOV3=TCubicProfile', 1)[0]
    # Original profile blocks are the final converter members; preserve the enclosing END markers.
    tail = profiles.split('  ProfilPIOV3=TCubicProfile', 1)[1]
    tail = tail[tail.index('  End of TCubicProfile') + len('  End of TCubicProfile'):]
    return (before.replace('    VNomEff=200.0,650.0,1000.0\n', '') + '  ProfilPIO=TCubicProfile' + v2 + tail).encode()


def candidate(raw):
    return build_inverter_candidate(map_ond(parse_ond_bytes(raw)), candidate_id='s12a2',
        inverter_definition_id='s12a2', revision_id='s12a2-r1', source_id='src-s12a2')


def upload(c, raw=OND, filename='synthetic.ond'):
    r = c.post('/api/component-library/imports', params={'filename': filename}, content=raw)
    assert r.status_code == 200, r.text
    return r.json()['entry']


def complete(c, rid, fields=None, source=SOURCE, dry=False):
    return c.post(f'/api/component-library/{rid}/complete', json={'fields': fields or {CURRENT: 26}, 'source': source, 'dry_run': dry})


def tree(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.fixture
def http(tmp_path):
    app = create_app(store_root=tmp_path/'projects', library_root=tmp_path/'library')
    with TestClient(app) as c:
        yield app, c, tmp_path/'library'


def stored(c, rid):
    return next(e for e in c.get('/api/component-library?include_hidden=true').json() if e['definition']['revision_id'] == rid)


@pytest.mark.parametrize('single', [False, True])
def test_complete_preview_provenance_pins_and_real_simulation(http, single):
    app, c, root = http
    base = upload(c, single_bytes() if single else OND); rid = base['revision_id']
    assert not base['simulation_ready']
    module = upload(c, PAN, 'synthetic.pan')['revision_id']
    # Reuse unchanged HTTP setup/real simulation helpers, not a fake runtime.
    spec = importlib.util.spec_from_file_location('s12a_setup', ROOT/'tests/unit/test_rb_fix_s12a_component_library.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    pid, url = helper.executable(app, c, module, rid)
    old_pin = deepcopy(c.get(url).json()['bundle']['pinned_components']['inverters'][rid])
    before = tree(root)
    preview = complete(c, rid, dry=True)
    assert preview.status_code == 200, preview.text
    p = preview.json(); assert p['simulation_ready'] and p['revision_id'].endswith('-r2')
    assert p['completed_fields'] == [{'path': CURRENT, 'value': 26, 'unit': 'A', 'source': SOURCE}]
    assert tree(root) == before
    result = complete(c, rid); assert result.status_code == 200, result.text
    new = result.json()['entry']; new_id = new['revision_id']; assert new['simulation_ready']
    saved = stored(c, new_id); old = stored(c, rid)
    assert old['library']['hidden'] and saved['library']['completed_from'] == rid
    assert saved['library']['revision_number'] == old['library']['revision_number'] + 1
    assert saved['library']['definition_id'] == old['library']['definition_id']
    provenance = saved['library']['field_provenance'][CURRENT][0]
    canonical = json.dumps({'fields': {CURRENT: 26.0}, 'source': SOURCE}, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    assert provenance['source_id'] == 'src-user-datasheet-' + hashlib.sha256(canonical.encode()).hexdigest()[:16]
    assert provenance['source_kind'] == 'user_supplied' and provenance['value'] == 26
    assert json.loads(provenance['notes']) == SOURCE
    assert saved['library']['completion']['source'] == SOURCE
    assert c.get(url).json()['bundle']['pinned_components']['inverters'][rid] == old_pin
    assert all(tree(root)[path] == content for path, content in before.items() if not path.endswith(f'{rid}.json'))
    if single:
        assert any(f['rule_id'] == 'INVERTER_SINGLE_EFFICIENCY_CURVE' and f['message'] == SINGLE_PROFILE_WARNING for f in new['findings'])
    # Separate project uses the newly completed revision, under the default shading selection.
    _, run_url = helper.executable(app, c, module, new_id)
    run = helper.simulate(c, run_url)
    assert run['model_manifest']['near_shading_runtime']['electrical_shading_scope'] == 'not_modeled'
    assert c.get(url).status_code == 200  # Base-pinned project still loads after auto-hide.


def test_idempotence_citation_and_raw_reimport_do_not_adopt_overlay(http):
    _, c, root = http; rid = upload(c)['revision_id']
    first = complete(c, rid).json()['entry']; before = tree(root)
    second = complete(c, rid).json(); assert not second['created'] and second['entry']['duplicate_of'] == first['revision_id']
    assert tree(root) == before
    other = complete(c, rid, source={**SOURCE, 'page_or_section': 'Table 2'}).json()
    assert other['created'] and other['entry']['revision_id'].endswith('-r3')
    raw = upload(c); assert raw['revision_id'] == rid and not raw['simulation_ready']


@pytest.mark.parametrize('fields,source,code', [
    ({CURRENT: 0}, SOURCE, 'completion_invalid'), ({CURRENT: 250}, SOURCE, 'completion_invalid'),
    ({'ac_limits.nominal_frequency_hz': 55}, SOURCE, 'completion_invalid'),
    ({CURRENT: 26, 'mppt_template.max_short_circuit_current_a': 25}, SOURCE, 'completion_invalid'),
    ({'dc_limits.max_dc_current_a': 5001}, SOURCE, 'completion_invalid'),
    ({'ac_limits.nominal_ac_power_w': 100}, SOURCE, 'completion_field_not_allowed'),
    ({'mppt_template.min_operating_voltage_v': 100}, SOURCE, 'completion_field_not_allowed'),
    ({CURRENT: '26'}, SOURCE, 'completion_invalid'), ({CURRENT: True}, SOURCE, 'completion_invalid'),
    ({CURRENT: 26}, None, 'completion_source_required'),
    ({CURRENT: 26}, {**SOURCE, 'document': '  '}, 'completion_source_required'),
    ({CURRENT: 26}, {**SOURCE, 'page_or_section': ''}, 'completion_source_required'),
    ({CURRENT: 26}, {**SOURCE, 'url': 'file:///tmp/fake'}, 'completion_invalid'),
])
def test_refusals_write_nothing(http, fields, source, code):
    _, c, root = http; rid = upload(c)['revision_id']; before = tree(root)
    r = complete(c, rid, fields, source)
    assert r.status_code == 422 and r.json()['detail']['code'] == code, r.text
    assert tree(root) == before


def test_missing_source_extras_nonfinite_unknown_and_existing_values(http):
    _, c, root = http; rid = upload(c)['revision_id']; before = tree(root)
    url = f'/api/component-library/{rid}/complete'
    for payload, code in [({'fields': {CURRENT: 26}}, 'completion_source_required'),
            ({'fields': {CURRENT: 26}, 'source': SOURCE, 'surprise': 1}, 'completion_invalid'),
            ({'fields': {CURRENT: float('nan')}, 'source': SOURCE}, 'completion_invalid'),
            ({'fields': {CURRENT: float('inf')}, 'source': SOURCE}, 'completion_invalid')]:
        r = c.post(url, content=json.dumps(payload), headers={'Content-Type': 'application/json'})
        assert r.status_code == 422 and r.json()['detail']['code'] == code, r.text
    assert complete(c, 'unknown').status_code == 404
    assert tree(root) == before
    complete(c, rid)
    ready = stored(c, rid[:-1]+'2'); before = tree(root)
    r = complete(c, ready['definition']['revision_id'])
    assert r.status_code == 422 and r.json()['detail']['code'] == 'completion_conflicts_with_file'
    assert tree(root) == before


def test_manufacturer_value_cannot_be_overwritten_even_with_same_value(http):
    _, c, root = http
    rid = upload(c)['revision_id']
    path = root/'inverters'/f'{rid}.json'
    # Synthetic stored manufacturer definition: an already known allowed value.
    # This is not a claim that the public OND encodes this field.
    entry = json.loads(path.read_text())
    entry['definition']['mppt_template']['max_operating_current_a'] = 26
    path.write_text(json.dumps(entry))
    before = tree(root)
    for value in (26, 27):
        response = complete(c, rid, {CURRENT: value})
        assert response.status_code == 422 and response.json()['detail']['code'] == 'completion_conflicts_with_file'
        assert tree(root) == before


def test_null_absence_remaining_fields_and_chained_provenance(http):
    _, c, root = http; rid = upload(c)['revision_id']
    path = root/'inverters'/f'{rid}.json'; entry = json.loads(path.read_text())
    entry['definition']['mppt_template']['max_operating_current_a'] = None
    path.write_text(json.dumps(entry))
    first = complete(c, rid).json()['entry']['revision_id']
    provenance = stored(c, first)['library']['field_provenance'][CURRENT]
    second = complete(c, first, {'ac_limits.nominal_frequency_hz': 50,
        'mppt_template.max_short_circuit_current_a': 40, 'dc_limits.max_dc_current_a': 5000})
    assert second.status_code == 200, second.text
    new = stored(c, second.json()['entry']['revision_id'])
    assert new['library']['field_provenance'][CURRENT] == provenance
    assert new['definition']['mppt_template']['max_operating_current_a'] == 26
    assert new['definition']['dc_limits']['max_dc_current_a'] == 5000
    assert new['definition']['ac_limits']['nominal_frequency_hz'] == 50
    assert not any(f['rule_id'] == 'INVERTER_AC_FREQUENCY_NOT_SPECIFIED' for f in new['library']['findings'])


def test_reason_codes_empty_file_and_module_completion_refusal(http):
    _, c, root = http
    r = c.post('/api/component-library/imports?filename=empty.ond', content=b'')
    assert r.status_code == 422 and r.json()['detail'] == {'code': 'component_file_empty', 'message': 'The file is empty. Copy it again from its source.'}
    assert not root.exists()
    p = upload(c); assert {'mppt_operating_current_missing', 'basic_design_incomplete_due_to_mppt'} <= {r['code'] for r in p['reasons']}
    module = upload(c, PAN, 'test.pan')['revision_id']; before = tree(root)
    r = complete(c, module); assert r.status_code == 422 and r.json()['detail']['code'] == 'completion_field_not_allowed'
    assert tree(root) == before


def test_single_curve_conversion_and_existing_three_profile_parity():
    if reason := missing_commit('1493ca0'):
        pytest.skip(reason)
    actual = candidate(single_bytes())
    assert actual['definition_schema_ready']
    curves = actual['canonical_data']['efficiency_model']['curves']
    assert [c['dc_voltage_v'] for c in curves] == [200, 600, 1000]
    assert curves[0]['points'] == curves[1]['points'] == curves[2]['points']
    assert [f['rule_id'] for f in actual['validation_findings']].count('INVERTER_SINGLE_EFFICIENCY_CURVE') == 1
    d = actual['derivations'][0]; assert d['method'] == 'single_profile_voltage_independent' and d['midpoint_reason']
    source_curve = candidate(OND)['canonical_data']['efficiency_model']['curves'][1]
    for voltage in (200, 350, 600, 830, 1000):
        for power in (500, 3000, 20000, 100000, 150000):
            output, _ = evaluate_voltage_dependent_conversion(actual['canonical_data']['efficiency_model'], dc_power_w=power,
                tracker_voltages_v=np.array([voltage]), tracker_powers_w=np.array([power]))
            assert output == pytest.approx(_curve_ac_output_w(source_curve, power), abs=1e-8)
    ns = {'__file__': str(ROOT/'components/ond/semantics.py'), '__name__': 's12a2_parent_semantics'}
    exec(subprocess.check_output(['git', 'show', '1493ca0:components/ond/semantics.py'], text=True), ns)
    source = map_ond(parse_ond_bytes(OND)).values_by_canonical_path
    nested = {}
    for path, value in source.items():
        node = nested
        for key in path.split('.')[:-1]: node = node.setdefault(key, {})
        node[path.split('.')[-1]] = value
    assert assemble_inverter_semantics(nested) == ns['assemble_inverter_semantics'](nested)


@pytest.mark.parametrize('nominal,expected', [(650, 650), (None, 600), (200, 600), (1000, 600), (float('nan'), 600)])
def test_single_anchor_policy_and_invalid_window(nominal, expected):
    raw = {'ond_efficiency_source': {'profile_mode': 'POutf_PIn', 'profiles': {'single': {'point_count': 2,
        'point_1': {'dc_power_w': 0, 'ac_power_w': 0}, 'point_2': {'dc_power_w': 100, 'ac_power_w': 90}}}},
        'mppt_template': {'min_operating_voltage_v': 200, 'max_operating_voltage_v': 1000, 'nominal_voltage_v': nominal}}
    data, derivation, warnings = assemble_inverter_semantics(raw)
    assert derivation[0]['anchors_v'] == [200, expected, 1000] and warnings == [SINGLE_PROFILE_WARNING]
    for low, high in [(None, 1000), (200, None), (1000, 200), (-1, 1000), (200, float('inf'))]:
        altered = deepcopy(raw); altered['mppt_template'].update(min_operating_voltage_v=low, max_operating_voltage_v=high)
        assert 'efficiency_model' not in assemble_inverter_semantics(altered)[0]


@pytest.mark.parametrize('pair', ['2831.2,3000.0', '-1,0', 'nan,0', 'inf,1'])
def test_single_curve_guard_refuses_broken_power_pair(pair):
    raw = single_bytes().replace(b'Point_2=3000.0,2831.2', b'Point_2='+pair.encode())
    assert raw != single_bytes()
    c = candidate(raw)
    assert not c['canonical_data']['efficiency_model'].get('curves')
    assert any('finite PIn >= POut >= 0' in f['message'] for f in c['validation_findings'])
