"""Wholly synthetic ENG4 imports, runtime tables and immutable remaps."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from fastapi.testclient import TestClient
import numpy as np
import pytest

from apps.api.server import create_app
from apps.api.component_library import IMPORTER_VERSION
from components.candidates import build_module_candidate
from components.pan import map_pan, parse_pan_bytes
from components.pan.semantics import assemble_module_semantics
from engine.optical import TabulatedIAMProfile, evaluate_tabulated_iam

ROOT = Path(__file__).resolve().parents[2]


def synthetic(first=10, modifier=1.):
    base = (ROOT / 'tests/fixtures/panond/synthetic_module.pan').read_bytes()
    profile = f'''  PVObject_IAM=pvIAM
    IAMMode=UserProfile
    IAMProfile=TCubicProfile
      NPtsMax=5
      NPtsEff=5
      Mode=3
      Point_1={first},{modifier}
      Point_2=30,0.999
      Point_3=60,0.9
      Point_4=80,0.6
      Point_5=90,0
    End of TCubicProfile
  End of PVObject pvIAM
'''.encode()
    return base.replace(b'End of PVObject pvModule', profile + b'End of PVObject pvModule')


def candidate(raw):
    return build_module_candidate(map_pan(parse_pan_bytes(raw)), candidate_id='eng4-synthetic',
        module_definition_id='eng4-module', revision_id='eng4-module-r1', source_id='eng4-source')


@pytest.mark.parametrize('first', [10, 20])
def test_positive_angle_unit_reference_imports_and_executes_cubic(first):
    result = candidate(synthetic(first))
    assert result['definition_schema_ready']
    iam = result['canonical_data']['optical']['iam']
    assert iam['interpolation_method'] == 'cubic'
    assert iam['points'][0] == {'angle_deg': 0., 'modifier': 1.}
    assert iam['points'][1] == {'angle_deg': float(first), 'modifier': 1.}
    derivation = next(x for x in result['derivations'] if x['target_path'] == 'optical.iam')
    assert derivation['inputs']['implied_normal_incidence_reference'] is True
    assert derivation['inputs']['original_first_point'] == {'angle_deg': float(first), 'modifier': 1.}
    assert derivation['inputs']['point_1'] == {'angle_deg': float(first), 'modifier': 1.}
    assert derivation['value'] == iam
    profile = TabulatedIAMProfile.from_points([(x['angle_deg'], x['modifier']) for x in iam['points']], interpolation_method='cubic', normalize=True)
    values = evaluate_tabulated_iam(np.array([0., first, 45., 90.]), profile)
    assert np.isfinite(values).all()
    assert values[:2] == pytest.approx([1., 1.], abs=1e-12)
    assert values[-1] == pytest.approx(0., abs=1e-12)


@pytest.mark.parametrize('modifier', [.99, 1.01, np.nextafter(1., 0.), np.nextafter(1., 2.)])
def test_ambiguous_nonunit_first_modifier_refuses_profile(modifier):
    result = candidate(synthetic(10, modifier))
    assert not result['canonical_data'].get('optical', {}).get('iam')
    assert any('explicit 0-degree reference' in x['message'] for x in result['validation_findings'])


def test_zero_start_semantics_and_provenance_are_byte_identical_to_parent():
    mapped = map_pan(parse_pan_bytes(synthetic(0))).values_by_canonical_path
    before = deepcopy(mapped)
    data = {'pan_iam_source': {k.removeprefix('pan_iam_source.'): deepcopy(v) for k, v in mapped.items() if k.startswith('pan_iam_source.')}}
    assembled = assemble_module_semantics(data, source_id='eng4-source')
    encoded = json.dumps(assembled, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    # Captured before production edits on 3b23eb4, from this synthetic input.
    assert sha256(encoded).hexdigest() == '5e6d5a9652a9c35da03e4ed1d6e893195df671f9454450391e794c0475b5a6ee'
    assert mapped == before
    derivation = next(x for x in assembled[1] if x['target_path'] == 'optical.iam')
    assert 'implied_normal_incidence_reference' not in derivation['inputs']


def test_importer_six_remaps_five_without_mutating_the_old_definition(tmp_path):
    library = tmp_path / 'library'
    app = create_app(store_root=tmp_path / 'projects', library_root=library)
    def upload(client):
        response = client.post('/api/component-library/imports', params={'filename': 'invented.pan'},
            content=synthetic(10), headers={'Content-Type': 'application/octet-stream'})
        assert response.status_code == 200, response.text
        return response.json()
    with TestClient(app) as client:
        first = upload(client)['entry']
        rid = first['revision_id']
        path = library / 'modules' / f'{rid}.json'
        stored = json.loads(path.read_text())
        stored['library']['importer_version'] = 6
        path.write_text(json.dumps(stored, ensure_ascii=False, indent=2) + '\n')
        old_definition = deepcopy(stored['definition'])
        remap = upload(client)
        assert IMPORTER_VERSION == 8
        assert remap['created'] and remap['entry']['remapped_from'] == rid
        current = json.loads((library / 'modules' / f"{remap['entry']['revision_id']}.json").read_text())
        assert current['library']['importer_version'] == 8
        assert json.loads(path.read_text())['definition'] == old_definition
        assert current['definition']['optical']['iam']['points'][0] == {'angle_deg': 0., 'modifier': 1.}
        assert not upload(client)['created']
