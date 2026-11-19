# OpenSIMPV — Phase 4.9A Unshaded Reference Matrix

**Status:** External-oracle ingestion tranche  
**Date:** 2026-09-24  
**Parent:** Phase 4.9 Reference Projects and UX Hardening  
**Source software:** PVsyst 8.1.6

## 1. Scope

Phase 4.9A freezes nine user-supplied unshaded hourly PVsyst exports before the shaded reference set is available.

This tranche does **not** close Phase 4.9.

The nine cases expand the external reference matrix across:

- two-orientation / one-inverter systems;
- multi-orientation / one-inverter systems;
- multi-orientation / four-inverter scaling;
- four DC/AC loading levels;
- one semantic ground-support reference.

All cases deliberately have no PVsyst 3-D scene.

## 2. Common source identity

Every source CSV reports:

~~~text
PVsyst version: 8.1.6
Project: Sampel for OpenSimPV_Project_Var2.PRJ
Site: Home_MN90.SIT
Weather: Home_MN90_SYN_1MIN.MET
Weather description: Home; Meteonorm 9.0 dll, Sat=100%; Synthetic
Simulation: hourly
Rows: 8760
~~~

The accepted Phase-3 component/site baseline is reused:

~~~text
latitude:  -6.4245°
longitude: 106.8307°
elevation: 82 m
timezone:  UTC+07:00

module: JKM550M-72HL4-V, 550 W
modules/string baseline: 18

inverter: SUN2000-100KTL-M1
nominal AC: 100 kW
~~~

No new weather, site, module or inverter identity is introduced by 4.9A.

## 3. Case matrix

| Case | User-declared family | Modules | Strings @ 18 modules | Inverters | DC kWp | Nominal AC kW | DC/AC |
|---|---|---:|---:|---:|---:|---:|---:|
| VC0 | 2 orientations, 1 inverter | 216 | 12 | 1 | 118.8 | 100 | 1.188 |
| VC1 | 2 orientations, 1 inverter | 252 | 14 | 1 | 138.6 | 100 | 1.386 |
| VC2 | 2 orientations, 1 inverter | 288 | 16 | 1 | 158.4 | 100 | 1.584 |
| VC3 | 2 orientations, 1 inverter | 324 | 18 | 1 | 178.2 | 100 | 1.782 |
| VC4 | multi-orientation, 1 inverter | 216 | 12 | 1 | 118.8 | 100 | 1.188 |
| VC5 | multi-orientation, 1 inverter | 252 | 14 | 1 | 138.6 | 100 | 1.386 |
| VC6 | multi-orientation, 1 inverter | 288 | 16 | 1 | 158.4 | 100 | 1.584 |
| VC7 | multi-orientation, 1 inverter | 324 | 18 | 1 | 178.2 | 100 | 1.782 |
| VC8 | multi-orientation, 4 inverters; ground semantic | 864 | 48 | 4 | 475.2 | 400 | 1.188 |

The size ladder is a **derived reconstruction** from the already-frozen Phase-3 component baseline plus source energy scaling. It is not presented as a field read directly from the detailed CSV.

## 4. Common weather check

All nine CSVs have identical hourly:

~~~text
GlobHor
DiffHor
T_Amb
WindVel
HSol
AzSol
~~~

Annual horizontal weather is:

~~~text
GlobHor = 1749.8706369 kWh/m²
DiffHor =  860.1768670 kWh/m²
BeamHor =  889.6933902 kWh/m²
~~~

This makes the matrix suitable for isolating orientation/topology/loading changes rather than weather changes.

## 5. Two-orientation ladder: VC0–VC3

VC0–VC3 have identical aggregate POA histories for a given timestamp and expose an additional PVsyst source column:

~~~text
MixLoss
~~~

The parser now treats MixLoss as an explicit positive array-loss channel in the EArrMPP reconciliation:

~~~text
EArrMPP
=
EArrNom
- GIncLss
- TempLss
- ModQual
- MisLoss
- MixLoss
- OhmLoss
~~~

where the existing PVsyst signed-loss convention for ModQual is retained.

The observed maximum source-rounding residual after including MixLoss is below 0.016 kW, so this external source family records a 0.02 kW balance tolerance. The global parser default is not weakened.

## 6. Multi-orientation ladder: VC4–VC7

VC4–VC7 are user-declared multi-orientation / one-inverter cases using the same weather and component baseline.

The aggregate detailed CSV does not expose:

~~~text
orientation count
individual tilt values
individual azimuth values
modules per orientation
strings per orientation
String → MPPT assignment
~~~

These are therefore **not reconstructed by inference**.

The ladder is also not a perfectly pure DC/AC-ratio isolation. Annual GlobInc varies from 1691.4987080 to 1692.8271174 kWh/m² across VC4–VC7, a range of 1.3284094 kWh/m². The aggregate orientation weighting therefore changes slightly as capacity is added. Later attribution must not assign every inter-case energy difference to inverter loading/clipping.

