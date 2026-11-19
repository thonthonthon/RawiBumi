
# OpenSIMPV — Phase 5.3 Correct Direct-Beam Shadow Kernel v0.1

**Status:** Phase-5.3 implementation anchor  
**Date:** 24 September 2026  
**Scope:** deterministic single-receiver direct-beam geometric visibility  
**Annual simulation integration:** not included  
**Diffuse / ground obstruction:** not included  
**Electrical mismatch:** not included

## 1. Objective

Phase 5.3 implements the first direct-beam geometry physics in Phase 5.

Flow:

    CompiledShadingGeometry
    + receiver_id
    + sun_vector
        -> direct-beam polygon projection
        -> receiver-clipped shadow union
        -> beam_visibility_factor

The objective is analytical correctness and a stable reference kernel. Acceleration is deliberately deferred.

## 2. Solver identity

Solver ID: opensimpv.beam_shadow.polygon_projection  
Solver version: 0.1  
Public API: calculate_direct_beam_shadow(...)  
Implementation: geometry/shading/beam.py  
Result schema: geometry/shading/beam-shadow-query-result.schema.json

## 3. Input authority

The solver consumes CompiledShadingGeometry from Phase 5.1. It does not read or reinterpret editable Scene geometry directly.

Authority chain:

    Scene
    -> Phase-5.1 compiler
    -> CompiledShadingGeometry
    -> Phase-5.3 beam kernel

## 4. Coordinate and vector convention

Phase-5.0 conventions remain binding:

    X = East
    Y = North
    Z = Up
    sun_vector = receiver/site -> sun

Physical shadow projection is opposite the sun vector.

For occluder point q, receiver-plane point p0, receiver normal n, and normalized sun vector s:

    t = n dot (q - p0) / (n dot s)
    q_projected = q - t s

The projection is evaluated only when the sun is on the receiver front side and the occluder geometry is sunward of the receiver plane.

## 5. Receiver-plane basis

Every query builds a deterministic local 2-D basis on the receiver plane. The receiver normal is normalized. A stable in-plane axis is derived from the longest receiver edge, with source vertex order breaking ties. The second axis is normal cross u.

All polygon operations occur in this receiver-local u/v plane.

## 6. Receiver planarity

Receiver vertices must agree with the declared receiver plane.

The kernel records receiver_planarity_max_error_m and fails closed if it exceeds:

    plane_distance_m = 1e-9 m

A nonplanar receiver is never silently flattened.

## 7. Sunward half-space clipping

Before projection, each occluder face is clipped to:

    n dot (x - p0) >= plane_distance_m

Geometry behind the receiver plane therefore cannot cast a forward shadow. Faces that cross the receiver plane are clipped at the positive plane epsilon.

## 8. Projected polygon handling

Each supported face is:

1. clipped to the receiver sunward half-space;
2. projected opposite the sun vector;
3. converted into receiver-local coordinates;
4. intersected with the receiver polygon.

Degenerate edge-on projections below the area tolerance are ignored. A materially nonzero but topologically invalid projected polygon raises BeamShadowError.

## 9. Shadow union rule

All receiver-clipped shadow polygons are unioned before shaded area is measured.

Therefore overlapping projected faces and overlapping occluders cannot double-count shaded area.

Definitions:

    beam_shaded_fraction = shaded_area_m2 / receiver_area_m2
    beam_visibility_factor = 1 - beam_shaded_fraction

Factor convention remains:

    1 = fully visible
    0 = fully blocked

## 10. Receiver self-occlusion

A receiver never occludes itself. An occluder is excluded when its source entity type and source entity ID are the same as the receiver source entity.

This exclusion is unconditional.

## 11. Module self-shading control

Other module occluders participate only when self_shading_enabled is true.

When self_shading_enabled is false, all other module_instance occluders are excluded. Canonical obstacles remain eligible according to their shading_enabled state.

## 12. Physics participation

The solver respects occluder.shading_enabled exactly. UI visibility is never consulted.

## 13. Surface occluder boundary

Phase 5.1 did not compile canonical Surfaces as occluders because Surface currently has no explicit shading_enabled engineering field.

Phase 5.3 preserves that boundary. Initial beam physics receives module-plane and canonical-obstacle occluders only. Surface occlusion is not inferred from UI state or surface type.

## 14. Supported occluder geometry

Version 0.1 executes polygon_faces only.

triangle_mesh input fails explicitly. No mesh geometry is silently approximated.

## 15. Sun below horizon

