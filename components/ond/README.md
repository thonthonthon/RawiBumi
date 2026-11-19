# OND adapter


This subsystem handles user-supplied PVsyst-style OND files.


The raw parser preserves:


- original text;
- field order;
- duplicate keys;
- indentation;
- field paths;
- raw values.


The semantic layer is deliberately conservative. The initial `mapping-ledger.yaml` maps
well-supported identity, MPPT-voltage, absolute-DC-voltage, phase, MPPT-count, input-count,
and operating-threshold fields. Ambiguous physical current fields remain unmapped.
Verified voltage-dependent efficiency profiles are assembled as described below.


References:


- pvlib PAN/OND reader:
  https://github.com/pvlib/pvlib-python/blob/main/pvlib/iotools/panond.py
- pvlib OND fixture:
  https://github.com/pvlib/pvlib-python/blob/main/tests/data/CPS%20SCH275KTL-DO-US-800-250kW_275kVA_1.OND
- pvlib parser tests:
  https://github.com/pvlib/pvlib-python/blob/main/tests/iotools/test_panond.py
- PVsyst inverter parameter documentation:
  https://www.pvsyst.com/help/component-database/grid-inverters/grid-inverters-main-interface/grid-inverters-main-parameters/index.html


OND fields shall never become canonical RawiBumi property names merely because their source
names appear intuitive.

ENG1 reads five verified display modes (`POutf_PIn`, `Efficiencyf_POut`,
`Efficf_POut`, `Efficf_PIn`, `Efficiencyf_PIn`) using the stored DC-input/AC-output
pairs without transforming the points. Unknown modes remain refused. Every point
must be finite and satisfy PIn ≥ POut ≥ 0 and efficiency ≤ 1; invalid profiles
produce a warning naming the voltage and point and are never clipped.

[PVsyst's display documentation](https://www.pvsyst.com/help-pvsyst7/inverters_curve.htm)
and [efficiency model](https://www.pvsyst.com/help/physical-models-used/grid-inverter/inverter-model-efficiency.html)
describe the display forms and power-transfer model. No official specification of
the `ModeAffEnum` strings or serialized `Point_n` storage order was found. The pair
order rests on the approved aggregate file evidence recorded in the mapping
ledger, together with the runtime sanity guard. No private file contents or names
are recorded.

A zero `EfficEuro` or `EfficMax` summary means not given and maps to null; the raw
source and mapping record are retained. Per-voltage values remain unchanged.
Nominal AC frequency is never guessed: absence emits
`INVERTER_AC_FREQUENCY_NOT_SPECIFIED` as a warning and does not block energy or
basic-design capability. Required power, voltage, phase and physical per-MPPT
operating-current checks remain. Check actual grid compatibility against the
inverter datasheet.

### Single efficiency profiles (DEC-85, importer v4)

A lone `ProfilPIO` uses the same verified Pin/Pout order and finite `PIn >= POut >= 0`
guard as the three-profile importer. Without voltage-specific profiles it expands to
three identical curves, warning `INVERTER_SINGLE_EFFICIENCY_CURVE`. The runtime's native
`one_dimensional_curve` is a resolution contract only, so no runtime/solver change is
made. Existing three-profile assembly takes precedence, including its refusals.

Anchors are MPPT minimum, nominal MPP voltage, and MPPT maximum. Nominal is used only
when finite and strictly inside the window; otherwise the middle is the midpoint.
Missing, non-finite or invalid window bounds prevent assembly. The
`single_profile_voltage_independent` derivation records the source points, actual
anchors, middle-anchor source and midpoint reason. The three identical transfers express
voltage independence; they are not three measured voltage profiles. Reference metrics
remain separate. Move/solver/model-resolution behavior is unchanged.
