"""Orientation-class series/parallel curves and terminal-envelope maxima.

Between bypass knees each series voltage is decreasing and concave in current.
Its inverse, their parallel sum, and the resistive terminal transform retain
concavity. P(V) is therefore concave on each positive-voltage segment. Enumerating
all knees (including string Voc/current-cap joins) certifies that no basin is lost.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
import math
from typing import Mapping

import numpy as np
from pvlib.pvsystem import i_from_v, v_from_i
from scipy.optimize import brentq

MODEL_ID = "rawibumi.mixed_orientation.v0.1"


def bypass_basis(definition):
    data = definition.get("cell_architecture") or {}
    count, forward = data.get("bypass_diode_count"), data.get("bypass_diode_forward_voltage_v")
    if count is not None and (isinstance(count, bool) or int(count) != count or count < 0):
        raise ValueError("bypass diode count must be a nonnegative integer")
    if forward is not None and (not math.isfinite(forward) or forward <= 0):
        raise ValueError("bypass forward voltage must be positive and finite")
    return {"diode_count": 3 if count is None else count,
            "forward_voltage_v": .7 if forward is None else forward,
            "count_basis": "assumed" if count is None else "data",
            "forward_voltage_basis": "assumed" if forward is None else "data",
            "no_bypass_current_limited": count == 0,
            "source_paths": ["cell_architecture.bypass_diode_count", "cell_architecture.bypass_diode_forward_voltage_v"]}


@dataclass(frozen=True)
class ModuleCurve:
    parameters: tuple[float, float, float, float, float]
    diode_count: int = 3
    forward_voltage_v: float = .7

    def __post_init__(self):
        il, io, rs, rsh, a = self.parameters
        if not all(math.isfinite(p) for p in self.parameters) or il < 0 or io <= 0 or rs < 0 or rsh <= 0 or a <= 0:
            raise ValueError("invalid mixed-class diode parameters")

    @cached_property
    def isc(self):
        return max(0., float(i_from_v(0., *self.parameters)))

    @cached_property
    def voc(self):
        return max(0., float(v_from_i(0., *self.parameters)))

    @cached_property
    def knee(self):
        return float(i_from_v(-self.diode_count * self.forward_voltage_v, *self.parameters)) if self.diode_count else self.isc

    def voltage(self, current):
        value = v_from_i(current, *self.parameters)
        return np.maximum(value, -self.diode_count * self.forward_voltage_v) if self.diode_count else value



def _root(function, low, high, *, maxiter, xtol=1e-11):
    try:
        value, result = brentq(function, low, high, xtol=xtol, rtol=4*np.finfo(float).eps,
                               maxiter=maxiter, full_output=True, disp=False)
    except (ValueError, RuntimeError) as exc:
        raise RuntimeError("mixed-orientation solver did not converge") from exc
    if not result.converged or not math.isfinite(value):
        raise RuntimeError("mixed-orientation solver did not converge")
    return float(value)


class StringCurve:
    def __init__(self, modules: Mapping[str, ModuleCurve], composition: Mapping[str, int], *, maxiter=128):
        if not composition or any(n < 1 or int(n) != n for n in composition.values()):
            raise ValueError("a composite string requires positive module counts")
        self.parts = [(modules[c], n) for c, n in composition.items()]
        self.parameters = np.asarray([m.parameters for m,_ in self.parts]).T
        self.counts = np.asarray([n for _,n in self.parts])
        self.floors = np.asarray([-m.diode_count*m.forward_voltage_v if m.diode_count else -np.inf for m,_ in self.parts])
        self.maxiter = maxiter
        self.cap = max(m.isc for m, _ in self.parts)
        self.voc = sum(m.voc*n for m, n in self.parts)
        self.join = self.voltage(self.cap)
        knees = [m.knee for m, _ in self.parts if 0 < m.knee < self.cap]
        # The starting grid locates candidate basins; exact knees certify the partition.
        self.current_grid = np.unique(np.r_[np.linspace(0., self.cap, 200), knees])
        self.voltage_grid = self.voltage(self.current_grid)
        self.knots = [0., self.voc, max(0., self.join), *[max(0., self.voltage(i)) for i in knees]]

    def voltage(self, current):
        current = np.asarray(current)
        if current.ndim:
            values = v_from_i(current[None,:], *self.parameters[:,:,None])
            return self.counts @ np.maximum(values,self.floors[:,None])
        values = v_from_i(float(current),*self.parameters)
        return float(self.counts @ np.maximum(values,self.floors))

    def slopes(self, currents):
        currents = np.asarray(currents)
        il,io,rs,rsh,a = self.parameters[:,:,None]
        values = v_from_i(currents[None,:],il,io,rs,rsh,a)
        slopes = -1./(io*np.exp((values+currents[None,:]*rs)/a)/a+1./rsh)-rs
        slopes = np.where(values<=self.floors[:,None],0.,slopes)
        return self.counts @ slopes

    def at_voltage(self, voltage):
        if voltage >= self.voc or self.cap == 0:
            return 0., 0.
        if voltage <= self.join:
            return self.cap, 0.
        # Interpolation is only a search seed; every accepted point solves the true sum.
        guess = float(np.interp(voltage, self.voltage_grid[::-1], self.current_grid[::-1]))
        delta = self.voltage(guess) - voltage
        low, high = (guess, self.cap) if delta >= 0 else (0., guess)
        current = _root(lambda i: self.voltage(i)-voltage, low, high, maxiter=self.maxiter, xtol=1e-12)
        slope = float(self.slopes([current])[0])
        if slope >= 0:
            raise RuntimeError("mixed-orientation inverse curve is not decreasing")
        return current, 1./slope

    def bounds(self, voltage):
        current, _ = self.at_voltage(voltage)
        if voltage >= self.voc or self.cap == 0:
            return (0.,0.),(0.,0.)
        error = 1e-12 + 4*np.finfo(float).eps*self.cap
        lo, hi = max(0.,current-error), min(self.cap,current+error)
        sample = [lo,hi]
        for m,_ in self.parts:
            if lo <= m.knee <= hi:
                sample.extend([max(lo,np.nextafter(m.knee,-np.inf)),min(hi,np.nextafter(m.knee,np.inf))])
        slopes = self.slopes(sample)
        inverse = [1./d for d in slopes if d < 0]
        if voltage <= self.join or hi == self.cap:
            inverse.append(0.)
        if not inverse:
            raise RuntimeError("mixed-orientation derivative enclosure failed")
        return (lo,hi),(min(inverse),max(inverse))


@dataclass(frozen=True)
class Peak:
    voltage_v: float
    current_a: float
    power_w: float


def merge_plateau_peaks(peaks, power_at_voltage, *, tolerance_w, partition_voltages=()):
    """A connected plateau is one peak; equally high separated basins remain distinct."""
    output = []
    for peak in sorted(peaks, key=lambda p: p.voltage_v):
        if output and abs(peak.power_w-output[-1].power_w) <= tolerance_w:
            left = output[-1]
            if min(power_at_voltage(v) for v in [(left.voltage_v+peak.voltage_v)/2,
                    *[v for v in partition_voltages if left.voltage_v < v < peak.voltage_v]]) >= min(left.power_w, peak.power_w)-tolerance_w:
                output[-1] = peak  # first reached when moving down from Voc
                continue
        output.append(peak)
    return output


class ParallelCurve:
    def __init__(self, strings, *, maxiter=128):
        if not strings:
            raise ValueError("an MPPT needs strings")
        shared = {}
        self.strings = []
        for string in strings:
            key = tuple(sorted((m.parameters,m.diode_count,m.forward_voltage_v,n) for m,n in string.parts))
            self.strings.append(shared.setdefault(key,string))
        self.unique_strings = list(dict.fromkeys(self.strings))
        self.maxiter = maxiter
        self.voc = max(s.voc for s in strings)
        self.knots = np.unique([v for s in strings for v in s.knots if 0 <= v <= self.voc])

    def point(self, voltage):
        unique = {s:s.at_voltage(voltage) for s in self.unique_strings}
        return sum(unique[s][0] for s in self.strings), sum(unique[s][1] for s in self.strings)

    def envelope(self, *, k=1., resistance_ohm=0., current_limit_a=None, voltage_window=None):
        if self.maxiter < 1:
            raise RuntimeError("mixed-orientation solver did not converge")
        if not math.isfinite(k) or k < 0 or not math.isfinite(resistance_ohm) or resistance_ohm < 0:
            raise ValueError("invalid terminal transform")
        if current_limit_a is not None and (not math.isfinite(current_limit_a) or current_limit_a < 0):
            raise ValueError("invalid MPPT current limit")
        if k == 0 or self.voc == 0:
            return {"peak": Peak(0.,0.,0.), "peaks": [], "error_bound_w": 0.}
        def terminal(v):
            current, slope = self.point(v)
            it = k*current
            vt = v-resistance_ohm*it
            derivative = it*(1-resistance_ohm*k*slope) + vt*k*slope
            return vt, it, derivative
        low, high = 0., self.voc
        if terminal(low)[0] < 0:
            low = _root(lambda v: terminal(v)[0], low, high, maxiter=self.maxiter)
        if current_limit_a is not None and terminal(low)[1] > current_limit_a:
            low = _root(lambda v: terminal(v)[1]-current_limit_a, low, high, maxiter=self.maxiter)
        if voltage_window is not None:
            vmin, vmax = voltage_window
            if not (math.isfinite(vmin) and math.isfinite(vmax) and 0 <= vmin <= vmax):
                raise ValueError("invalid MPPT voltage window")
            if vmin > terminal(high)[0] or vmax < terminal(low)[0]:
                return {"peak": Peak(0.,0.,0.), "peaks": [], "error_bound_w": 0.}
            if terminal(low)[0] < vmin:
                low = _root(lambda v: terminal(v)[0]-vmin, low, high, maxiter=self.maxiter)
            if terminal(high)[0] > vmax:
                high = _root(lambda v: terminal(v)[0]-vmax, low, high, maxiter=self.maxiter)
        knots = np.unique(np.r_[low, self.knots[(self.knots > low) & (self.knots < high)], high])
        candidates, segment_maxima, certificates = [], [], []
        for a, b in zip(knots[:-1], knots[1:]):
            # One-sided values avoid the derivative discontinuity at bypass/Voc joins.
            epsilon = min((b-a)/4, max(1e-10, self.voc*1e-12))
            left, right = a+epsilon, b-epsilon
            dl, dr = terminal(left)[2], terminal(right)[2]
            if dl > 0 and dr < 0:
                v = _root(lambda v: terminal(v)[2], left, right, maxiter=self.maxiter)
            else:
                v = b if dl >= 0 else a
            vt, it, _ = terminal(v)
            segment_maxima.append((v, Peak(vt, it, max(0.,vt*it))))
            # A tangent bounds a concave terminal P(V) segment from above. Enclose
            # inner-root current/slope errors before using that bound as a certificate.
            probe = min(max(v,left),right)
            unique = {string:string.bounds(probe) for string in self.unique_strings}
            iv = [unique[string] for string in self.strings]
            ilo, ihi = (sum(row[0][j] for row in iv) for j in (0,1))
            slo, shi = (sum(row[1][j] for row in iv) for j in (0,1))
            vtlo, vthi = probe-resistance_ohm*k*ihi, probe-resistance_ohm*k*ilo
            dlo = k*ilo + max(0.,vthi)*k*slo/(1-resistance_ohm*k*slo)
            dhi = k*ihi + max(0.,vtlo)*k*shi/(1-resistance_ohm*k*shi)
            pa,pb = terminal(a)[0],terminal(b)[0]
            position_error = resistance_ohm*k*len(self.strings)*(1e-12+4*np.finfo(float).eps*sum(t.cap for t in self.strings))
            distances = (pa-vthi-position_error,pb-vtlo+position_error)
            vp,ip,_ = terminal(probe)
            objective_error = k*(self.voc+2*resistance_ohm*k*sum(t.cap for t in self.strings))*(ihi-ilo)
            certificates.append(vp*ip + objective_error + max(0.,*[d*x for d in (dlo,dhi) for x in distances]))

        if len(knots) == 1:
            vt,it,_ = terminal(low)
            segment_maxima = [(low,Peak(vt,it,max(0.,vt*it)))]
        tolerance = max(1e-8, k*self.voc*sum(s.cap for s in self.strings)*1e-10)
        for index,(v,peak) in enumerate(segment_maxima):
            if index and v == knots[index] and segment_maxima[index-1][1].power_w > peak.power_w+tolerance:
                continue
            if index+1 < len(segment_maxima) and v == knots[index+1] and segment_maxima[index+1][1].power_w > peak.power_w+tolerance:
                continue
            if not candidates or peak.voltage_v != candidates[-1].voltage_v:
                candidates.append(peak)
        def power_at(vt):
            raw = _root(lambda v: terminal(v)[0]-vt, low, high, maxiter=self.maxiter)
            v,i,_ = terminal(raw)
            return v*i
        peaks = merge_plateau_peaks(candidates, power_at, tolerance_w=tolerance,
                                    partition_voltages=[terminal(v)[0] for v in knots])
        best = max(peaks, key=lambda p: (p.power_w,p.voltage_v)) if peaks else Peak(0.,0.,0.)
        error = max(0.,max(certificates,default=best.power_w)-best.power_w)
        if error > max(1e-7,best.power_w*1e-7) or not math.isfinite(best.power_w):
            raise RuntimeError(f"mixed-orientation error certificate failed: {error} W")
        return {"peak": best, "peaks": peaks, "error_bound_w": error}


def combine_curves(modules, compositions, **terminal_options):
    maxiter = terminal_options.pop("maxiter", 128)
    curve = ParallelCurve([StringCurve(modules,c,maxiter=maxiter) for c in compositions],maxiter=maxiter)
    raw = curve.envelope()
    w0 = curve.envelope(k=terminal_options.get("k",1.), resistance_ohm=terminal_options.get("resistance_ohm",0.))
    wi = curve.envelope(k=terminal_options.get("k",1.), resistance_ohm=terminal_options.get("resistance_ohm",0.),
                        current_limit_a=terminal_options.get("current_limit_a"))
    wiv = curve.envelope(**terminal_options)
    if not (w0["peak"].power_w+1e-6 >= wi["peak"].power_w >= wiv["peak"].power_w-1e-6):
        raise RuntimeError("mixed-orientation nested envelopes do not reconcile")
    return {"raw": raw, "w0": w0, "wi": wi, "wiv": wiv, "voc_v": curve.voc}


# Frozen before Amendment 3: fd87f13c0708e1688678d543dfc8b14ad58af3d575a463250c525f480b8d0d2c


import pytest


class DenseBranchOracle:
    """Independent dense current curves discover peaks; true one-sided SDM refines them."""
    def __init__(self, modules, compositions):
        self.strings = [StringCurve(modules, row) for row in compositions]
        self.voc = max(s.voc for s in self.strings)
        self.knots = np.unique([0., self.voc, *[v for s in self.strings for v in s.knots if 0 <= v <= self.voc]])
        self.knees = [np.array([s.voltage(m.knee) if m.diode_count and 0 < m.knee < s.cap else -np.inf
                               for m, _ in s.parts]) for s in self.strings]
        grid = [np.linspace(0., self.voc, 32769), self.knots]
        self.samples = []
        for s in self.strings:
            current = np.unique(np.r_[np.linspace(0., s.cap, 8193),
                [m.knee for m, _ in s.parts if 0 < m.knee < s.cap]])
            voltage = s.voltage(current)
            self.samples.append((voltage[::-1], current[::-1]))
            grid.append(voltage[(voltage > 0) & (voltage < self.voc)])
        self.grid = np.unique(np.concatenate(grid))
        self.currents = sum(np.where(self.grid >= s.voc, 0., np.interp(self.grid, v, i))
                            for s, (v, i) in zip(self.strings, self.samples))

    def point(self, voltage, side=0):
        total = slope = 0.
        for s, knee_v, (sample_v, sample_i) in zip(self.strings, self.knees, self.samples):
            if s.cap == 0 or voltage > s.voc or (voltage == s.voc and side >= 0):
                continue
            if voltage <= s.join:
                total += s.cap
                continue
            position = np.clip(np.searchsorted(sample_v, voltage, side='right'), 1, len(sample_v)-1)
            low = sample_i[min(len(sample_i)-1, position+1)]
            high = sample_i[max(0, position-2)]
            if voltage == s.voc:
                current = 0.
            else:
                # Dense samples seed the bracket; exact SDM signs verify it.
                if s.voltage(low) < voltage or s.voltage(high) > voltage:
                    low, high = 0., s.cap
                current = brentq(lambda i: s.voltage(i)-voltage, low, high,
                                 xtol=1e-14, rtol=4*np.finfo(float).eps, maxiter=256)
            il, io, rs, rsh, a = s.parameters
            v = v_from_i(current, *s.parameters)
            derivative = -1/(io*np.exp((v+current*rs)/a)/a+1/rsh)-rs
            clamp = (voltage < knee_v) | ((voltage == knee_v) & (side < 0))
            derivative = np.where(clamp, 0., derivative)
            total += current
            slope += 1/float(s.counts @ derivative)
        return total, slope

    def envelope(self, *, k=1., resistance_ohm=0., current_limit_a=None, voltage_window=None):
        if k == 0 or self.voc == 0:
            return []
        def terminal(v, side=0):
            current, slope = self.point(v, side)
            vt, it = v-resistance_ohm*k*current, k*current
            return vt, it, it+vt*k*slope/(1-resistance_ohm*k*slope)
        low, high = 0., self.voc
        if terminal(low)[0] < 0:
            low = brentq(lambda v: terminal(v)[0], low, high, xtol=1e-12)
        if current_limit_a is not None and terminal(low)[1] > current_limit_a:
            low = brentq(lambda v: terminal(v)[1]-current_limit_a, low, high, xtol=1e-12)
        if voltage_window is not None:
            vmin, vmax = voltage_window
            if vmin > terminal(high)[0] or vmax < terminal(low)[0]:
                return []
            if terminal(low)[0] < vmin:
                low = brentq(lambda v: terminal(v)[0]-vmin, low, high, xtol=1e-12)
            if terminal(high)[0] > vmax:
                high = brentq(lambda v: terminal(v)[0]-vmax, low, high, xtol=1e-12)
        if high-low < 1e-10:
            v, i, _ = terminal(high)
            return [Peak(v, i, max(0., v*i))]
        grid = np.unique(np.r_[low, self.grid[(self.grid > low) & (self.grid < high)], high])
        currents = np.interp(grid, self.grid, self.currents)
        power = (grid-resistance_ohm*k*currents)*k*currents
        candidates = list(np.flatnonzero((power[1:-1] >= power[:-2]) & (power[1:-1] >= power[2:]))+1)
        # Domain boundaries and physical joins use the actual one-sided branch.
        raw = []
        if terminal(low, 1)[2] <= 0:
            raw.append(low)
        if terminal(high, -1)[2] >= 0:
            raw.append(high)
        searched = set()
        for j in candidates:
            branch = self.knots[np.searchsorted(self.knots, grid[j], side='right')-1]
            next_branch = self.knots[min(len(self.knots)-1, np.searchsorted(self.knots, grid[j], side='right'))]
            left, right = max(low, branch), min(high, next_branch)
            if (left, right) in searched:
                continue
            searched.add((left, right))
            if terminal(left, 1)[2] > 0 and terminal(right, -1)[2] < 0:
                raw.append(brentq(lambda v: terminal(v, 1 if v == left else -1 if v == right else 0)[2],
                                  left, right, xtol=1e-11))
        for knot in self.knots[(self.knots > low) & (self.knots < high)]:
            if terminal(knot, -1)[2] >= 0 and terminal(knot, 1)[2] <= 0:
                raw.append(knot)
        peaks = []
        for r in sorted(raw):
            vt, it, _ = terminal(r)
            if not peaks or abs(vt-peaks[-1].voltage_v) > 1e-6:
                peaks.append(Peak(vt, it, max(0., vt*it)))
        assert peaks, 'dense oracle did not resolve a maximum'
        return peaks


def _compositions(parameters, counts, diode_count=3):
    modules = {str(c): ModuleCurve(tuple(row), diode_count, .7) for c, row in enumerate(parameters)}
    compositions = [{str(c): int(n) for c, n in enumerate(row) if n} for row in counts]
    return modules, compositions


def _batch_peaks(result, hour=0):
    mask = result['peak_mask'][hour]
    return [Peak(float(v), float(i), float(p)) for v, i, p in zip(
        result['peak_voltages'][hour, mask], result['peak_currents'][hour, mask], result['peak_powers'][hour, mask])]


def _gaps(peaks):
    if len(peaks) < 2:
        return np.zeros(3)
    ordered = sorted((p.power_w for p in peaks), reverse=True)
    return np.array([ordered[0]-max(peaks, key=lambda p: p.voltage_v).power_w,
                     ordered[0]-ordered[1], ordered[0]-ordered[-1]])


def test_seed_5103_hour_23_sixth_peak_and_gaps(record_property):
    from engine.simulation.mixed_orientation import BatchCurves
    parameters = np.array([[8.063104040961244, 5.855305276515367e-11, .203, 366.0691004567312, 1.8635990114704721],
        [.6378775860466815, 8.446930563153071e-12, .203, 1621.2090086234991, 1.7909432948766386],
        [18.408421874081764, 4.2983104835846326e-9, .203, 294.459749663862, 2.046154135903841],
        [3.3857431224753247, 1.9783399754058757e-11, .203, 745.3300330961854, 1.822214666821369],
        [10.646957659973994, 1.354780801839076e-10, .203, 319.9561492725034, 1.8968154465022835]])
    counts = [[2, 2, 1, 1, 4], [2, 2, 2, 1, 3]]
    modules, compositions = _compositions(parameters, counts)
    frozen = combine_curves(modules, compositions)['raw']['peaks']
    expected = DenseBranchOracle(modules, compositions).envelope()
    result = BatchCurves(parameters[None], counts, [3]*5, [.7]*5).nested()['wiv']
    peaks = _batch_peaks(result)
    assert len(frozen) == 5
    assert len(expected) == len(peaks) == 6
    assert peaks[-1].voltage_v == pytest.approx(445.96786762579035, abs=1e-5)
    assert peaks[-1].power_w == pytest.approx(545.921896690596, abs=1e-6)
    assert np.allclose(_gaps(peaks), _gaps(expected), rtol=1e-7, atol=1e-7)
    record_property('corrected_oracle_disagreement', 'seed 5103 hour 23: frozen 5 peaks; corrected and shipped 6')


def test_two_humps_in_initial_segment_recovers_omitted_global():
    from engine.simulation.mixed_orientation import BatchCurves
    parameters = np.array([[10., 1e-9, .2, 500., 1.5], [.2, 1e-9, .2, 500., 1.5]])
    counts = [[5, 5]]
    modules, compositions = _compositions(parameters, counts)
    curve = ParallelCurve([StringCurve(modules, compositions[0])])
    curve.knots = np.array([0., curve.voc])
    frozen = curve.envelope()
    oracle = DenseBranchOracle(modules, compositions).envelope()
    batch = BatchCurves(parameters[None], counts, [3, 3], [.7, .7])
    batch.knots = np.array([[0., batch.voc[0]]])
    with pytest.raises(RuntimeError, match='uncertifiable non-concave'):
        batch.certify_concavity(np.array([0.]), batch.voc, np.array([0]), np.ones(1), np.zeros(1))
    result = batch.nested()['raw']
    peaks = _batch_peaks(result)
    assert len(peaks) == len(oracle) == 2
    assert frozen['peak'].power_w < max(p.power_w for p in oracle)*.1
    assert result['power_w'][0] == pytest.approx(max(p.power_w for p in oracle), rel=1e-7)
    assert np.allclose(_gaps(peaks), _gaps(oracle), rtol=1e-7, atol=1e-7)


import pytest


@pytest.mark.parametrize("diode_count",[0,3])
def test_500_random_hours_compositions_against_oracles(diode_count, record_property):
    from engine.simulation.mixed_orientation import BatchCurves
    rng=np.random.default_rng(5103)
    hours,classes,strings=500,5,2
    from apps.api.catalog import load_reference_catalog
    from engine.simulation.unshaded import _module_runtime_properties
    from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
    module=load_reference_catalog()['modules']['mod-rawibumi-uat-550-r1']
    parameter_set=_module_runtime_properties(module)[0]
    irradiance=rng.uniform(.01,1300.,(hours,classes))
    irradiance[::7,1:3]=0.
    ambient=rng.uniform(10.,35.,(hours,1))
    temperature=ambient+irradiance*rng.uniform(.015,.04,(hours,classes))
    parameters=np.stack(calculate_pvsyst_diode_parameters(effective_irradiance_w_m2=irradiance,
        cell_temperature_c=temperature,parameter_set=parameter_set),axis=-1)
    # The standard all-dark convention uses an identical state on every class.
    parameters[::101,:,:]=np.array([0.,1e-9,.2,500.,1.5])
    counts=np.stack([[rng.multinomial(10,np.ones(classes)/classes) for _ in range(strings)] for _ in range(hours)])
    diodes=np.full(classes,diode_count);forward=np.full(classes,.7)
    k=rng.uniform(.7,1.3,hours);k[::103]=0.
    resistance=rng.uniform(0.,.8,hours);resistance[::3]=0.
    limit=rng.uniform(.1,35,hours);limit[::13]=0.;limit[::11]=1000.
    vmin=rng.uniform(0.,300,hours);vmax=vmin+rng.uniform(10.,400.,hours)
    vmin[::17]=1000.;vmax[::17]=1100.
    vmin[::19]=0.;vmax[::19]=2000.
    batch=BatchCurves(parameters,counts,diodes,forward)
    actual=batch.nested(k=k,resistance_ohm=resistance,current_limit_a=limit,voltage_window=(vmin,vmax))
    if diode_count:
        # Seeded hour 36 is a rising join, falsely called a peak by the frozen solver.
        assert int(actual['raw']['peak_mask'][36].sum()) == 6
        assert min(p.voltage_v for p in _batch_peaks(actual['raw'],36)) == pytest.approx(105.73958194155, abs=1e-6)
    multi=boundary=dark=0
    disagreements=[]
    for hour in range(hours):
        modules={str(c):ModuleCurve(tuple(parameters[hour,c]),int(diodes[c]),float(forward[c])) for c in range(classes)}
        compositions=[{str(c):int(n) for c,n in enumerate(row) if n} for row in counts[hour]]
        try:
            expected=combine_curves(modules,compositions,k=k[hour],resistance_ohm=resistance[hour],
                current_limit_a=limit[hour],voltage_window=(vmin[hour],vmax[hour]))
        except RuntimeError as exc:
            # Amendment 4 excludes uncertified frozen basins; corrected checks
            # below still cover every stage and every peak of this hour.
            expected=None
            disagreements.append({'hour':hour,'frozen_failure':str(exc)})
        oracle=DenseBranchOracle(modules,compositions)
        # Every branch knee/Voc must partition the frozen basins. Between these
        # joins, V''(I)<=0 implies inverse I''(V)<=0 and terminal P''(Vt)<=0.
        basins_certified=np.array_equal(ParallelCurve(oracle.strings).knots,oracle.knots)
        options=dict(k=float(k[hour]),resistance_ohm=float(resistance[hour]))
        specs={'raw':{},'w0':options,'wi':{**options,'current_limit_a':float(limit[hour])},
            'wiv':{**options,'current_limit_a':float(limit[hour]),'voltage_window':(float(vmin[hour]),float(vmax[hour]))}}
        for stage in ('raw','w0','wi','wiv'):
            got=actual[stage];reference=expected[stage] if expected is not None else None
            corrected=oracle.envelope(**specs[stage])
            peaks=_batch_peaks(got,hour)
            best=max((p.power_w for p in corrected),default=0.)
            tolerance=max(1e-7,best*1e-7)
            assert got['error_bound_w'][hour]<=tolerance
            assert abs(got['power_w'][hour]-best)<=tolerance,(hour,stage)
            assert len(peaks)==len(corrected),(hour,stage,peaks,corrected)
            assert np.allclose([p.power_w for p in peaks],[p.power_w for p in corrected],rtol=1e-7,atol=1e-7),(hour,stage)
            assert np.allclose(_gaps(peaks),_gaps(corrected),rtol=1e-7,atol=tolerance),(hour,stage)
            scalar=reference['peaks'] if reference is not None else []
            # A frozen basin is eligible only when its complete peak partition
            # agrees with the independent dense, one-sided branch search.
            certified=reference is not None and basins_certified and len(scalar)==len(corrected) and np.allclose(
                [p.power_w for p in scalar],[p.power_w for p in corrected],rtol=1e-7,atol=1e-7)
            if certified:
                assert abs(got['power_w'][hour]-reference['peak'].power_w)<=reference['error_bound_w']+got['error_bound_w'][hour]+1e-8
                assert np.allclose(_gaps(peaks),_gaps(scalar),rtol=1e-7,atol=tolerance)
            else:
                disagreements.append({'hour':hour,'stage':stage,'frozen_count':len(scalar),'corrected_count':len(corrected)})
            if stage=='wiv' and len(peaks)>1:multi+=1
        wired=actual['w0']
        if resistance[hour]==0 and k[hour]>0:
            assert wired['power_w'][hour]==k[hour]*actual['raw']['power_w'][hour]
            assert wired['voltage_v'][hour]==actual['raw']['voltage_v'][hour]
        if wired['current_a'][hour]<=limit[hour]:
            assert actual['wi']['power_w'][hour]==wired['power_w'][hour]
        if vmin[hour]<=actual['wi']['voltage_v'][hour]<=vmax[hour]:
            assert actual['wiv']['power_w'][hour]==actual['wi']['power_w'][hour]
        final=actual['wiv']
        if final['power_w'][hour]>0:
            assert final['current_a'][hour]<=limit[hour]+1e-8
            assert vmin[hour]-1e-8<=final['voltage_v'][hour]<=vmax[hour]+1e-8
            boundary+=abs(final['voltage_v'][hour]-vmin[hour])<1e-7 or abs(final['voltage_v'][hour]-vmax[hour])<1e-7
        dark+=not parameters[hour,:,0].any()
    record_property("corrected_oracle_disagreements",disagreements)
    assert boundary>0 and dark>0
    if diode_count:assert multi>0


def test_vectorized_nonconvergence_remains_explicit():
    import pytest
    from engine.simulation.mixed_orientation import BatchCurves
    parameters=np.broadcast_to(np.array([10.,1e-9,.2,500.,1.5]),(2,1,5)).copy()
    with pytest.raises(RuntimeError,match='did not converge'):
        BatchCurves(parameters,[[10]],[3],[.7],maxiter=0).nested()


def test_exact_maximizer_boundaries_retain_the_peak_and_identity():
    from engine.simulation.mixed_orientation import BatchCurves
    parameters = np.array([[[10., 1e-9, .2, 500., 1.5], [.2, 1e-9, .2, 500., 1.5]]])
    batch = BatchCurves(parameters, [[5, 5]], [3, 3], [.7, .7])
    wired = batch.nested(k=1.2, resistance_ohm=.2)['w0']
    voltage, current = wired['voltage_v'], wired['current_a']
    for limit, window in ((current, None), (None, (voltage, voltage+10)),
            (None, (voltage-10, voltage)), (current, (voltage, voltage+10)),
            (current, (voltage-10, voltage))):
        final = batch.nested(k=1.2, resistance_ohm=.2,
            current_limit_a=limit, voltage_window=window)['wiv']
        assert np.array_equal(final['power_w'], wired['power_w'])
        assert np.array_equal(final['voltage_v'], wired['voltage_v'])
        peaks = _batch_peaks(final)
        assert any(p.power_w == pytest.approx(wired['power_w'][0], abs=1e-8) for p in peaks)
        assert len(peaks) == (2 if window is None else 1)


def test_current_and_window_intersection_retains_a_lower_local_peak():
    from engine.simulation.mixed_orientation import BatchCurves
    parameters = np.array([[[10., 1e-9, .2, 500., 1.5], [5., 1e-9, .2, 500., 1.5]]])
    batch = BatchCurves(parameters, [[5, 5]], [3, 3], [.7, .7])
    wired = batch.nested(k=1.2, resistance_ohm=.2)['w0']
    local = min(_batch_peaks(wired), key=lambda p: p.voltage_v)
    assert local.power_w < wired['power_w'][0]
    for minimum in (local.voltage_v-10, local.voltage_v):
        final = batch.nested(k=1.2, resistance_ohm=.2, current_limit_a=local.current_a,
            voltage_window=(minimum,local.voltage_v))['wiv']
        assert len(_batch_peaks(final)) == 1
        assert final['power_w'][0] == pytest.approx(local.power_w, abs=1e-8)
        assert final['voltage_v'][0] == pytest.approx(local.voltage_v, abs=1e-10)
        assert final['current_a'][0] <= local.current_a+1e-12
