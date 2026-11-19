"""INV1 hand-calculated voltage-policy oracles and resolved-selector integration."""
import numpy as np
import pandas as pd
import pytest
from electrical.mppt import MPPTAggregationResult
from engine.inverter import (
    INVERTER_VOLTAGE_DEPENDENT as OLD,
    INVERTER_VOLTAGE_DEPENDENT_BOUNDED as NEW,
    ADJACENT_ENVELOPE_POLICY as POLICY,
    evaluate_voltage_dependent_conversion as evaluate,
    simulate_voltage_dependent_inverter,
)


def curves(anchors=(400., 600., 800.), outputs=(90., 98., 96.)):
    return [{"dc_voltage_v": v, "points": [
        {"dc_power_w": 0., "ac_power_w": 0.},
        {"dc_power_w": 100., "ac_power_w": y},
    ]} for v, y in zip(anchors, outputs)]


def conversion(voltage, *, model=NEW, table=None, power=100., weights=None):
    voltages=np.atleast_1d(voltage).astype(float)
    powers=np.full(len(voltages),power/len(voltages)) if weights is None else np.asarray(weights,dtype=float)
    return evaluate({"curves": curves() if table is None else table},dc_power_w=power,
        tracker_voltages_v=voltages,tracker_powers_w=powers,model_id=model)


@pytest.mark.parametrize("voltage,expected", [(400,90.),(500,95.25),(600,98.),(650,98.),(700,98.),(750,97.4375),(800,96.)])
def test_hand_lagrange_and_adjacent_envelope(voltage,expected):
    # In normalized coordinates Q(u)=90+13u-5u², u=(V-400)/200.
    ac,eta=conversion(voltage)
    assert ac==pytest.approx(expected,abs=2e-13)
    assert eta==ac/100


def test_legacy_overshoot_and_default_are_preserved_exactly():
    ac,eta=conversion(650,model=OLD)
    assert ac==98.4375 and eta==.984375
    kwargs={"dc_power_w":100.,"tracker_voltages_v":np.array([650.]),"tracker_powers_w":np.array([100.])}
    assert evaluate({"curves":curves()},**kwargs)==evaluate({"curves":curves()},**kwargs,model_id=OLD)
    assert conversion(650)[0]==98.


@pytest.mark.parametrize("voltage", [-1000.,400.,500.,600.,800.,2000.])
@pytest.mark.parametrize("power", [0.,1.,100.,500.])
def test_two_anchor_branch_is_bit_identical(voltage,power):
    table=curves((400.,800.),(90.,96.))
    assert conversion(voltage,table=table,power=power)==conversion(voltage,table=table,power=power,model=OLD)


@pytest.mark.parametrize("voltage,endpoint", [(0.,400.),(2000.,800.)])
def test_outside_voltage_domain_clamps_to_endpoint(voltage,endpoint):
    assert conversion(voltage)==conversion(endpoint)


def test_continuity_on_both_sides_of_all_anchors():
    for v in [400.,600.,800.]:
        center=conversion(v)[0]
        assert abs(conversion(v-1e-7)[0]-center)<1e-7
        assert abs(conversion(v+1e-7)[0]-center)<1e-7


def test_mixed_voltages_unequal_loading_keeps_whole_inverter_power_basis():
    # Whole-inverter outputs at 500 and 750 V: 95.25 and 97.4375 W.
    ac,eta=conversion([500.,750.],weights=[25.,75.])
    expected=.25*95.25+.75*97.4375
    assert ac==pytest.approx(expected,abs=2e-13)
    assert eta==ac/100.


def test_final_composite_guard_handles_one_ulp_excess():
    table=curves(outputs=(98.,98.,98.))
    # Independent binary-rounding witness: equal tracker shares can sum above unity.
    power=7.7;anchor=power*.98;eta=0.
    for pi in [power/3]*3:eta+=(pi/power)*(anchor/power)
    assert power*eta>anchor
    for n in range(2,18):
        for power in [7.7,10.,99.,100.,1234.56789]:
            ac,eta=conversion(np.linspace(401,799,n),power=power,table=table)
            # Each anchor holds exactly the existing endpoint efficiency.
            from engine.inverter.model import _curve_ac_output_w
            exact_anchor=_curve_ac_output_w(table[0],power)
            assert ac<=exact_anchor
            assert ac>=exact_anchor
            assert eta==ac/power


def test_seeded_nonmonotone_profiles_stay_inside_adjacent_anchors():
    from engine.inverter.model import _curve_ac_output_w
    rng=np.random.default_rng(170)
    for _ in range(100):
        outputs=rng.uniform(70.,99.,3);v=float(rng.uniform(400,800));table=curves(outputs=outputs)
        j=0 if v<600 else 1;ac,_=conversion(v,table=table)
        anchor_outputs=[_curve_ac_output_w(c,100.) for c in table]
        assert min(anchor_outputs[j:j+2])<=ac<=max(anchor_outputs[j:j+2])
        # Unsorted input retains the same sorted-anchor polynomial.
        assert conversion(v,table=list(reversed(table)))==(ac,ac/100.)


def test_four_anchor_stencil_discontinuity_is_inherited_not_replaced():
    table=curves((400.,600.,800.,1000.),(90.,98.,91.6,96.4))
    left=conversion(700.-1e-7,table=table)[0];right=conversion(700.+1e-7,table=table)[0]
    assert left==pytest.approx(96.6,abs=1e-7)
    assert right==pytest.approx(93.4,abs=1e-7)
    assert right-left==pytest.approx(-3.2,abs=1e-7)


