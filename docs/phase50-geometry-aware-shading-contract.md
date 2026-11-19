# OpenSIMPV — Phase 5.0 Geometry-Aware Shading Contract v0.1

**Status:** Phase-5.0 implementation anchor  
**Date:** 24 September 2026  
**Scope:** Shading API / canonical boundary only  
**Production shadow solver:** Not included in Phase 5.0

## 1. Purpose

Phase 5.0 freezes the machine-facing contract that later geometry-aware shading
work must obey.

It does not implement production shadow projection, ray intersection, sky-view
integration, ground-view integration, spatial acceleration, annual shading
caching, or electrical mismatch.

The boundary is:

```text
Canonical SceneRevision
        ↓
deterministic shading-geometry compilation
        ↓
CompiledShadingGeometry
        ↓
beam / sky / ground solvers
        ↓
ShadingResult
        ↓
geometry-aware irradiance integration
```

The canonical Scene remains the engineering authority throughout this chain.

## 2. Authority model

```text
SceneRevision
= authoritative engineering geometry

GeneratedScene3D
= derived verification geometry

CompiledShadingGeometry
= derived numerical shading geometry
```

`CompiledShadingGeometry` is explicitly:

```text
authority = derived_numerical_only
editable = false
```

If any derived artifact disagrees with the canonical Scene, the Scene wins.

Phase 5 must reuse the stable Phase-4 surface/module/height semantics rather than
inventing a second interpretation of geometry.

## 3. Coordinate convention

The Phase-5 shading coordinate basis is:

```text
scene_local_east_north_up_m

X = East
Y = North
Z = Up
unit = metre
```

The basis is the existing canonical local engineering coordinate system, not
screen pixels, map pixels, or a renderer coordinate system.

## 4. Solar azimuth and sun-vector convention

Solar azimuth is clockwise from north:

```text
0°   = North
90°  = East
180° = South
270° = West
```

The frozen vector name and direction are:

```text
sun_vector
= normalized vector from receiver/site toward the sun
```

For solar azimuth `A` and elevation `E`:

```text
x = cos(E) sin(A)
y = cos(E) cos(A)
z = sin(E)
```

in the local East/North/Up basis.

The opposite photon-travel direction may be derived where an algorithm requires
it, but shall not also be named `sun_vector`.

Phase 5.0 provides
`sun_vector_from_azimuth_elevation()` as executable contract evidence.

Below-horizon handling is a later solver responsibility. The vector convention
itself remains defined for elevations down to -90°.

## 5. Factor convention

All geometric visibility factors use:

```text
visibility = 1.0  → fully visible / unblocked
visibility = 0.0  → fully blocked
```

and:

```text
shaded_fraction = 1 - visibility_factor
```

Fields shall not ambiguously mix a loss fraction and a visibility factor.

The frozen identifier is:

```text
visibility_one_clear_zero_blocked
```

## 6. Separate physical channels

At minimum the geometry-aware contract distinguishes:

```text
beam_visibility
sky_visibility
ground_visibility
```

Optional directional diffuse visibility may be added where the transposition
model requires directional sky information.

A single unexplained global near-shading multiplier is not a Phase-5-compliant
representation.

## 7. Receiver taxonomy

A receiver is geometry on which visibility is evaluated.

The Phase-5.0 compiled contract supports:

```text
module_plane
aggregate_plane
```

with source lineage to:

```text
module_instance
pv_field
surface
```

The compiled receiver retains:

```text
receiver_id
source entity identity
vertices_3d
center_xyz
normal_xyz
area_m2
enabled state
PV-field / support / module lineage where applicable
```

Engineering annual simulation is expected to reach module granularity. Preview
or lower-fidelity modes may use aggregates if the approximation is explicit.

## 8. Occluder taxonomy

An occluder is derived from physical canonical geometry that is enabled for
shading participation.

The compiled contract supports source lineage to:

```text
obstacle
module_instance
surface
imported_mesh
pv_field
```

and solver-neutral compiled representations:

```text
polygon_faces
triangle_mesh
```

A compiled occluder contains polygonal faces, bounds, source identity, and an
explicit `shading_enabled` state.

