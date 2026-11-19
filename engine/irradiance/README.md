# Irradiance completion and plane-of-array transposition


Phase 3.2 implements two explicit numerical layers:


```text
canonical GHI / DNI / DHI
        ↓
interval-aware component completion
        ↓
unshaded POA transposition
```


## Irradiance completion


RawiBumi never synthesizes GHI in this layer.


When only one of DNI/DHI is missing, the engine first uses the horizontal irradiance
identity where numerically stable:


```text
GHI = DNI · cos(zenith) + DHI
```


DHI can be derived directly whenever DNI is known. DNI derivation is allowed only when
`cos(zenith)` exceeds the configured low-sun threshold.


At low sun, missing DNI is set to zero rather than dividing by a vanishing cosine. When both
DNI and DHI are missing at low sun, the interval becomes diffuse-only:


```text
DNI = 0
DHI = GHI
```


Daytime intervals with both components missing require an explicit decomposition model.
No model is silently selected.


Supported Phase-3.2 decomposition model IDs:


```text
irradiance.decomposition.erbs.pvlib.v0.1
irradiance.decomposition.disc.pvlib.v0.1
irradiance.decomposition.dirint.pvlib.v0.1
```


Source DNI/DHI values are never overwritten. Every interval records the method used for each
component.


## Plane-of-array transposition


Supported transposition model IDs:


```text
poa.transposition.isotropic.pvlib.v0.1
poa.transposition.haydavies.pvlib.v0.1
poa.transposition.perez.pvlib.v0.1
poa.transposition.perez_driesse.pvlib.v0.1
poa.transposition.pvsyst81_perez.v0.1
```


`model_id` is mandatory so the engine never chooses a transposition method by convenience.


## PVsyst 8.1 Perez compatibility boundary


`poa.transposition.pvsyst81_perez.v0.1` is deliberately separate from
ordinary pvlib Perez and Perez-Driesse.


For a 60-minute simulation, PVsyst 8.1 retains the Perez-1990 hourly basis.
RawiBumi therefore uses the `allsitescomposite1990` coefficient family and
then applies the PVsyst low-sun rule.


For sub-hourly simulation, PVsyst 8.1 uses a different 48-coefficient table for
each supported integer divisor of 60 minutes. PVsyst documents the existence,
shape, fitting purpose, and timestep dependence of these tables, but its current
public help does not publish the production numeric tables.


RawiBumi therefore fails closed for sub-hourly PVsyst compatibility unless an
explicit `PerezCoefficientSet` is supplied. The set carries:


```text
coefficient_set_id
timestep_seconds
8 x 6 Perez coefficient table
source_reference
pvsyst81_production_verified
```


A table whose timestep does not match the simulation is rejected. A table not
verified as the PVsyst 8.1 production set is rejected by default. It may be run
only behind an explicit diagnostic override, and the result metadata then says
that coefficient parity is unverified.


The public EUPVSEC 2023 one-minute coefficient table is not silently promoted to
the PVsyst 8.1 production table because PVsyst states that the production refit
was later performed using a larger 113-site dataset and generated a separate
table for each timestep.


### Low-sun handling


PVsyst applies the following transposition cutoff:


```text
HSol < 2 degrees:
    BeamInc = 0
    CircInc = 0
```


RawiBumi applies that rule only in the named PVsyst-8.1 compatibility path.
The cutoff uses true/geometric solar elevation, consistent with PVsyst's HSol
geometry definition. Isotropic diffuse, horizon diffuse, and ground-reflected
irradiance remain active and the POA component ledger is reconciled after the
cutoff.


The cutoff is strict: exactly 2 degrees is not cut off.


Perez-Driesse remains a useful RawiBumi alternative model, but is never labeled
as a PVsyst-compatible path.


The result preserves:


```text
AOI
extraterrestrial DNI
relative air mass


POA beam
POA sky diffuse
POA ground diffuse
POA diffuse
POA global
```


For Hay-Davies, Perez, and Perez-Driesse, the engine also exposes sky-diffuse subcomponents
available in pvlib 0.15.2:


```text
POA isotropic
POA circumsolar
POA horizon
```


This is required for later component-specific optical treatment in Phase 3.3.


Phase 3.2 is strictly unshaded:


```text
beam shading factor    = 1
diffuse shading factor = 1
ground shading factor  = 1
```


and all POA outputs use the RawiBumi canonical azimuth convention:


```text
0° North
90° East
180° South
270° West
```