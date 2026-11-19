# Optical incidence-angle modeling

Phase 3.3 adds component-aware incidence-angle modification after unshaded POA
transposition.

Supported model IDs:

```text
iam.none.v0.1
iam.tabulated.pvlib_interp.v0.1
```

The tabulated model stores the source reference angles, IAM values, interpolation method,
and normalization policy explicitly.

For the PVsyst reference PAN, the source profile is a `TCubicProfile`, so the benchmark
configuration uses cubic interpolation rather than silently replacing the source profile with
a different IAM equation.

Direct beam and Perez/Hay-Davies circumsolar irradiance use the IAM evaluated at the solar
angle of incidence.

Diffuse factors for isotropic sky, horizon, and ground-reflected irradiance are derived from
the same tabulated IAM curve with Marion solid-angle integration
(`pvlib.iam.marion_integrate`). They are not hidden empirical constants.

The result keeps these terms separately:

```text
IAM beam
IAM sky
IAM horizon
IAM ground

effective beam
effective isotropic sky
effective circumsolar
effective horizon
effective sky diffuse
effective ground diffuse
effective total diffuse
effective irradiance
IAM delta
```

Effective irradiance reconciles exactly from the retained components.

The optical layer currently represents IAM only. Spectral modifiers, soiling, shading, and
other losses are separate stages.
