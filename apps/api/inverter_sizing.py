"""Read-only inverter area and the same temperature sizing limits used by Suggest."""
from components.design_integration import inverter_design_snapshot, inverter_inputs_per_mppt, module_nameplate_w
from .stringing_suggestion import stringing_limits
from .systems_overview import systems_overview


def inverter_sizing(bundle, inverter_instance_id):
    design = bundle['electrical_design']
    inverter = next((i for i in design['inverter_instances'] if i['inverter_instance_id'] == inverter_instance_id), None)
    if inverter is None:
        raise KeyError(f'inverter not found: {inverter_instance_id}')
    definition = bundle['pinned_components']['inverters'][inverter['inverter_definition_revision_id']]
    snapshot = inverter_design_snapshot(definition)
    fields = list(inverter.get('paired_pv_field_ids') or [f['pv_field_id'] for f in bundle['scene'].get('pv_fields', [])])
    modules = [m for m in bundle['scene'].get('module_instances', []) if m['pv_field_id'] in fields]
    definitions = bundle['pinned_components']['modules']
    area_kwp = sum(module_nameplate_w(definitions[m['module_definition_revision_id']]) for m in modules) / 1000.
    ac_kw = float(snapshot['ac_limits'].get('nominal_ac_power_w') or 0) / 1000.
    reasons = []
    revisions = {m['module_definition_revision_id'] for m in modules}
    if not modules:
        reasons = [{'code': 'NO_MODULES', 'message': 'No modules in the inverter area.'}]
    elif len(revisions) != 1:
        reasons = [{'code': 'MIXED_MODULES', 'message': 'The area holds more than one module type; choose fields with one type for sizing.'}]
    limits = {} if reasons else stringing_limits(definition, definitions[next(iter(revisions))], design, len(modules))
    reasons = reasons or limits.get('reasons', [])
    mppts = limits.get('mppts')
    if mppts is None:
        mppts = []
        for spec in snapshot['mppts']:
            inputs, source = inverter_inputs_per_mppt(definition, int(spec['index']))
            mppts.append({'index': int(spec['index']), 'inputs': inputs, 'inputs_source': source, 'max_strings_by_isc': None})
    lengths = limits.get('lengths', [])
    overview = systems_overview(bundle)
    # Distances are exactly the overview's union-polygon distances, filtered to the inverter area.
    included = {i for i, b in enumerate(overview['buildings']) if set(b['pv_field_ids']).intersection(fields)}
    warnings = [{**d, 'from_name': overview['buildings'][d['from_index']]['name'],
                 'to_name': overview['buildings'][d['to_index']]['name']}
                for d in overview['distances'] if d['over_threshold'] and d['from_index'] in included and d['to_index'] in included]
    return {'schema_name': 'InverterSizing', 'schema_version': '0.1', 'pv_field_ids': fields,
            'module_count': len(modules), 'area_kwp': area_kwp, 'ac_kw': ac_kw,
            'dc_ac_ratio': area_kwp / ac_kw if ac_kw > 0 else None,
            'string_length_min': min(lengths) if lengths else None, 'string_length_max': max(lengths) if lengths else None,
            'reasons': reasons, 'mppt_count': snapshot['mppt_count'], 'mppts': mppts, 'distance_warnings': warnings}