UI visibility is not physics authority.

```text
visible = display concern
shading_enabled = physics concern
```

Reference/dimension lines are never physical occluders.

## 9. Self-shading semantics

`self_shading_enabled` is mandatory for geometry-aware execution.

When false, module-to-module occlusion is excluded.

When true, physically distinct module receivers/occluders may participate in
row-to-row or table-to-table self-shading.

A receiver shall never occlude itself. Later kernels must exclude the matching
receiver/source entity and use a documented numerical epsilon where needed.

## 10. CompiledShadingGeometry contract

The machine-readable schema is:

```text
geometry/shading/compiled-shading-geometry.schema.json
```

The artifact binds:

```text
source Scene ID/revision/hash
coordinate-system identity
coordinate basis
compiler ID/version
compilation-input hash
receiver set
occluder set
3-D bounds
compiler findings
geometry-payload hash
```

`geometry_payload_sha256` is the canonical hash of the numerical geometry
payload defined by the compiler implementation. Phase 5.1 must freeze the exact
canonical serialization used to calculate it.

No production compiler is implemented in Phase 5.0.

## 11. ShadingConfiguration compatibility rule

The Phase-4 `SimulationConfiguration.shading_configuration` carrier remains
schema version 0.1.

Its previous minimal form remains valid, including:

```text
beam_method
diffuse_method
albedo_method
fidelity_level
sun_position_resolution_seconds
electrical_shading_method
```

This preserves existing unshaded and external-reference benchmark objects.

A future geometry-aware Phase-5 worker must additionally require:

```text
geometry_contract_version = 0.1
coordinate_basis = scene_local_east_north_up_m
sun_vector_convention = receiver_to_sun
factor_convention = visibility_one_clear_zero_blocked
receiver_granularity
self_shading_enabled
sun_position_resolution_seconds
cache_policy
```

The stricter executable gate is:

```text
assert_geometry_aware_shading_configuration()
```

Therefore:

```text
old Phase-4 configuration
→ remains serializable / reproducible

active Phase-5 geometry execution
→ must opt into the explicit Phase-5 contract
```

## 12. Fidelity and resolution

Fidelity levels remain:

```text
preview
fast
engineering
detailed
research
```

Fidelity is not itself a numerical resolution.

Any active solver must separately expose the relevant resolution in its model
manifest and/or geometric configuration.

Examples include:

```text
receiver subdivision
sun-position temporal resolution
sky-dome resolution
ground-view resolution
angular cache bins
mesh / chord tolerance
```

`sun_position_resolution_seconds = null` has one frozen meaning for active
Phase-5 validation:

> use the canonical simulation solar-evaluation timestamps without additional
> temporal coarsening.

It does not mean an unspecified hidden resolution.

## 13. Diffuse contract

Diffuse obstruction is not direct-beam shadowing.

The result schema therefore preserves `sky_visibility` independently.

For anisotropic transposition models, later implementations must document how
isotropic, circumsolar, and horizon components consume geometric visibility.

A scalar sky factor shall not silently be applied to physically distinct
components where the selected transposition model requires different treatment.

Phase 5.0 does not select the production diffuse solver.

## 14. Ground/albedo contract

Ground obstruction remains independent of sky obstruction.

The result schema preserves:

```text
ground_visibility
```

This channel modifies the front-side ground-reflected contribution required by
the current monofacial chain.

Full bifacial rear-side irradiance remains outside Phase 5.

## 15. ShadingResult contract

The machine-readable schema is:

```text
geometry/shading/shading-result.schema.json
```

It binds:

```text
source Scene revision
compiled geometry hash
shading configuration hash
solver manifest
fidelity
receiver granularity
factor convention
modeled channels
record count
inline or dataset storage
approximations
findings
```

High-volume annual factors may use the existing Parquet
`ResultDatasetReference` rather than embedding all records in JSON.

The semantic contract remains the same regardless of storage.

## 16. Electrical-shading boundary

Phase 5.0 freezes:

```text
electrical_shading_scope = not_modeled
```

for geometry-aware `ShadingResult`.

The strict configuration gate rejects active electrical methods other than:

