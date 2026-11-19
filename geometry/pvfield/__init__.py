"""Phase-4.3 deterministic PV field packing APIs."""

from .commands import PVFieldPackingSession
from .geometry import (
    edge_azimuth_deg,
    field_bounds,
    field_to_scene,
    point_in_polygon,
    polygon_contains_polygon,
    polygon_distance,
    polygons_overlap_or_touch,
    rectangle_polygon,
    scene_to_field,
)
from .identity import (
    MODULE_IDENTITY_VERSION,
    MODULE_REPLACEMENT_IDENTITY_VERSION,
    generated_module_id,
    packing_slot_key,
    placement_fingerprint,
    replacement_generated_module_id,
)
from .impact import (
    LAYOUT_IMPACT_VERSION,
    layout_impact_report,
)
from .manual import (
    MANUAL_LAYOUT_EDIT_VERSION,
    affected_string_memberships,
    manual_module_edit_report,
)
from .models import (
    ModuleFootprint,
    PACKING_COMMAND_VERSION,
    PACKING_GEOMETRY_BASIS,
    PackingConflict,
    PackingResult,
)
from .packing import (
    pack_field,
    packing_input_hash,
    packing_snap_edges,
    replace_field_layout,
    support_edge_azimuth,
    validate_field_layout,
)

__all__ = [
    "LAYOUT_IMPACT_VERSION",
    "MANUAL_LAYOUT_EDIT_VERSION",
    "MODULE_IDENTITY_VERSION",
    "MODULE_REPLACEMENT_IDENTITY_VERSION",
    "ModuleFootprint",
    "PACKING_COMMAND_VERSION",
    "PACKING_GEOMETRY_BASIS",
    "PVFieldPackingSession",
    "PackingConflict",
    "PackingResult",
    "affected_string_memberships",
    "edge_azimuth_deg",
    "field_bounds",
    "field_to_scene",
    "generated_module_id",
    "layout_impact_report",
    "manual_module_edit_report",
    "pack_field",
    "packing_slot_key",
    "packing_input_hash",
    "packing_snap_edges",
    "point_in_polygon",
    "polygon_contains_polygon",
    "polygon_distance",
    "placement_fingerprint",
    "polygons_overlap_or_touch",
    "rectangle_polygon",
    "replacement_generated_module_id",
    "replace_field_layout",
    "scene_to_field",
    "support_edge_azimuth",
    "validate_field_layout",
]
