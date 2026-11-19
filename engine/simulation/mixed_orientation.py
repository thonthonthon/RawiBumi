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

    @cached_property
    def batch(self):
        return BatchCurves(np.asarray([[m.parameters for m, _ in self.parts]]),
            [[n for _, n in self.parts]], [m.diode_count for m, _ in self.parts],
            [m.forward_voltage_v for m, _ in self.parts], maxiter=self.maxiter)

    def at_voltage(self, voltage):
        current, slope, _ = self.batch.point(np.array([voltage]))
        return float(current[0]), float(slope[0])

    def bounds(self, voltage):
        ilo, ihi, slo, shi = self.batch.bounds(np.array([voltage]), np.array([0]))
        return (float(ilo[0]), float(ihi[0])), (float(slo[0]), float(shi[0]))


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

    @cached_property
    def batch(self):
        states = list(dict.fromkeys(m for s in self.unique_strings for m, _ in s.parts))
        counts = [[sum(n for m, n in s.parts if m == state) for state in states] for s in self.strings]
        return BatchCurves(np.array([[m.parameters for m in states]]), counts,
            [m.diode_count for m in states], [m.forward_voltage_v for m in states], maxiter=self.maxiter)

    def point(self, voltage):
        current, slope, _ = self.batch.point(np.array([voltage]))
        return float(current[0]), float(slope[0])

    def envelope(self, **options):
        return _scalar_envelope(self.batch.envelope(**options))


def _scalar_envelope(result):
    mask = result["peak_mask"][0]
    return {"peak": Peak(float(result["voltage_v"][0]), float(result["current_a"][0]), float(result["power_w"][0])),
        "peaks": [Peak(float(v), float(i), float(p)) for v, i, p in zip(result["peak_voltages"][0,mask],
            result["peak_currents"][0,mask], result["peak_powers"][0,mask])],
        "error_bound_w": float(result["error_bound_w"][0])}


def combine_curves(modules, compositions, **terminal_options):
    maxiter = terminal_options.pop("maxiter", 128)
    curve = ParallelCurve([StringCurve(modules,c,maxiter=maxiter) for c in compositions],maxiter=maxiter)
    result = curve.batch.nested(**terminal_options)
    envelopes = {name: _scalar_envelope(result[name]) for name in ("raw", "w0", "wi", "wiv")}
    if not (envelopes["w0"]["peak"].power_w+1e-6 >= envelopes["wi"]["peak"].power_w >= envelopes["wiv"]["peak"].power_w-1e-6):
        raise RuntimeError("mixed-orientation nested envelopes do not reconcile")
    return {**envelopes, "voc_v": curve.voc}


EPS = np.finfo(float).eps


class _SolverError(RuntimeError):
    def __init__(self, message, rows):
        super().__init__(message)
        self.rows = np.asarray(rows, dtype=int)


def _module_voltage(current, il, io, rs, rsh, a):
    voltage = v_from_i(current, il, io, rs, rsh, a)
    junction = voltage+current*rs
    # Remove Lambert-W subtraction cancellation before enclosing derivatives.
    for _ in range(2):
        residual = io*np.expm1(junction/a)+junction/rsh-(il-current)
        junction -= residual/(io*np.exp(junction/a)/a+1./rsh)
    return junction-current*rs