```text
null
none
not_modeled
```

Thus geometric visibility does not become a bypass-substring, module-IV,
string-IV, or MPPT-mismatch claim.

Those effects remain Phase 6.

The legacy `electrical_shading_method` field remains present only for
configuration compatibility and future phase migration.

## 17. Solver manifest

Every modeled geometric channel must identify:

```text
model_id
model_version
resolution
notes
```

The required channel slots are:

```text
beam
sky_diffuse
ground
```

An unimplemented channel is represented by an explicit model such as `none`,
not by omitted provenance.

## 18. Cache identity

The machine-readable cache contract is:

```text
geometry/shading/shading-cache-manifest.schema.json
```

A shading cache is derived state and never engineering authority.

A valid cache identity shall depend on all material inputs, including as
applicable:

```text
source Scene revision
compiled geometry hash
shading configuration hash
solver manifest/version
fidelity
sampling resolution
receiver set
sun state / angular bin
```

The Phase-5 cache modes are:

```text
none
exact
angular_bins
```

`angular_bins` requires explicit azimuth and altitude bin sizes.

Approximate cache reuse must therefore be identifiable from configuration and
must not masquerade as exact evaluation.

## 19. Findings and fail-closed behavior

Derived geometry or shading processing may emit:

```text
info
warning
error
```

findings.

Later workers must fail closed where unresolved geometry makes the requested
physics materially ambiguous.

Unknown dimensions, unsupported geometry, or unsupported electrical coupling
must not silently become:

```text
zero shading
generic dimensions
project-average orientation
project-average irradiance
```

## 20. Existing numerical worker remains unchanged in Phase 5.0

Phase 5.0 does not activate geometry-aware simulation.

The existing canonical worker may continue to emit:

```text
SIMULATION_SCOPE_UNSHADED_ONLY
SIMULATION_SCOPE_REQUIRES_ONE_ORIENTATION
```

for currently unsupported execution scopes.

Those blockers are removed or refined only by later Phase-5 implementation
tranches after the necessary physics path exists.

## 21. Machine-readable artifacts introduced

```text
geometry/shading/shading-configuration.schema.json
geometry/shading/compiled-shading-geometry.schema.json
geometry/shading/shading-result.schema.json
geometry/shading/shading-cache-manifest.schema.json
geometry/shading/contract.py
```

`SimulationConfiguration.shading_configuration` now resolves through the
dedicated shading-configuration schema.

Schema registries used by design and canonical validation include the shading
schema directory.

## 22. Validation evidence

Phase 5.0 tests prove:

1. local ENU sun-vector cardinal directions;
2. normalized receiver-to-sun vectors;
3. visibility/shaded-fraction semantics;
4. invalid visibility factors fail;
5. active Phase-5 geometry configuration requires explicit contract fields;
6. Phase-5 geometry configuration rejects detailed electrical shading;
7. existing Phase-4 unshaded configurations remain schema-valid;
8. existing PVsyst external-reference shading configurations remain schema-valid;
9. an explicit Phase-5 shading configuration validates inside
   `SimulationConfiguration`;
10. example compiled geometry, shading result, and cache artifacts validate
    against their schemas.

## 23. Deliberate Phase-5.0 deferrals

Not implemented here:

```text
Scene → CompiledShadingGeometry compiler
receiver extraction
occluder-face compilation
beam shadow geometry
polygon clipping
ray intersection
sky dome integration
ground-view integration
spatial acceleration / BVH
production cache
annual geometry-aware SimulationRun
frontend shadow preview
electrical mismatch
```

## 24. Phase-5.0 acceptance gate

Phase 5.0 is complete when:

- conventions above are documented and executable;
- machine-readable schemas validate;
- old Phase-4 configurations remain compatible;
- active geometry-aware configurations cannot omit critical conventions;
- derived geometry is explicitly non-authoritative;
- geometric and electrical shading remain distinct;
- CI passes without activating a production shading solver.

After this gate:

```text
──────── PHASE 5.0 SHADING CONTRACT FROZEN ────────
```

Phase 5.1 may implement deterministic:

```text
SceneRevision
→ CompiledShadingGeometry
```

against this contract.