@pytest.mark.parametrize("table", [curves((400.,400.,800.)),curves((400.,float('nan'),800.))])
def test_invalid_voltage_anchors_fail_closed(table):
    with pytest.raises(ValueError,match="anchors"):
        conversion(650,table=table)


def test_unknown_model_fails_even_with_zero_input():
    with pytest.raises(ValueError,match="unsupported inverter model"):
        conversion(650,model="inverter.unknown",power=0.)


def synthetic_inverter():
    return {"inverter_definition_id":"inv1-synthetic","revision_id":"inv1-r1",
        "efficiency_model":{"model_type":"voltage_dependent_curves","curves":curves()},
        "ac_limits":{"nominal_ac_power_w":200.,"max_ac_power_w":200.},
        "dc_limits":{"max_dc_voltage_v":1200.},
        "mppt_template":{"count":1,"min_operating_voltage_v":200.,"max_operating_voltage_v":1000.,"max_operating_current_a":10.},
        "operating_thresholds":{"startup_power_w":1.,"night_loss_w":2.,"standby_loss_w":1.}}


def test_real_inverter_selector_metadata_and_unchanged_nonconversion_stages():
    idx=pd.date_range('2026-01-01',periods=3,freq='h',tz='UTC');p=np.array([0.,.5,100.]);v=np.full(3,650.)
    f=pd.DataFrame({'mppt_pmp_w':p,'mppt_vmp_v':v,'mppt_voc_v':v+10,'mppt_imp_a':p/v,'active':p>0},index=idx)
    bank={1:MPPTAggregationResult(1,('invented-string',),f,{})}
    old=simulate_voltage_dependent_inverter(bank,synthetic_inverter());new=simulate_voltage_dependent_inverter(bank,synthetic_inverter(),model_id=NEW)
    assert old.metadata['model_id']==OLD and old.metadata['efficiency_voltage_interpolation']=='bounded_quadratic_v0.1'
    assert new.metadata['model_id']==NEW and new.metadata['efficiency_voltage_interpolation']==POLICY
    for c in ['dc_to_converter_w','dc_voltage_threshold_loss_w','dc_power_threshold_loss_w','night_consumption_w','standby_consumption_w','ac_power_limit_w']:
        assert np.array_equal(old.frame[c],new.frame[c])
    assert new.frame.ac_net_output_w.iloc[-1]==98.
    assert old.frame.ac_net_output_w.iloc[-1]==98.4375


def test_browser_and_resolver_explicit_selection_preserve_legacy_auto_default():
    from apps.api.study import _phase5_configuration
    from engine.simulation.models import resolve_inverter_model
    from tests.unit.test_phase38e_canonical_simulation_run import _project_revision,_inverter_definition
    assert _phase5_configuration(_project_revision(),configuration_id='inv1')['model_selections']['inverter']==NEW
    definition=_inverter_definition()
    auto=resolve_inverter_model(definition,resolution_id='inv1')
    old=resolve_inverter_model(definition,resolution_id='inv1',requested_model_id=OLD)
    new=resolve_inverter_model(definition,resolution_id='inv1',requested_model_id=NEW)
    assert auto['selected_model']['model_id']==old['selected_model']['model_id']==OLD
    assert new['status']=='resolved' and new['selected_model']['model_id']==NEW


@pytest.mark.parametrize('model',[OLD,NEW])
def test_canonical_run_and_manifest_record_policy_only_for_new_model(tmp_path,model):
    from tests.unit.test_phase38e_canonical_simulation_run import _inputs
    from engine.simulation import run_canonical_simulation
    from engine.simulation.artifacts import verify_run_package
    project,config,store=_inputs();config['model_selections']['inverter']=model
    result=run_canonical_simulation(project,config,revision_store=store,output_directory=tmp_path,
        simulation_run_id='inv1-canonical',engine_version='inv1-test',executed_at='2026-01-01T00:00:00Z')
    assert result.backend_result is not None,result.simulation_run['validation_findings']
    assert result.backend_result.electrical.inverter.metadata['model_id']==model
    run=result.simulation_run;manifest=run['reproducibility_manifest']['model_manifest']
    assert run['model_manifest']['inverter']==model
    for mapping in [run['model_manifest'],manifest]:
        if model==NEW:assert mapping['inverter_voltage_interpolation']==POLICY
        else:assert 'inverter_voltage_interpolation' not in mapping
    verify_run_package(result.artifact_directory)


def test_detailed_continuation_uses_new_resolved_selector(tmp_path):
    from tests.integration.test_phase69a_detailed_backend import _canonical_fixture
    from tests.integration.test_phase69a_closure import _declare
    from tests.unit.test_phase69a_canonical_dispatch import _run
    from engine.simulation.artifacts import verify_run_package
    project,config,store,_,_=_canonical_fixture();store=_declare(store,'separate_from_parameterization')
    config['model_selections']['inverter']=NEW
    result=_run(tmp_path,project,config,store,name='inv1-detailed',executed_at='2026-01-01T00:00:00Z')
    assert result.backend_result is not None,result.simulation_run['validation_findings']
    assert result.backend_result.electrical.inverter.metadata['model_id']==NEW
    assert result.simulation_run['model_manifest']['inverter_voltage_interpolation']==POLICY
    assert result.simulation_run['reproducibility_manifest']['model_manifest']['inverter_voltage_interpolation']==POLICY
    verify_run_package(result.artifact_directory)
