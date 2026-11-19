# 3D verification / height model

Phase 4.4 generates a deterministic, derived 3D verification artifact from the canonical 2D Scene.

Core rules:

- 2D Scene geometry remains authoritative and editable;
- 3D output is derived, non-editable, and renderer-neutral;
- `base_elevation_m` is the plane elevation at the surface elevation reference;
- absent/null elevation reference means the polygon boundary centroid;
- surface `azimuth_deg` is the downhill/facing direction (0=N, 90=E);
- surface slope rises opposite that azimuth;
- obstacles are vertical extrusions from `base_elevation_m` by `height_m`;
- module geometry preserves physical width/height from the pinned field footprint;
- module tilt/azimuth generate explicit row/downhill axes, normal and four 3D corners;
- mounting height is a vertical Z offset between support-plane elevation at module center and module center;
- obvious module/support-plane penetration is reported, not silently corrected;
- imported mesh editing and near-shading physics are out of Phase 4.4.

Primary APIs:

- `SurfacePlane`
- `generate_scene3d()`
- `canonical_scene3d_json()`
- `canonical_scene3d_hash()`

The generated artifact is described by `generated-scene3d.schema.json`.
