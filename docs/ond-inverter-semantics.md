# OND inverter semantics v0.1


This document records the first evidence-backed expansion of RawiBumi's OND adapter using
the redistributable manufacturer-supplied Huawei SUN2000-100KTL-M1 OND fixture.


The goal is not to mirror PVsyst field names in the canonical schema. Each OND field is
translated only when its engineering meaning is supported by PVsyst documentation,
manufacturer evidence, or an independently implemented OND importer.


## Huawei anchor


The fixture contains:


```text
PNomConv=100.000
PMaxOUT=110.000
VOutConv=380.0
VMppMin=200
VMPPMax=1000
VmppNom=1000.0
VAbsMax=1100
PSeuil=500.0


PNomDC=130.000
PMaxDC=130.000
IDCMax=0.0
IMaxDC=40.0


INomAC=152.0
IMaxAC=168.8


EfficMax=98.97
EfficEuro=98.82


TPNom=40.0
TPMax=30.0
TPLim1=60.0
TPLimAbs=62.0
PLim1=36.000


VNomEff=200.0,650.0,1000.0
ProfilPIOV1 ...
ProfilPIOV2 ...
ProfilPIOV3 ...


NbInputs=20
NbMPPT=10
Night_Loss=2.00
```


Huawei's current public SUN2000-100KTL-M1 datasheet independently confirms the major AC,
voltage, and topology values: 100 kW nominal active power, 110 kW maximum active power,
1100 V maximum input voltage, 200–1000 V MPPT range, 10 MPPTs, 20 inputs, 152.0 A rated
output current at 380 V, and 168.8 A maximum output current at 380 V.


## Canonical mapping


The following OND semantics are now mapped:


| OND field | Canonical field | Interpretation |
| --- | --- | --- |
| `PNomConv` | `ac_limits.nominal_ac_power_w` | continuous nominal AC active power |
| `PMaxOUT` | `ac_limits.max_ac_power_w` | conditional maximum AC active power |
| `VOutConv` | `ac_limits.nominal_ac_voltage_v` | configured nominal AC voltage |
| `INomAC` | `ac_limits.nominal_ac_current_a` | nominal AC current |
| `IMaxAC` | `ac_limits.max_ac_current_a` | maximum AC current |
| `PNomDC` | `array_sizing_limits.nominal_pv_array_power_w` | recommended PV-array STC power |
| `PMaxDC` | `array_sizing_limits.max_pv_array_power_w` | maximum contractual PV-array STC power |
| `IMaxDC` | `array_sizing_limits.max_pv_current_a` | contractual PV-current field; not a physical operating-current limit |
| `EfficMax` | efficiency reference metric | maximum-efficiency summary |
| `EfficEuro` | efficiency reference metric | European weighted-efficiency summary |
| `Night_Loss` | `operating_thresholds.night_loss_w` | night self-consumption/loss |
| `TPMax` | temperature derating model | temperature up to which PMax is available |
| `TPNom` | temperature derating model | temperature at which available power reaches PNom |
| `TPLim1`, `PLim1` | temperature derating model | high-temperature power breakpoint |
| `TPLimAbs` | temperature derating model | absolute high-temperature threshold |


The existing mappings for MPPT range, absolute DC voltage, phase, MPPT count, input count,
and minimum input-power threshold remain unchanged.


## Voltage-dependent efficiency curves


PVsyst documents an inverter efficiency model based on up to three transfer curves at three
DC input voltages. During simulation it interpolates between the voltage-specific curves.


The Huawei OND provides three voltage anchors:


```text
200 V
650 V
1000 V
```


and three `ProfilPIOV1/2/3` profiles. CASSYS's open OND importer independently interprets
each `Point_i` pair as:


```text
Pin, Pout
```


and computes efficiency as `Pout / Pin`.


RawiBumi therefore assembles each profile into:


```text
dc_voltage_v
points:
  dc_power_w
  ac_power_w
  efficiency_fraction
```


Only `Point_1 ... Point_NPtsEff` are used. Trailing zero placeholders are preserved by the
raw parser/mapping record but excluded from the canonical active curve.


The first Huawei point is `500 W -> 0 W`; zero efficiency at a startup/threshold point is
valid in a transfer curve and is therefore not rejected by engineering validation.


## Important current-limit distinction


The Huawei datasheet distinguishes:


```text
maximum operating current per MPPT = 26 A
maximum short-circuit current per MPPT = 40 A
```


The supplied OND contains:


```text
IDCMax=0.0
IMaxDC=40.0
```


PVsyst documentation treats its PV-current field as a contractual/sizing condition, often
associated with array Isc, while physical MPPT operating-current limitation is a separate
concept. Therefore RawiBumi does **not** reinterpret `IMaxDC=40 A` as the missing
26 A MPPT operating-current limit.


For v0.1:


- `IMaxDC` is stored only under `array_sizing_limits`;
- `mppt_template.max_operating_current_a` remains missing;
- `IDCMax=0` remains unmapped;
- `mppt_design_ready` remains false for the OND-only candidate;
- `basic_yield_ready` may still be true because the OND provides the voltage domain,
  AC rating, and executable efficiency curves needed for lower-fidelity energy conversion.


The multi-source overlay layer may add the 26 A manufacturer-datasheet value with its own
field-level provenance record. Once that independent source is attached, current-limit design
checks and current-clipping refinement can become available without pretending the value came
from the OND.


## Temperature-dependent output power


PVsyst documents conditional PMax and high-temperature derating as separate from the normal
continuous PNom limit.


For the Huawei fixture RawiBumi preserves:


```text
TPMax  = 30 °C
PMax   = 110 kW


TPNom  = 40 °C
PNom   = 100 kW


TPLim1 = 60 °C
PLim1  = 36 kW


TPLimAbs = 62 °C
```


The component stores these breakpoints without silently inventing an additional zero-power
point at `TPLimAbs`. The temperature reference basis is currently stored as `unknown`
because PVsyst allows the project/simulation configuration to define whether the relevant
temperature is external ambient, shifted ambient, or another inverter-temperature proxy.


## Remaining unresolved fields


The following Huawei OND fields remain preserved but are not yet promoted to canonical
simulation parameters:


- `IDCMax`;
- `Vmpp_PMax`;
- `PInEffMax`;
- `PThreshEff`;
- `EfficMaxV`;
- `EfficEuroV`;
- detailed auxiliary switch/protection flags.


They should be mapped only when their engineering role is needed and supported by sufficient
evidence.


## Primary evidence


PVsyst inverter input/output documentation:
https://www.pvsyst.com/help/physical-models-used/grid-inverter/inverter-model-input-and-output.html


PVsyst inverter main-parameter documentation:
https://www.pvsyst.com/help/component-database/grid-inverters/grid-inverters-main-interface/grid-inverters-main-parameters/index.html


PVsyst inverter efficiency documentation:
https://www.pvsyst.com/help/physical-models-used/grid-inverter/inverter-model-efficiency.html


PVsyst temperature-dependent output parameters:
https://www.pvsyst.com/help-pvsyst7/inverter_outputparameter.htm


Huawei SUN2000-100KTL-M1 manufacturer datasheet:
https://solar.huawei.com/-/media/Solar/attachment/pdf/mea/datasheet/SUN2000-100KTL-M1.pdf


CASSYS OND importer:
https://github.com/CanadianSolar/CASSYS/blob/master/CASSYS%20Interface/DatabaseImportModule.vba