The cases are source-verified performance oracles now, but exact canonical Phase-4 project reconstruction remains pending those design metadata.

## 7. VC8 ground semantic and multi-inverter case

VC8 is assigned the Phase-4.9 ground-support role requested by the user.

For this no-shading tranche, the rooftop-versus-ground distinction is intentionally not treated as a separate PV yield model. With equivalent orientation and thermal assumptions, support type itself adds no numerical scene effect here.

Therefore VC8 has two uses:

~~~text
OpenSIMPV Scene role:
exercise a ground support surface instead of roof support

Electrical/reference role:
multi-orientation
four inverters
low DC/AC ratio
~~~

It is **not** claimed that the CSV proves ground and roof are universally physically identical. No 3-D scene or structural/thermal mounting distinction is present in this source set.

## 8. VC4 ↔ VC8 controlled scaling result

VC4 and VC8 provide a particularly clean isolation.

Their aggregate irradiance is identical:

~~~text
VC4 GlobInc = VC8 GlobInc
VC4 GlobEff = VC8 GlobEff
~~~

VC8 is approximately four times VC4 on the array side:

~~~text
VC8 EArrMPP      = 711342.2077 kWh
4 × VC4 EArrMPP = 711342.2072 kWh
difference       ≈ +0.0005 kWh
~~~

The relation breaks only after the array virtual-MPP boundary.

One-inverter VC4:

~~~text
IL_Pmax = 5013.5680 kWh
ILPmxSH = 1075.3836 kWh
E_Grid  = 169365.8941 kWh
~~~

Four-inverter VC8:

~~~text
IL_Pmax =   11.1850 kWh
ILPmxSH =  234.6169 kWh
E_Grid  = 701350.1026 kWh
~~~

Compared with four independent copies of VC4, VC8 gains approximately +23886.5262 kWh grid energy, or +3.526%.

The primary controlled difference is therefore inverter operating-point/clipping capacity, not array-side irradiance/module physics.

This makes VC8 a useful future multi-inverter execution benchmark.

## 9. Current numerical-engine scope boundary

The current Phase-4.8 numerical execution scope remains:

~~~text
fixed_tilt_unshaded_homogeneous_single_inverter.v0.1
~~~

Therefore these new references must not be silently flattened.

~~~text
VC0–VC3:
two orientations
→ outside current homogeneous-orientation execution scope

VC4–VC7:
multi-orientation
→ outside current homogeneous-orientation execution scope

VC8:
multi-orientation + four inverters
→ outside current homogeneous-orientation and single-inverter scope
~~~

These cases are still useful immediately for external-oracle freezing, canonical project reconstruction once exact design metadata is known, save/reload invariants, design validation, explicit unsupported-scope behavior, and later numerical-engine expansion.

## 10. Frozen source targets

The machine-readable manifest is:

~~~text
tests/benchmarks/phase49a_unshaded_reference_matrix_20260924.yaml
~~~

It freezes for every case:

- source filename;
- SHA-256;
- byte size;
- row/column count;
- simulation date;
- family classification;
- reconstructed nominal sizing;
- source channel availability;
- annual irradiance/array/inverter/grid targets;
- monthly EArrMPP;
- monthly E_Grid.

Uploaded source CSVs remain external and are not redistributed.

## 11. Design facts still required

The aggregate CSV is insufficient to reconstruct these values uniquely:

~~~text
exact tilt per orientation
exact azimuth per orientation
module allocation per orientation
string allocation per orientation
String → MPPT mapping

for VC8:
inverter allocation by orientation/string
~~~

The hourly aggregate incidence/irradiance series cannot uniquely recover that engineering topology.

OpenSIMPV therefore records these values as unresolved rather than guessing them.

The upcoming shaded package may supply part or all of this information through SHD/DAE/project design context.

## 12. 4.9A acceptance boundary

4.9A is complete when:

1. all nine raw sources are fingerprinted;
2. common weather/site/component provenance is tied back to the accepted Phase-3 baseline;
3. annual and monthly source targets are frozen;
4. MixLoss is explicitly represented in detailed-output attribution;
5. VC4/VC8 array-side scaling and inverter-side divergence are regression-tested;
6. missing orientation/topology data remains explicit;
7. the repository regression suite passes.

It does not close full Phase 4.9.

## 13. Next tranche

The next tranche is expected to be the shaded reference family supplied by the user.

That tranche should add, where available:

~~~text
DAE
SHD
PVsyst detailed simulation CSV
exact shaded-scene geometry context
orientation/topology metadata
~~~

Phase-4.9 closure will then combine:

~~~text
unshaded matrix
+
shaded geometry cases
+
canonical save/reload/rerun projects
~~~