class BatchCurves:
    def __init__(self, parameters, counts, diode_counts, forward_voltages, *, maxiter=128):
        self.parameters = np.asarray(parameters, dtype=float)
        if self.parameters.ndim != 3 or self.parameters.shape[2] != 5:
            raise ValueError('mixed parameters must have shape (hours, classes, 5)')
        self.h, self.c = self.parameters.shape[:2]
        counts = np.asarray(counts, dtype=float)
        self.physical_strings = counts.shape[-2]
        self.multiplicity = np.ones(self.physical_strings)
        if counts.ndim == 2:
            # Exact duplicate strings share their solve, retaining multiplicity.
            distinct, multiplicity = {}, []
            for row in counts:
                key = tuple(row)
                if key not in distinct:
                    distinct[key] = len(distinct)
                    multiplicity.append(0)
                multiplicity[distinct[key]] += 1
            counts = np.asarray(list(distinct))
            self.multiplicity = np.asarray(multiplicity)
        self.counts = np.broadcast_to(counts, (self.h,*counts.shape[-2:])).copy()
        if self.counts.shape[2] != self.c or np.any(self.counts<0) or np.any(self.counts != np.floor(self.counts)) or np.any(self.counts.sum(axis=2)==0):
            raise ValueError('invalid composite module counts')
        self.s = self.counts.shape[1]
        self.maxiter = maxiter
        il,io,rs,rsh,a = self.parameters.transpose(2,0,1)
        if not np.isfinite(self.parameters).all() or np.any(il<0) or np.any(io<=0) or np.any(rs<0) or np.any(rsh<=0) or np.any(a<=0):
            raise ValueError('invalid mixed-class diode parameters')
        self.diodes = np.broadcast_to(np.asarray(diode_counts), (self.c,))
        self.forward = np.broadcast_to(np.asarray(forward_voltages), (self.c,))
        if np.any(~np.isfinite(self.diodes)|(self.diodes<0)|(self.diodes!=np.floor(self.diodes))) or np.any(~np.isfinite(self.forward)|(self.forward<=0)):
            raise ValueError('invalid bypass basis')
        self.floors = np.where(self.diodes>0,-self.diodes*self.forward,-np.inf)
        self.isc = np.maximum(0.,i_from_v(0.,il,io,rs,rsh,a))
        self.module_voc = np.maximum(0.,_module_voltage(0.,il,io,rs,rsh,a))
        self.knees = np.where(self.diodes>0,i_from_v(-self.diodes*self.forward,il,io,rs,rsh,a),self.isc)
        self.minimum_slope = rs+1./(io*np.exp(self.module_voc/a)/a+1./rsh)
        self.cap = np.max(np.where(self.counts>0,self.isc[:,None,:],0.),axis=2)
        self.string_voc = np.sum(self.counts*self.module_voc[:,None,:],axis=2)
        self.voc = self.string_voc.max(axis=1)
        current = self.cap[:,:,None]*np.linspace(0.,1.,200)
        knees = np.broadcast_to(self.knees[:,None,:],self.counts.shape)
        valid = (self.counts>0)&(knees>0)&(knees<self.cap[:,:,None])
        current = np.sort(np.concatenate((current,np.where(valid,knees,0.)),axis=2),axis=2)
        self.grid_i = current
        self.grid_v = self._grid_voltage(current)
        self.join = self.grid_v[:,:,-1]
        knee_voltage = self._grid_voltage(np.where(valid,knees,0.))
        knots = np.concatenate((np.zeros((self.h,1)),self.string_voc,
            np.maximum(0.,self.join),np.where(valid,np.maximum(0.,knee_voltage),0.).reshape(self.h,-1)),axis=1)
        self.knots = np.sort(knots,axis=1)
        self.branch_knots = self.knots.copy()
        self.knee_voltage = np.where(valid & (knee_voltage>=0),knee_voltage,-np.inf)
        self.cap_sum = self.cap @ self.multiplicity

    def _grid_voltage(self, current):
        il,io,rs,rsh,a = self.parameters.transpose(2,0,1)
        v = _module_voltage(current[:,:,None,:],il[:,None,:,None],io[:,None,:,None],
            rs[:,None,:,None],rsh[:,None,:,None],a[:,None,:,None])
        return np.sum(self.counts[:,:,:,None]*np.maximum(v,self.floors[None,None,:,None]),axis=2)

    def series(self, current, rows, string, *, raw_slopes=False, clamped=None):
        il,io,rs,rsh,a = self.parameters[rows].transpose(2,0,1)
        v = _module_voltage(current[:,None],il,io,rs,rsh,a)
        conductance = io*np.exp((v+current[:,None]*rs)/a)/a+1./rsh
        slopes = -1./conductance-rs
        curvature = -(conductance-1./rsh)/(a*conductance**3)
        if raw_slopes:
            return v,slopes
        if clamped is None:
            clamped = v<=self.floors
        weights = self.counts[rows,string]
        return (np.sum(weights*np.maximum(v,self.floors),axis=1),
            np.sum(weights*np.where(clamped,0.,slopes),axis=1),
            np.sum(weights*np.where(clamped,0.,curvature),axis=1))

    def string_point(self, voltage, rows, string, *, side=0):
        cap,voc,join = self.cap[rows,string],self.string_voc[rows,string],self.join[rows,string]
        side = np.broadcast_to(np.asarray(side),(len(voltage),))
        on = ((voltage<voc)|((voltage==voc)&(side<0)))&(cap>0)
        plateau = on&((voltage<join)|((voltage==join)&(side<=0)))
        work = on&~plateau
        current = np.where(plateau,cap,0.)
        slope,curvature = np.zeros_like(current),np.zeros_like(current)
        if not work.any():
            return current,slope,curvature
        indices = np.flatnonzero(work)
        rr,target = rows[indices],voltage[indices]
        low_idx,high_idx = np.zeros(len(indices),dtype=int),np.full(len(indices),self.grid_i.shape[2]-1,dtype=int)
        for _ in range(int(np.ceil(np.log2(self.grid_i.shape[2])))+1):
            mid = (low_idx+high_idx)//2
            before = self.grid_v[rr,string,mid]>=target
            low_idx = np.where(before,mid,low_idx)
            high_idx = np.where(before,high_idx,mid)
        lo,hi = self.grid_i[rr,string,low_idx].copy(),self.grid_i[rr,string,high_idx].copy()
        vlo,vhi = self.grid_v[rr,string,low_idx],self.grid_v[rr,string,high_idx]
        x = lo+np.divide(vlo-target,vlo-vhi,out=np.zeros_like(lo),where=vlo!=vhi)*(hi-lo)
        x = np.clip(x,lo,hi)
        uncapped = (self.diodes==0)|(hi[:,None]<=self.isc[rr])|(hi[:,None]<self.knees[rr]-1e-12)
        minimum = np.sum(self.counts[rr,string]*self.minimum_slope[rr]*uncapped,axis=1)
        tolerance = 1e-12+4*EPS*cap[indices]
        pending = np.ones(len(indices),dtype=bool)
        for _ in range(self.maxiter):
            ids = np.flatnonzero(pending)
            if not len(ids):
                break
            v,d,dd = self.series(x[ids],rr[ids],string)
            f = v-target[ids]
            error = np.divide(abs(f),minimum[ids],out=np.full(len(ids),np.inf),where=minimum[ids]>0)
            done = (error<=tolerance[ids])|((hi[ids]-lo[ids])<=tolerance[ids])|(f==0)
            if done.any():
                dest = ids[done]
                # Branch membership comes from voltage relative to the physical
                # knee, not an inverse-current estimate whose error spans it.
                knee_v = self.knee_voltage[rr[dest],string]
                clamp = ((target[dest,None]<knee_v)|((target[dest,None]==knee_v)&(side[indices[dest],None]<0)))&(self.diodes>0)
                _,derivative,second = self.series(x[dest],rr[dest],string,clamped=clamp)
                current[indices[dest]] = x[dest]
                slope[indices[dest]] = 1./derivative
                curvature[indices[dest]] = -second/derivative**3
                pending[dest] = False
            ids2 = ids[~done]
            if not len(ids2):
                continue
            f,d = f[~done],d[~done]
            lo[ids2] = np.where(f>=0,x[ids2],lo[ids2])
            hi[ids2] = np.where(f<0,x[ids2],hi[ids2])
            proposed = x[ids2]-f/d
            safe = np.isfinite(proposed)&(proposed>lo[ids2])&(proposed<hi[ids2])&(proposed!=x[ids2])
            x[ids2] = np.where(safe,proposed,(lo[ids2]+hi[ids2])/2.)
        if pending.any():
            raise _SolverError('mixed-orientation solver did not converge (string current)', rr[pending])
        return current,slope,curvature

    def point(self, voltage, rows=None, *, side=0):
        voltage = np.asarray(voltage,dtype=float)
        shape = voltage.shape
        if rows is None:
            rows = np.broadcast_to(np.arange(self.h).reshape((self.h,)+(1,)*(voltage.ndim-1)),shape).ravel()
        flat = voltage.ravel()
        side = np.broadcast_to(np.asarray(side),shape).ravel()
        total = [np.zeros(len(flat)) for _ in range(3)]
        for string in range(self.s):
            values = self.string_point(flat,rows,string,side=side)
            for i in range(3):total[i] += values[i]*self.multiplicity[string]
        return tuple(v.reshape(shape) for v in total)

    def root(self, function, low, high, rows, *, decreasing=False, xtol=1e-11):
        low,high = np.asarray(low).copy(),np.asarray(high).copy()
        x = (low+high)/2.
        fa,_ = function(low,rows)
        fb,_ = function(high,rows)
        x = np.where(fa==0,low,np.where(fb==0,high,x))
        pending = (fa!=0)&(fb!=0)
        bracketed = ((fa>=0)&(fb<=0)) if decreasing else ((fa<=0)&(fb>=0))
        if np.any(pending&~bracketed):
            raise _SolverError('mixed-orientation solver did not converge (unbracketed root)', rows[pending&~bracketed])
        for _ in range(self.maxiter):
            ids = np.flatnonzero(pending)
            if not len(ids):break
            f,d = function(x[ids],rows[ids])
            tolerance = xtol+4*EPS*abs(x[ids])
            step = np.divide(f,d,out=np.full(len(ids),np.inf),where=d!=0)
            done = (abs(step)<=tolerance)|((high[ids]-low[ids])<=tolerance)|(f==0)
            pending[ids[done]] = False
            ids2 = ids[~done]
            f,step = f[~done],step[~done]
            lower = f>0 if decreasing else f<0
            low[ids2] = np.where(lower,x[ids2],low[ids2])
            high[ids2] = np.where(lower,high[ids2],x[ids2])
            proposed = x[ids2]-step
            safe = np.isfinite(proposed)&(proposed>low[ids2])&(proposed<high[ids2])&(proposed!=x[ids2])
            x[ids2] = np.where(safe,proposed,(low[ids2]+high[ids2])/2.)
        if pending.any():raise _SolverError('mixed-orientation solver did not converge (voltage)', rows[pending])
        return x

    def terminal(self, voltage, rows, k, resistance, *, side=0):
        i,d,dd = self.point(voltage,rows,side=side)
        kk,rr = k[rows],resistance[rows]
        vt,it = voltage-rr*kk*i,kk*i
        den = 1-rr*kk*d
        derivative = it+vt*kk*d/den
        second = 2*kk*d+vt*kk*dd/den**2
        return vt,it,derivative,second

    def bounds(self, voltage, rows, *, side=0):
        ilo,ihi,slo,shi = (np.zeros(len(rows)) for _ in range(4))
        for string in range(self.s):
            current,_,_ = self.string_point(voltage,rows,string,side=side)
            cap,voc,join = self.cap[rows,string],self.string_voc[rows,string],self.join[rows,string]
            on = ((voltage<voc)|((voltage==voc)&(np.asarray(side)<0)))&(cap>0)
            error = 1e-12+4*EPS*cap
            lo,hi = np.maximum(0.,current-error),np.minimum(cap,current+error)
            low_slope,high_slope = np.full(len(rows),np.inf),np.full(len(rows),-np.inf)
            for sample in (lo,hi):
                _,d,_ = self.series(sample,rows,string)
                inverse = np.divide(1.,d,out=np.full(len(rows),np.nan),where=d<0)
                low_slope = np.fmin(low_slope,inverse)
                high_slope = np.fmax(high_slope,inverse)
            for c in range(self.c):
                knee = self.knees[rows,c]
                inside = (lo<=knee)&(knee<=hi)&(self.counts[rows,string,c]>0)
                selected = np.flatnonzero(inside)
                if not len(selected):continue
                for sample in (np.maximum(lo[selected],np.nextafter(knee[selected],-np.inf)),
                               np.minimum(hi[selected],np.nextafter(knee[selected],np.inf))):
                    _,d,_ = self.series(sample,rows[selected],string)
                    inverse = np.divide(1.,d,out=np.full(len(selected),np.nan),where=d<0)
                    low_slope[selected] = np.fmin(low_slope[selected],inverse)
                    high_slope[selected] = np.fmax(high_slope[selected],inverse)
            capped = (voltage<=join)|(hi==cap)
            low_slope = np.where(capped,np.minimum(low_slope,0.),low_slope)
            high_slope = np.where(capped,np.maximum(high_slope,0.),high_slope)
            if np.any(on&(~np.isfinite(low_slope)|~np.isfinite(high_slope))):
                raise _SolverError('mixed-orientation derivative enclosure failed', rows[on&(~np.isfinite(low_slope)|~np.isfinite(high_slope))])
            weight = self.multiplicity[string]
            ilo += weight*np.where(on,lo,0.);ihi += weight*np.where(on,hi,0.)
            slo += weight*np.where(on,low_slope,0.);shi += weight*np.where(on,high_slope,0.)
        return ilo,ihi,slo,shi

    def certified_grid(self, initial):
        # Subdivide at every bypass transition and string Voc. A smooth SDM
        # branch has V''(I)<=0, hence I''(V)<=0 and terminal P''(Vt)<=0.
        if np.array_equal(initial,self.branch_knots):return initial
        return np.sort(np.concatenate((initial,self.branch_knots),axis=1),axis=1)

    def certify_concavity(self,a,b,rows,k,resistance):
        hidden = (self.branch_knots[rows]>a[:,None])&(self.branch_knots[rows]<b[:,None])
        if hidden.any():
            raise _SolverError('uncertifiable non-concave segment: unpartitioned branch transition', rows[hidden.any(axis=1)])
        vt = self.terminal(a,rows,k,resistance)[0]
        midpoint = (a+b)/2.
        _,_,_,second = self.terminal(midpoint,rows,k,resistance)
        if np.any(vt<0) or np.any(~np.isfinite(second)|(second>0)):
            raise _SolverError('uncertifiable non-concave terminal segment', rows[(vt<0)|~np.isfinite(second)|(second>0)])

    def derivative_bounds(self,v,rows,k,resistance,*,side=0):
        ilo,ihi,slo,shi=self.bounds(v,rows,side=side)
        kk,rr=k[rows],resistance[rows]
        vlo,vhi=v-rr*kk*ihi,v-rr*kk*ilo
        return (kk*ilo+np.maximum(0.,vhi)*kk*slo/(1-rr*kk*slo),
                kk*ihi+np.maximum(0.,vlo)*kk*shi/(1-rr*kk*shi))

    def checked_signs(self,left,right,rows,k,resistance):
        # The analytic concavity proof plus enclosed one-sided/midpoint signs
        # rules out an undetected sign reversal between accepted grid points.
        dl=self.terminal(left,rows,k,resistance,side=1)[2]
        dr=self.terminal(right,rows,k,resistance,side=-1)[2]
        middle=(left+right)/2.
        ll,lh=self.derivative_bounds(left,rows,k,resistance,side=1)
        # Adjacent floats can round the midpoint onto either endpoint.
        middle_side=np.where(middle==left,1,np.where(middle==right,-1,0))
        ml,mh=self.derivative_bounds(middle,rows,k,resistance,side=middle_side)
        rl,rh=self.derivative_bounds(right,rows,k,resistance,side=-1)
        if np.any(lh<ml)|np.any(mh<rl):
            raise _SolverError('uncertifiable segment: undetected derivative sign change', rows[(lh<ml)|(mh<rl)])
        return dl,dr

    def certificates(self, a,b,maximum,valid,k,resistance):
        upper = np.full_like(a,-np.inf)
        rows,cols = np.nonzero(valid)
        if not len(rows):return upper
        aa,bb,v = a[rows,cols],b[rows,cols],maximum[rows,cols]
        self.certify_concavity(aa,bb,rows,k,resistance)
        epsilon = np.minimum((bb-aa)/4.,np.maximum(1e-10,self.voc[rows]*1e-12))
        probe = np.clip(v,aa+epsilon,bb-epsilon)
        ilo,ihi,slo,shi = self.bounds(probe,rows)
        kk,rr = k[rows],resistance[rows]
        vtlo,vthi = probe-rr*kk*ihi,probe-rr*kk*ilo
        dlo = kk*ilo+np.maximum(0.,vthi)*kk*slo/(1-rr*kk*slo)
        dhi = kk*ihi+np.maximum(0.,vtlo)*kk*shi/(1-rr*kk*shi)
        pa,pb = self.terminal(aa,rows,k,resistance)[0],self.terminal(bb,rows,k,resistance)[0]
        position = rr*kk*self.physical_strings*(1e-12+4*EPS*self.cap_sum[rows])
        left,right = pa-vthi-position,pb-vtlo+position
        vp,ip,_,_ = self.terminal(probe,rows,k,resistance)
        objective = kk*(self.voc[rows]+2*rr*kk*self.cap_sum[rows])*(ihi-ilo)
        tangent = np.maximum.reduce([np.zeros(len(rows)),dlo*left,dlo*right,dhi*left,dhi*right])
        upper[rows,cols] = vp*ip+objective+tangent
        return upper

    def result(self, knots, maximum, upper, k, resistance, empty, *, parent=None, shortcut=None):
        a,b = knots[:,:-1],knots[:,1:]
        valid = (b>a)&~empty[:,None]&(k[:,None]>0)&(self.voc[:,None]>0)
        rows,cols = np.nonzero(valid)
        voltage,current,power = (np.zeros_like(a) for _ in range(3))
        if len(rows):
            vv,ii,_,_ = self.terminal(maximum[rows,cols],rows,k,resistance)
            voltage[rows,cols],current[rows,cols],power[rows,cols] = vv,ii,np.maximum(0.,vv*ii)
        tolerance = np.maximum(1e-8,k*self.voc*self.cap_sum*1e-10)
        width = valid.shape[1]
        mask = np.zeros_like(valid)
        if len(rows):
            raw = maximum[rows,cols]
            left = self.terminal(raw,rows,k,resistance,side=-1)[2]
            right = self.terminal(raw,rows,k,resistance,side=1)[2]
            interior = (raw>a[rows,cols])&(raw<b[rows,cols])
            at_low, at_high = raw==knots[rows,0], raw==knots[rows,-1]
            # Local one-sided signs reject a monotone join even when adjacent
            # nearly identical knots hide the following segment's larger peak.
            mask[rows,cols] = interior|((at_low|(left>=0))&(at_high|(right<=0)))
        if parent is not None:
            retained = parent['peak_mask']&(maximum==parent['maximum'])
            clipped_low = (maximum==knots[:,0,None])&(parent['maximum']<=knots[:,0,None])
            clipped_high = (maximum==knots[:,-1,None])&(parent['maximum']>=knots[:,-1,None])
            mask |= valid&(retained|clipped_low|clipped_high)
        # Deduplicate shared knots and merge only connected plateaus, in voltage order.
        previous = np.full(self.h,-1,dtype=int)
        knot_v,knot_i,_,_ = self.terminal(knots.ravel(),np.repeat(np.arange(self.h),knots.shape[1]),k,resistance)
        knot_p = (knot_v*knot_i).reshape(knots.shape)
        for col in range(width):
            rr = np.flatnonzero(mask[:,col]&(previous>=0))
            if len(rr):
                pc = previous[rr]
                duplicate = voltage[rr,col]==voltage[rr,pc]
                mask[rr[duplicate],col] = False
                rr = rr[~duplicate];pc = previous[rr]
                equal = abs(power[rr,col]-power[rr,pc])<=tolerance[rr]
                rr,pc = rr[equal],pc[equal]
                if len(rr):
                    midpoint = (voltage[rr,col]+voltage[rr,pc])/2.
                    # The root helper may call a subset, so bind midpoint by hour.
                    mids = np.zeros(self.h);mids[rr] = midpoint
                    def midpoint_fn(v,h):
                        i,d,_ = self.point(v,h)
                        return v-resistance[h]*k[h]*i-mids[h],1-resistance[h]*k[h]*d
                    raw = self.root(midpoint_fn,knots[rr,0],knots[rr,-1],rr)
                    mv,mi,_,_ = self.terminal(raw,rr,k,resistance)
                    inside = (knots[rr]>maximum[rr,pc,None])&(knots[rr]<maximum[rr,col,None])
                    bottom = np.minimum(power[rr,col],power[rr,pc])-tolerance[rr]
                    connected = ((mv*mi)>=bottom)&np.all(~inside|(knot_p[rr]>=bottom[:,None]),axis=1)
                    mask[rr[connected],pc[connected]] = False
            previous = np.where(mask[:,col],col,previous)
        degenerate = ~empty&(k>0)&(self.voc>0)&(knots[:,0]==knots[:,-1])
        rr = np.flatnonzero(degenerate)
        if len(rr):
            vv,ii,_,_ = self.terminal(knots[rr,0],rr,k,resistance)
            voltage[rr,0],current[rr,0],power[rr,0] = vv,ii,np.maximum(0.,vv*ii)
            mask[rr,0] = True
        score = np.where(mask,power,-np.inf)
        best_power = np.maximum(0.,score.max(axis=1))
        tied = mask&(power==best_power[:,None])
        best_col = np.argmax(np.where(tied,voltage,-np.inf),axis=1)
        rr = np.arange(self.h)
        best_v,best_i = voltage[rr,best_col],current[rr,best_col]
        best_raw = maximum[rr,best_col]
        if parent is not None:
            best_raw = np.where(shortcut,parent['raw_voltage_v'],best_raw)
            best_power = np.where(shortcut,parent['power_w'],best_power)
            best_v = np.where(shortcut,parent['voltage_v'],best_v)
            best_i = np.where(shortcut,parent['current_a'],best_i)
        error = np.maximum(0.,np.max(upper,axis=1)-best_power)
        error = np.where(degenerate|empty|(k==0)|(self.voc==0),0.,error)
        if np.any(error>np.maximum(1e-7,best_power*1e-7)) or not np.isfinite(best_power).all():
            bad = np.flatnonzero((error>np.maximum(1e-7,best_power*1e-7))|~np.isfinite(best_power))
            raise _SolverError(f'mixed-orientation error certificate failed: rows {bad[:10]}, errors {error[bad[:10]]}', bad)
        return dict(raw_voltage_v=best_raw,voltage_v=best_v,current_a=best_i,power_w=best_power,peak_voltages=voltage,
            peak_currents=current,peak_powers=power,peak_mask=mask,error_bound_w=error,
            knots=knots,maximum=maximum,upper=upper,empty=empty,k=k,resistance=resistance)

    def envelope(self, *, k=1., resistance_ohm=0., current_limit_a=None, voltage_window=None, raw=None):
        if self.maxiter<1:raise _SolverError('mixed-orientation solver did not converge', np.arange(self.h))
        k=np.broadcast_to(np.asarray(k,dtype=float),(self.h,)).copy()
        resistance=np.broadcast_to(np.asarray(resistance_ohm,dtype=float),(self.h,)).copy()
        if np.any(~np.isfinite(k)|(k<0)|~np.isfinite(resistance)|(resistance<0)):
            raise ValueError('invalid terminal transform')
        low,high=np.zeros(self.h),self.voc.copy()
        rr=np.arange(self.h)
        vt=self.terminal(low,rr,k,resistance)[0]
        bind=(vt<0)&(k>0)&(self.voc>0)
        if bind.any():
            rows=np.flatnonzero(bind)
            def zero(v,h):
                i,d,_=self.point(v,h)
                return v-resistance[h]*k[h]*i,1-resistance[h]*k[h]*d
            low[rows]=self.root(zero,low[rows],high[rows],rows)
        # Keep the feasible boundary on the nonnegative terminal branch.
        vt=self.terminal(low,rr,k,resistance)[0]
        # Two current solves can differ across their certified error intervals.
        position=resistance*k*self.physical_strings*(1e-12+4*EPS*self.cap_sum)
        low=np.where(bind,low+np.maximum(0.,-vt)+2*position+4*EPS*self.voc,low)
        knots=np.clip(self.certified_grid(self.knots),low[:,None],high[:,None])
        a,b=knots[:,:-1],knots[:,1:]
        valid=(b>a)&(k[:,None]>0)&(self.voc[:,None]>0)
        rows,cols=np.nonzero(valid)
        maximum=a.copy()
        if raw is not None:
            maximum[resistance==0]=raw["maximum"][resistance==0]
            rows,cols=np.nonzero(valid&(resistance[:,None]!=0))
        if len(rows):
            left = np.nextafter(a[rows,cols], b[rows,cols])
            right = np.nextafter(b[rows,cols], a[rows,cols])
            interior = left < right
            # Adjacent floats have no representable interior; certify both ends.
            left = np.where(interior, left, a[rows,cols])
            right = np.where(interior, right, b[rows,cols])
            self.certify_concavity(a[rows,cols],b[rows,cols],rows,k,resistance)
            dl,dr=self.checked_signs(left,right,rows,k,resistance)
            maximum[rows,cols]=np.where(dl>=0,b[rows,cols],a[rows,cols])
            narrow = ~interior
            if narrow.any():
                av, ai, _, _ = self.terminal(left[narrow], rows[narrow], k, resistance)
                bv, bi, _, _ = self.terminal(right[narrow], rows[narrow], k, resistance)
                maximum[rows[narrow],cols[narrow]] = np.where(av*ai > bv*bi, left[narrow], right[narrow])
            basin=(dl>0)&(dr<0)&interior
            def derivative(v,h):
                _,_,f,d=self.terminal(v,h,k,resistance)
                return f,d
            if basin.any():maximum[rows[basin],cols[basin]]=self.root(derivative,left[basin],right[basin],rows[basin],decreasing=True)
        solve=valid if raw is None else valid&(resistance[:,None]!=0)
        upper=self.certificates(a,b,maximum,solve,k,resistance)
        if raw is not None:
            zero=resistance==0
            upper[zero]=np.multiply(raw["upper"][zero],k[zero,None],
                out=raw["upper"][zero].copy(),where=k[zero,None]>0)
        result=self.result(knots,maximum,upper,k,resistance,np.zeros(self.h,dtype=bool))
        if current_limit_a is not None:result=self.restrict(result,current_limit_a=current_limit_a)
        if voltage_window is not None:result=self.restrict(result,voltage_window=voltage_window)
        return result

    def restrict(self,parent,*,current_limit_a=None,voltage_window=None):
        k,resistance=parent['k'],parent['resistance']
        low,high=parent['knots'][:,0].copy(),parent['knots'][:,-1].copy()
        empty=parent['empty'].copy();rr=np.arange(self.h)
        shortcut=np.ones(self.h,dtype=bool)
        eligible=parent['peak_mask'].copy()
        if current_limit_a is not None:
            limit=np.broadcast_to(np.asarray(current_limit_a,dtype=float),(self.h,))
            if np.any(~np.isfinite(limit)|(limit<0)):raise ValueError('invalid MPPT current limit')
            bind=(self.terminal(low,rr,k,resistance)[1]>limit)&~empty
            rows=np.flatnonzero(bind)
            if len(rows):
                def current(v,h):
                    i,d,_=self.point(v,h)
                    return k[h]*i-limit[h],k[h]*d
                low[rows]=self.root(current,low[rows],high[rows],rows,decreasing=True)
            shortcut &= parent['current_a']<=limit
            eligible &= parent['peak_currents']<=limit[:,None]
            known_low=np.min(np.where(eligible,parent['maximum'],np.inf),axis=1)
            low=np.minimum(low,known_low)
            low = np.where(shortcut, np.minimum(low,parent['raw_voltage_v']), low)
        if voltage_window is not None:
            vmin,vmax=(np.broadcast_to(np.asarray(v,dtype=float),(self.h,)) for v in voltage_window)
            if np.any(~np.isfinite(vmin)|~np.isfinite(vmax)|(vmin<0)|(vmin>vmax)):raise ValueError('invalid MPPT voltage window')
            lv,hv=self.terminal(low,rr,k,resistance)[0],self.terminal(high,rr,k,resistance)[0]
            inside = (parent['voltage_v']>=vmin)&(parent['voltage_v']<=vmax)&~parent['empty']&shortcut
            eligible &= (parent['peak_voltages']>=vmin[:,None])&(parent['peak_voltages']<=vmax[:,None])
            known_low=np.min(np.where(eligible,parent['maximum'],np.inf),axis=1)
            known_high=np.max(np.where(eligible,parent['maximum'],-np.inf),axis=1)
            empty |= ((vmin>hv)|(vmax<lv))&~(inside|eligible.any(axis=1))
            for target,lower,bind in ((vmin,True,(lv<vmin)&~empty),(vmax,False,(hv>vmax)&~empty)):
                rows=np.flatnonzero(bind)
                if len(rows):
                    def boundary(v,h):
                        i,d,_=self.point(v,h)
                        return v-resistance[h]*k[h]*i-target[h],1-resistance[h]*k[h]*d
                    root=self.root(boundary,low[rows],high[rows],rows)
                    if lower:
                        low[rows]=root
                        low=np.minimum(low,known_low)
                        low=np.where(inside,np.minimum(low,parent['raw_voltage_v']),low)
                    else:
                        high[rows]=root
                        high=np.maximum(high,known_high)
            low = np.where(inside, np.minimum(low,parent['raw_voltage_v']), low)
            high = np.where(inside, np.maximum(high,parent['raw_voltage_v']), high)
            shortcut &= inside
        knots=np.clip(parent['knots'],low[:,None],high[:,None])
        maximum=np.clip(parent['maximum'],knots[:,:-1],knots[:,1:])
        valid=(knots[:,1:]>knots[:,:-1])&~empty[:,None]&(k[:,None]>0)&(self.voc[:,None]>0)
        changed=valid&((knots[:,:-1]!=parent['knots'][:,:-1])|(knots[:,1:]!=parent['knots'][:,1:]))
        upper=np.where(valid,parent['upper'],-np.inf).copy()
        revised=self.certificates(knots[:,:-1],knots[:,1:],maximum,changed,k,resistance)
        upper=np.where(changed,revised,upper)
        return self.result(knots,maximum,upper,k,resistance,empty,parent=parent,shortcut=shortcut&~empty)

    def nested(self,*,k=1.,resistance_ohm=0.,current_limit_a=None,voltage_window=None,raw=None):
        raw=self.envelope() if raw is None else raw
        kk=np.broadcast_to(np.asarray(k,dtype=float),(self.h,))
        resistance=np.broadcast_to(np.asarray(resistance_ohm,dtype=float),(self.h,))
        if np.any(~np.isfinite(kk)|(kk<0)|~np.isfinite(resistance)|(resistance<0)):
            raise ValueError('invalid terminal transform')
        zero=resistance==0
        if zero.any():
            scaled={name:values.copy() if isinstance(values,np.ndarray) else values for name,values in raw.items()}
            for name in ('current_a','power_w','peak_currents','peak_powers','error_bound_w','upper'):
                factor=kk.reshape((-1,)+(1,)*(scaled[name].ndim-1))
                scaled[name]=np.multiply(scaled[name],factor,out=scaled[name].copy(),where=factor>0)
                if name=='upper':scaled[name][kk==0]=np.where(np.isfinite(raw[name][kk==0]),0.,-np.inf)
                else:scaled[name][kk==0]=0.
            scaled['k'],scaled['resistance']=kk,resistance
            scaled['voltage_v'][kk==0]=0.
            scaled['raw_voltage_v'][kk==0]=0.
            scaled['peak_mask'][kk==0]=False
        wired=scaled if zero.all() else self.envelope(k=kk,resistance_ohm=resistance,raw=raw)
        if zero.any() and not zero.all():
            for name in wired:
                if isinstance(wired[name],np.ndarray):wired[name][zero]=scaled[name][zero]
        wi=self.restrict(wired,current_limit_a=current_limit_a) if current_limit_a is not None else wired
        wiv=self.restrict(wi,voltage_window=voltage_window) if voltage_window is not None else wi
        return dict(raw=raw,w0=wired,wi=wi,wiv=wiv,voc_v=self.voc)


