# PAN/OND semantic mapping v0.1


RawiBumi treats PAN and OND as external interchange formats, not as its internal schema.


The import chain is:


```text
source file
  -> lossless raw parser
  -> field inventory
  -> versioned mapping ledger
  -> semantic mapping records
  -> canonical candidate builder
  -> engineering validation
```


## Confidence policy


Every ledger rule is classified as:


- `confirmed`
- `documented`
- `empirically_verified`
- `inferred`
- `unknown`


Only rules with `auto_map: true` are applied automatically. The initial ledgers prohibit
automatic mapping for `unknown` and `inferred` rules.


## Current boundary


The semantic mapper currently produces:


- a canonical-path/value map;
- a FieldMappingRecord for every applied rule;
- an ordered list of unmapped raw fields;
- mapping warnings.


It does **not** yet build a complete `ModuleDefinition` or `InverterDefinition`.
That builder is intentionally a later stage because some source fields require cross-field
logic, model-specific grouping, or stronger evidence.


Examples deliberately deferred:


- additional PAN technology-code normalization beyond verified codes;
- additional PAN temperature-coefficient conventions beyond verified fields;
- physical OND MPPT operating-current mapping where the source field is ambiguous;
- OND fields such as IDCMax, Vmpp_PMax, PInEffMax, PThreshEff, EfficMaxV and EfficEuroV;
- heterogeneous MPPT groups.


## Evidence sources


Primary format/model evidence currently comes from:


- PVsyst official module documentation:
  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/index.html
- PVsyst PNom/Pmpp distinction:
  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/pv-modules-basic-data/pnom-and-pmppstc-definitions.html
- PVsyst one-diode parameters:
  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/pv-modules-model-parameters.html
- PVsyst inverter parameters:
  https://www.pvsyst.com/help/component-database/grid-inverters/grid-inverters-main-interface/grid-inverters-main-parameters/index.html
- pvlib PAN/OND parser:
  https://github.com/pvlib/pvlib-python/blob/main/pvlib/iotools/panond.py
- pvlib PAN/OND parser tests:
  https://github.com/pvlib/pvlib-python/blob/main/tests/iotools/test_panond.py
- pvlib public PAN fixture:
  https://github.com/pvlib/pvlib-python/blob/main/tests/data/ET-M772BH550GL.PAN
- pvlib public OND fixture:
  https://github.com/pvlib/pvlib-python/blob/main/tests/data/CPS%20SCH275KTL-DO-US-800-250kW_275kVA_1.OND


RawiBumi does not redistribute the pvlib example component fixtures listed above.


## Manufacturer-supplied regression fixtures


The repository does contain two separately confirmed redistributable manufacturer files under
`tests/fixtures/panond/manufacturer/`:


- Jinkosolar `JKM550M-72HL4-V_SGS_6079M3.PAN`;
- Huawei Technologies `Huawei_Sun2000_100KTL_M1.OND`.


The PAN file embeds `DataSource=Manufacturer 2020 SGS-CSTC`; the OND file embeds
`DataSource=Manufacturer 2018`. The repository maintainer supplied both files and explicitly
confirmed that they are redistributable and manufacturer-distributed rather than copies from
the PVsyst built-in database.


Because neither file embeds a standard SPDX software license, RawiBumi does not invent one.
Instead, `provenance.json` records the original received SHA-256, byte size, embedded source
statement, and the explicit redistribution basis.


These fixtures have two roles:


1. verify that existing safe mappings work on real manufacturer files; and
2. expose additional real-world fields for evidence-driven mapping work.


Their presence does not make intuitive OND names such as `PNomConv`, `IMaxDC`, or
efficiency-profile fields automatically canonical. Those remain unmapped until their scope
and units are verified independently.




## Huawei-backed OND expansion


The manufacturer-supplied Huawei SUN2000-100KTL-M1 fixture is now the first real-world anchor
for completing inverter semantics beyond the minimal OND mapping.


Evidence-backed mappings now include nominal/max AC power, configured AC voltage, nominal/max
AC current, PV-array nameplate/sizing fields, night loss, temperature-dependent output-power
breakpoints, efficiency summary metrics, and three voltage-dependent Pin/Pout transfer
profiles.


The current-scope decision remains deliberately conservative: Huawei's datasheet distinguishes
26 A maximum operating current per MPPT from 40 A maximum short-circuit current per MPPT,
while the OND contains IMaxDC=40 A and IDCMax=0. Therefore IMaxDC is not promoted to the
physical MPPT operating-current limit.


See `docs/ond-inverter-semantics.md` and
`docs/decisions/0003-ond-dc-current-scope.md`.