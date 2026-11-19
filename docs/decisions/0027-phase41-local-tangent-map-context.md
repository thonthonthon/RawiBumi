# ADR 0027 — Local tangent-plane engineering coordinates; map projection is context

**Status:** Accepted  
**Date:** 2026-09-23

## Context

Phase 4.1 requires a reversible relationship between geographic coordinates,
map coordinates, and a numerically stable local metric engineering frame.

The product specifications also require:

- X East / Y North / Z Up as the recommended basis;
- exact engineering dimensions independent of pixels;
- map-provider independence;
- user-entered dimensions to supersede map measurements;
- operation across ordinary rooftop and ground-mounted PV sites.

Using raw latitude/longitude for editing creates poor numerical ergonomics.
Using Web-Mercator metres as construction dimensions imports projection scale
distortion into engineering geometry.

A UTM project CRS would provide metric coordinates but introduces zone identity
as an avoidable project concern and can create discontinuities for sites near a
zone boundary.

## Decision

1. WGS84 / EPSG:4326 is the canonical geographic reference.
2. Canonical engineering coordinates use a WGS84 ECEF-derived local tangent
   plane.
3. The zero-rotation basis is East, North, Up.
4. An optional engineering-frame rotation is applied about Up.
5. Rotation is positive clockwise and defines the true azimuth of local +Y.
6. EPSG:3857 is supported only as map context.
7. Floating world pixels and zoom are viewport/map values and never canonical
   dimensions.
8. Map measurements are converted through geographic coordinates into the local
   engineering frame before reporting metres.
9. Map providers are represented by a renderer-independent configuration.
10. Uploaded orthophotos reference ImportedAsset records and are calibrated into
    local XY using a six-parameter affine fit from at least three control points.
11. No mandatory external GIS runtime library is required for the Phase-4.1
    transform path.

## Consequences

### Positive

- engineering dimensions are zoom-independent;
- one site has one stable local metric frame;
- crossing a UTM-like zone boundary does not change project coordinates;
- map providers can be changed or removed without changing engineering geometry;
- offline/self-hosted operation remains possible after site geometry exists;
- orthophotos become traceable references rather than pixel geometry databases.

### Limitations

- the local tangent plane is a site-scale engineering frame, not a replacement
  for national surveying or cadastral CRS workflows;
- EPSG:3857 scale values remain approximate display values;
- affine orthophoto calibration does not correct higher-order lens or terrain
  distortion;
- survey-grade imported coordinate systems may require a later explicit CRS
  adapter.

## Rejected alternatives

### Store geometry directly in latitude/longitude

Rejected because small engineering edits become numerically awkward and the
geometry model would depend on angular units.

### Use EPSG:3857 metres as engineering coordinates

Rejected because pseudo-Mercator scale is latitude-dependent.

### Make UTM the canonical project coordinate system

Rejected because zone selection is unnecessary for a local PV engineering
workspace and creates an avoidable boundary case.

### Store image pixels and infer metres from viewport zoom

Rejected because construction dimensions would change with presentation state.
