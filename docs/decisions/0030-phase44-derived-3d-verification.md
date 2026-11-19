# ADR 0030 — 3D is a deterministic derived verification view

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4.4 requires surface elevation, roof slope, obstacle/parapet height, module tilt and mounting elevation to become inspectable in 3D.

The source specifications explicitly require 3D to remain secondary to the 2D engineering editor. They do not, however, define the elevation datum of a sloped surface.

Without an explicit datum, identical values of boundary, slope, azimuth and base elevation can be interpreted differently by different renderers.

## Decision

1. Canonical Scene remains the engineering authority.
2. GeneratedScene3D is derived, renderer-neutral, non-editable state.
3. `base_elevation_m` is the surface-plane elevation at an explicit elevation-reference point.
4. If no reference is stored, the boundary centroid is the deterministic default.
5. Surface azimuth is the downhill/facing direction using 0=N, 90=E, clockwise positive.
6. Surface slope must satisfy 0 <= slope < 90 degrees; vertical walls use obstacle primitives.
7. Obstacles/parapets are initially vertical extrusions of their canonical footprint.
8. Module centers are vertically offset from the support plane by `mounting_height_m`.
9. Module physical dimensions are preserved in 3D. Projection is allowed to change; stretching is not.
10. Height inconsistencies produce findings rather than automatic geometry repair.
11. Missing module physical dimensions produce unresolved module geometry rather than invented dimensions.
12. Generated output is versioned and deterministically hashed.
13. No generic 3D mesh editor and no near-shading solver are introduced in Phase 4.4.

## Consequences

The same canonical Scene drives both plan and 3D views, sloped-roof behavior becomes renderer-independent, module tilt can be inspected using exact physical dimensions, and Phase 5 receives a stable geometric foundation.

The centroid datum is a compatibility default rather than a claim that every survey measures elevation at a roof centroid. Projects with a known datum can store an explicit XY elevation reference.

Imported mesh editing, complex curved surfaces and shading physics remain deferred.
