# Site, map, and coordinate foundation

Phase 4.1 implements the coordinate boundary required by the Engineering Design
Environment.

## Authority hierarchy

Canonical engineering geometry is stored in local metric coordinates.

```text
WGS84 geographic coordinates
        ↓
WGS84 ECEF
        ↓
local tangent-plane ENU
        ↓
optional project XY rotation
        ↓
canonical local X/Y/Z metres
```

Map coordinates and pixels are presentation/context only.

Web-Mercator / EPSG:3857 helpers are provided for map display, but raw
pseudo-Mercator metres and pixel distances are never accepted as canonical
engineering dimensions.

## Local frame

At zero rotation:

```text
X = East
Y = North
Z = Up
```

`rotation_from_true_north_deg` is positive clockwise. A +30 degree rotation
therefore places local +Y at true azimuth 30 degrees and local +X at 120 degrees.

The local frame is tangent-plane based instead of UTM-zone based. This avoids
coordinate discontinuities at UTM-like zone boundaries and keeps one stable
engineering frame for a project.

## Map providers

`MapLayerConfiguration` is renderer-independent. It records:

- provider identity and provider kind;
- tile/style references;
- credential references rather than embedded credentials;
- attribution and license notes;
- map/aerial/orthophoto/grid layer identity;
- source/imported-asset references;
- orthophoto georeferencing.

Current visibility, opacity, viewport, and camera remain UI-only
`DesignWorkspaceState`.

## Uploaded orthophotos

Phase 4.1 supports affine image-to-local calibration from at least three control
points.

```text
image pixel
  -> affine calibration
  -> canonical local XY metres
  -> engineering measurement
```

The fit reports RMS control-point error. Degenerate control-point geometry fails
closed.

## Measurement

Measurement functions report:

- delta X/Y/Z;
- horizontal distance;
- 3-D distance;
- local azimuth;
- true-north azimuth.

Geographic or world-pixel measurements are first converted into the local
engineering frame. Map zoom therefore cannot change the engineering dimension.

## Numerical scope

The WGS84/local conversion is implemented directly from the WGS84 ellipsoid and
ECEF/ENU equations, without a mandatory GIS runtime dependency. The intended
Phase-4.1 project scale is ordinary rooftop and ground-mounted PV sites; tests
cover millimetre-scale local offsets through multi-kilometre ground sites.

See:

- `docs/site-map-coordinate-foundation.md`
- `docs/decisions/0027-phase41-local-tangent-map-context.md`
