# Mitsubishi PV-UE125MF5N measured-IV subset


This directory contains a compact, redistributable **real measured** IV-curve fixture derived
from `pvlib/pvlib-python` v0.15.2 `tests/data/PVsyst_demo.csv`.


The underlying campaign is described in Sandia report **SAND2015-8598**, which states that
the example uses measured outdoor IV curves for a 36-cell Mitsubishi PV-UE125MF5N 125 W
crystalline-silicon module tested in Albuquerque, New Mexico. Cell temperature was estimated
from three thermocouples attached to the module backsheet, and effective irradiance was
measured in the module plane with a silicon reference cell.


Source report:
https://www.osti.gov/servlets/purl/1223058


Upstream data:
https://github.com/pvlib/pvlib-python/blob/v0.15.2/tests/data/PVsyst_demo.csv


## What RawiBumi redistributes


The upstream file contains 3,585 curves with up to 56 voltage/current samples per curve. RawiBumi
redistributes 12 curves selected to span the measured irradiance/temperature domain within
upstream indices 0–2999, the range exercised by pvlib's own `fit_pvsyst_sandia` regression
test. The original source indices are recorded in `dataset-manifest.json`.


The numerical summary and IV rows of those selected curves are copied unchanged. The only
format modification is the curve-count field on line 2, changed from 3585 to 12.


This subset is intended for ingestion, provenance, QA, and regression testing. It is not an
IEC 61853 matrix and it is not automatically independent validation evidence for a model
fitted from the same Sandia/pvlib measurement campaign.


## Integrity


The manifest records both the immutable upstream Git blob SHA and SHA-256 of the complete
upstream file, plus SHA-256 of this redistributed subset.


## License


The upstream pvlib-python repository is BSD-3-Clause licensed. The required copyright,
conditions, and disclaimer are retained in `LICENSE-pvlib-BSD-3-Clause.txt`.