def class_parameters(dc, definition):
    """Fill only the mixed class's inactive SDM rows at their real irradiance/Tc."""
    from components.pan.pvsyst_sdm import calculate_pvsyst_diode_parameters
    from engine.module.pvsyst import SDM_COLUMNS
    from .unshaded import _module_runtime_properties
    frame = dc.coupled_module.electrical.frame
    values = frame[list(SDM_COLUMNS)].to_numpy(dtype=float).copy()
    inactive = ~frame["active"].to_numpy(dtype=bool)
    if inactive.any():
        parameter_set = _module_runtime_properties(definition)[0]
        params = calculate_pvsyst_diode_parameters(
            effective_irradiance_w_m2=dc.optical.frame["effective_irradiance_w_m2"].to_numpy()[inactive],
            cell_temperature_c=dc.coupled_module.thermal.frame["cell_temperature_c"].to_numpy()[inactive],
            parameter_set=parameter_set)
        for c, data in enumerate(params):
            values[inactive,c] = np.broadcast_to(np.asarray(data,dtype=float), (int(inactive.sum()),))
    return values


def _product_error(exc, mppt, index):
    rows = np.unique(getattr(exc, 'rows', np.arange(len(index))))
    time = index[int(rows[0])].isoformat()
    others = f' (and {len(rows)-1} other intervals)' if len(rows)>1 else ''
    return ValueError(
        f"Mixed-orientation simulation could not be solved for MPPT {mppt['mppt_index']} "
        f"({mppt['mppt_instance_id']}) on inverter {mppt['inverter_instance_id']} "
        f"at {time}{others}: {exc}"
    )


