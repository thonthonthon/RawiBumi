"""USE4B: source-aware allocation, unchanged legacy bytes, and shared inverter sizing."""
from __future__ import annotations
from copy import deepcopy
import json
from math import ceil, floor, inf
from typing import Any, Sequence

import pytest

from apps.api.stringing_suggestion import suggest_mppt_layout, stringing_limits, _layouts, _unavailable, MAX_VERIFIED_CANDIDATES
from apps.api.live_checks import validate_design
from apps.api.study import _validation_configuration
from components.design_integration import inverter_design_snapshot, inverter_inputs_per_mppt
from validation.engineering.electrical import module_design_state
from tests.unit.test_rb_fix_s2_honest_preflight import Project, INVERTER, MODULE
from tests.unit.test_rb_s14b_electrical import _two_fields, _inverter, _mppts, _command, _ok


def test_absent_and_all_null_sources_match_frozen_allocator_bytes(tmp_path):
    p = Project(tmp_path, 40, weather=False, strings=False)
    bundle = p.bundle()
    session = p.service._electrical_session(bundle)
    modules = [m['module_instance_id'] for m in bundle['scene']['module_instances']]
    session.create_string(string_id='kept', module_instance_ids=modules[:10])
    session.assign_strings_to_mppt(['kept'], mppt_instance_id=_mppts(p)[0])
    session.create_string(string_id='free', module_instance_ids=modules[10:20])
    bundle['electrical_design'] = session.electrical_design
    old = p.service._electrical_session(bundle)
    expected = legacy_apply_mppt_layout(old, _inverter(p), [[10], [10, 10]])
    assert expected['kept_string_ids'] == ['kept'] and expected['reused_string_ids'] == ['free'] and expected['created_string_ids']
    for kwargs in ({}, {'sources': [None, None]}):
        current = p.service._electrical_session(bundle)
        actual = current.apply_mppt_layout(_inverter(p), [[10], [10, 10]], **kwargs)
        assert json.dumps(actual) == json.dumps(expected)
        assert current.canonical_json() == old.canonical_json()


def test_restricted_fresh_allocation_precedes_any_source_without_reordering_output(tmp_path):
    p, a, b = _two_fields(tmp_path, 25., count=10)
    bundle = p.bundle()
    # Row-major ordering is by field ID; make roof B precede roof A explicitly.
    renamed = {bundle['scene']['pv_fields'][0]['pv_field_id']: 'z-A', bundle['scene']['pv_fields'][1]['pv_field_id']: 'a-B'}
    for field in bundle['scene']['pv_fields']:
        field['pv_field_id'] = renamed[field['pv_field_id']]
    for module in bundle['scene']['module_instances']:
        module['pv_field_id'] = renamed[module['pv_field_id']]
    session = p.service._electrical_session(bundle)
    for string in list(session.electrical_design['strings']):
        session.delete_string(string['string_id'])
    bundle['electrical_design'] = session.electrical_design
    assert session._ordered_modules(a + b, ordering='row_major') == b + a
    result = session.apply_mppt_layout(_inverter(p), [[10], [10]], sources=[None, ['a-B']])
    strings = session.electrical_design['strings']
    assert result['created_string_ids'] == ['S001', 'S002']
    assert [(s['string_id'], s['target_mppt_instance_id'], s['module_instance_ids']) for s in strings] == [
        ('S001', _mppts(p)[0], a), ('S002', _mppts(p)[1], b)]
    ids = [mid for s in strings for mid in s['module_instance_ids']]
    assert len(ids) == len(set(ids)) == 20
    repeat = p.service._electrical_session(bundle)
    assert repeat.apply_mppt_layout(_inverter(p), [[10], [10]], sources=[None, ['a-B']]) == result
    assert repeat.canonical_json() == session.canonical_json()


