# User component data templates


RawiBumi does not require PVsyst PAN/OND to be the complete definition of a component.
PAN/OND is one source adapter. A component may be progressively assembled from manufacturer
files, datasheets, open databases, laboratory data, user measurements, or manually entered
engineering values.


The central rule is:


```text
minimum trustworthy data -> usable lower-fidelity calculation
additional trustworthy data -> additional checks and/or higher-fidelity calculation
missing optional refinement -> disclosed limitation, not fabricated value
```


## Recommended files


### `module.csv`


One row per PV module. This is the normal spreadsheet-friendly entry format.


Required for a useful basic module record are identity, dimensions, STC electrical values,
and temperature coefficients. More detailed cell architecture, bifacial data, limits, and
single-diode parameters are optional refinements.


Temperature coefficients may be entered either in absolute canonical units:


- `alpha_isc_a_per_c`
- `beta_voc_v_per_c`
- `gamma_pmp_w_per_c`


or in the common manufacturer percentage form:


- `alpha_isc_pct_per_c`
- `beta_voc_pct_per_c`
- `gamma_pmp_pct_per_c`


When only percentage coefficients are supplied, RawiBumi converts them using the supplied
STC Isc/Voc/Pmp. Blank cells mean **unknown/not supplied**, never zero.


### `inverter.csv`


One row per inverter. It supports AC ratings, DC/MPPT limits, physical MPPT current limits,
PV-array sizing constraints, losses, efficiency summaries, and temperature derating.


A missing MPPT current limit does not prevent lower-fidelity yield calculation if the inverter
has sufficient voltage, AC-power, and efficiency information. It does prevent the software
from claiming current-limit design validation or current-clipping fidelity.


This distinction is deliberate.


### `inverter-efficiency-curve.csv`


Optional long-form table for detailed measured/manufacturer inverter efficiency.


Each row is one operating point:


```text
DC voltage, DC input power, AC output power
```


or DC input power plus efficiency percentage. Rows are grouped by manufacturer/model and
DC voltage to create voltage-dependent efficiency curves.


### `module-iv-reference.csv`


Optional measured or laboratory module-performance matrix. It uses the same canonical IV
reference fields already supported by RawiBumi and may include uncertainty columns.


This file is evidence for validation. It is not silently used as fitting data unless a
separate fitting workflow explicitly says so.


## Advanced YAML overlays


`module-advanced.yaml` and `inverter-advanced.yaml` expose the nested canonical structure
for parameters that do not fit naturally into a flat CSV. Delete unknown fields or leave
them null. Null values are ignored.


YAML overlays are particularly useful for:


- richer cell/module topology;
- additional supported electrical models;
- per-MPPT data;
- future loss/derating structures;
- fields that RawiBumi adds after these CSV templates were published.


The canonical schema is therefore allowed to evolve beyond PAN/OND without forcing PAN/OND
users to provide every newer field.


## Multi-source priority


Every CSV/YAML source may carry an integer `source_priority` / `priority`.


Suggested convention:


```text
10  legacy/imported low-confidence source
50  PAN/OND or open database source
80  independently curated public source
100 manufacturer datasheet/manual
120 manufacturer test report or certified laboratory data
```


The numbers are policy inputs, not truth scores. Identical values accumulate provenance.
A higher-priority value can refine/replace a lower-priority value. Conflicting values at the
same priority are rejected by default so the engineer must resolve them explicitly.


## Licensing and attribution


The template contains optional:


- `license_spdx`
- `license_url`
- `attribution`
- `source_url`


Do not invent a license. If redistribution permission exists but no SPDX identifier applies,
leave `license_spdx` blank and explain the basis in `source_notes`.


## Fidelity philosophy


Module calculation should progress roughly as:


```text
STC + temperature coefficients
    -> basic yield model
+ validated single-diode parameters
    -> detailed electrical model
+ bifacial data
    -> bifacial refinement
+ internal topology / bypass mapping
    -> detailed electrical shading refinement
+ independent IV measurements
    -> stronger validation evidence
```


Inverter calculation should progress roughly as:


```text
AC rating + MPPT voltage domain + explicit efficiency model
    -> basic yield
+ detailed efficiency curves
    -> voltage/load-dependent conversion refinement
+ physical MPPT current limit
    -> current-limit checks/clipping refinement
+ temperature derating
    -> thermal output-limit refinement
+ detailed per-MPPT data
    -> heterogeneous-MPPT refinement
```


Capability flags communicate what was actually supported in a given calculation. Optional
missing data should reduce fidelity, not silently invent engineering values.