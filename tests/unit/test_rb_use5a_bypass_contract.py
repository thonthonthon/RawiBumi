from pathlib import Path
import numpy as np
import pytest
from components.pan import parse_pan_text,map_pan
from engine.simulation.mixed_orientation import ModuleCurve,StringCurve,bypass_basis,class_parameters
from tests.unit.test_rb_use5a_mixed_iv import module


def test_zero_diodes_is_not_the_missing_count_fallback():
    zero=bypass_basis({'cell_architecture':{'bypass_diode_count':0}})
    missing=bypass_basis({})
    assert zero['diode_count']==0 and zero['no_bypass_current_limited']
    assert missing['diode_count']==3 and missing['count_basis']=='assumed'
    weak=module(.1,diodes=0)
    unprotected=StringCurve({'a':module(),'b':weak},{'a':9,'b':1})
    protected=StringCurve({'a':module(),'b':module(.1)},{'a':9,'b':1})
    unprotected_current=unprotected.at_voltage(100.)[0]
    assert unprotected_current < protected.at_voltage(100.)[0]
    assert unprotected.voltage(unprotected_current)==pytest.approx(100.,abs=1e-8)
    assert unprotected_current<module().isc*.1
    assert weak.voltage(2.) < -2.1


def test_pan_forward_voltage_preserves_signed_source_provenance():
    from tests.unit.test_phase52_execution_groups import ROOT
    raw=(ROOT/'tests/fixtures/panond/manufacturer/JKM550M-72HL4-V_SGS_6079M3.PAN').read_text(encoding='utf-8-sig')
    result=map_pan(parse_pan_text(raw))
    assert result.values_by_canonical_path['cell_architecture.bypass_diode_forward_voltage_v']==.7
    mapped=next(m for m in result.mapped_fields if m['canonical_path']=='cell_architecture.bypass_diode_forward_voltage_v')
    assert mapped['source_value']=='-0.70'
    assert mapped['canonical_value']==.7


def test_dark_class_keeps_real_sdm_and_bypass_voltage(tmp_path):
    from engine.simulation.unshaded import run_fixed_tilt_class_dc,prepare_fixed_tilt_context,_module_runtime_properties
    from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
    from engine.module.pvsyst import SDM_COLUMNS
    from tests.integration.test_rb_use5a_circular_roof import physics_fixture
    weather,bindings,_,_,_=physics_fixture(tmp_path,circular=True,periods=24)
    config=next(iter(bindings.values()))['config']
    context=prepare_fixed_tilt_context(weather,config=config)
    dc=run_fixed_tilt_class_dc(context,config=config)
    inactive=~dc.coupled_module.electrical.frame.active.to_numpy()
    assert inactive.any() and (~inactive).any()
    params=class_parameters(dc,config.module_definition)
    expected=calculate_pvsyst_diode_parameters(
        effective_irradiance_w_m2=dc.optical.frame.effective_irradiance_w_m2.to_numpy()[inactive],
        cell_temperature_c=dc.coupled_module.thermal.frame.cell_temperature_c.to_numpy()[inactive],
        parameter_set=_module_runtime_properties(config.module_definition)[0])
    for col,values in enumerate(expected):assert params[inactive,col]==pytest.approx(values)
    assert np.isnan(dc.coupled_module.electrical.frame.loc[inactive,list(SDM_COLUMNS)].to_numpy()).all()
    dark=ModuleCurve(tuple(params[np.flatnonzero(inactive)[0]]))
    bright=ModuleCurve(tuple(params[np.flatnonzero(~inactive)[-2]]))
    curve=StringCurve({'bright':bright,'dark':dark},{'bright':9,'dark':1})
    assert curve.voltage(bright.isc*.8)==pytest.approx(9*bright.voltage(bright.isc*.8)-2.1)
    from engine.simulation.mixed_orientation import combine_curves
    assert combine_curves({'dark':dark},[{'dark':10}])['raw']['peak'].power_w==0

@pytest.mark.parametrize('raw',['-0.70','0.70'])
def test_absolute_conversion_accepts_both_source_signs(raw):
    result=map_pan(parse_pan_text(f'PVObject_=pvModule\n  VRevDiode={raw}\nEnd of PVObject_\n'))
    assert result.values_by_canonical_path['cell_architecture.bypass_diode_forward_voltage_v']==.7
    row=next(r for r in result.mapped_fields if r['canonical_path']=='cell_architecture.bypass_diode_forward_voltage_v')
    assert row['source_value']==raw and row['conversion']=='abs_float'


def test_ambiguous_forward_voltage_is_not_selected_by_line_order():
    result=map_pan(parse_pan_text('PVObject_=pvModule\n  VRevDiode=-0.70\n  VRevDiode=-0.50\nEnd of PVObject_\n'))
    assert 'cell_architecture.bypass_diode_forward_voltage_v' not in result.values_by_canonical_path
    assert any('Ambiguous duplicate source path' in warning for warning in result.warnings)
    assert len([f for f in result.unmapped_fields if f['key']=='VRevDiode'])==2


@pytest.mark.parametrize('raw',['NaN','inf','not-a-number'])
def test_invalid_forward_voltage_retains_raw_evidence_and_warning(raw):
    result=map_pan(parse_pan_text(f'PVObject_=pvModule\n  VRevDiode={raw}\nEnd of PVObject_\n'))
    assert 'cell_architecture.bypass_diode_forward_voltage_v' not in result.values_by_canonical_path
    assert any('Could not map' in warning for warning in result.warnings)
    assert any(field['key']=='VRevDiode' for field in result.unmapped_fields)


@pytest.mark.parametrize('forward',[0.,-1.,float('nan'),float('inf')])
def test_explicit_invalid_bypass_basis_is_refused(forward):
    with pytest.raises(ValueError,match='positive and finite'):
        bypass_basis({'cell_architecture':{'bypass_diode_count':3,'bypass_diode_forward_voltage_v':forward}})


def test_partial_fallback_keeps_supplied_values():
    count_only=bypass_basis({'cell_architecture':{'bypass_diode_count':2}})
    voltage_only=bypass_basis({'cell_architecture':{'bypass_diode_forward_voltage_v':.6}})
    assert (count_only['diode_count'],count_only['forward_voltage_v'])==(2,.7)
    assert (count_only['count_basis'],count_only['forward_voltage_basis'])==('data','assumed')
    assert (voltage_only['diode_count'],voltage_only['forward_voltage_v'])==(3,.6)
    assert (voltage_only['count_basis'],voltage_only['forward_voltage_basis'])==('assumed','data')