def test_sources_filter_kept_reused_and_fresh_modules_atomically(tmp_path):
    p, a, b = _two_fields(tmp_path, 25., count=10)
    bundle = p.bundle()
    fields = [f['pv_field_id'] for f in bundle['scene']['pv_fields']]
    session = p.service._electrical_session(bundle)
    # The old first string lies outside MPPT 1's new source; it must be released and reused on MPPT 2.
    result = session.apply_mppt_layout(_inverter(p), [[10], [10]], sources=[[fields[1]], [fields[0]]])
    assert result['kept_string_ids'] == ['S002'] and result['reused_string_ids'] == ['S001']
    assigned = {s['target_mppt_instance_id']: s['module_instance_ids'] for s in session.electrical_design['strings']}
    assert assigned[_mppts(p)[0]] == b and assigned[_mppts(p)[1]] == a
    session.set_inverter_pairing(_inverter(p), [fields[1]])
    with pytest.raises(ValueError, match='MPPT 2 source'):
        session.apply_mppt_layout(_inverter(p), [[10], [10]], sources=[[fields[1]], None])
    session.set_inverter_pairing(_inverter(p), [])
    for sid in ['S001', 'S002']:
        session.delete_string(sid)
    session.apply_mppt_layout(_inverter(p), [[5], [5]], sources=[[fields[1]], [fields[0]]])
    strings = [s for s in session.electrical_design['strings'] if s.get('target_mppt_instance_id')]
    assert all(set(s['module_instance_ids']) <= set(b if s['target_mppt_instance_id'] == _mppts(p)[0] else a) for s in strings)
    ids = [mid for s in strings for mid in s['module_instance_ids']]
    assert len(ids) == len(set(ids)) == 10
    before = session.canonical_json()
    with pytest.raises(ValueError, match='MPPT 2 source'):
        session.apply_mppt_layout(_inverter(p), [[5, 5], [10]], sources=[[fields[0]], [fields[0]]])
    assert session.canonical_json() == before


@pytest.mark.parametrize('kind', ['length', 'empty', 'unknown', 'outside', 'shape'])
def test_bad_sources_are_refused_without_mutation(tmp_path, kind):
    p, _, _ = _two_fields(tmp_path, 25.)
    bundle = p.bundle()
    fields = [f['pv_field_id'] for f in bundle['scene']['pv_fields']]
    session = p.service._electrical_session(bundle)
    if kind == 'outside':
        session.set_inverter_pairing(_inverter(p), [fields[0]])
    source = {'length': [None], 'empty': [[], None], 'unknown': [['missing'], None], 'outside': [[fields[1]], None], 'shape': [[123], None]}[kind]
    before = session.canonical_json()
    with pytest.raises(ValueError):
        session.apply_mppt_layout(_inverter(p), [[10], [10]], sources=source)
    assert session.canonical_json() == before


def test_sizing_uses_shared_limits_and_read_only_area_distances(tmp_path):
    p, _, _ = _two_fields(tmp_path, 25., count=10)
    bundle = p.bundle()
    fields = [f['pv_field_id'] for f in bundle['scene']['pv_fields']]
    _ok(p, _command('set_inverter_pairing', {'inverter_instance_id': _inverter(p), 'pv_field_ids': fields}))
    before = p.path.read_bytes()
    result = p.client.get(p.url + f'/inverters/{_inverter(p)}/sizing')
    assert result.status_code == 200, result.text
    sizing = result.json()
    assert sizing['schema_name'] == 'InverterSizing' and sizing['module_count'] == 20
    assert sizing['area_kwp'] == 11. and sizing['ac_kw'] == 150.
    assert sizing['dc_ac_ratio'] == pytest.approx(11 / 150)
    assert ceil(sizing['area_kwp'] / (sizing['ac_kw'] * 1.25)) == 1
    bundle = p.bundle()
    limits = stringing_limits(bundle['pinned_components']['inverters'][INVERTER], bundle['pinned_components']['modules'][MODULE], bundle['electrical_design'], 20)
    assert (sizing['string_length_min'], sizing['string_length_max']) == (min(limits['lengths']), max(limits['lengths']))
    assert sizing['mppts'] == limits['mppts'] and sizing['mppt_count'] == 2
    assert sizing['distance_warnings'] == [] and p.path.read_bytes() == before
    assert p.client.patch(p.url, json={'distance_warning_m': 1}).status_code == 200
    warnings = p.client.get(p.url + f'/inverters/{_inverter(p)}/sizing').json()['distance_warnings']
    assert len(warnings) == 1 and warnings[0]['distance_m'] == pytest.approx(20. - 3.45)
    assert p.client.get(p.url + '/inverters/missing/sizing').status_code in (404, 422)
    assert p.client.get('/api/projects/missing/inverters/missing/sizing').status_code == 404
    bundle = p.bundle()
    bundle['pinned_components']['modules'][MODULE]['capability_flags']['detailed_sdm_ready'] = False
    bundle['pinned_components']['modules'][MODULE]['temperature_coefficients'] = {}
    p.service.store.save(bundle)
    unavailable = p.client.get(p.url + f'/inverters/{_inverter(p)}/sizing')
    assert unavailable.status_code == 200, unavailable.text
    assert unavailable.json()['string_length_min'] is None and unavailable.json()['reasons']


