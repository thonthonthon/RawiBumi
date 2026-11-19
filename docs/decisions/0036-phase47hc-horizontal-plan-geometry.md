# ADR 0036 — Canonical PV geometry uses horizontal plan XY and support-derived center Z

**Status:** Accepted  
**Date:** 2026-09-24

## Context

Phase 4 already uses local engineering X=East-like horizontal, Y=North-like horizontal and Z=Up coordinates.

PV packing originally treated component physical width/height directly as the 2-D footprint even when the module was tilted. Generated 3-D also used those stored packing dimensions as physical plane dimensions. On sloped surfaces, generated ModuleInstance Z used support base elevation rather than the support plane elevation at module XY.

These behaviors could make the 2-D footprint, canonical Z and derived 3-D geometry disagree.

## Decision

1. Scene boundary_2d remains a horizontal engineering-plan projection.
2. No hidden support-surface UV canonical editing frame is introduced.
3. ModuleInstance X/Y are horizontal engineering-plan center coordinates.
4. ModuleInstance Z is canonical center elevation.
5. Canonical module center Z equals support-plane elevation at module XY plus PVField.mounting_height_m.
6. mounting_height_m is a vertical Z offset, not surface-normal distance.
7. Canonical Scene editing re-synchronizes module Z after support-geometry changes without changing X/Y or identity.
8. Physical module-plane dimensions come from component mechanical dimensions and portrait/landscape orientation.
9. 2-D packing uses the horizontal projection of that physical plane.
10. For the current one-axis tilt convention, projected width equals oriented plane width and projected height equals oriented plane height × cos(tilt).
11. Module gaps, row pitch and setbacks are horizontal-plan distances in v0.1.
12. 90° module tilt is representable in canonical data but unsupported for area packing because its horizontal projected height is zero.
13. GeneratedScene3D uses canonical ModuleInstance Z and independently reports any residual from the expected support-derived Z.
14. GeneratedScene3D uses full physical module dimensions and exposes the XY projection of its 3-D corners.
15. Legacy support_surface_2d footprints remain readable and are reconstructed into the new projection semantics.
16. Z remains outside generated ModuleInstance identity because it is derived from the same object's support relationship.

## Consequences

2-D and 3-D now describe the same physical module geometry.

Map/survey geometry remains directly usable without a second coordinate system.

Support edits do not silently repack fields, while module elevation remains internally coherent.

Phase 5 near-shading can consume 3-D geometry without inheriting a known 2-D projection mismatch.
