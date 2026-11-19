"""Orchestrator-owned regressions for the offline manufacturer reference."""
from tests.unit._availability import missing_private_path
from copy import deepcopy
import json
import socket
import sys

import pytest

from tools import rb_post3d_07_huawei_design_preflight as tool
from components.validation import inverter_capabilities, validate_inverter
from validation.engineering.electrical import validate_engineering_design


def test_identity_intake_and_nameplate():
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    first = tool.intake()
    assert first == tool.intake()
    evidence, module, inverter, mappings = first
    assert evidence[tool.OND]['repository_sha256'] == tool.HASHES[tool.OND]
    assert evidence[tool.PAN]['original_byte_size'] == 1440
    mod = module['canonical_data']
    assert mod['stc']['nominal_power_w'] == 550
    assert mod['stc']['pmp_w'] == pytest.approx(550.105)
    assert mod['temperature_coefficients']['beta_voc_per_c'] == pytest.approx(-0.1379)
    inv = inverter['canonical_data']
    assert inv['array_sizing_limits']['max_pv_current_a'] == 40
    assert inv['array_sizing_limits']['nominal_pv_array_power_w'] == 130000
    assert inv['array_sizing_limits']['max_pv_array_power_w'] == 130000
    assert inv['dc_limits'].get('max_dc_current_a') is None
    assert inv['dc_limits'].get('max_dc_short_circuit_current_a') is None
    assert len(inv['efficiency_model']['curves']) == 3
    assert inv['capability_flags'] == inverter_capabilities(inv, validate_inverter(inv))
    assert inv['capability_flags']['mppt_design_ready'] is True
    assert inverter['field_provenance']['mppt_template.max_operating_current_a'][-1]['source_id'] == tool.HASHES[tool.PDF]
    assert mappings['ond']['unmapped_fields']
    assert not tool.intake(include_overlay=False)[2]['capability_flags']['mppt_design_ready']
    arithmetic = tool.preflight()
    assert arithmetic['dc_nameplate_wp'] == 104500
    assert arithmetic['dc_ac_ratio'] == 1.045


def test_real_validator_topology_envelope_and_determinism(monkeypatch):
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    calls = []
    def spy(*args, **kwargs):
        calls.append(kwargs)
        return validate_engineering_design(*args, **kwargs)
    monkeypatch.setattr(tool, 'validate_engineering_design', spy)
    first = tool.validate()
    assert tool.serialized(first) == tool.serialized(tool.validate())
    assert len(calls) == 2
    scene, design = first['scene'], first['electrical_design']
    assert len(scene['module_instances']) == 190
    assert len(design['strings']) == len(design['mppt_instances']) == 10
    ids = []
    for string, mppt in zip(design['strings'], design['mppt_instances']):
        assert len(string['module_instance_ids']) == 19
        ids.extend(string['module_instance_ids'])
        assert string['target_mppt_instance_id'] == mppt['mppt_instance_id']
        assert mppt['connected_string_ids'] == [string['string_id']]
    assert len(set(ids)) == 190
    assert first['stc_string']['vmp_v'] == pytest.approx(777.1)
    assert first['stc_string']['voc_v'] == pytest.approx(942.78)
    assert first['stc_string']['imp_a'] == 13.45
    assert first['stc_string']['isc_a'] == 14.03
    state = first['module_temperature_envelope']
    u = state['voltage_uncertainty_fraction']
    assert state['voc_min_temp_v']*19*(1+u) < 1100
    assert state['vmp_min_temp_v']*19*(1+u) < 1000
    assert state['vmp_max_temp_v']*19*(1-u) > 200
    assert max(state['imp_min_temp_a'], state['imp_max_temp_a'])*(1+state['current_uncertainty_fraction']) < 26
    assert max(state['isc_min_temp_a'], state['isc_max_temp_a'])*(1+state['current_uncertainty_fraction']) < 40
    assert state['max_system_voltage_v'] == 1500
    report = first['report']
    assert report['status'] == 'valid_with_findings'
    assert not report['blocking_simulation']
    rules = {f['rule_id'] for f in report['findings']}
    assert 'INVERTER_TOTAL_DC_CURRENT_LIMIT_UNAVAILABLE' in rules
    assert 'INVERTER_TOTAL_DC_ISC_LIMIT_UNAVAILABLE' in rules
    assert report['scene_revision_id'] == scene['revision_id']
    assert not first['readiness']['LEVEL_2_EXECUTION_READY']
    comparison = first['20S_comparison_only']
    assert comparison['cold_voc_v'] == pytest.approx(state['voc_min_temp_v'] * 20)
    assert comparison['conservative_margin_v'] == pytest.approx(13.66869772431528)
    assert 0 < comparison['conservative_margin_v'] < 1100 - state['voc_min_temp_v'] * 19
    current_findings = [f for f in report['findings'] if f['rule_id'] == 'STRING_DESIGN_CURRENT_COMPUTED']
    assert len(current_findings) == 10
    assert current_findings[0]['measured_value'] == max(state['imp_min_temp_a'], state['imp_max_temp_a'])
    assert state['model_basis'] == 'validated_pvsyst_singlediode'
    assert not state['downgraded']
    assert u == state['current_uncertainty_fraction'] == 0


