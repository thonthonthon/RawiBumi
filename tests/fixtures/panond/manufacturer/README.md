# Manufacturer-supplied PAN/OND fixtures


These two files are intentionally different from the generic synthetic fixtures in the parent
directory.


They are manufacturer-distributed component files supplied to RawiBumi by the repository
maintainer, who confirmed that the files are redistributable. They are therefore suitable as
real-world parser/mapping regression fixtures without redistributing the PVsyst built-in
component database.


## Included fixtures


- `JKM550M-72HL4-V_SGS_6079M3.PAN` — Jinkosolar JKM550M-72HL4-V module.
  The file itself states `DataSource=Manufacturer 2020 SGS-CSTC` and identifies
  SGS-CSTC Standards Technical Service Co., Ltd.
- `Huawei_Sun2000_100KTL_M1.OND` — Huawei Technologies SUN2000-100KTL-M1
  inverter. The file states `DataSource=Manufacturer 2018` and contains a Huawei
  source comment.


## Redistribution boundary


No claim is made that PAN or OND files from the PVsyst built-in database are generally
redistributable. These fixtures are included because their provenance and redistribution
status were separately confirmed by the repository maintainer.


The files do not embed an SPDX license. For that reason, RawiBumi records the redistribution
basis explicitly in `provenance.json` rather than inventing a software-license identifier.


## Integrity


`provenance.json` records SHA-256 and original byte size of the files as received. Repository
line-ending normalization may change the byte hash of the checked-in text file; the original
source hash remains the provenance anchor.


These fixtures are intended for:


- lossless-parser regression;
- semantic-mapping regression;
- field-inventory expansion;
- component-candidate validation;
- evidence-backed discovery of currently unmapped PAN/OND fields.


They are not treated as authoritative definitions of the RawiBumi canonical schema.