@pytest.mark.parametrize('length', [None, 9, 10])
def test_suggest_matches_frozen_pre_refactor_bytes(tmp_path, length):
    p = Project(tmp_path, 20, weather=False, strings=length is not None, string_length=length)
    bundle = p.bundle()
    expected = legacy_suggest_mppt_layout(p.service, bundle, _inverter(p))
    actual = suggest_mppt_layout(p.service, bundle, _inverter(p))
    assert json.dumps(actual) == json.dumps(expected)


def test_api_sources_dry_run_and_single_undo(tmp_path):
    p, _, _ = _two_fields(tmp_path, 25.)
    fields = [f['pv_field_id'] for f in p.bundle()['scene']['pv_fields']]
    cmd = _command('apply_mppt_layout', {'inverter_instance_id': _inverter(p), 'layout': [[10], [10]], 'sources': [[fields[1]], [fields[0]]]})
    before = p.path.read_bytes()
    dry = p.client.post(p.url + '/electrical/commands', json={'dry_run': True, 'commands': [cmd]})
    assert dry.status_code == 200, dry.text
    assert dry.json()['dry_run'] and p.path.read_bytes() == before
    old = p.bundle()['electrical_design']['strings']
    history_before = p.client.get(p.url).json()['history']['past']
    view = _ok(p, cmd)
    assert len(view['history']['past']) == len(history_before) + 1
    fence = {'expected_project_revision_id': view['bundle']['workspace_state']['active_project_revision_id'], 'expected_entry_id': view['history']['past'][-1]['entry_id']}
    undo = p.client.post(p.url + '/undo', json=fence)
    assert undo.status_code == 200, undo.text
    assert p.bundle()['electrical_design']['strings'] == old
    for sources in ([None], [[], None], [['missing'], None], [[fields[0]] * 501, None]):
        cmd['parameters']['sources'] = sources
        assert p.client.post(p.url + '/electrical/commands', json={'commands': [cmd]}).status_code == 422


