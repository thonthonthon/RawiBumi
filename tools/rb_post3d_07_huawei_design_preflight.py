"""Offline Huawei/Jinko engineering reference intake; never executes energy simulation."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from components.candidates import build_inverter_candidate, build_module_candidate
from components.ond import parse_ond_text
from components.ond.mapper import map_ond
from components.pan import parse_pan_text
from components.pan.mapper import map_pan
from components.source_overlay import ComponentSourceFragment, build_candidate_from_fragments
from components.validation import inverter_capabilities, validate_inverter
from electrical.topology import ElectricalTopologyEditorSession, new_electrical_design
from geometry.pvfield import PVFieldPackingSession
from geometry.scene import SceneEditorSession
from validation.engineering.electrical import validate_engineering_design, _module_state

PREFIX = 'rb-post3d-07'
STAMP = '2026-10-11T00:00:00Z'
MODULE_REV = PREFIX + '-jinko-r1'
INVERTER_REV = PREFIX + '-huawei-r1'
PROJECT_REV = PREFIX + '-project-r1'
OUTPUT = ROOT / '.ai/validation/rb_post3d_07'
MANUFACTURER = 'tests/fixtures/panond/manufacturer/'
OND = MANUFACTURER + 'Huawei_Sun2000_100KTL_M1.OND'
PAN = MANUFACTURER + 'JKM550M-72HL4-V_SGS_6079M3.PAN'
PDF = '.ai/evidence/rb_post3d_07/Huawei_100KTL_M1_Datasheet.pdf'
URL = 'https://solar.huawei.com/-/media/Solar/attachment/pdf/apac/datasheet/SUN2000-100KTL-M1.pdf'
HASHES = {
    OND: 'f4e753a7d4b8057136cb528a0cbcdda0126a059e6d745ece889dce8f889f16de',
    PAN: 'aff43dc4f6b5213abd87a14e0814fda47b8bb51bf7cb439bfa5fa590190229f3',
    PDF: '8a6f1de9b134464c0748881ca33a0ba1b0c61f427a0887eadefd2a9f97fee4dc',
}
ORIGINALS = {
    OND: ('391f307112b4e5543ea9135b005e5408856d8e93c677cd60ed485615ab95b6f3', 3587),
    PAN: ('24bc13172fd13646f1a9a408d3fd462b1e7b6b8ee84923c83335e15e1f1b8764', 1440),
}
# Transcription from the pinned Huawei datasheet technical specifications.
OVERLAY = {
    'ac_limits': {'nominal_frequency_hz': 50.0},
    'dc_limits': {'startup_voltage_v': 200.0},
    'mppt_template': {'max_operating_current_a': 26.0,
                      'max_short_circuit_current_a': 40.0},
}


def configuration():
    """Canonical study configuration, copied to avoid importing API/simulation orchestration."""
    return dict(schema_name='EngineeringValidationConfiguration', schema_version='0.1',
                minimum_cell_temperature_c=-10.0, maximum_cell_temperature_c=70.0,
                design_irradiance_w_m2=1000.0, orientation_tolerance_deg=0.1,
                dc_ac_ratio_warning_min=None, dc_ac_ratio_warning_max=None,
                temperature_model_policy='detailed_then_linear_fallback',
                fallback_voltage_uncertainty_fraction=0.05,
                fallback_current_uncertainty_fraction=0.05)


def fingerprint(data):
    return hashlib.sha256(data).hexdigest()


def sources(root=ROOT):
    records = json.loads((root / (MANUFACTURER + 'provenance.json')).read_text())['fixtures']
    result = {}
    for path, expected in HASHES.items():
        data = (root / path).read_bytes()
        if fingerprint(data) != expected:
            raise ValueError(f'source identity mismatch: {path}')
        if path == PDF and not data.startswith(b'%PDF-'):
            raise ValueError('invalid PDF signature')
        item = {'repository_sha256': expected, 'byte_size': len(data)}
        if path in ORIGINALS:
            original = b'\xef\xbb\xbf' + data.replace(b'\n', b'\r\n')
            original_hash, size = ORIGINALS[path]
            record = next(r for r in records if r['path'] == Path(path).name)
            if (fingerprint(original), len(original)) != (original_hash, size):
                raise ValueError(f'original serialization mismatch: {path}')
            if (record['original_sha256'], record['original_byte_size']) != (original_hash, size):
                raise ValueError(f'provenance record mismatch: {path}')
            item.update(original_sha256=original_hash, original_byte_size=size,
                        serialization_difference='UTF-8 BOM + CRLF versus BOM-free LF; same source revision',
                        provenance_record=record)
        result[path] = item
    return result


def intake(root=ROOT, *, include_overlay=True):
    evidence = sources(root)
    if OVERLAY != {
        'ac_limits': {'nominal_frequency_hz': 50.0},
        'dc_limits': {'startup_voltage_v': 200.0},
        'mppt_template': {'max_operating_current_a': 26.0, 'max_short_circuit_current_a': 40.0},
    }:
        raise ValueError('unknown or unsupported datasheet overlay field/value')
    ond = map_ond(parse_ond_text((root / OND).read_text(encoding='utf-8')))
    pan = map_pan(parse_pan_text((root / PAN).read_text(encoding='utf-8')))
    module = build_module_candidate(pan, candidate_id=PREFIX+'-module-candidate',
        module_definition_id=PREFIX+'-jinko', revision_id=MODULE_REV, source_id=HASHES[PAN])
    base = build_inverter_candidate(ond, candidate_id=PREFIX+'-ond-candidate',
        inverter_definition_id=PREFIX+'-huawei', revision_id=INVERTER_REV, source_id=HASHES[OND])
    data = dict(base['canonical_data'])
    data.pop('capability_flags', None)  # recomputed by the overlay builder, never supplied
    fragments = [ComponentSourceFragment(HASHES[OND], data, 50, 'manufacturer_component_file')]
    if include_overlay:
        fragments.append(ComponentSourceFragment(HASHES[PDF], OVERLAY, 100,
            'manufacturer_datasheet', URL, 'Pinned PDF technical specifications; transcribed offline'))
    inverter = build_candidate_from_fragments('inverter', fragments,
        candidate_id=PREFIX+'-inverter-candidate', definition_id=PREFIX+'-huawei', revision_id=INVERTER_REV)
    inv = inverter['canonical_data']
    if inv['capability_flags'] != inverter_capabilities(inv, validate_inverter(inv)):
        raise ValueError('capabilities are not derived from component data')
    stc = module['canonical_data']['stc']
    for key, expected in dict(nominal_power_w=550, pmp_w=550.105, vmp_v=40.9, voc_v=49.62, imp_a=13.45, isc_a=14.03).items():
        if abs(stc[key] - expected) > 1e-8:
            raise ValueError(f'unexpected module STC {key}')
    if abs(module['canonical_data']['temperature_coefficients']['beta_voc_per_c'] + 0.1379) > 1e-8:
        raise ValueError('unexpected Voc temperature coefficient')
    return evidence, module, inverter, {'ond': ond.as_import_record_payload(), 'pan': pan.as_import_record_payload()}


def build_design(module, inverter):
    base = dict(schema_name='Scene', schema_version='0.1', scene_id=PREFIX+'-scene',
        project_id=PREFIX, revision_id=PREFIX+'-scene-base', coordinate_system_id=PREFIX+'-enu',
        map_layer_configuration=None, created_at=STAMP, notes='NUMERICAL TEST ASSUMPTION: synthetic fixed-tilt layout',
        surfaces=[], obstacles=[], reference_lines=[], pv_fields=[], module_instances=[],
        revision_number=1, created_by=PREFIX, supersedes_revision_id=None, status='active', change_summary='Synthetic reference')
    editor = SceneEditorSession(base)
    editor.draw_rectangle(surface_id=PREFIX+'-surface', scene_object_id=PREFIX+'-object',
        name='NUMERICAL TEST ASSUMPTION', surface_type='flat_roof', origin_x_m=0.0,
        origin_y_m=0.0, width_m=60.0, height_m=40.0, base_elevation_m=0.0,
        usable_for_pv=True, geometry_source='user_override')
    packing = PVFieldPackingSession(editor.scene, {MODULE_REV: module})
    packing.create_field(pv_field_id=PREFIX+'-field', name='Synthetic field',
        support_surface_id=PREFIX+'-surface', module_definition_revision_id=MODULE_REV,
        orientation='portrait', azimuth_deg=0.0, tilt_deg=10.0,
        module_gap_x_m=0.02, module_gap_y_m=0.02, row_pitch_m=3.0,
        mounting_height_m=0.2, perimeter_setback_m=0.0, obstacle_setback_m=0.0,
        requested_row_count=10, requested_modules_per_row=19)
    packing.fill_area(PREFIX+'-field')
    scene = SceneEditorSession(packing.scene).commit_revision(revision_id=PREFIX+'-scene-r1',
        revision_number=1, change_summary='NUMERICAL TEST ASSUMPTION', created_by=PREFIX, created_at=STAMP)
    modules = sorted(scene['module_instances'], key=lambda m: (m['row_index'], m['column_index']))
    if len(modules) != 190:
        raise ValueError('synthetic packing must produce exactly 190 modules')
    electrical = new_electrical_design(project_id=PREFIX, electrical_revision_id=PREFIX+'-electrical-draft',
        pcc_id=PREFIX+'-pcc', project_revision_id=PROJECT_REV)
    topology = ElectricalTopologyEditorSession(scene, electrical, project_revision_id=PROJECT_REV,
        module_definitions={MODULE_REV: module}, inverter_definitions={INVERTER_REV: inverter})
    inv = topology.add_inverter(inverter_instance_id=PREFIX+'-inv', inverter_definition_revision_id=INVERTER_REV, name='Huawei reference')
    if len(inv['mppt_instance_ids']) != 10:
        raise ValueError('exactly ten MPPTs required')
    for i, mppt in enumerate(inv['mppt_instance_ids']):
        sid = f'{PREFIX}-string-{i+1:02d}'
        topology.create_string(string_id=sid, module_instance_ids=[m['module_instance_id'] for m in modules[i*19:(i+1)*19]], name=sid)
        topology.assign_strings_to_mppt([sid], mppt_instance_id=mppt)
    design = topology.commit_revision(electrical_revision_id=PREFIX+'-electrical-r1', revision_number=1,
        change_summary='19S x 10; one string per MPPT', created_by=PREFIX, created_at=STAMP)
    return scene, design


def preflight(root=ROOT):
    evidence, module, inverter, mappings = intake(root)
    inv = inverter['canonical_data']
    required = {'ac_limits.nominal_ac_power_w': 100000, 'ac_limits.max_ac_power_w': 110000,
        'ac_limits.nominal_ac_voltage_v': 380, 'ac_limits.nominal_frequency_hz': 50,
        'dc_limits.max_dc_voltage_v': 1100, 'mppt_template.count': 10,
        'mppt_template.total_input_count': 20, 'mppt_template.min_operating_voltage_v': 200,
        'mppt_template.max_operating_voltage_v': 1000}
    for path, expected in required.items():
        value = inv
        for key in path.split('.'):
            value = value.get(key, {})
        if value != expected:
            raise ValueError(f'mandatory source value unknown or unexpected: {path}')
    if inv.get('phase_configuration') != 'three_phase':
        raise ValueError('AC phase configuration incomplete')
    nameplate = module['canonical_data']['stc']['nominal_power_w']
    ac_power = inv['ac_limits']['nominal_ac_power_w']
    return {'status': 'PASS', 'sources': evidence, 'module_count': 190, 'series_count': 19,
            'strings': 10, 'mppts': 10, 'dc_nameplate_wp': 190*nameplate, 'dc_ac_ratio': 190*nameplate/ac_power}


def validate(root=ROOT):
    arithmetic = preflight(root)
    evidence, module, inverter, mappings = intake(root)
    mod, inv = module['canonical_data'], inverter['canonical_data']
    for candidate in (module, inverter):
        if any(f['severity'] in {'error', 'blocking_error'} for f in candidate['validation_findings']):
            raise ValueError('source component intake has mandatory validation errors')
    scene, electrical = build_design(mod, inv)
    cfg = configuration()
    report = validate_engineering_design(scene, electrical, project_revision_id=PROJECT_REV,
        component_revisions={MODULE_REV: mod, INVERTER_REV: inv}, configuration=cfg,
        design_validation_report_id=PREFIX+'-report-r1', generated_at=STAMP)
    # Private resolver intentionally shared with the real validator: its detailed
    # model and fallback policy must also govern the comparison/sensitivity evidence.
    # Regression coverage checks this envelope against the actual report currents.
    state = asdict(_module_state(mod, cfg))
    cold_voc = state['voc_min_temp_v'] * 19
    comparison_voc = state['voc_min_temp_v'] * 20
    return {'sources': evidence, 'mapping_records': mappings, 'module_candidate': module,
        'inverter_candidate': inverter, 'scene': scene, 'electrical_design': electrical,
        'report': report, 'module_temperature_envelope': state,
        'stc_string': dict(vmp_v=19*mod['stc']['vmp_v'], voc_v=19*mod['stc']['voc_v'], imp_a=mod['stc']['imp_a'], isc_a=mod['stc']['isc_a']),
        'arithmetic': arithmetic,
        'voc_tolerance_sensitivity': {'basis': 'NUMERICAL TEST ASSUMPTION; not PAN power tolerance; independent of configured model uncertainty',
            'samples': [{'fraction': t, 'cold_voc_v': cold_voc*(1+t), 'margin_v': 1100-cold_voc*(1+t)} for t in (0.01, 0.02, 0.03)]},
        '20S_comparison_only': {'dc_wp': 110000, 'dc_ac_ratio': 1.1, 'cold_voc_v': comparison_voc,
            'conservative_cold_voc_v': comparison_voc*(1+state['voltage_uncertainty_fraction']),
            'conservative_margin_v': 1100-comparison_voc*(1+state['voltage_uncertainty_fraction'])},
        'readiness': {'SOURCE_BACKED_COMPONENT': True,
            'ENGINEERING_DESIGN_VALIDATED': not report['blocking_simulation'],
            'LEVEL_2_EXECUTION_READY': False, 'PHYSICAL_YIELD_VALIDATED': False},
        'limitations': ['Input-specific and total-inverter current/Isc limits unknown',
            'Synthetic geometry and -10/+70 C envelope are numerical assumptions, not site evidence',
            'No substring/bypass evidence, thermal basis resolution, energy simulation or yield calibration']}


def serialized(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument('--preflight', action='store_true', help='Read-only offline source and arithmetic checks')
    modes.add_argument('--validate', action='store_true', help='Write real engineering report to isolated ignored directory')
    args = parser.parse_args(argv)
    try:
        if args.preflight:
            print(serialized(preflight()), end='')
            return 0
        result = validate()
        if OUTPUT.resolve() != ROOT.resolve() / '.ai/validation/rb_post3d_07' or (OUTPUT / 'validation.json').is_symlink():
            raise ValueError('output path must not redirect outside isolated evidence directory')
        OUTPUT.mkdir(parents=True, exist_ok=True)
        (OUTPUT / 'validation.json').write_text(serialized(result), encoding='utf-8')
        print(serialized(result['report']), end='')
        return int(result['report']['blocking_simulation'])
    except (ValueError, KeyError, OSError) as exc:
        print(f'BLOCKED: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