If normalized sun_vector.z is at or below horizon_z, the result is:

    status = no_direct_beam_sun_below_horizon
    beam_visibility_factor = 1
    beam_shaded_fraction = 0
    shaded_area_m2 = 0

This is a neutral geometric modifier. It does not imply that beam irradiance exists below the horizon; upstream irradiance physics owns beam availability.

## 16. Receiver backside

If receiver_normal dot sun_vector is at or below incidence_dot, the result is:

    status = no_direct_beam_receiver_backside
    beam_visibility_factor = 1
    beam_shaded_fraction = 0

Again the factor is neutral because no front-side beam contribution is geometrically applicable.

## 17. Numerical tolerances

Reference tolerance manifest:

    plane_distance_m = 1e-9
    parallel_dot     = 1e-12
    area_m2          = 1e-10
    horizon_z        = 1e-12
    incidence_dot    = 1e-12

Every result records the exact values used.

## 18. Geometry engine

Planar intersection and union use pinned Shapely 2.1.2 backed by GEOS.

Dependency:

    shapely==2.1.2

Every result records both Shapely and GEOS runtime versions because topology-engine changes can create numerical differences.

## 19. Result contract

BeamShadowQueryResult records:

- solver ID/version;
- compiled geometry hash;
- receiver ID;
- normalized sun vector;
- vector convention;
- projection direction;
- factor convention;
- status;
- receiver area;
- receiver-sun dot product;
- receiver planarity residual;
- shaded area;
- beam visibility factor;
- beam shaded fraction;
- self-shading state;
- contributing occluder IDs;
- projected face count;
- clipped shadow polygon count;
- geometry-engine provenance;
- tolerance manifest.

No electrical loss field exists.

## 20. Contributing occluders

contributing_occluder_ids contains every eligible occluder whose projected geometry intersects the receiver above the area tolerance. The list is deterministic and sorted.

An occluder may be listed even when its shadow is fully overlapped by another occluder; total shaded area still uses the union.

## 21. Analytical validation matrix

Phase-5.3 tests cover:

1. no occluder -> 100% visibility;
2. full rectangular block -> 0% visibility;
3. exact half rectangular overlap -> 50% visibility;
4. diagonal triangular half-area overlap -> 50% visibility;
5. overlapping occluders -> union area with no double counting;
6. rotated horizontal receiver;
7. tilted receiver;
8. low solar altitude with known lateral projection;
9. occluder behind receiver -> zero shadow;
10. receiver-boundary touch -> zero-area shadow;
11. sun below horizon;
12. receiver backside;
13. receiver cannot self-occlude;
14. other-module shading follows self_shading_enabled;
15. disabled occluder is ignored;
16. non-normalized sun vector is normalized;
17. missing compiled geometry hash fails closed;
18. unknown receiver fails closed;
19. closed six-face box projects to the expected area;
20. nonplanar receiver fails closed;
21. unsupported triangle-mesh input fails explicitly.

## 22. Validation hierarchy

Phase 5.3 uses:

    closed-form analytical geometry
    -> controlled synthetic geometry
    -> compiler/runtime integration
    -> external software comparison later

PVsyst does not define the solver equations and is not used to tune these tolerances.

## 23. Determinism

For identical compiled geometry hash, receiver ID, sun vector, self-shading setting, tolerances, and Shapely/GEOS runtime, the reference kernel is expected to reproduce the same scalar result.

No random sampling is used.

## 24. No acceleration

The kernel directly evaluates eligible occluders.

Not implemented here:

- BVH;
- AABB tree;
- spatial index;
- ray accelerator;
- GPU path;
- angular shadow cache.

Correctness is frozen before optimization.

## 25. Deliberate non-goals

Phase 5.3 does not implement:

- annual/timeseries shading execution;
- batch all-receiver shading artifacts;
- diffuse sky obstruction;
- ground obstruction;
- circumsolar treatment;
- electrical mismatch;
- bypass-diode behavior;
- same-MPPT heterogeneous IV physics;
- PVsyst calibration;
- interactive frontend shadow preview.

## 26. Exit gate

Phase 5.3 is complete when:

    CompiledShadingGeometry
    + receiver
    + sun vector
    -> analytically validated beam_visibility_factor

with correct overlap union, self-shadow exclusion, self-shading control, explicit horizon/backside behavior, fail-closed unsupported geometry, explicit tolerances, and geometry-engine provenance.

After closure:

    -------- PHASE 5.3 DIRECT-BEAM REFERENCE KERNEL STABLE --------

Phase 5.4 may build module/receiver-level beam-factor orchestration and diagnostic shadow artifacts around this kernel without redefining its geometry physics.