def _product_solve(action, mppt, index):
    try:
        return action()
    except RuntimeError as exc:
        raise _product_error(exc, mppt, index) from exc


def build_mixed_arrays(units, physical_mppts, context):
    """One physical circuit per mixed MPPT; class rows are optical attribution only."""
    from electrical.mppt import MPPTAggregationResult
    from engine.inverter.model import _mppt_limits
    from engine.losses.array import ArrayLossResult, apply_pre_inverter_array_losses
    from engine.losses.staged import apply_circuit_losses
    from .unshaded import _loss_chain_options
    from dataclasses import replace
    import pandas as pd

    parameters = {key: class_parameters(u.dc,u.config.module_definition) for key,u in units.items()}
    basis = {key: bypass_basis(u.config.module_definition) for key,u in units.items()}
    index = context.temporal.timeline.frame.index
    durations = context.temporal.timeline.frame["duration_seconds"].to_numpy()/3600.
    outputs, diagnostics = [], []
    # Identical compositions on several physical MPPTs share exact array solves.
    curve_cache = {}
    for mppt in physical_mppts:
        class_ids = list(dict.fromkeys(c for s in mppt["strings"] for c in s["composition"]))
        selected = units[class_ids[0]]
        config = selected.config
        key = int(mppt["mppt_index"])
        assignments = {key: tuple(s["string_id"] for s in mppt["strings"])}
        circuit_config = replace(config, modules_in_series=mppt["modules_in_series"],
                                 string_ids=assignments[key], mppt_assignments=assignments)
        options = _loss_chain_options(circuit_config)
        reference = options.get("circuit_references", {}).get(key)
        resistance = reference["resistance_ohm"] if reference is not None else config.dc_array_resistance_ohm
        limits = _mppt_limits(config.inverter_definition,key)
        counts = {c: sum(s["composition"].get(c,0) for s in mppt["strings"]) for c in class_ids}
        independent = sum(units[c].dc.coupled_module.electrical.frame["pmp_w"].to_numpy()*counts[c] for c in class_ids)
        active = np.logical_or.reduce([units[c].dc.coupled_module.electrical.frame["active"].to_numpy() for c in class_ids])
        raw, raw_v, raw_i, voc, isc = (np.zeros(len(index)) for _ in range(5))
        compositions = [s["composition"] for s in mppt["strings"]]
        composition_key = tuple(tuple(sorted(c.items())) for c in compositions)
        if active.any():
            if composition_key not in curve_cache:
                batch = _product_solve(lambda: BatchCurves(np.stack([parameters[c][active] for c in class_ids], axis=1),
                    [[row.get(c, 0) for c in class_ids] for row in compositions],
                    [basis[c]["diode_count"] for c in class_ids],
                    [basis[c]["forward_voltage_v"] for c in class_ids]), mppt, index[active])
                result = _product_solve(batch.envelope, mppt, index[active])
                short = _product_solve(lambda: batch.point(np.zeros(batch.h))[0], mppt, index[active])
                curve_cache[composition_key] = batch, result, short, {}
            batch, result, short_current, cache = curve_cache[composition_key]
            raw[active], raw_v[active], raw_i[active] = result["power_w"], result["voltage_v"], result["current_a"]
            voc[active], isc[active] = batch.voc, short_current
        if np.any(raw > independent+1e-6):
            raise _product_error(_SolverError("mixed MPPT exceeds the independent module MPP bound", np.flatnonzero(raw>independent+1e-6)), mppt, index)
        raw_frame = pd.DataFrame({"mppt_pmp_w":raw,"mppt_vmp_v":raw_v,"mppt_imp_a":raw_i,
                                  "mppt_voc_v":voc,"mppt_isc_a":isc,"active":active},index=index)
        item = MPPTAggregationResult(key,assignments[key],raw_frame,{"model_id":MODEL_ID})
        if config.loss_settings is None:
            scalar = apply_pre_inverter_array_losses({key:item},
                module_quality_loss_fraction=selected.dc.module_runtime.module_quality_loss_fraction,
                module_mismatch_loss_fraction=config.module_mismatch_loss_fraction,
                string_mismatch_loss_fraction=config.string_mismatch_loss_fraction)
        else:
            scalar = apply_circuit_losses({key:item},config.loss_settings,
                {key:{**reference,"resistance_ohm":0.}},quality=selected.dc.module_runtime.module_quality_loss_fraction)
        power = scalar.frame["before_dc_wiring_w"].to_numpy()
        k = np.divide(power,raw,out=np.zeros_like(raw),where=raw>0)
        w0, wi, wiv, v0, i0, vf, it = (np.zeros(len(index)) for _ in range(7))
        multi = np.zeros(len(index),dtype=bool)
        gaps = {name:np.zeros(len(index)) for name in ("simple_tracker","second_highest","lowest")}
        if active.any():
            transform = (k[active].tobytes(), float(resistance), limits["max_current"],
                         limits["min_voltage"], limits["max_voltage"])
            if transform not in cache:
                cache[transform] = _product_solve(lambda: batch.nested(k=k[active], resistance_ohm=resistance,
                    current_limit_a=limits["max_current"], voltage_window=(limits["min_voltage"],limits["max_voltage"]),
                    raw=result), mppt, index[active])
            solved = cache[transform]
            a, b, c = (solved[name] for name in ("w0", "wi", "wiv"))
            w0[active], wi[active], wiv[active] = a["power_w"], b["power_w"], c["power_w"]
            v0[active], i0[active], vf[active], it[active] = a["voltage_v"], a["current_a"], c["voltage_v"], c["current_a"]
            mask, peaks = c["peak_mask"], c["peak_powers"]
            multiple = (mask.sum(axis=1)>1)&(c["power_w"]>0)
            multi[active] = multiple
            ordered = np.sort(np.where(mask, peaks, -np.inf), axis=1)
            highest_voltage = np.argmax(np.where(mask, c["peak_voltages"], -np.inf), axis=1)
            simple = peaks[np.arange(batch.h), highest_voltage]
            lowest = np.min(np.where(mask, peaks, np.inf), axis=1)
            for name, lower in (("simple_tracker", simple), ("second_highest", ordered[:,-2]), ("lowest", lowest)):
                gaps[name][active] = np.where(multiple, c["power_w"]-lower, 0.)
        if np.any(w0>power+1e-6) or np.any(wi>w0+1e-6) or np.any(wiv>wi+1e-6):
            raise _product_error(_SolverError("mixed terminal envelopes are not nested", np.flatnonzero((w0>power+1e-6)|(wi>w0+1e-6)|(wiv>wi+1e-6))), mppt, index)
        frame = scalar.frame.copy()
        frame["raw_array_mpp_w"] = independent
        frame["orientation_mismatch_loss_w"] = np.maximum(0.,independent-raw)
        frame["after_orientation_mismatch_w"] = raw
        frame["dc_wiring_loss_w"] = power-w0
        frame["array_virtual_mpp_w"] = w0
        wired = raw_frame.copy()
        wired["mppt_pmp_w"], wired["mppt_vmp_v"], wired["mppt_imp_a"] = w0,v0,i0
        envelopes = pd.DataFrame({"w0":w0,"wi":wi,"wiv":wiv,"voltage_v":vf,"current_a":it},index=index)
        metadata = {"model_id":MODEL_ID,"mixed_terminal_envelopes":envelopes,
                    "terminal_limits":limits,"dc_wiring_basis":"nested_terminal_envelope_difference"}
        wired_item = MPPTAggregationResult(key,item.string_ids,wired,metadata)
        circuits = {str(key):{**reference,"loss_attribution_basis":"nested_terminal_envelope_difference"}} if reference is not None else {}
        outputs.append(ArrayLossResult({key:wired_item},frame,{"circuits":circuits,"dc_wiring_basis":"nested_terminal_envelope_difference"}))
        diagnostics.append({"inverter_instance_id":mppt["inverter_instance_id"],"mppt_instance_id":mppt["mppt_instance_id"],
            "multi_peak_interval_count":int(multi.sum()), "multi_peak_duration_hours":float(durations[multi].sum()),
            "energy_gaps_wh":{name:float(np.dot(values,durations)) for name,values in gaps.items()},
            "multi_peak_mask":multi,
            "breakdown":{**mppt,"raw_dc_energy_wh":float(np.dot(independent,durations)),
                "combined_dc_energy_wh":float(np.dot(raw,durations)),
                "post_array_loss_dc_energy_wh":float(np.dot(w0,durations)),
                "dc_loss_energy_wh":{c:float(np.dot(frame[c],durations)) for c in frame if c.endswith("_loss_w")}}})
    return outputs, diagnostics