# Frozen b02965f behavior: these copies make identity checks independent of the refactored code.
def legacy_apply_mppt_layout(self, inverter_instance_id: str, layout: Sequence[Sequence[int]],
                      pv_field_ids: Sequence[str] | None = None) -> dict[str, Any]:
    """Make the inverter's MPPTs carry strings of these lengths (one list per MPPT, one length per input, 0 =
    empty). Matching strings stay; the inverter's other strings are unassigned; the rest come from unassigned
    strings of the right length in the pool, then from unstrung pool modules in row-major order."""
    inverter = self._inverter(inverter_instance_id)
    mppts = sorted((m for m in self._design.get("mppt_instances", []) if m.get("inverter_instance_id") == inverter_instance_id),
                   key=lambda m: int(m["index"]))
    rows = [list(row) for row in layout]
    if len(rows) != len(mppts):
        raise ValueError(f"the layout has {len(rows)} MPPTs; inverter {inverter_instance_id} has {len(mppts)}")
    for i, row in enumerate(rows):
        if any(type(n) is not int or n < 0 for n in row):
            raise ValueError("string lengths must be whole numbers of 0 or more")
        used = sum(1 for n in row if n > 0)
        capacity = self._mppt_capacity(mppts[i])
        if capacity is not None and used > capacity:
            raise ValueError(f"MPPT {i + 1} would use {used} inputs; it has {capacity} verified DC inputs")
    pool = list(pv_field_ids or inverter.get("paired_pv_field_ids") or [])
    known = {str(f["pv_field_id"]) for f in self._scene.get("pv_fields", [])}
    if [f for f in pool if f not in known]:
        raise ValueError(f"unknown PV fields: {[f for f in pool if f not in known]}")
    in_pool = (lambda mid: True) if not pool else (lambda mid: str(self._scene_module(mid).get("pv_field_id")) in pool)

    strings = self._design.get("strings", [])
    mppt_ids = [str(m["mppt_instance_id"]) for m in mppts]
    mine = [s for s in strings if s.get("target_mppt_instance_id") in mppt_ids]
    kept: list[dict[str, Any]] = []
    wanted: list[tuple[str, int]] = []
    for mppt_id, row in zip(mppt_ids, rows):
        for n in (n for n in row if n > 0):
            match = next((s for s in mine if s not in kept and s["target_mppt_instance_id"] == mppt_id
                          and len(s["module_instance_ids"]) == n), None)
            if match is not None:
                kept.append(match)
            else:
                wanted.append((mppt_id, n))
    released = [s for s in mine if s not in kept]
    free = [s for s in strings if (s.get("target_mppt_instance_id") is None or s in released)
            and s.get("module_instance_ids") and all(in_pool(m) for m in s["module_instance_ids"])]
    strung = {str(m) for s in strings for m in s.get("module_instance_ids", [])}
    candidates = [str(m["module_instance_id"]) for m in self._scene.get("module_instances", [])
                  if m.get("enabled") is True and str(m["module_instance_id"]) not in strung and in_pool(str(m["module_instance_id"]))]
    unstrung = self._ordered_modules(candidates, ordering="row_major") if candidates else []
    plan: list[tuple[str, dict[str, Any] | None, list[str] | None]] = []
    for mppt_id, n in wanted:
        reuse = next((s for s in free if len(s["module_instance_ids"]) == n), None)
        if reuse is not None:
            free.remove(reuse)
            plan.append((mppt_id, reuse, None))
            continue
        if len(unstrung) < n:
            raise ValueError(f"not enough unstrung modules for a {n}-module string ({len(unstrung)} left in the pool)")
        plan.append((mppt_id, None, unstrung[:n]))
        unstrung = unstrung[n:]
    new_ids = iter(self._new_string_ids(sum(1 for _, _, ids in plan if ids is not None)))

    def operation() -> dict[str, Any]:
        for string in released:
            string["target_mppt_instance_id"], string["enabled"] = None, False
        reused, created = [], []
        targets: dict[str, list[str]] = {m: [str(s["string_id"]) for s in kept if s["target_mppt_instance_id"] == m] for m in mppt_ids}
        for mppt_id, string, ids in plan:
            if string is None:
                string = self._new_string(next(new_ids), ids, "apply_mppt_layout")
                self._design["strings"].append(string)
                created.append(string["string_id"])
            else:
                reused.append(string["string_id"])
            string["target_mppt_instance_id"], string["enabled"] = mppt_id, True
            targets[mppt_id].append(str(string["string_id"]))
        for mppt in mppts:
            mppt["connected_string_ids"] = sorted(targets[str(mppt["mppt_instance_id"])])
        return {"inverter_instance_id": inverter_instance_id, "kept_string_ids": sorted(s["string_id"] for s in kept),
                "unassigned_string_ids": sorted(s["string_id"] for s in released if s.get("target_mppt_instance_id") is None),
                "reused_string_ids": sorted(reused), "created_string_ids": created}

    return self._mutate(operation)