def test_configuration_matches_canonical_study():
    from apps.api.study import _validation_configuration
    assert tool.configuration() == _validation_configuration()


@pytest.mark.parametrize('source', [tool.OND, tool.PAN, tool.PDF, tool.MANUFACTURER+'provenance.json'])
@pytest.mark.parametrize('tamper', [False, True])
def test_missing_or_changed_sources_fail_closed(tmp_path, source, tamper):
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    paths = [*tool.HASHES, tool.MANUFACTURER+'provenance.json']
    for path in paths:
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((tool.ROOT / path).read_bytes())
    if tamper:
        if source.endswith('provenance.json'):
            records = json.loads((tmp_path / source).read_text())
            for record in records['fixtures']:
                record['original_sha256'] = '0' * 64
            (tmp_path / source).write_text(json.dumps(records))
        else:
            (tmp_path / source).write_bytes(b'unknown source')
    else:
        (tmp_path / source).unlink()
    with pytest.raises((ValueError, OSError)):
        tool.preflight(tmp_path)


def test_unknown_overlay_and_flag_forgery_rejected(monkeypatch):
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    overlay = deepcopy(tool.OVERLAY)
    overlay['capability_flags'] = {'basic_design_ready': True}
    monkeypatch.setattr(tool, 'OVERLAY', overlay)
    with pytest.raises(ValueError, match='unknown or unsupported'):
        tool.intake()


def test_missing_overlay_really_blocks_design():
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    _, module, inverter, _ = tool.intake(include_overlay=False)
    mod, inv = module['canonical_data'], inverter['canonical_data']
    scene, design = tool.build_design(mod, inv)
    report = validate_engineering_design(scene, design, project_revision_id=tool.PROJECT_REV,
        component_revisions={tool.MODULE_REV: mod, tool.INVERTER_REV: inv},
        configuration=tool.configuration(), design_validation_report_id='missing-overlay', generated_at=tool.STAMP)
    assert report['blocking_simulation']
    assert 'INVERTER_MPPT_DESIGN_READY_FALSE' in {f['rule_id'] for f in report['findings']}


def test_cli_offline_readonly_and_isolated_output(monkeypatch, tmp_path):
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    def forbidden(*args, **kwargs):
        raise AssertionError('network or simulation acquisition attempted')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    # Weather is imported transitively; guard its actual acquisition entry point.
    from weather.providers.open_meteo import OpenMeteoHistoricalAdapter
    monkeypatch.setattr(OpenMeteoHistoricalAdapter, 'acquire', forbidden)
    monkeypatch.setitem(sys.modules, 'engine.simulation', None)
    monkeypatch.setattr(tool, 'ROOT', tmp_path)
    monkeypatch.setattr(tool, 'OUTPUT', tmp_path / '.ai/validation/rb_post3d_07')
    with pytest.raises(SystemExit) as help_exit:
        tool.main(['--help'])
    assert help_exit.value.code == 0
    assert tool.main(['--preflight']) == 0
    assert list(tmp_path.rglob('*')) == []
    assert tool.main(['--validate']) == 0
    target = tool.OUTPUT / 'validation.json'
    before = target.read_bytes()
    assert tool.main(['--validate']) == 0
    assert before == target.read_bytes()
    assert [p for p in tmp_path.rglob('*') if p.is_file()] == [target]
    monkeypatch.setattr(tool, 'preflight', lambda: (_ for _ in ()).throw(ValueError('invalid source')))
    assert tool.main(['--preflight']) == 1


def _current_limit_report(field, limit):
    if reason := missing_private_path(tool.PDF):
        pytest.skip(reason)
    _, module, inverter, _ = tool.intake()
    mod, inv = module['canonical_data'], deepcopy(inverter['canonical_data'])
    inv['mppt_template'][field] = limit
    inv['capability_flags'] = inverter_capabilities(inv, validate_inverter(inv))
    scene, design = tool.build_design(mod, inv)
    return validate_engineering_design(scene, design, project_revision_id=tool.PROJECT_REV,
        component_revisions={tool.MODULE_REV: mod, tool.INVERTER_REV: inv},
        configuration=tool.configuration(), design_validation_report_id='current-limit-test', generated_at=tool.STAMP)


@pytest.mark.parametrize('field,limit', [('max_short_circuit_current_a', 10)])
def test_physical_current_limit_violation_blocks(field, limit):
    report = _current_limit_report(field, limit)
    assert report['blocking_simulation']
    assert any(f['classification'] == 'INVALID' and f['category'] == 'electrical_current' for f in report['findings'])


def test_operating_current_above_the_mppt_limit_warns_without_blocking():
    # USE-D5: the inverter limits the operating current (a reported loss); only Isc is a hard limit.
    report = _current_limit_report('max_operating_current_a', 10)
    exceeded = [f for f in report['findings'] if f['rule_id'] == 'MPPT_OPERATING_CURRENT_EXCEEDED']
    assert exceeded and all(f['classification'] == 'WARNING' for f in exceeded)
    assert not any(f['classification'] == 'INVALID' and f['category'] == 'electrical_current' for f in report['findings'])
    assert not report['blocking_simulation']
