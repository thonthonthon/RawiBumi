# PVsyst single-diode model validation v0.1


This layer validates that a PAN-derived PVsyst single-diode parameter set reproduces its
source reference electrical behavior before RawiBumi advertises
`detailed_sdm_ready = true`.


## Pipeline


```text
PAN
 -> lossless parser
 -> semantic mapping
 -> canonical ModuleDefinition candidate
 -> normalize temperature coefficients
 -> complete PVsyst SDM reference parameters
 -> pvlib calcparams_pvsyst()
 -> pvlib singlediode()
 -> compare Isc / Voc / Imp / Vmp / Pmp at reference conditions
 -> store residuals and implementation version
 -> detailed_sdm_ready only on pass
```


## Temperature coefficients


For the currently verified PAN field family:


- `muISC` is converted from mA/K to canonical A/K.
- `muVocSpec` is converted from mV/K to canonical V/K.
- `muPmpReq` is converted from %/K to fraction/K and then to canonical absolute W/K using
  the source-backed reference `Pmp`. That second conversion is stored as an explicit
  derivation.
- the resulting canonical coefficient basis is `absolute`.


Unknown technology codes and unsupported coefficient conventions are not guessed.


## Completing I_L_ref and I_o_ref


When PAN provides Isc, Voc, Rs, Rsh, Gamma, series-cell count, and reference temperature,
RawiBumi solves the single-diode equations at the short-circuit and open-circuit points to
derive `I_L_ref` and `I_o_ref`. The derivation is stored in the candidate.


For recognized crystalline-silicon PAN technology, `EgRef = 1.121 eV` is applied as the
documented PVsyst/pvlib crystalline-silicon model default and recorded as a derivation rather
than an unexplained constant.


## Validation implementation


Validation is pinned to **pvlib 0.15.2** for reproducible reference behavior.


RawiBumi calls:


- `pvlib.pvsystem.calcparams_pvsyst()` at the PAN reference irradiance and temperature;
- `pvlib.pvsystem.singlediode(..., method="lambertw")`.


The validation result stores the pvlib version, solver, modeled reference points, signed and
absolute relative residuals, and pass/fail state.


The initial pointwise tolerance is 2% for each of Isc, Voc, Imp, Vmp, and Pmp. It is explicit
and versioned; it is not a hidden fitting correction.


## Important limitation


Passing this test means the RawiBumi/pvlib PVsyst-v6 model reproduces the PAN reference
points within the accepted tolerance. It does **not** mean bit-for-bit identity with the
PVsyst desktop application across all irradiance, temperature, recombination, reverse-bias,
IAM, bifacial, or spectral conditions.


A later validation matrix will add off-STC irradiance and temperature points.


## References


- pvlib repository:
  https://github.com/pvlib/pvlib-python
- pvlib single-diode modeling guide:
  https://github.com/pvlib/pvlib-python/blob/main/docs/sphinx/source/user_guide/modeling_topics/singlediode.rst
- pvlib `calcparams_pvsyst` implementation:
  https://github.com/pvlib/pvlib-python/blob/main/pvlib/pvsystem.py
- public pvlib PAN fixture used only as semantic/reference evidence:
  https://github.com/pvlib/pvlib-python/blob/main/tests/data/ET-M772BH550GL.PAN
- PVsyst module model documentation:
  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/pv-modules-model-parameters.html


RawiBumi's executable tests use synthetic redistributable PAN fixtures rather than copying
third-party component datasets into the project.
## Off-STC validation matrix\n\nThe v0.1 off-STC grid is:\n\n- effective irradiance: 200, 600, and 1000 W/m²;\n- cell temperature: 0, 25, 50, and 75 °C;\n- total operating points: 12.\n\nEach operating point must be finite and physically coherent: Isc, Voc, Imp, Vmp, and Pmp are positive; Voc > Vmp; Isc >= Imp; and Pmp is numerically consistent with Vmp × Imp.\n\nThe matrix also checks expected monotonic behavior. At fixed temperature, Isc, Voc, and Pmp must increase with irradiance. At fixed irradiance, the direction of Isc, Voc, and Pmp with temperature is taken from the signs of the source-backed temperature coefficients.\n\n### Source-anchored temperature-slope check\n\nAt reference irradiance, RawiBumi evaluates the model at Tref ± 5 °C and forms centered finite-difference slopes for Isc, Voc, and Pmp. These are compared with the source-backed PAN coefficients.\n\nThe current provisional relative tolerances are 2% for Isc, 5% for Voc, and 15% for Pmp. The looser Pmp tolerance is deliberate: PAN muPmpReq is a source target/requested coefficient, while the resulting PVsyst-v6 behavior depends on the coupled single-diode parameter set, including muGamma. These tolerances are explicit and configurable and should be revisited against a larger verified PAN corpus.\n\n### Readiness gate\n\ndetailed_sdm_ready = true now requires both STC source-point reproduction and the off-STC matrix validation described above. A schema-valid component may still remain useful for layout or basic yield without satisfying this detailed-model gate.\n\n## Important limitation\n\nPassing these checks means the RawiBumi/pvlib PVsyst-v6 model is internally coherent over the defined matrix and is consistent with the available source temperature coefficients within the stated tolerances. It does not establish bit-for-bit identity with the PVsyst desktop application, because PAN files do not provide a complete off-STC reference matrix.\n\nFuture validation should add independently sourced IEC 61853 or measured IV matrices when licensing and provenance permit.\n\n## References\n\n- pvlib repository:\n  https://github.com/pvlib/pvlib-python\n- pvlib single-diode modeling guide:\n  https://github.com/pvlib/pvlib-python/blob/main/docs/sphinx/source/user_guide/modeling_topics/singlediode.rst\n- pvlib calcparams_pvsyst implementation:\n  https://github.com/pvlib/pvlib-python/blob/main/pvlib/pvsystem.py\n- public pvlib PAN fixture used only as semantic/reference evidence:\n  https://github.com/pvlib/pvlib-python/blob/main/tests/data/ET-M772BH550GL.PAN\n- PVsyst module model documentation:\n  https://www.pvsyst.com/help/component-database/photovoltaics-modules/pv-modules-main-interface/pv-modules-model-parameters.html\n\nRawiBumi's executable tests use synthetic redistributable PAN fixtures rather than copying third-party component datasets into the project.\n