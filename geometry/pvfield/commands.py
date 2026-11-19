"""Explicit Phase-4.3 PV packing commands.

Scene changes made elsewhere never trigger an automatic rebuild. Repacking occurs
only when one of these commands is explicitly invoked.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence

from geometry.scene.snapping import SnapEngine
from geometry.scene.surface_plane import module_center_z, module_position_z_basis

from .geometry import field_bounds
from .identity import placement_fingerprint
from .impact import layout_impact_report
from .manual import (
    MANUAL_LAYOUT_EDIT_VERSION,
    manual_module_edit_report,
)
from .models import PACKING_COMMAND_VERSION, ModuleFootprint, PackingResult
from .packing import (
    _field as _legacy_field,
    _surface,
    pack_field,
    packing_snap_edges,
    replace_field_layout,
    support_edge_azimuth,
    validate_field_layout,
)


def _field(scene, field_id):
    field = _legacy_field(scene, field_id)
    from .explicit import assert_generated_layout
    assert_generated_layout(field)
    return field


class PVFieldPackingSession:
    def __init__(
        self,
        scene: Mapping[str, Any],
        module_definitions: Mapping[str, Mapping[str, Any]],
        *,
        electrical_design: Mapping[str, Any] | None = None,
    ) -> None:
        self._scene = deepcopy(dict(scene))
        self._scene.setdefault("pv_fields", [])
        self._scene.setdefault("module_instances", [])
        self._module_definitions = {
            str(key): deepcopy(dict(value))
            for key, value in module_definitions.items()
        }
        self._electrical_design = (
            deepcopy(dict(electrical_design))
            if electrical_design is not None
            else None
        )
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []

    @property
    def scene(self) -> dict[str, Any]:
        return deepcopy(self._scene)

    @property
    def electrical_design(self) -> dict[str, Any] | None:
        return (
            deepcopy(self._electrical_design)
            if self._electrical_design is not None
            else None
        )

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def redo_depth(self) -> int:
        return len(self._redo)

    def _module_definition(self, revision_id: str) -> Mapping[str, Any]:
        try:
            return self._module_definitions[revision_id]
        except KeyError as exc:
            raise KeyError(
                f"module definition revision not available: {revision_id}"
            ) from exc

    def _module_instance(self, module_instance_id: str) -> dict[str, Any]:
        for module in self._scene.get("module_instances", []):
            if str(module.get("module_instance_id")) == module_instance_id:
                from .explicit import assert_generated_layout
                assert_generated_layout(_field(self._scene,str(module["pv_field_id"])))
                return module
        raise KeyError(f"module instance not found: {module_instance_id}")

    def _mark_manual_layout(
        self,
        field: dict[str, Any],
        module: dict[str, Any],
        *,
        edit_kind: str,
    ) -> None:
        from .explicit import assert_generated_layout
        assert_generated_layout(field)
        metadata = module.setdefault("metadata", {})
        if metadata.get("manual_position_override") is not True:
            metadata["pre_manual_placement_fingerprint"] = (
                metadata.get("placement_fingerprint")
                or placement_fingerprint(field, module)
            )
        metadata["manual_position_override"] = True
        metadata["manual_edit_version"] = MANUAL_LAYOUT_EDIT_VERSION
        metadata["manual_edit_kind"] = edit_kind
        metadata["placement_fingerprint"] = placement_fingerprint(
            field, module
        )
        metadata["identity_origin"] = "manual_edit_preserved"

        field_metadata = field.setdefault("metadata", {})
        if field.get("packing_input_hash") is not None:
            field_metadata.setdefault(
                "last_generated_packing_input_hash",
                field.get("packing_input_hash"),
            )
        field_metadata["manual_edit_version"] = MANUAL_LAYOUT_EDIT_VERSION
        field_metadata["row_layouts_status"] = "generated_lineage_only"
        field["layout_source"] = "generated_then_edited"
        field["layout_status"] = "manual"
        # The current layout is no longer the direct output represented by the
        # previous packing hash. Keep that hash only as provenance metadata.
        field["packing_input_hash"] = None

    def _mutate(self, operation):
        before = deepcopy(self._scene)
        try:
            result = operation()
        except Exception:
            self._scene = before
            raise
        self._undo.append(before)
        self._redo.clear()
        return result

    def undo(self) -> bool:
        if not self._undo:
            return False
        previous = self._undo.pop()
        self._redo.append(deepcopy(self._scene))
        self._scene = previous
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        following = self._redo.pop()
        self._undo.append(deepcopy(self._scene))
        self._scene = following
        return True

    def create_field(
        self,
        *,
        pv_field_id: str,
        name: str,
        support_surface_id: str,
        module_definition_revision_id: str,
        orientation: str,
        azimuth_deg: float,
        tilt_deg: float,
        module_gap_x_m: float,
        module_gap_y_m: float,
        row_pitch_m: float,
        mounting_height_m: float,
        perimeter_setback_m: float = 0.0,
        obstacle_setback_m: float = 0.0,
        table_configuration: Mapping[str, Any] | None = None,
        exclusion_rules: Mapping[str, Any] | None = None,
        row_alignment: str = "start",
        requested_row_count: int | None = None,
        requested_modules_per_row: int | None = None,
        rows_per_table: int | None = None,
        leftover_depth: str | None = None,
        depth_alignment: str | None = None,
    ) -> dict[str, Any]:
        if row_alignment not in {"start", "center", "end"} or depth_alignment not in {None, "start", "center", "end"}:
            raise ValueError("alignment must be start, center, or end")

        def operation() -> dict[str, Any]:
            if any(
                item.get("pv_field_id") == pv_field_id
                for item in self._scene["pv_fields"]
            ):
                raise ValueError(f"duplicate pv_field_id: {pv_field_id}")
            _surface(self._scene, support_surface_id)
            module = self._module_definition(
                module_definition_revision_id
            )
            footprint = ModuleFootprint.from_definition(
                module, orientation, float(tilt_deg)
            )
            parameters: dict[str, Any] = {
                "row_alignment": row_alignment
            }
            if depth_alignment is not None:
                parameters["depth_alignment"] = depth_alignment
            if requested_row_count is not None:
                parameters["requested_row_count"] = int(
                    requested_row_count
                )
            if requested_modules_per_row is not None:
                parameters["requested_modules_per_row"] = int(
                    requested_modules_per_row
                )
            table = deepcopy(dict(table_configuration)) if table_configuration is not None else None
            rows = rows_per_table if rows_per_table is not None else (table or {}).get("rows_per_table", 1)
            leftover = leftover_depth if leftover_depth is not None else (table or {}).get("leftover_depth", "smaller_table")
            if type(rows) is not int or not 1 <= rows <= 10:
                raise ValueError("rows_per_table must be an integer from 1 to 10")
            if leftover not in {"smaller_table", "smaller_table_front", "leave_empty"}:
                raise ValueError("unsupported leftover_depth")
            if rows > 1:
                table = {**(table or {}), "rows_per_table": rows, "leftover_depth": leftover}
            elif table is not None:
                had_table_rows = "rows_per_table" in table or "leftover_depth" in table
                table.pop("rows_per_table", None)
                table.pop("leftover_depth", None)
                if had_table_rows and not table:
                    table = None
            field = {
                "pv_field_id": pv_field_id,
                "scene_id": self._scene["scene_id"],
                "name": name,
                "support_surface_id": support_surface_id,
                "module_definition_revision_id": (
                    module_definition_revision_id
                ),
                "orientation": orientation,
                "azimuth_deg": float(azimuth_deg) % 360.0,
                "tilt_deg": float(tilt_deg),
                "mounting_height_m": float(mounting_height_m),
                "layout_mode": "deterministic_grid",
                "row_count": 0,
                "modules_per_row": 0,
                "module_gap_x_m": float(module_gap_x_m),
                "module_gap_y_m": float(module_gap_y_m),
                "row_pitch_m": float(row_pitch_m),
                "table_configuration": table,
                "boundary_constraint_id": support_surface_id,
                "setback_configuration": {
                    "perimeter_setback_m": float(
                        perimeter_setback_m
                    ),
                    "edge_specific_setbacks": None,
                    "obstacle_setback_m": float(
                        obstacle_setback_m
                    ),
                    "walkway_rules": {
                        "treat_walkway_surfaces_as_exclusions": True
                    },
                },
                "exclusion_rules": deepcopy(
                    dict(
                        exclusion_rules
                        or {
                            "use_scene_exclusion_surfaces": True,
                            "surface_types": [
                                "exclusion_area",
                                "walkway",
                            ],
                            "use_scene_obstacles": True,
                            "surface_ids": [],
                            "obstacle_ids": [],
                        }
                    )
                ),
                "packing_parameters": parameters,
                "module_footprint": footprint.to_mapping(),
                "packing_command_version": PACKING_COMMAND_VERSION,
                "generated_module_instance_ids": [],
                "row_layouts": [],
                "layout_source": "manual",
                "layout_status": "unpacked",
                "resolved_exclusion_ids": [],
                "packing_input_hash": None,
                "notes": None,
            }
            from .explicit import assert_packable_field
            assert_packable_field(self._scene, field)
            self._scene["pv_fields"].append(field)
            return deepcopy(field)

        return self._mutate(operation)

    def update_field(
        self, pv_field_id: str, *, orientation=None, azimuth_deg=None,
        tilt_deg=None, mounting_height_m=None, module_gap_x_m=None,
        module_gap_y_m=None, row_pitch_m=None, perimeter_setback_m=None,
        obstacle_setback_m=None, module_definition_revision_id=None, rows_per_table=None, leftover_depth=None,
        row_alignment=None, depth_alignment=None,
    ) -> dict[str, Any]:
        changes = {key: value for key, value in {
            "orientation": orientation, "azimuth_deg": azimuth_deg,
            "tilt_deg": tilt_deg, "mounting_height_m": mounting_height_m,
            "module_gap_x_m": module_gap_x_m, "module_gap_y_m": module_gap_y_m,
            "row_pitch_m": row_pitch_m, "perimeter_setback_m": perimeter_setback_m,
            "obstacle_setback_m": obstacle_setback_m, "rows_per_table": rows_per_table, "leftover_depth": leftover_depth,
            "module_definition_revision_id": module_definition_revision_id,
            "row_alignment": row_alignment, "depth_alignment": depth_alignment,
        }.items() if value is not None}

        def operation():
            original = deepcopy(self._scene)
            field = next((item for item in original["pv_fields"] if item["pv_field_id"] == pv_field_id), None)
            if field is None:
                raise ValueError(f"PV field not found: {pv_field_id}")
            from .explicit import assert_generated_layout
            assert_generated_layout(field)
            if changes.get("module_definition_revision_id") == field["module_definition_revision_id"]:
                changes.pop("module_definition_revision_id")
            if not changes:
                raise ValueError("field update requires at least one parameter")
            scalars = ("orientation", "azimuth_deg", "tilt_deg", "mounting_height_m",
                       "module_gap_x_m", "module_gap_y_m", "row_pitch_m")
            parameters = {key: field[key] for key in scalars}
            setback = field.get("setback_configuration") or {}
            parameters.update({key: setback.get(key, 0.0) for key in (
                "perimeter_setback_m", "obstacle_setback_m"
            )})
            parameters.update({key: value for key, value in changes.items() if key != "module_definition_revision_id"})
            scratch = deepcopy(original)
            scratch["pv_fields"] = [item for item in scratch["pv_fields"] if item["pv_field_id"] != pv_field_id]
            scratch["module_instances"] = [item for item in scratch["module_instances"] if item["pv_field_id"] != pv_field_id]
            temporary = PVFieldPackingSession(scratch, self._module_definitions)
            packing = field.get("packing_parameters") or {}
            aligned = {key: parameters.pop(key) for key in ("row_alignment", "depth_alignment") if key in parameters}
            validated = temporary.create_field(
                pv_field_id=pv_field_id, name=field["name"],
                support_surface_id=field["support_surface_id"],
                module_definition_revision_id=changes.get("module_definition_revision_id", field["module_definition_revision_id"]),
                table_configuration=field.get("table_configuration"),
                exclusion_rules=field.get("exclusion_rules"),
                row_alignment=aligned.get("row_alignment", packing.get("row_alignment", "start")),
                depth_alignment=aligned.get("depth_alignment", packing.get("depth_alignment")),
                requested_row_count=packing.get("requested_row_count"),
                requested_modules_per_row=packing.get("requested_modules_per_row"),
                **parameters,
            )
            candidate = deepcopy(field)
            candidate.update({key: validated[key] for key in (*scalars, "module_definition_revision_id", "module_footprint", "table_configuration")})
            if aligned:  # only an alignment change rewrites the stored packing parameters
                candidate["packing_parameters"] = validated["packing_parameters"]
            candidate.setdefault("setback_configuration", {}).update({
                key: validated["setback_configuration"][key]
                for key in ("perimeter_setback_m", "obstacle_setback_m")
            })
            temporary._scene["pv_fields"][-1] = candidate
            result = temporary._repack(pv_field_id)
            generated = temporary.scene
            # Match against the untouched identity basis, never the edited field.
            replacement = PackingResult(
                pv_field=_field(generated, pv_field_id),
                module_instances=tuple(item for item in generated["module_instances"] if item["pv_field_id"] == pv_field_id),
                rejected_candidate_count=result["rejected_candidate_count"],
                packing_input_hash=result["packing_input_hash"],
            )
            self._scene = replace_field_layout(original, replacement)
            result["layout_impact"] = layout_impact_report(
                original, self._scene, pv_field_id, electrical_design=self._electrical_design,
            )
            return result

        return self._mutate(operation)

    def delete_field(self, pv_field_id: str) -> dict[str, Any]:
        def operation():
            if not any(item["pv_field_id"] == pv_field_id for item in self._scene["pv_fields"]):
                raise ValueError(f"PV field not found: {pv_field_id}")
            removed = sorted(item["module_instance_id"] for item in self._scene["module_instances"]
                             if item["pv_field_id"] == pv_field_id)
            self._scene["pv_fields"] = [item for item in self._scene["pv_fields"] if item["pv_field_id"] != pv_field_id]
            self._scene["module_instances"] = [item for item in self._scene["module_instances"] if item["pv_field_id"] != pv_field_id]
            return {"pv_field_id": pv_field_id, "removed_module_instance_ids": removed}

        return self._mutate(operation)

    def _repack(self, pv_field_id: str) -> dict[str, Any]:
        before_scene = deepcopy(self._scene)
        field = _field(self._scene, pv_field_id)
        from .explicit import assert_packable_field
        assert_packable_field(self._scene, field)
        module = self._module_definition(
            str(field["module_definition_revision_id"])
        )
        result = pack_field(self._scene, field, module)
        self._scene = replace_field_layout(self._scene, result)
        impact = layout_impact_report(
            before_scene,
            self._scene,
            pv_field_id,
            electrical_design=self._electrical_design,
        )
        return {
            "pv_field_id": pv_field_id,
            "module_count": result.module_count,
            "rejected_candidate_count": (
                result.rejected_candidate_count
            ),
            "packing_input_hash": result.packing_input_hash,
            "layout_impact": impact,
        }

    def fill_area(self, pv_field_id: str) -> dict[str, Any]:
        return self._mutate(lambda: self._repack(pv_field_id))

    def rebuild_field(self, pv_field_id: str) -> dict[str, Any]:
        return self._mutate(lambda: self._repack(pv_field_id))

    def change_orientation(
        self,
        pv_field_id: str,
        orientation: str,
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            field = _field(self._scene, pv_field_id)
            module = self._module_definition(
                str(field["module_definition_revision_id"])
            )
            ModuleFootprint.from_definition(
                module, orientation, float(field.get("tilt_deg", 0.0))
            )
            field["orientation"] = orientation
            return self._repack(pv_field_id)

        return self._mutate(operation)

    def orient_to_edge(
        self,
        pv_field_id: str,
        *,
        edge_index: int,
        alignment_axis: str = "row",
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            field = _field(self._scene, pv_field_id)
            edge_azimuth = support_edge_azimuth(
                self._scene,
                str(field["support_surface_id"]),
                edge_index,
            )
            if alignment_axis == "row":
                field["azimuth_deg"] = (
                    edge_azimuth - 90.0
                ) % 360.0
            elif alignment_axis == "column":
                field["azimuth_deg"] = edge_azimuth
            else:
                raise ValueError(
                    "alignment_axis must be row or column"
                )
            return self._repack(pv_field_id)

        return self._mutate(operation)

    def align_rows(
        self,
        pv_field_id: str,
        *,
        alignment: str,
    ) -> dict[str, Any]:
        if alignment not in {"start", "center", "end"}:
            raise ValueError(
                "alignment must be start, center, or end"
            )

        def operation() -> dict[str, Any]:
            field = _field(self._scene, pv_field_id)
            field.setdefault("packing_parameters", {})[
                "row_alignment"
            ] = alignment
            return self._repack(pv_field_id)

        return self._mutate(operation)

    def equalize_spacing(
        self,
        pv_field_id: str,
        *,
        axis: str,
    ) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            field = _field(self._scene, pv_field_id)
            support = _surface(
                self._scene, str(field["support_surface_id"])
            )
            vertices = [
                tuple(point)
                for point in support["boundary_2d"]["vertices"]
            ]
            min_x, min_y, max_x, max_y = field_bounds(
                vertices, float(field["azimuth_deg"])
            )
            footprint = ModuleFootprint.from_definition(
                self._module_definition(
                    str(field["module_definition_revision_id"])
                ),
                str(field["orientation"]),
                float(field.get("tilt_deg", 0.0)),
            )
            setback = float(
                (field.get("setback_configuration") or {}).get(
                    "perimeter_setback_m"
                )
                or 0.0
            )
            if axis == "horizontal":
                count = int(
                    field.get("modules_per_row") or 0
                )
                if count <= 1:
                    raise ValueError(
                        "horizontal equal spacing requires at least two modules per row"
                    )
                usable = max_x - min_x - 2.0 * setback
                gap = (
                    usable
                    - count * footprint.plan_projection_width_m
                ) / (count - 1)
                if gap < -1e-12:
                    raise ValueError(
                        "current module count cannot fit the support width"
                    )
                field["module_gap_x_m"] = max(0.0, gap)
            elif axis == "rows":
                count = int(field.get("row_count") or 0)
                if count <= 1:
                    raise ValueError(
                        "row equal spacing requires at least two rows"
                    )
                usable = max_y - min_y - 2.0 * setback
                pitch = (
                    usable - footprint.plan_projection_height_m
                ) / (count - 1)
                minimum = (
                    footprint.plan_projection_height_m
                    + float(field["module_gap_y_m"])
                )
                if pitch < minimum - 1e-12:
                    raise ValueError(
                        "equal row spacing would violate module_gap_y_m"
                    )
                field["row_pitch_m"] = pitch
            else:
                raise ValueError(
                    "axis must be horizontal or rows"
                )
            return self._repack(pv_field_id)

        return self._mutate(operation)

    def find_maximum_modules(
        self,
        pv_field_id: str,
        *,
        orientations: Sequence[str] = (
            "portrait",
            "landscape",
        ),
    ) -> dict[str, Any]:
        """Advisory only; no engineering state is mutated."""
        current = _field(self._scene, pv_field_id)
        from .explicit import assert_packable_field
        assert_packable_field(self._scene,current)
        proposals: list[dict[str, Any]] = []
        for orientation in orientations:
            candidate = deepcopy(current)
            candidate["orientation"] = orientation
            module = self._module_definition(
                str(candidate["module_definition_revision_id"])
            )
            try:
                result = pack_field(
                    self._scene, candidate, module
                )
            except ValueError as exc:
                proposals.append(
                    {
                        "orientation": orientation,
                        "valid": False,
                        "reason": str(exc),
                        "module_count": None,
                        "row_count": None,
                        "modules_per_row": None,
                        "packing_input_hash": None,
                    }
                )
                continue
            proposals.append(
                {
                    "orientation": orientation,
                    "valid": True,
                    "reason": None,
                    "module_count": result.module_count,
                    "row_count": result.pv_field["row_count"],
                    "modules_per_row": result.pv_field[
                        "modules_per_row"
                    ],
                    "packing_input_hash": (
                        result.packing_input_hash
                    ),
                }
            )
        proposals.sort(
            key=lambda item: (
                item["valid"] is False,
                -int(item["module_count"] or 0),
                str(item["orientation"]),
            )
        )
        return {
            "pv_field_id": pv_field_id,
            "suggestion_type": "maximum_module_count",
            "proposals": proposals,
            "current_orientation": current["orientation"],
            "engineering_state_mutated": False,
        }

    def remove_modules(self, module_instance_ids: Sequence[str]) -> dict[str, Any]:
        """Remove explicit placements in one undo step, retaining field lineage."""
        ids = set(module_instance_ids)
        if not ids:
            raise ValueError("module_instance_ids must not be empty")

        def operation() -> dict[str, Any]:
            by_id = {
                str(module["module_instance_id"]): module
                for module in self._scene["module_instances"]
            }
            unknown = ids - by_id.keys()
            if unknown:
                raise ValueError(f"module instances not found: {sorted(unknown)}")
            affected = sorted({str(by_id[value]["pv_field_id"]) for value in ids})
            for field_id in affected:
                representative = next(
                    by_id[value] for value in sorted(ids)
                    if str(by_id[value]["pv_field_id"]) == field_id
                )
                # Reuse the manual-edit marker on a removed placement so every
                # surviving module remains byte-for-byte unchanged.
                self._mark_manual_layout(
                    _field(self._scene, field_id), representative,
                    edit_kind="remove_modules",
                )
            self._scene["module_instances"] = [
                module for module in self._scene["module_instances"]
                if str(module["module_instance_id"]) not in ids
            ]
            return {"removed_module_instance_ids": sorted(ids), "pv_field_ids": affected}

        return self._mutate(operation)

    def move_modules(self, module_instance_ids: Sequence[str], dx_m: float, dy_m: float) -> dict[str, Any]:
        """Translate explicit placements rigidly, without snapping, in one undo step."""
        import math

        ids = list(module_instance_ids)
        if not ids or len(set(ids)) != len(ids):
            raise ValueError("module_instance_ids must be nonempty and unique")
        dx, dy = float(dx_m), float(dy_m)
        if not all(math.isfinite(value) for value in (dx, dy)):
            raise ValueError("module move delta must be finite")

        def operation() -> dict[str, Any]:
            by_id = {str(module["module_instance_id"]): module for module in self._scene["module_instances"]}
            unknown = set(ids) - by_id.keys()
            if unknown:
                raise ValueError(f"module instances not found: {sorted(unknown)}")
            affected = set()
            for module_id in ids:
                module = by_id[module_id]
                field = _field(self._scene, str(module["pv_field_id"]))
                transform = module["transform"]
                transform["position_x_m"] = float(transform["position_x_m"]) + dx
                transform["position_y_m"] = float(transform["position_y_m"]) + dy
                support = _surface(self._scene, str(field["support_surface_id"]))
                transform["position_z_m"] = module_center_z(
                    support, transform["position_x_m"], transform["position_y_m"], float(field["mounting_height_m"]),
                    field=field, table_row_offset=(module.get("metadata") or {}).get("table_row_offset", 0),
                )
                module.setdefault("metadata", {})["position_z_basis"] = module_position_z_basis(module)
                self._mark_manual_layout(field, module, edit_kind="move")
                affected.add(str(field["pv_field_id"]))
            return {"moved_module_instance_ids": ids, "pv_field_ids": sorted(affected)}

        return self._mutate(operation)

    def fill_move_modules(self, module_instance_ids: Sequence[str], dx_m: float, dy_m: float) -> dict[str, Any]:
        """Apply a pure drop-fill plan in one undo step, retaining placed identities."""
        from .drop_fill import drop_fill

        def operation():
            fields = {str(self._module_instance(mid)["pv_field_id"]) for mid in module_instance_ids}
            if len(fields) != 1:
                from .drop_fill import DropFillError
                raise DropFillError("drop_fill_one_field", "Fill works within one field.")
            field = _field(self._scene, next(iter(fields)))
            plan = drop_fill(self._scene, field, self._module_definition(str(field["module_definition_revision_id"])), module_instance_ids, dx_m, dy_m)
            for mid, placement in plan["placements"].items():
                module = self._module_instance(mid)
                module["transform"] = deepcopy(placement["transform"])
                for key in ("row_index", "column_index", "table_index"):
                    module[key] = placement[key]
                module.setdefault("metadata", {}).update(placement["metadata"])
                module["metadata"]["position_z_basis"] = module_position_z_basis(module)
                self._mark_manual_layout(field, module, edit_kind="move_fill")
            removed = set(plan["removed_ids"])
            self._scene["module_instances"] = [m for m in self._scene["module_instances"] if m["module_instance_id"] not in removed]
            return plan

        return self._mutate(operation)

    def move_module(
        self,
        module_instance_id: str,
        *,
        target_x_m: float,
        target_y_m: float,
        snap_tolerance_m: float | None = None,
        snap_kinds: Iterable[str] | None = None,
        grid_spacing_m: float | None = None,
        snap_override: bool = False,
    ) -> dict[str, Any]:
        """Explicitly move one existing module while preserving its identity."""
        module = self._module_instance(module_instance_id)
        field = _field(self._scene, str(module["pv_field_id"]))
        before_transform = deepcopy(module["transform"])
        raw = (float(target_x_m), float(target_y_m))
        resolved = raw
        snap_mapping = None

        if snap_tolerance_m is not None:
            supplemental = packing_snap_edges(self._scene)
            snapper = SnapEngine(
                self._scene,
                supplemental_edges=supplemental,
                exclude_entity_ids={module_instance_id},
            )
            kwargs: dict[str, Any] = {
                "tolerance_m": float(snap_tolerance_m),
                "override": bool(snap_override),
                "grid_spacing_m": grid_spacing_m,
            }
            if snap_kinds is not None:
                kwargs["enabled_kinds"] = tuple(snap_kinds)
            snap_result = snapper.resolve(raw, **kwargs)
            resolved = snap_result.snapped_point
            snap_mapping = {
                "applied": snap_result.applied,
                "kind": snap_result.kind,
                "source_entity_id": snap_result.source_entity_id,
                "feature_index": snap_result.feature_index,
                "raw_point": [raw[0], raw[1]],
                "snapped_point": [
                    snap_result.snapped_point[0],
                    snap_result.snapped_point[1],
                ],
                "distance_m": snap_result.distance_m,
                "visible_marker": snap_result.visible_marker,
            }

        def operation() -> dict[str, Any]:
            target = self._module_instance(module_instance_id)
            target_field = _field(
                self._scene, str(target["pv_field_id"])
            )
            target["transform"]["position_x_m"] = float(resolved[0])
            target["transform"]["position_y_m"] = float(resolved[1])
            support = _surface(
                self._scene, str(target_field["support_surface_id"])
            )
            target["transform"]["position_z_m"] = module_center_z(
                support,
                float(resolved[0]),
                float(resolved[1]),
                float(target_field["mounting_height_m"]),
                field=target_field, table_row_offset=(target.get("metadata") or {}).get("table_row_offset", 0),
            )
            target.setdefault("metadata", {})[
                "position_z_basis"
            ] = module_position_z_basis(target)
            self._mark_manual_layout(
                target_field,
                target,
                edit_kind="move",
            )
            return manual_module_edit_report(
                self._scene,
                pv_field_id=str(target["pv_field_id"]),
                module_instance_id=module_instance_id,
                edit_kind="move",
                before_transform=before_transform,
                electrical_design=self._electrical_design,
                snap=snap_mapping,
            )

        return self._mutate(operation)

    def rotate_module(
        self,
        module_instance_id: str,
        *,
        azimuth_deg: float,
    ) -> dict[str, Any]:
        """Explicitly change one module plan azimuth while preserving identity."""
        module = self._module_instance(module_instance_id)
        before_transform = deepcopy(module["transform"])
        azimuth = float(azimuth_deg) % 360.0

        def operation() -> dict[str, Any]:
            target = self._module_instance(module_instance_id)
            target_field = _field(
                self._scene, str(target["pv_field_id"])
            )
            target["transform"]["rotation_z_deg"] = azimuth
            self._mark_manual_layout(
                target_field,
                target,
                edit_kind="rotate",
            )
            return manual_module_edit_report(
                self._scene,
                pv_field_id=str(target["pv_field_id"]),
                module_instance_id=module_instance_id,
                edit_kind="rotate",
                before_transform=before_transform,
                electrical_design=self._electrical_design,
            )

        return self._mutate(operation)

    def conflict_report(
        self, pv_field_id: str
    ) -> dict[str, Any]:
        return validate_field_layout(
            self._scene, pv_field_id
        )

    def snap_edges(self):
        return packing_snap_edges(self._scene)
