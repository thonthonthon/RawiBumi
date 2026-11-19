# RawiBumi — Site, Map, and Coordinate Foundation v0.1


**Status:** Phase 4.1 implementation specification  
**Date:** 2026-09-23  
**Parent:** Engineering Design Environment Specification v0.1


## 1. Purpose


Phase 4.1 establishes the spatial reference foundation used by the future 2D
scene editor.


The governing invariant is:


```text
map coordinates = context
local XY metres = engineering geometry authority
```


The map is not the construction geometry database.


## 2. Canonical site anchor


`Project.site` carries:


- site latitude and longitude;
- optional site elevation;
- timezone;
- geodetic true-north reference;
- one `LocalCoordinateSystem`.


The canonical geographic CRS is WGS84 / EPSG:4326.


## 3. LocalCoordinateSystem


The local coordinate system records:


```text
coordinate_system_id
site_id
origin_latitude_deg
origin_longitude_deg
origin_elevation_m
geographic_crs = EPSG:4326
local_frame = rotated_enu
X basis = East
Y basis = North
Z = Up
rotation_from_true_north_deg
rotation_convention
optional map projection = EPSG:3857 / context_only
```


### 3.1 Numerical transform


The reversible path is:


```text
geodetic WGS84
  ↔ WGS84 ECEF
  ↔ local ENU
  ↔ rotated engineering XY
```


This deliberately avoids using UTM as the canonical project frame. A project can
cross a UTM-like zone boundary without changing coordinate system or introducing
a false jump.


### 3.2 Rotation convention


`rotation_from_true_north_deg` is positive clockwise and describes the true
azimuth of the local +Y axis.


At zero rotation:


```text
+Y = true North
+X = East
```


At +30 degrees:


```text
+Y true azimuth = 30°
+X true azimuth = 120°
```


## 4. Map projection and scale


Web maps may use EPSG:3857.


RawiBumi provides:


- WGS84 ↔ EPSG:3857 conversion;
- WGS84 ↔ floating world-pixel conversion by zoom;
- map ground-resolution calculation;
- map scale-factor calculation.


These values are display/context values only.


An engineering edge remains 10.000 m regardless of map zoom because dimensions
are measured in local geometry after geographic conversion, never from pixel
length.


## 5. Map-provider abstraction


`MapLayerConfiguration` is renderer-independent and supports provider kinds:


```text
xyz_raster
maplibre_style
uploaded_asset
none
```


Layer kinds:


```text
base_map
aerial_imagery
orthophoto
engineering_grid
```


Provider configuration may carry:


- tile URL template;
- style URL;
- credential reference;
- attribution requirement and attribution text;
- license note.


Raw credentials are not a canonical provider field.


Required provider attribution remains available to the client through
`required_attributions()`.


Map-provider configuration does not contain current visibility/opacity/camera
state. Those remain UI-only workspace state.


## 6. Uploaded orthophoto reference


Orthophoto assets use the existing `ImportedAsset.asset_type = orthophoto`
boundary.


A scene map layer references the asset ID and an affine local georeference.


Phase 4.1 georeference:


```text
>= 3 pixel/local control points
  -> least-squares six-parameter affine fit
  -> pixel ↔ local XY transform
  -> RMS control-point error
```


The affine model allows pixel-axis orientation, scale, rotation, shear, and
translation to be represented. Degenerate control points are rejected.


## 7. Measurement tools


The numerical measurement foundation supports:


- local point-to-point measurement;
- geographic point-to-point measurement through the local frame;
- world-pixel measurement through geographic/local conversion;
- calibrated orthophoto pixel measurement.


Outputs include:


```text
delta_x_m
delta_y_m
delta_z_m
horizontal_distance_m
spatial_distance_m
local_azimuth_deg
true_azimuth_deg
```


No measurement function treats screen pixels or raw Web-Mercator metres as
construction truth.


## 8. Dimensional authority and overrides


The Phase-4 hierarchy remains:


1. local/geographic scale;
2. component-database physical dimensions;
3. explicit user-entered dimensions/elevations.


Map-derived measurements are contextual inputs.


When a later editor command changes a 40.37 m map-derived edge to an explicit
40.00 m engineering dimension, the canonical local geometry becomes 40.00 m.
That editing operation belongs to Phase 4.2; Phase 4.1 provides the coordinate
and measurement basis only.


## 9. Persistence boundary


Canonical:


- site geographic anchor;
- local coordinate-system definition;
- scene `coordinate_system_id`;
- map provider/source references needed for traceability;
- orthophoto georeference;
- engineering geometry in local metres.


UI-only:


- zoom;
- viewport centre;
- selected layer;
- visibility;
- opacity;
- camera;
- selected objects.


Simulation does not require map pixels, viewport state, or a live map provider.


## 10. Regression gate


Phase 4.1 tests prove:


- map zoom independence;
- geographic → local → geographic round-trip;
- true-north/project-rotation correctness;
- small rooftop dimensions;
- large ground-mounted site precision;
- continuity across a UTM-like zone boundary;
- Web-Mercator context round-trip and scale behavior;
- uploaded-orthophoto affine calibration;
- fail-closed degenerate orthophoto calibration;
- schema linkage between project site, scene coordinate-system ID, and map config.


## 11. Exit criterion


Phase 4.1 is complete when exact metric geometry can be persisted and reproduced
independently of map rendering.


Phase 4.2 may then implement the constrained 2D editor against this foundation.