def run_record(plan, units, diagnostics, context):
    import pandas as pd
    timeline = context.temporal.timeline.frame
    durations = timeline["duration_seconds"].to_numpy()/3600.
    mask = np.logical_or.reduce([d["multi_peak_mask"] for d in diagnostics])
    start, end = timeline.index[0], timeline["interval_end"].iloc[-1]
    complete = (start==pd.Timestamp(year=start.year,month=1,day=1,tz=start.tz)
        and end==start+pd.DateOffset(years=1)
        and np.isclose(durations.sum(),(end-start).total_seconds()/3600.,rtol=0,atol=1e-9)
        and all(timeline["interval_end"].iloc[:-1].to_numpy()==timeline.index[1:].to_numpy()))
    rows = [{k:v for k,v in d.items() if k not in {"multi_peak_mask","breakdown"}} for d in diagnostics]
    return {"model_id":MODEL_ID,"scope_label":"Mixed orientation simulated — beyond what PVsyst/HelioScope simulate",
        "shading_basis":"orientation_class_average","tracker_basis":"ideal_global_mpp",
        "dc_wiring_basis":"nested_terminal_envelope_difference",
        "mixed_string_ids":[s["string_id"] for m in plan["mixed_orientation"]["mppts"] for s in m["strings"] if len(s["composition"])>1],
        "mixed_mppt_instance_ids":[m["mppt_instance_id"] for m in plan["mixed_orientation"]["mppts"]],
        "bypass_basis_by_module_revision":{u.config.module_definition["revision_id"]:bypass_basis(u.config.module_definition) for u in units.values()},
        "mppts":rows,"period_totals":{"start_time":start.isoformat(),"end_time":end.isoformat(),
            "duration_hours":float(durations.sum()),"multi_peak_interval_count":int(mask.sum()),
            "multi_peak_duration_hours":float(durations[mask].sum()),
            "multi_peak_mppt_interval_count":sum(d["multi_peak_interval_count"] for d in rows),
            "multi_peak_mppt_duration_hours":sum(d["multi_peak_duration_hours"] for d in rows),
            "energy_gaps_wh":{name:sum(d["energy_gaps_wh"][name] for d in rows) for name in ("simple_tracker","second_highest","lowest")}},
        "is_complete_year":bool(complete)}
