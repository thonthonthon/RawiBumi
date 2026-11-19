"""Independent dense-current oracle and exact uniform limit."""
import numpy as np
import pytest
from pvlib.pvsystem import singlediode, v_from_i
from engine.simulation.mixed_orientation import ModuleCurve, StringCurve, ParallelCurve, Peak, combine_curves, merge_plateau_peaks


def module(light=10.,diodes=3):
    return ModuleCurve((light,1e-9,.2,500.,1.5),diodes)


def test_forced_uniform_raw_matches_legacy_at_one_part_per_million():
    m=module()
    actual=combine_curves({'a':m},[{'a':10}]*2)['raw']['peak'].power_w
    assert actual==pytest.approx(singlediode(*m.parameters)['p_mp']*20,rel=1e-6)


def test_series_bypass_and_parallel_addition_no_backfeed():
    strong,weak=module(),module(.1)
    string=StringCurve({'s':strong,'w':weak},{'s':9,'w':1})
    assert string.voltage(8.)==pytest.approx(9*float(v_from_i(8.,*strong.parameters))-2.1)
    curve=ParallelCurve([string,string])
    i,_=curve.point(200.)
    one,_=string.at_voltage(200.)
    assert i==pytest.approx(2*one)
    assert string.at_voltage(string.voc+1)==(0.,0.)


def test_random_series_oracle_uses_dense_true_current_curves():
    rng=np.random.default_rng(427)
    for _ in range(20):
        modules={str(c):module(float(rng.uniform(.05,14))) for c in range(3)}
        counts={c:int(rng.integers(1,8)) for c in modules}
        current=np.linspace(0,max(m.isc for m in modules.values()),100001)
        voltage=sum(n*np.maximum(v_from_i(current,*modules[c].parameters),-2.1) for c,n in counts.items())
        oracle=np.max(np.maximum(voltage,0)*current)
        actual=combine_curves(modules,[counts])['raw']['peak'].power_w
        assert actual==pytest.approx(oracle,rel=.001)
        assert 0 <= actual <= sum(n*singlediode(*modules[c].parameters)['p_mp'] for c,n in counts.items())+1e-6


def test_nested_envelopes_and_final_point_constraints():
    r=combine_curves({'a':module(),'b':module(1.)},[{'a':9,'b':1},{'b':10}],
                     k=1.3,resistance_ohm=.2,current_limit_a=7.,voltage_window=(200,300))
    p,p0,pi,piv=(r[c]['peak'].power_w for c in ('raw','w0','wi','wiv'))
    assert 1.3*p >= p0 >= pi >= piv
    final=r['wiv']['peak']
    assert final.current_a<=7+1e-8 and 200-1e-8<=final.voltage_v<=300+1e-8
    assert p0-pi+pi-piv+1.3*p-p0 == pytest.approx(1.3*p-piv)
    assert combine_curves({'a':module()},[{'a':10}],voltage_window=(1000,1100))['wiv']['peak'].power_w==0


def test_nonconvergence_fails_explicitly():
    with pytest.raises(RuntimeError,match='did not converge'):
        combine_curves({'a':module()},[{'a':10}],maxiter=0)


def test_peak_plateau_and_equal_peaks_with_dip():
    peaks=[Peak(1,1,1),Peak(2,.5,1)]
    assert len(merge_plateau_peaks(peaks,lambda v:1.,tolerance_w=1e-8))==1
    assert len(merge_plateau_peaks(peaks,lambda v:0.,tolerance_w=1e-8))==2


def test_boundary_maximum_and_simple_tracker_order():
    r=combine_curves({'a':module(),'b':module(.2)},[{'a':9,'b':1}],voltage_window=(280,290))
    peaks=r['wiv']['peaks']
    assert peaks and all(280-1e-8<=p.voltage_v<=290+1e-8 for p in peaks)
    simple=max(peaks,key=lambda p:p.voltage_v)
    assert simple.voltage_v == max(p.voltage_v for p in peaks)

def test_parallel_oracle_with_random_distinct_compositions():
    rng=np.random.default_rng(818)
    for _ in range(12):
        modules={str(c):ModuleCurve((float(rng.uniform(.1,14)),float(rng.uniform(.5e-9,2e-9)),
                    float(rng.uniform(.1,.5)),float(rng.uniform(200,800)),float(rng.uniform(1.2,2.)))) for c in range(3)}
        compositions=[{c:int(rng.integers(1,6)) for c in modules} for _ in range(3)]
        currents=np.linspace(0,max(m.isc for m in modules.values()),100001)
        curves=[]
        for composition in compositions:
            voltage=sum(n*np.maximum(v_from_i(currents,*modules[c].parameters),-2.1) for c,n in composition.items())
            curves.append((voltage,currents))
        voltage=np.linspace(0,max(v[0] for v,_ in curves),100001)
        current=sum(np.interp(voltage,v[::-1],i[::-1],right=0.) for v,i in curves)
        oracle=np.max(voltage*current)
        result=combine_curves(modules,compositions)
        assert result['raw']['peak'].power_w==pytest.approx(oracle,rel=.001)
        assert result['raw']['error_bound_w']<=max(1e-7,result['raw']['peak'].power_w*1e-7)


def test_two_real_peaks_and_tracker_comes_from_voc():
    result=combine_curves({'a':module(),'b':module(.2)},[{'a':5,'b':5}])['wiv']
    assert len(result['peaks'])==2
    simple=max(result['peaks'],key=lambda p:p.voltage_v)
    assert simple.power_w < result['peak'].power_w
    assert simple.voltage_v > result['peak'].voltage_v

def test_identical_compositions_share_a_curve_without_losing_multiplicity():
    parts={'a':module(),'b':module(.5)}
    strings=[StringCurve(parts,{'a':5,'b':5}) for _ in range(3)]
    curve=ParallelCurve(strings)
    assert len(curve.unique_strings)==1
    current,_=curve.point(100.)
    assert current==pytest.approx(3*strings[0].at_voltage(100.)[0])

def test_constrained_parallel_oracle_on_the_terminal_curve():
    parts={'a':module(),'b':module(.7)}
    compositions=[{'a':5,'b':5},{'a':10}]
    grid=np.linspace(0,max(m.isc for m in parts.values()),100001)
    strings=[]
    for composition in compositions:
        voltage=sum(n*np.maximum(v_from_i(grid,*parts[c].parameters),-2.1) for c,n in composition.items())
        strings.append(voltage)
    raw_voltage=np.linspace(0,max(v[0] for v in strings),200001)
    raw_current=sum(np.interp(raw_voltage,v[::-1],grid[::-1],right=0.) for v in strings)
    k,resistance=1.17,.2
    terminal_i=k*raw_current
    terminal_v=raw_voltage-resistance*terminal_i
    power=terminal_v*terminal_i
    masks=[terminal_v>=0,(terminal_v>=0)&(terminal_i<=7.),
        (terminal_i<=7.)&(terminal_v>=200.)&(terminal_v<=300.)]
    result=combine_curves(parts,compositions,k=k,resistance_ohm=resistance,current_limit_a=7.,voltage_window=(200.,300.))
    for stage,mask in zip(('w0','wi','wiv'),masks):
        oracle=np.max(power[mask]) if mask.any() else 0.
        assert result[stage]['peak'].power_w==pytest.approx(oracle,rel=.001)