def legacy_suggest_mppt_layout(service: Any, bundle: dict[str, Any], inverter_instance_id: str,
                        pv_field_ids: list[str] | None = None) -> dict[str, Any]:
    design = bundle["electrical_design"]
    inverter = next((i for i in design["inverter_instances"] if i["inverter_instance_id"] == inverter_instance_id), None)
    if inverter is None:
        raise KeyError(f"inverter not found: {inverter_instance_id}")
    definition = bundle["pinned_components"]["inverters"][inverter["inverter_definition_revision_id"]]
    snapshot = inverter_design_snapshot(definition)
    specs = snapshot["mppts"]
    fields = list(pv_field_ids or inverter.get("paired_pv_field_ids") or [f["pv_field_id"] for f in bundle["scene"].get("pv_fields", [])])
    mine = {m["mppt_instance_id"] for m in design["mppt_instances"] if m["inverter_instance_id"] == inverter_instance_id}
    taken = {mid for s in design.get("strings", []) if s.get("target_mppt_instance_id") and s["target_mppt_instance_id"] not in mine
             for mid in s.get("module_instance_ids", [])}
    pool = [m for m in bundle["scene"].get("module_instances", []) if m["pv_field_id"] in fields and m["module_instance_id"] not in taken]
    if not pool:
        return _unavailable("NO_MODULES", "No free modules in the inverter's PV fields.")
    revisions = {m["module_definition_revision_id"] for m in pool}
    if len(revisions) != 1:
        return _unavailable("MIXED_MODULES", "The fields hold more than one module type; pair the inverter with one type.")
    module = bundle["pinned_components"]["modules"][next(iter(revisions))]
    try:
        state = module_design_state(module, _validation_configuration(design))
    except ValueError as exc:
        return _unavailable("MODULE_MODEL_UNAVAILABLE", f"The module has no temperature model for sizing: {exc}")
    uv, ui = state.voltage_uncertainty_fraction, state.current_uncertainty_fraction
    voc_cold, vmp_cold = state.voc_min_temp_v * (1 + uv), state.vmp_min_temp_v * (1 + uv)
    vmp_hot, isc = state.vmp_max_temp_v * (1 - uv), state.isc_max_temp_a * (1 + ui)
    absolute = min(float(snapshot["dc_limits"].get("max_dc_voltage_v") or inf), float(state.max_system_voltage_v or inf))
    low = max(float(s.get("min_operating_voltage_v") or 0) for s in specs)
    high = min(float(s.get("max_operating_voltage_v") or inf) for s in specs)
    lengths = [n for n in range(1, len(pool) + 1) if n * voc_cold <= absolute and n * vmp_hot >= low and n * vmp_cold <= high]
    if not lengths:
        return _unavailable("NO_STRING_LENGTH", "No string length keeps cold Voc under the voltage limit and Vmp inside "
                            "the MPPT window at the design temperatures.")
    inputs, inputs_source = inverter_inputs_per_mppt(definition, int(specs[0]["index"]))
    caps = []
    for spec in specs:
        mppt_inputs, _ = inverter_inputs_per_mppt(definition, int(spec["index"]))
        cap = float(mppt_inputs) if mppt_inputs else inf
        if spec.get("max_short_circuit_current_a"):
            cap = min(cap, floor(float(spec["max_short_circuit_current_a"]) / isc))
        caps.append(cap)
    candidates = _layouts(lengths, caps, len(pool), limit=MAX_VERIFIED_CANDIDATES)
    if not candidates:
        return _unavailable("ISC_LIMIT", "One string's short-circuit current already exceeds the MPPT limit.")
    # Most modules strung first. Within one module count, layouts that keep the existing strings (Apply reuses those of
    # the right length) come before a restring, which replaces the inverter's own and the free strings in its fields in
    # the same commit as the layout.
    replaceable = sorted(s["string_id"] for s in design.get("strings", [])
                         if (s.get("target_mppt_instance_id") in mine or not s.get("target_mppt_instance_id"))
                         and s.get("module_instance_ids") and all(m in {x["module_instance_id"] for x in pool} for m in s["module_instance_ids"]))
    rejected = []
    shortlist = candidates[:MAX_VERIFIED_CANDIDATES]
    attempts = [(c, replace) for used in sorted({c[0][0] for c in shortlist})
                for replace in (([], replaceable) if replaceable else ([],)) for c in shortlist if c[0][0] == used]
    for (_, layout), replace in attempts:
        strings = [n for mppt in layout for n in mppt if n]
        notation = " ; ".join(",".join(str(n) for n in mppt) for mppt in layout)
        trial = deepcopy(bundle)
        session = service._electrical_session(trial)
        try:
            for string_id in replace:
                session.delete_string(string_id)
            session.apply_mppt_layout(inverter_instance_id, layout, pv_field_ids=fields)
        except ValueError as exc:
            rejected.append({"layout": notation, "rule_ids": [], "reason": str(exc)})
            continue
        trial["electrical_design"] = session.electrical_design
        report = validate_design(trial)
        relevant = {inverter_instance_id, *mine,
                    *(s["string_id"] for s in trial["electrical_design"]["strings"] if s.get("target_mppt_instance_id") in mine)}
        findings = [f for f in report["findings"] if str(f.get("entity_id")) in relevant]
        invalid = [f for f in findings if f["classification"] == "INVALID"]
        if invalid:
            rejected.append({"layout": notation, "rule_ids": sorted({f["rule_id"] for f in invalid})})
            continue
        return {"schema_name": "MpptLayoutSuggestion", "schema_version": "0.1", "status": "suggestion_available",
                "inverter_instance_id": inverter_instance_id, "pv_field_ids": fields, "layout": layout,
                "replace_string_ids": list(replace),
                "string_length": max(strings), "string_lengths": sorted(set(strings), reverse=True),
                "string_count": len(strings), "modules_used": sum(strings), "modules_left": len(pool) - sum(strings),
                "inputs_per_mppt": inputs, "inputs_per_mppt_source": inputs_source,
                "warnings": [{"rule_id": f["rule_id"], "entity_id": f.get("entity_id"), "message": f["message"]}
                             for f in findings if f["classification"] == "WARNING"],
                "basis": "Sized from the design validation's module envelopes; verified by the same validation.",
                "rejected": rejected, "reasons": []}
    return _unavailable("NO_VALID_LAYOUT", "Every sized layout still fails the design validation.", rejected=rejected)
