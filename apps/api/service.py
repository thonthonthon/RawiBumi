"""Phase-6.0C product-shell service over existing canonical engineering kernels."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4
from zoneinfo import ZoneInfo

from components.design_integration import module_nameplate_w
from electrical.topology import (
    ElectricalTopologyEditorSession,
    canonical_electrical_hash,
    new_electrical_design,
)
from geometry.coordinates import LocalCoordinateSystem, LocalPoint
from geometry.pvfield import (
    ModuleFootprint,
    PVFieldPackingSession,
    rectangle_polygon,
    polygons_overlap_or_touch,
)
from geometry.scene import SceneEditorSession, canonical_scene_hash
from geometry.pvfield.scene_layout import validate_scene_layout
from geometry.pvfield.packing import _resolved_exclusions
from geometry.pvfield.impact import layout_impact_report
from geometry.shading import GroundDomeResolution, SkyDomeResolution, compile_shading_geometry
from engine.module import MODULE_PVSYST_SDM
from engine.simulation.shading_accuracy import (default_shading_accuracy, resolve_shading_accuracy, patch_shading_accuracy)
from engine.simulation.optics_thermal import default_optics_thermal_settings, resolve_optics_thermal_settings, patch_optics_thermal_settings
from engine.losses.settings import default_loss_settings, patch_loss_settings, resolve_loss_settings
from engine.simulation.models.module_resolver import resolve_module_model
from shading.electrical import (
    build_module_equivalent_irradiance_from_module_shading,
    derive_electrical_region_map,
    evaluate_level1_module_approximation,
    evaluate_module_receiver_visibility,
)

from .catalog import catalog_summaries, load_reference_catalog
from .component_library import ComponentLibraryStore
from .electrical_shading_state import (
    assert_electrical_shading_selection_state,
    ensure_electrical_shading_bundle_state,
    import_project_electrical_shading_asset,
    resolve_project_module_electrical_shading_capability,
    set_project_module_electrical_shading_selection,
)
from .project_store import FileProjectStore, ProjectNotFoundError
from .history import DesignHistory, SCENE_ENVELOPE, ELECTRICAL_ENVELOPE, OPTIONAL_KEYS, FINGERPRINT_EXCLUDED_SITE_KEYS, design_fingerprint, validate_restored_bundle
from .imagery import ImageryAssetStore, validate_imagery
from .live_checks import topology_checks
from .migrations import CURRENT_SCHEMA_VERSION, migrate


# Reviewed cloned-entity keys that reference other scene entities (UX2 copy audit).
COPY_CLEARED_KEYS = ("parent_surface_id", "group_id")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _token(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


def _number(value: Any, name: str) -> float:
    try:
        resolved = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    return resolved


class ProjectConflictError(RuntimeError):
    pass


class TopologyConsistencyError(ValueError):
    """An electrical batch that still needs structural repairs before commit."""

    def __init__(self, message, findings):
        super().__init__(message)
        self.findings = deepcopy(findings)


class GeometryConflictError(ValueError):
    """A rejected draft with structured, reviewable geometry conflicts."""

    def __init__(self, message, conflicts, options=None):
        super().__init__(message)
        self.conflicts = deepcopy(conflicts)
        self.options = deepcopy(options)


class DependentFieldError(ValueError):
    """A refused opt-in support edit, with its dependent-field impact."""

    def __init__(self, message, dependent_fields):
        super().__init__(message)
        self.dependent_fields = deepcopy(dependent_fields)


class ProjectShellService:
    """Minimal product service.

    This class owns persistence/orchestration only. Scene, packing, coordinate and
    topology calculations stay in the established RawiBumi domain kernels.
    """

    def __init__(self, store: FileProjectStore, *, library_root: str | Path | None = None) -> None:
        self.store = store
        self.history = DesignHistory()
        self.imagery = ImageryAssetStore(store.root.parent / "imagery")
        self.library = ComponentLibraryStore(library_root if library_root is not None else store.root.parent / "component-library")
        self._reference_catalog = load_reference_catalog()
        self.refresh_catalog()

    def refresh_catalog(self) -> None:
        with self.library._lock:
            catalog = deepcopy(self._reference_catalog)
            entries = self.library.entries(include_hidden=True)
            for entry in entries:
                kind, definition = entry["kind"], entry["definition"]
                revision_id = definition["revision_id"]
                assert revision_id.startswith("lib-") and revision_id not in catalog[kind], "Component catalogue revision collision"
                catalog[kind][revision_id] = deepcopy(definition)
            self.catalog = catalog
            self._library_entries = {entry["definition"]["revision_id"]: entry for entry in entries}

    def catalog_view(self) -> dict[str, Any]:
        return catalog_summaries(self.catalog, library_entries=self._library_entries)

    def _project_catalog_view(self, bundle: dict[str, Any]) -> dict[str, Any]:
        # Global visibility does not remove the definitions an existing project owns.
        # This is a derived view only: pins, library files and the global catalogue stay unchanged.
        catalog = deepcopy(self.catalog)
        pinned_ids = set()
        for kind in ("modules", "inverters"):
            for revision_id, definition in (bundle.get("pinned_components") or {}).get(kind, {}).items():
                if revision_id.startswith("lib-"):
                    catalog[kind][revision_id] = deepcopy(definition)
                    pinned_ids.add(revision_id)
        return catalog_summaries(catalog, library_entries=self._library_entries, pinned_revision_ids=pinned_ids)

    def list_projects(self) -> list[dict[str, Any]]:
        return self.store.list()

    def project_summary(self, project_id: str) -> dict[str, Any]:
        """USE3b: one project's system summary for the projects page (PV, inverters, last successful run)."""
        from .project_store import project_system_summary

        return project_system_summary(self.get_bundle(project_id))

    def _touch(self, bundle: dict[str, Any]) -> None:
        bundle["updated_at"] = _now()

    def _save(self, bundle: dict[str, Any], *, expect_new: bool = False, history_mode: str = "edit",
              history_label: str | None = None) -> dict[str, Any]:
        with self.store._lock:
            expected_updated_at = bundle.get("updated_at")
            project_id = str(bundle["project"]["project_id"])
            current = None
            try:
                current = self.store.load(project_id)
            except ProjectNotFoundError:
                if not expect_new:
                    raise
            else:
                if expect_new or current.get("updated_at") != expected_updated_at:
                    raise ProjectConflictError("project changed concurrently; reload and retry")
            ensure_electrical_shading_bundle_state(bundle)
            assert_electrical_shading_selection_state(bundle)
            revision = bundle["project"]["project_revision"]
            summary = revision.get("change_summary") or "Edit design"
            if current and current["project"]["project_revision"].get("project_revision_id") == revision.get("project_revision_id"):
                # No new revision: the stored summary describes an earlier edit.
                summary = history_label or "Edit design"
            if current and current["project"].get("name") != bundle["project"].get("name"):
                summary = "Rename project"
            staged = self.history.prepare(project_id, current, bundle, summary, mode=history_mode)
            self._touch(bundle)
            saved = self.store.save(bundle)
            self.history.publish(project_id, staged)
            return saved

    def _project_revision_id(self, bundle: dict[str, Any]) -> str:
        return str(bundle["project"]["project_revision"]["project_revision_id"])

    def restore_history(self, project_id, *, redo=False, expected_project_revision_id, expected_entry_id,
                        require_idle=None, weather_store=None):
        """Restore exact design content with fresh revision envelopes; never restore runs."""
        from jsonschema import ValidationError
        from .weather_store import FileWeatherRevisionStore, WeatherRevisionNotFoundError
        with self.store._lock:
            current = self.get_bundle(project_id)
            target, label, staged = self.history.target(project_id, current, redo=redo,
                expected_project_revision_id=expected_project_revision_id, expected_entry_id=expected_entry_id)
            draft = deepcopy(current)
            for key in OPTIONAL_KEYS:
                if key in target:
                    draft[key] = deepcopy(target[key])
                else:
                    draft.pop(key, None)
            for key, excluded in (("project", {"project_revision"}), ("scene", SCENE_ENVELOPE),
                                  ("electrical_design", ELECTRICAL_ENVELOPE), ("site_workspace_bootstrap", {"workspace_context"})):
                draft[key] = {**deepcopy(target[key]), **{k: deepcopy(v) for k, v in current[key].items() if k in excluded}}
            for key in FINGERPRINT_EXCLUDED_SITE_KEYS:
                if key in current["project"]["site"]:
                    draft["project"]["site"][key] = deepcopy(current["project"]["site"][key])
                else:
                    draft["project"]["site"].pop(key, None)
            for key in ("project_id", "schema_name", "schema_version"):
                if draft["project"].get(key) != current["project"].get(key):
                    raise ValueError("history target has a different project identity")
            if draft["scene"].get("scene_id") != current["scene"].get("scene_id") or draft["electrical_design"].get("project_id") != project_id:
                raise ValueError("history target has a different scene/electrical identity")
            site_changed = draft["project"]["site"] != current["project"]["site"]
            weather_changed = draft.get("weather_selection") != current.get("weather_selection")
            if require_idle and (site_changed or weather_changed):
                require_idle(project_id)
            self._validate_changed_scene_bounds(current["scene"], draft["scene"])
            summary = ("Redo: " if redo else "Undo: ") + label
            # Only a part whose content differs gets a fresh revision. A context-only restore (imagery, project
            # labels) keeps the scene and electrical revisions, so the scene hash is unchanged (UX1 D1).
            changed = lambda part, envelope: any(draft[part].get(k) != current[part].get(k)
                                                 for k in set(draft[part]) | set(current[part]) if k not in envelope)
            scene_changed = changed("scene", SCENE_ENVELOPE)
            electrical_changed = scene_changed or changed("electrical_design", ELECTRICAL_ENVELOPE)
            if scene_changed:
                scene_number = int(current["scene"]["revision_number"]) + 1
                draft["scene"] = SceneEditorSession(draft["scene"]).commit_revision(
                    revision_id=f"{draft['scene']['scene_id']}-r{scene_number}", revision_number=scene_number,
                    change_summary=summary, created_by="browser-api", status="active")
            else:
                draft["scene"] = deepcopy(current["scene"])
            from geometry.pvfield.explicit import is_explicit, table_for_module
            explicit = {f["pv_field_id"]: f for f in draft["scene"].get("pv_fields", []) if is_explicit(f)}
            for module in draft["scene"].get("module_instances", []):
                if module.get("pv_field_id") in explicit:
                    table_for_module(module, explicit[module["pv_field_id"]])
            definitions = self._component_definitions(draft, "modules")
            for module in draft["scene"].get("module_instances", []):
                if module["module_definition_revision_id"] not in draft["pinned_components"]["modules"]:
                    raise ValueError("history target is missing a pinned module definition")
            for inverter in draft["electrical_design"].get("inverter_instances", []):
                if inverter["inverter_definition_revision_id"] not in draft["pinned_components"]["inverters"]:
                    raise ValueError("history target is missing a pinned inverter definition")
            next_project = f"{project_id}-r{int(current['project']['project_revision']['revision_number']) + 1}"
            if electrical_changed:
                session = ElectricalTopologyEditorSession(draft["scene"], draft["electrical_design"],
                    project_revision_id=next_project, module_definitions=definitions,
                    inverter_definitions=self._component_definitions(draft, "inverters"))
                electrical_number = int(current["electrical_design"].get("revision_number") or 1) + 1
                draft["electrical_design"] = session.commit_revision(
                    electrical_revision_id=f"{project_id}-electrical-r{electrical_number}", revision_number=electrical_number,
                    change_summary=summary, created_by="browser-api", status="active")
                if "topology_editor_version" not in target["electrical_design"]:
                    draft["electrical_design"].pop("topology_editor_version", None)
                draft["electrical_design"]["project_revision_id"] = next_project
            else:
                draft["electrical_design"] = deepcopy(current["electrical_design"])
            if "loss_settings" in draft:
                resolve_loss_settings(draft["loss_settings"])
                from engine.losses.settings import has_circuit_extensions, resolve_circuit_loss_settings
                if has_circuit_extensions(draft["loss_settings"]):
                    resolve_circuit_loss_settings(draft["loss_settings"], draft["scene"], draft["electrical_design"],
                        {**draft["pinned_components"]["modules"], **draft["pinned_components"]["inverters"]})
            if "optics_thermal_settings" in draft:
                resolve_optics_thermal_settings(draft["optics_thermal_settings"])
            if "shading_accuracy" in draft:
                resolve_shading_accuracy(draft["shading_accuracy"])
            selection = draft.get("weather_selection")
            if selection:
                try:
                    weather = (weather_store or FileWeatherRevisionStore(self.store.root.parent / "weather")).load(project_id, selection["revision_id"])
                except WeatherRevisionNotFoundError as exc:
                    raise ValueError("The weather dataset needed for undo is no longer available") from exc
                if (weather.dataset["revision_id"] != selection["revision_id"] or weather.dataset["weather_dataset_id"] != selection["weather_dataset_id"]
                        or weather.dataset["site_id"] != draft["project"]["site"]["site_id"] or weather.dataset["timezone"] != draft["project"]["site"]["timezone"]):
                    raise ValueError("history weather selection does not match the project site")
            # Overlay images are kept until project deletion, so a restored layer's image must still exist.
            validate_imagery(draft.get("imagery"), project_id=project_id, assets=self.imagery)
            self._bump_project_revision(draft, change_summary=summary)
            draft["project"]["project_revision"]["weather_dataset_revision_id"] = selection["revision_id"] if selection else None
            assert_electrical_shading_selection_state(draft)
            try:
                validate_restored_bundle(draft)
            except ValidationError as exc:
                raise ValueError(f"invalid history target: {exc.message}") from exc
            self._save(draft, history_mode="neutral")
            self.history.publish(project_id, staged)
            return self.project_view(project_id)

    def _component_definitions(
        self,
        bundle: dict[str, Any],
        kind: str,
    ) -> dict[str, dict[str, Any]]:
        if kind not in {"modules", "inverters"}:
            raise ValueError(f"unsupported component kind {kind!r}")
        merged = deepcopy(self.catalog[kind])
        merged.update(deepcopy(bundle["pinned_components"].get(kind, {})))
        return merged

    def _pin_component(
        self,
        bundle: dict[str, Any],
        kind: str,
        revision_id: str,
    ) -> dict[str, Any]:
        definitions = self._component_definitions(bundle, kind)
        try:
            definition = deepcopy(definitions[revision_id])
        except KeyError as exc:
            raise ValueError(
                f"{kind[:-1]} component revision not available: {revision_id}"
            ) from exc
        bundle["pinned_components"].setdefault(kind, {})[revision_id] = deepcopy(
            definition
        )
        return definition

    def _bump_project_revision(
        self,
        bundle: dict[str, Any],
        *,
        change_summary: str,
    ) -> None:
        project = bundle["project"]
        current = project["project_revision"]
        number = int(current["revision_number"]) + 1
        project_id = str(project["project_id"])
        project["project_revision"] = {
            "project_revision_id": f"{project_id}-r{number}",
            "revision_number": number,
            "scene_revision_id": bundle["scene"]["revision_id"],
            "electrical_revision_id": bundle["electrical_design"][
                "electrical_revision_id"
            ],
            "weather_dataset_revision_id": current.get(
                "weather_dataset_revision_id"
            ),
            "simulation_defaults_revision_id": current.get(
                "simulation_defaults_revision_id"
            ),
            "supersedes_revision_id": current["project_revision_id"],
            "change_summary": change_summary,
        }
        bundle["workspace_state"]["active_project_revision_id"] = (
            project["project_revision"]["project_revision_id"]
        )

    def _commit_scene(
        self,
        bundle: dict[str, Any],
        draft_scene: dict[str, Any],
        *,
        change_summary: str,
    ) -> None:
        self._validate_changed_scene_bounds(bundle["scene"], draft_scene)
        current_number = int(bundle["scene"].get("revision_number") or 1)
        editor = SceneEditorSession(draft_scene)
        committed = editor.commit_revision(
            revision_id=f"{draft_scene['scene_id']}-r{current_number + 1}",
            revision_number=current_number + 1,
            change_summary=change_summary,
            created_by="browser-api",
            status="active",
        )
        bundle["scene"] = committed
        self._bump_project_revision(bundle, change_summary=change_summary)

    @staticmethod
    def _validate_changed_scene_bounds(before, after):
        for collection, key, geometry_key in (("surfaces", "surface_id", "boundary_2d"),
                                               ("obstacles", "obstacle_id", "footprint")):
            previous = {item[key]: item for item in before.get(collection, [])}
            for item in after.get(collection, []):
                old = previous.get(item[key])
                if collection == "obstacles" and item.get("obstacle_type") == "imported_mesh":
                    if old != item:
                        from geometry.scene.mesh import resolve_mesh
                        resolve_mesh(item)
                    continue
                compared = (geometry_key, "base_elevation_m", "height_m")
                if old is not None and all(old.get(k) == item.get(k) for k in compared):
                    continue
                label = f"scene entity {item[key]}"
                geometry = item[geometry_key]
                points = list(geometry["vertices"]) + [p for hole in geometry.get("holes", []) for p in hole]
                if any(not math.isfinite(float(v)) or abs(float(v)) > 50_000 for p in points for v in p):
                    raise ValueError(f"{label}: vertex coordinates must be within +/-50000 m")
                if any(max(float(p[axis]) for p in points) - min(float(p[axis]) for p in points) > 10_000
                       for axis in (0, 1)):
                    raise ValueError(f"{label}: bounding-box side must be <=10000 m")
                if not -1000 <= float(item.get("base_elevation_m", 0)) <= 10000:
                    raise ValueError(f"{label}: base_elevation_m must be within [-1000, 10000]")
                if collection == "obstacles" and not 0 <= float(item["height_m"]) <= 1000:
                    raise ValueError(f"{label}: height_m must be within [0, 1000]")

    @staticmethod
    def _validate_azimuth(azimuth):
        if not 0 <= float(azimuth) < 360:
            raise ValueError("azimuth_deg must be within [0, 360)")

    def _commit_electrical(
        self,
        bundle: dict[str, Any],
        session: ElectricalTopologyEditorSession,
        *,
        change_summary: str,
    ) -> None:
        current_number = int(
            bundle["electrical_design"].get("revision_number") or 1
        )
        design_id = str(bundle["electrical_design"]["project_id"])
        committed = session.commit_revision(
            electrical_revision_id=f"{design_id}-electrical-r{current_number + 1}",
            revision_number=current_number + 1,
            change_summary=change_summary,
            created_by="browser-api",
            status="active",
        )
        bundle["electrical_design"] = committed
        self._bump_project_revision(bundle, change_summary=change_summary)

    def create_project(
        self,
        *,
        name: str,
        latitude_deg: float,
        longitude_deg: float,
        timezone_name: str,
        elevation_m: float | None = None,
        workspace_mode: str = "map_overlay",
        description: str | None = None,
    ) -> dict[str, Any]:
        if not str(name).strip():
            raise ValueError("project name is required")
        latitude = _number(latitude_deg, "latitude_deg")
        longitude = _number(longitude_deg, "longitude_deg")
        if not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude_deg must be within [-90, 90]")
        if not -180.0 <= longitude <= 180.0:
            raise ValueError("longitude_deg must be within [-180, 180]")
        try:
            ZoneInfo(str(timezone_name))
        except Exception as exc:
            raise ValueError(f"invalid IANA timezone {timezone_name!r}") from exc
        elevation = 0.0 if elevation_m is None else _number(elevation_m, "elevation_m")
        if not -500 <= elevation <= 9000:
            raise ValueError("elevation_m must be within [-500, 9000]")
        if workspace_mode not in {"map_overlay", "blank_engineering_plane"}:
            raise ValueError("workspace_mode must be map_overlay or blank_engineering_plane")

        project_id = _token("project")
        site_id = f"{project_id}-site"
        coordinate_system_id = f"{project_id}-lcs"
        project_revision_id = f"{project_id}-r1"
        scene_id = f"{project_id}-scene"
        scene_revision_id = f"{scene_id}-r1"
        electrical_revision_id = f"{project_id}-electrical-r1"

        lcs = LocalCoordinateSystem(
            coordinate_system_id=coordinate_system_id,
            site_id=site_id,
            origin_latitude_deg=latitude,
            origin_longitude_deg=longitude,
            origin_elevation_m=elevation,
            rotation_from_true_north_deg=0.0,
        )

        project = {
            "schema_name": "Project",
            "schema_version": "0.1",
            "project_id": project_id,
            "name": str(name).strip(),
            "description": description,
            "status": "design",
            "site": {
                "site_id": site_id,
                "name": str(name).strip(),
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "elevation_m": elevation,
                "timezone": str(timezone_name),
                "local_coordinate_system": lcs.to_mapping(),
                "north_reference": "geodetic_true_north",
            },
            "project_revision": {
                "project_revision_id": project_revision_id,
                "revision_number": 1,
                "scene_revision_id": scene_revision_id,
                "electrical_revision_id": electrical_revision_id,
                "weather_dataset_revision_id": None,
                "simulation_defaults_revision_id": None,
                "change_summary": "Initial browser project.",
            },
        }

        scene = {
            "schema_name": "Scene",
            "schema_version": "0.1",
            "scene_id": scene_id,
            "project_id": project_id,
            "revision_id": scene_revision_id,
            "coordinate_system_id": coordinate_system_id,
            "map_layer_configuration": None,
            "created_at": _now(),
            "notes": "Phase-6.0C browser workspace scene.",
            "surfaces": [],
            "obstacles": [],
            "reference_lines": [],
            "pv_fields": [],
            "module_instances": [],
            "revision_number": 1,
            "created_by": "browser-api",
            "supersedes_revision_id": None,
            "status": "active",
            "change_summary": "Initial empty browser scene.",
        }

        electrical = new_electrical_design(
            project_id=project_id,
            electrical_revision_id=electrical_revision_id,
            pcc_id=f"{project_id}-pcc",
            revision_number=1,
            project_revision_id=project_revision_id,
        )
        electrical["created_at"] = _now()
        electrical["created_by"] = "browser-api"
        electrical["status"] = "active"
        electrical["change_summary"] = "Initial empty browser electrical design."

        workspace_state = {
            "schema_name": "DesignWorkspaceState",
            "schema_version": "0.1",
            "workspace_state_id": f"{project_id}-workspace",
            "project_id": project_id,
            "active_project_revision_id": project_revision_id,
            "mode": "plan",
            "active_tool": None,
            "plan_viewport": {
                "center_x_m": 0.0,
                "center_y_m": 0.0,
                "pixels_per_m": 20.0,
                "rotation_deg": 0.0,
            },
            "selection": {
                "selected_entity_ids": [],
                "primary_entity_id": None,
            },
            "snap_preferences": {
                "enabled": True,
                "vertex": True,
                "edge": True,
                "midpoint": True,
                "snap_tolerance_m": 0.10,
                "grid_spacing_m": 0.5,
                "override_active": False,
            },
            "layer_visibility": {
                "surfaces": True,
                "obstacles": True,
                "modules": True,
                "map": workspace_mode == "map_overlay",
            },
            "panel_state": {
                "site_workspace_mode": workspace_mode,
            },
            "updated_at": _now(),
        }

        bootstrap = {
            "schema_name": "SiteWorkspaceBootstrap",
            "schema_version": "0.1",
            "project_id": project_id,
            "site": {
                "site_id": site_id,
                "latitude_deg": latitude,
                "longitude_deg": longitude,
                "elevation_m": elevation,
                "timezone": str(timezone_name),
                "north_reference": "geodetic_true_north",
                "local_coordinate_system_id": coordinate_system_id,
            },
            "workspace_context": {
                "mode": workspace_mode,
                "map_layer_configuration_id": (
                    "openfreemap-liberty-context"
                    if workspace_mode == "map_overlay"
                    else None
                ),
                "show_true_north": True,
                "show_metric_grid": True,
            },
        }

        bundle = {
            "schema_name": "ProjectWorkspaceBundle",
            "schema_version": "0.1",
            "project": project,
            "scene": scene,
            "electrical_design": electrical,
            "pinned_components": {
                "modules": {},
                "inverters": {},
            },
            "pinned_electrical_shading_assets": {
                "module_topologies": {},
                "electrical_parameterization_evidence": {},
                "sources": {},
            },
            "electrical_shading_selections": {},
            "site_workspace_bootstrap": bootstrap,
            "workspace_state": workspace_state,
            "shading_accuracy": default_shading_accuracy(),
            "loss_settings": default_loss_settings(),
            "weather_selection": None,
            "simulation_runs": [],
            "updated_at": _now(),
        }
        return self._save(bundle, expect_new=True)

    def get_bundle(self, project_id: str) -> dict[str, Any]:
        bundle = self.store.load(project_id)
        if bundle.get("schema_version") != CURRENT_SCHEMA_VERSION:
            # DATA1: upgrade once, after a protected backup of the original; a newer file is refused unchanged.
            with self.store._lock:
                bundle, applied = migrate(bundle)
                if applied:
                    self.store.protect(project_id, "schema-upgrade")
                    self.store.save(bundle)
        ensure_electrical_shading_bundle_state(bundle)
        assert_electrical_shading_selection_state(bundle)
        return bundle

    def save_bundle(self, bundle: dict[str, Any], *, history_mode: str = "edit") -> dict[str, Any]:
        """Persist a product bundle after another orchestration layer updates it."""
        return self._save(bundle, history_mode=history_mode)

    def update_losses(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        current = bundle.get("loss_settings", {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"})
        updated = patch_loss_settings(current, patch)
        from engine.losses.settings import bind_circuit_overrides
        updated = bind_circuit_overrides(updated, bundle["scene"], bundle["electrical_design"])
        if updated != current:
            bundle["loss_settings"] = updated
            self._bump_project_revision(bundle, change_summary="Updated loss settings.")
            self._save(bundle)
        return self.project_view(project_id)

    def update_shading_accuracy(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        current = bundle.get("shading_accuracy", default_shading_accuracy())
        updated = patch_shading_accuracy(current, patch)
        if updated != current:
            bundle["shading_accuracy"] = updated
            self._bump_project_revision(bundle, change_summary="Updated shading accuracy.")
            self._save(bundle)
        return self.project_view(project_id)

    def update_optics_thermal(self, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        current = bundle.get("optics_thermal_settings", default_optics_thermal_settings())
        updated = patch_optics_thermal_settings(current, patch)
        if resolve_optics_thermal_settings(updated)["values"] != resolve_optics_thermal_settings(current)["values"] or updated != current:
            bundle["optics_thermal_settings"] = updated
            self._bump_project_revision(bundle, change_summary="Updated optics and thermal settings.")
            self._save(bundle)
        return self.project_view(project_id)

    def update_imagery(self, project_id, config):
        """Persist context-only imagery (UX1): an undo step with no scene, electrical or project revision bump."""
        with self.store._lock:
            bundle = self.get_bundle(project_id)
            validate_imagery(config, project_id=project_id, assets=self.imagery)
            if config is None:
                bundle.pop("imagery", None)
            else:
                bundle["imagery"] = deepcopy(config)
            self._save(bundle, history_label="Edit imagery")
            return self.project_view(project_id)

    def update_uncertainty_assumptions(self, project_id, ledger):
        """UNC1: the project's annual-Pxx assumption ledger (or None to clear it). An undo step with no design revision
        bump: the ledger is applied to a completed run's energy after the fact and never changes a simulation."""
        from engine.uncertainty.annual_pxx import validate_ledger
        with self.store._lock:
            bundle = self.get_bundle(project_id)
            if ledger is None:
                bundle.pop("uncertainty_assumptions", None)
            else:
                bundle["uncertainty_assumptions"] = deepcopy(validate_ledger(ledger))
            self._save(bundle, history_label="Edit uncertainty assumptions")
            return self.project_view(project_id)

    def systems_overview(self, project_id):
        from .systems_overview import systems_overview
        return systems_overview(self.get_bundle(project_id))

    def update_project(self, project_id, **changes):
        with self.store._lock:
            bundle = self.get_bundle(project_id)
            bundle["project"].update(changes)
            self._save(bundle, history_label="Edit project details")
            return self.project_view(project_id)

    def update_site_details(self, project_id, *, copy_if_missing=False, **changes):
        if not changes or set(changes) - {"address", "installation"}:
            raise ValueError("site details update requires only address or installation")
        with self.store._lock:
            bundle = self.get_bundle(project_id)
            site = bundle["project"]["site"]
            if copy_if_missing:
                changes = {key: value for key, value in changes.items() if key not in site}
            if not any(key not in site or site[key] != value for key, value in changes.items()):
                return self.project_view(project_id)
            site.update(changes)
            self._save(bundle)
            return self.project_view(project_id)

    def update_site(self, project_id, *, clear_weather_selection=False, **changes):
        with self.store._lock:
            bundle = self.get_bundle(project_id)
            site = bundle["project"]["site"]
            changed = {key: value for key, value in changes.items() if value != site.get(key)}
            if not changed:
                return self.project_view(project_id)
            new = {**site, **changed}
            try:
                ZoneInfo(new["timezone"])
            except Exception as exc:
                raise ValueError(f"invalid IANA timezone {new['timezone']!r}") from exc
            if not -500 <= float(new["elevation_m"]) <= 9000:
                raise ValueError("elevation_m must be within [-500, 9000]")
            lcs = LocalCoordinateSystem(
                coordinate_system_id=site["local_coordinate_system"]["coordinate_system_id"],
                site_id=site["site_id"], origin_latitude_deg=new["latitude_deg"],
                origin_longitude_deg=new["longitude_deg"], origin_elevation_m=new["elevation_m"],
                rotation_from_true_north_deg=0.0,
            )
            weather_bound = bool(set(changed) & {"latitude_deg", "longitude_deg", "elevation_m", "timezone"})
            selection = bundle.get("weather_selection")
            if weather_bound and selection:
                if not clear_weather_selection:
                    raise ValueError(f"site change invalidates pinned weather {selection['revision_id']}; clear_weather_selection=true is required")
                bundle["weather_selection"] = None
                bundle["project"]["project_revision"]["weather_dataset_revision_id"] = None
            site.update(changed)
            site["local_coordinate_system"] = lcs.to_mapping()
            bootstrap = bundle["site_workspace_bootstrap"]["site"]
            for key in ("latitude_deg", "longitude_deg", "elevation_m", "timezone"):
                bootstrap[key] = site[key]
            self._bump_project_revision(bundle, change_summary=(
                f"Updated site keys {sorted(changed)}; geometry stays in local metres; map-overlay placement moves."
            ))
            self._save(bundle)
            return self.project_view(project_id)

    def module_electrical_shading_capability(
        self,
        project_id: str,
        *,
        module_revision_id: str,
        topology_revision_id: str | None = None,
        region_parameterization_evidence_id: str | None = None,
        cell_parameterization_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        """Return derived capability without mutating design authority."""
        bundle = self.get_bundle(project_id)
        return resolve_project_module_electrical_shading_capability(
            bundle,
            self.catalog,
            module_revision_id=module_revision_id,
            topology_revision_id=topology_revision_id,
            region_parameterization_evidence_id=(
                region_parameterization_evidence_id
            ),
            cell_parameterization_evidence_id=cell_parameterization_evidence_id,
        )

    def set_module_electrical_shading_selection(
        self,
        project_id: str,
        *,
        module_revision_id: str,
        requested_fidelity: str,
        fallback_policy: str = "fail_closed",
        topology_revision_id: str | None = None,
        region_parameterization_evidence_id: str | None = None,
        cell_parameterization_evidence_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist explicit Phase-6.2 asset/fidelity selection.

        This is simulation/product selection state. It intentionally does not
        mutate SceneRevision or ElectricalDesignRevision.
        """
        bundle = self.get_bundle(project_id)
        result = set_project_module_electrical_shading_selection(
            bundle,
            self.catalog,
            module_revision_id=module_revision_id,
            requested_fidelity=requested_fidelity,
            fallback_policy=fallback_policy,
            topology_revision_id=topology_revision_id,
            region_parameterization_evidence_id=(
                region_parameterization_evidence_id
            ),
            cell_parameterization_evidence_id=cell_parameterization_evidence_id,
        )
        self._save(bundle)
        return result

    def import_electrical_shading_asset(
        self,
        project_id: str,
        *,
        asset_kind: str,
        asset: dict[str, Any],
        sources: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Import explicit user/local JSON asset into the project pin set."""
        bundle = self.get_bundle(project_id)
        result = import_project_electrical_shading_asset(
            bundle,
            asset_kind=asset_kind,
            asset=asset,
            sources=sources,
        )
        self._save(bundle, history_mode="barrier")
        return result

    def electrical_region_map(
        self,
        project_id: str,
        *,
        module_instance_id: str,
    ) -> dict[str, Any]:
        """Derive the Phase-6.3 region map from persisted exact topology selection."""
        bundle = self.get_bundle(project_id)
        modules = {
            str(item["module_instance_id"]): item
            for item in bundle["scene"].get("module_instances", [])
        }
        try:
            module_instance = modules[str(module_instance_id)]
        except KeyError as exc:
            raise ValueError(
                f"module instance not available: {module_instance_id}"
            ) from exc

        module_revision_id = str(module_instance["module_definition_revision_id"])
        selection = (bundle.get("electrical_shading_selections") or {}).get(
            module_revision_id
        )
        if not isinstance(selection, dict):
            raise ValueError(
                "module revision has no persisted electrical-shading selection"
            )
        topology_revision_id = selection.get("module_topology_revision_id")
        if not isinstance(topology_revision_id, str) or not topology_revision_id:
            raise ValueError(
                "persisted electrical-shading selection has no topology revision"
            )
        topologies = (
            (bundle.get("pinned_electrical_shading_assets") or {})
            .get("module_topologies")
            or {}
        )
        try:
            topology = topologies[topology_revision_id]
        except KeyError as exc:
            raise ValueError(
                "selected topology revision is not project-pinned"
            ) from exc

        compiled = compile_shading_geometry(bundle["scene"])
        return derive_electrical_region_map(
            compiled,
            topology,
            module_instance_id=str(module_instance_id),
        )

    def level1_module_snapshot(
        self,
        project_id: str,
        *,
        module_instance_id: str,
        sun_vector_xyz: list[float],
        unshaded_poa: dict[str, float],
        optical_modifier: dict[str, float],
        optical_model_manifest: dict[str, Any],
        module_temperature_c: float,
        interval_start: str,
        evaluation_time: str,
        self_shading_enabled: bool,
        sky_dome_resolution: dict[str, Any],
        ground_dome_resolution: dict[str, Any],
        geometric_fidelity_level: str = "engineering",
    ) -> dict[str, Any]:
        """Evaluate one non-persisted Phase-6.4 Level-1 module snapshot.

        The endpoint is deliberately module-local. It consumes the current saved Scene,
        one exact pinned ModuleDefinition revision, the persisted electrical-shading
        selection, and explicit irradiance/thermal snapshot inputs. It does not solve
        string, bypass, or MPPT interaction and does not mutate design authority.
        """
        bundle = self.get_bundle(project_id)
        modules = {
            str(item["module_instance_id"]): item
            for item in bundle["scene"].get("module_instances", [])
        }
        try:
            module_instance = modules[str(module_instance_id)]
        except KeyError as exc:
            raise ValueError(
                f"module instance not available: {module_instance_id}"
            ) from exc

        module_revision_id = str(module_instance["module_definition_revision_id"])
        selection = (bundle.get("electrical_shading_selections") or {}).get(
            module_revision_id
        )
        if not isinstance(selection, dict):
            raise ValueError(
                "module revision has no persisted electrical-shading selection"
            )
        if selection.get("resolved_fidelity") not in {
            "level_1_module_approximation",
            "level_2_bypass_substring",
            "level_3_cell_submodule_iv",
        }:
            raise ValueError(
                "persisted electrical-shading selection does not authorize Level 1"
            )

        pinned_modules = (bundle.get("pinned_components") or {}).get("modules") or {}
        try:
            module_definition = pinned_modules[module_revision_id]
        except KeyError as exc:
            raise ValueError(
                "selected module revision is not project-pinned"
            ) from exc

        resolved_model = resolve_module_model(
            deepcopy(module_definition),
            resolution_id=(
                f"phase64:{bundle['project']['project_id']}:{module_revision_id}"
            ),
            requested_model_id=MODULE_PVSYST_SDM,
        )
        if resolved_model.get("status") != "resolved":
            raise ValueError(
                "project-pinned module cannot resolve the validated detailed SDM required by Level 1"
            )

        try:
            sky_resolution = SkyDomeResolution.from_mapping(sky_dome_resolution)
            ground_resolution = GroundDomeResolution.from_mapping(
                ground_dome_resolution
            )
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

        compiled = compile_shading_geometry(bundle["scene"])
        module_shading = evaluate_module_receiver_visibility(
            compiled,
            module_instance_id=str(module_instance_id),
            sun_vector_xyz=sun_vector_xyz,
            self_shading_enabled=self_shading_enabled,
            sky_resolution=sky_resolution,
            ground_resolution=ground_resolution,
            timestamp=evaluation_time,
            fidelity_level=geometric_fidelity_level,
        )
        receiver_id = str(module_shading["inline_records"][0]["receiver_id"])
        equivalent = build_module_equivalent_irradiance_from_module_shading(
            module_shading,
            module_instance_id=str(module_instance_id),
            module_definition_revision_id=module_revision_id,
            receiver_id=receiver_id,
            unshaded_poa=unshaded_poa,
            optical_modifier=optical_modifier,
            optical_model_manifest=optical_model_manifest,
            module_temperature_c=module_temperature_c,
            interval_start=interval_start,
            evaluation_time=evaluation_time,
        )
        result = evaluate_level1_module_approximation(
            module_definition,
            resolved_model,
            equivalent,
            source_electrical_revision_id=str(
                bundle["electrical_design"]["electrical_revision_id"]
            ),
        )
        return {
            "source_shading_result": module_shading,
            "module_equivalent_irradiance_state": equivalent,
            "module_state": result.module_state,
            "electrical_shading_result": result.electrical_shading_result,
        }

    def set_workspace_mode(
        self,
        project_id: str,
        mode: str,
    ) -> dict[str, Any]:
        if mode not in {"map_overlay", "blank_engineering_plane"}:
            raise ValueError("unsupported workspace mode")
        bundle = self.get_bundle(project_id)
        context = bundle["site_workspace_bootstrap"]["workspace_context"]
        context["mode"] = mode
        context["map_layer_configuration_id"] = (
            "openfreemap-liberty-context" if mode == "map_overlay" else None
        )
        bundle["workspace_state"]["panel_state"]["site_workspace_mode"] = mode
        bundle["workspace_state"]["layer_visibility"]["map"] = mode == "map_overlay"
        bundle["workspace_state"]["updated_at"] = _now()
        return self._save(bundle)

    def scene_geometry(self, project_id, *, operations, dry_run=False, discard_dependent_strings=False):
        from geometry.scene.bulk import GeometryBatchError,validate_batch_limits
        validate_batch_limits(operations)
        if type(dry_run) is not bool or type(discard_dependent_strings) is not bool:
            raise GeometryBatchError("dry_run and discard_dependent_strings must be booleans")
        bundle=self.get_bundle(project_id)
        definitions=self._component_definitions(bundle,"modules")
        editor=SceneEditorSession(bundle["scene"])
        effects=editor.geometry_batch(operations,definitions)
        draft=editor.scene
        removed={mid for effect in effects for mid in effect["removed_module_ids"]}
        strings=sorted(item["string_id"] for item in bundle["electrical_design"].get("strings",[]) if removed.intersection(item["module_instance_ids"]))
        conflicts=[c for c in validate_scene_layout(draft,definitions)["conflicts"] if c["code"] not in {"module_obstacle_setback","module_exclusion_overlap"}]
        added_ids={mid for e in effects for mid in e["added_module_ids"]}
        added_revisions={m["module_definition_revision_id"] for m in draft.get("module_instances",[]) if m["module_instance_id"] in added_ids}
        def counts(scene):
            modules=scene.get("module_instances",[])
            return {"mesh_count":sum(o.get("obstacle_type")=="imported_mesh" for o in scene.get("obstacles",[])),
                    "table_count":sum(len(f.get("tables",[])) for f in scene.get("pv_fields",[]) if f.get("field_kind")=="explicit_layout"),
                    "module_count":len(modules),"stc_power_w":sum(module_nameplate_w(definitions[m["module_definition_revision_id"]]) for m in modules) if all(m["module_definition_revision_id"] in definitions for m in modules) else None}
        changed=canonical_scene_hash(draft)!=canonical_scene_hash(bundle["scene"]) or bool(strings)
        preview={"dry_run":True,"changed":changed,"operations":effects,"before":counts(bundle["scene"]),"after":counts(draft),"string_ids":strings,"requires_discard_dependent_strings":bool(strings),"conflicts":conflicts}
        if dry_run:return preview
        if conflicts:
            last=effects[-1]
            raise GeometryBatchError("Geometry batch has physical or unresolved geometry conflicts; nothing was saved.",code="geometry_conflict",operation_index=last["operation_index"],operation_id=last["operation_id"],object_id=last["object_id"],findings=conflicts)
        if strings and not discard_dependent_strings:
            raise GeometryBatchError(f"Delete requires discard_dependent_strings=true for string_ids: {strings}.",code="dependent_strings",findings=[{"string_id":i} for i in strings])
        if not changed:return self.project_view(project_id)
        # Pins are added only after all refusal checks, to the same isolated bundle.
        for revision in sorted(added_revisions):self._pin_component(bundle,"modules",revision)
        return self._commit_layout_edit(bundle,draft,strings,change_summary="Applied atomic mesh/explicit-table geometry batch.")

    def scene_geometry_3d(self, project_id):
        from geometry.scene3d import generate_scene3d
        return generate_scene3d(self.get_bundle(project_id)["scene"])

    def add_surface_rectangle(
        self,
        project_id: str,
        *,
        name: str,
        origin_x_m: float,
        origin_y_m: float,
        width_m: float,
        height_m: float,
        base_elevation_m: float = 0.0,
        surface_type: str = "flat_roof",
        usable_for_pv: bool = True,
        on_module_conflict: str = "reject",
        discard_dependent_strings: bool = False,
        discard_manual_layout: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        editor = SceneEditorSession(bundle["scene"])
        surface_id = _token("surface")
        editor.draw_rectangle(
            surface_id=surface_id,
            scene_object_id=f"obj-{surface_id}",
            name=str(name).strip() or "Surface",
            surface_type=surface_type,
            origin_x_m=_number(origin_x_m, "origin_x_m"),
            origin_y_m=_number(origin_y_m, "origin_y_m"),
            width_m=_number(width_m, "width_m"),
            height_m=_number(height_m, "height_m"),
            base_elevation_m=_number(base_elevation_m, "base_elevation_m"),
            usable_for_pv=bool(usable_for_pv),
            geometry_source="user_override",
        )
        if self._is_keepout_surface(editor.scene, surface_id):
            self._validate_changed_scene_bounds(bundle["scene"], editor.scene)
            return self._commit_obstacle_edit(
                bundle, editor.scene, surface_id, entity_kind="keepout",
                on_module_conflict=on_module_conflict,
                discard_dependent_strings=discard_dependent_strings,
                discard_manual_layout=discard_manual_layout, dry_run=dry_run,
                change_summary=f"Added surface {surface_id}.",
            )
        self._commit_scene(
            bundle,
            editor.scene,
            change_summary=f"Added surface {surface_id}.",
        )
        self._save(bundle)
        return self.project_view(project_id)

    def move_scene_entity(
        self,
        project_id: str,
        *,
        entity_id: str,
        dx_m: float,
        dy_m: float,
        on_module_conflict: str = "reject",
        discard_dependent_strings: bool = False,
        discard_manual_layout: bool = False,
        dry_run: bool = False,
        dependent_fields: str = "reject",
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        editor = SceneEditorSession(bundle["scene"])
        collection, canonical_id = self._resolve_scene_target(editor, str(entity_id))
        if dependent_fields == "apply" and collection == "surfaces":
            fields = self._dependent_surface_fields(bundle, {canonical_id})
            if fields:
                return self._apply_dependent_scene_edit(bundle, fields, "move", [str(entity_id)],
                    {"dx_m": _number(dx_m, "dx_m"), "dy_m": _number(dy_m, "dy_m")},
                    discard_dependent_strings=discard_dependent_strings,
                    discard_manual_layout=discard_manual_layout, dry_run=dry_run)
        self._guard_scene_targets(bundle, [(collection, canonical_id)], "move")
        editor.move(
            [str(entity_id)],
            dx_m=_number(dx_m, "dx_m"),
            dy_m=_number(dy_m, "dy_m"),
        )
        keepout = collection == "surfaces" and self._is_keepout_surface(editor.scene, canonical_id)
        if keepout:
            self._validate_changed_scene_bounds(bundle["scene"], editor.scene)
        return self._commit_obstacle_edit(
            bundle, editor.scene, canonical_id if collection == "obstacles" or keepout else None,
            entity_kind="keepout" if keepout else "obstacle",
            on_module_conflict=on_module_conflict if collection == "obstacles" or keepout else "reject",
            discard_dependent_strings=discard_dependent_strings,
            discard_manual_layout=discard_manual_layout,
            dry_run=dry_run,
            change_summary=(
                f"Moved scene entity {entity_id} by "
                f"({_number(dx_m, 'dx_m')}, {_number(dy_m, 'dy_m')}) m."
            ),
        )

    @staticmethod
    def _is_keepout_surface(scene, entity_id):
        return any(surface["surface_id"] == entity_id
                   and surface.get("surface_type") in {"exclusion_area", "walkway"}
                   for surface in scene.get("surfaces", []))

    @staticmethod
    def _resolve_scene_target(editor, entity_id):
        collection, entity = editor._find(entity_id)
        # Delegate lookup ordering/alias precedence to the authoritative engine.
        return collection, str(entity.get("surface_id") or entity.get("obstacle_id")
                               or entity.get("reference_line_id") or entity.get("scene_object_id"))

    @staticmethod
    def _guard_scene_targets(bundle, targets, kind):
        for collection, entity_id in targets:
            entity=next((e for e in bundle["scene"].get(collection,[]) if entity_id in {e.get("obstacle_id"),e.get("surface_id"),e.get("reference_line_id")}),{})
            if entity.get("obstacle_type")=="imported_mesh" and kind!="delete":
                raise ValueError(f"mesh {entity_id}: read-only; use whole-mesh replacement or delete")
            explicit=[f["pv_field_id"] for f in bundle["scene"].get("pv_fields",[]) if collection=="surfaces" and f.get("field_kind")=="explicit_layout" and any(t.get("support_surface_id")==entity_id for t in f.get("tables",[]))]
            # A copy leaves the source and its fields untouched; the duplicate never carries fields.
            if explicit and kind!="copy":raise ValueError(f"support surface carries explicit fields {explicit}; delete those fields first")
            fields = [str(f["pv_field_id"]) for f in bundle["scene"].get("pv_fields", [])
                      if collection == "surfaces" and str(f.get("support_surface_id")) == entity_id]
            if fields and kind not in {"edit_elevation", "edit_plane", "copy"}:
                if kind == "delete":
                    raise ValueError(f"support surface is already used by PV fields {fields}; delete the fields first (DELETE /pv-fields/{{id}})")
                raise ValueError("support surface is already used by PV fields "
                    f"{fields}; rebuild/impact handling is required before moving it")

    def scene_command(
        self, project_id, command, *, on_module_conflict="reject",
        discard_dependent_strings=False, discard_manual_layout=False, dry_run=False, dependent_fields="reject",
    ):
        bundle = self.get_bundle(project_id)
        editor = SceneEditorSession(bundle["scene"])
        kind = command["command_type"]
        ids = command["target_entity_ids"]
        targets = [self._resolve_scene_target(editor, entity_id) for entity_id in ids]
        canonical_ids = [entity_id for _, entity_id in targets]
        if dependent_fields == "apply" and kind in {"move", "rotate", "move_vertex", "edit_exact_dimension", "edit_exact_angle", "scale", "delete", "insert_vertex", "delete_vertex", "move_edge", "add_hole", "remove_hole"}:
            supports = {entity_id for collection, entity_id in targets if collection == "surfaces"}
            if kind == "delete":
                # Engine delete also matches aliases across collections, including
                # ambiguous aliases in legacy scenes. Include every removed roof.
                supports = {item["surface_id"] for item in bundle["scene"].get("surfaces", [])
                            if item["surface_id"] in ids or item.get("scene_object_id") in ids}
            fields = self._dependent_surface_fields(bundle, supports)
            if fields:
                return self._apply_dependent_scene_edit(bundle, fields, kind, ids, command["parameters"],
                    discard_dependent_strings=discard_dependent_strings,
                    discard_manual_layout=discard_manual_layout, dry_run=dry_run)
        if kind == "set_reference_anchor":
            editor.set_reference_anchor(ids[0], **command["parameters"])
            if dry_run:
                return {"dry_run": True, "conflicts": []}
            return self._commit_layout_edit(bundle, editor.scene, [], change_summary=f"Set reference anchor on {canonical_ids}.")
        if kind in {"group", "ungroup"}:
            if any(collection != "surfaces" for collection, _ in targets):
                raise ValueError("buildings may group surfaces only")
            if kind == "group" and command["parameters"].get("name") is None and not any(
                b["building_id"] == command["parameters"]["group_id"] for b in bundle["scene"].get("buildings", [])
            ):
                raise ValueError("a new building requires a name")
            getattr(editor, kind)(canonical_ids, **command["parameters"])
            if dry_run:
                return {"dry_run": True, "conflicts": []}
            return self._commit_layout_edit(bundle, editor.scene, [], change_summary=f"Scene command {kind} on {canonical_ids}.")
        self._guard_scene_targets(bundle, targets, kind)
        parameters = command["parameters"]
        if kind == "draw_polygon":
            parameters = {**parameters, "name": str(parameters.get("name", "Surface")).strip() or "Surface"}
            self._validate_azimuth(parameters.get("azimuth_deg", 0))
            if not 0 <= float(parameters.get("slope_deg", 0)) < 90:
                raise ValueError("slope_deg must be within [0, 90)")
            entity_id = _token("surface")
            editor.draw_polygon(surface_id=entity_id, scene_object_id=f"obj-{entity_id}",
                                geometry_source="user_override", **parameters)
            canonical_ids = [entity_id]
        elif kind == "copy":
            collection, source_id = targets[0]
            if collection not in {"surfaces", "obstacles"}:
                raise ValueError("copy supports roofs, keep-outs and obstacles only")
            entity_id = _token("surface" if collection == "surfaces" else "obstacle")
            editor.copy(source_id, new_entity_id=entity_id, new_scene_object_id=f"obj-{entity_id}",
                        dx_m=parameters["dx_m"], dy_m=parameters["dy_m"])
            canonical_ids = [entity_id]
        elif kind in {"move", "rotate", "scale", "delete"}:
            getattr(editor, kind)(ids, **parameters)
        elif kind in {"move_vertex", "edit_exact_dimension", "edit_exact_angle", "edit_elevation",
                      "insert_vertex", "delete_vertex", "move_edge", "edit_height", "edit_plane", "add_hole", "remove_hole"}:
            getattr(editor, kind)(ids[0], **parameters)
        else:
            raise ValueError(f"command_type {kind} is not supported by /scene/commands yet")
        draft = editor.scene
        # Engine deletion matches id aliases across collections. Guard every
        # removed support, including ambiguous aliases in older stored scenes.
        if kind == "delete":
            remaining = {s["surface_id"] for s in draft.get("surfaces", [])}
            removed = {s["surface_id"] for s in bundle["scene"].get("surfaces", [])} - remaining
            fields = [f["pv_field_id"] for f in self._dependent_surface_fields(bundle,removed)]
            if fields:
                raise ValueError(f"support surface is already used by PV fields {fields}; delete the fields first (DELETE /pv-fields/{{id}})")
        summary = f"Scene command {kind} on {canonical_ids} ({command['command_id']})."
        if kind == "copy":
            collection, source_id = targets[0]
            clone = next(e for e in draft[collection] if e.get("surface_id", e.get("obstacle_id")) == canonical_ids[0])
            # The duplicate stands alone: it joins neither the source's parent surface nor its group.
            for key in COPY_CLEARED_KEYS:
                if key in clone:
                    clone[key] = None
            source = next(e for e in bundle["scene"][collection] if e.get("surface_id", e.get("obstacle_id")) == source_id)
            summary = f"Duplicate {source.get('name') or source_id}."
            if parameters.get("with_pv") and collection == "surfaces":
                draft = self._copy_surface_fields(bundle, draft, source_id, canonical_ids[0], parameters["dx_m"], parameters["dy_m"])
                summary = f"Paste {source.get('name') or source_id} with PV."
        keepout = bool(canonical_ids) and self._is_keepout_surface(draft, canonical_ids[0])
        if keepout or kind in {"insert_vertex", "delete_vertex", "move_edge", "edit_height", "edit_plane", "add_hole", "remove_hole", "copy"}:
            self._validate_changed_scene_bounds(bundle["scene"], draft)
        if kind != "delete" and ((keepout and kind != "edit_plane") or (targets and targets[0][0] == "obstacles")):
            return self._commit_obstacle_edit(bundle, draft, canonical_ids[0],
                entity_kind="keepout" if keepout else "obstacle",
                on_module_conflict=on_module_conflict, discard_dependent_strings=discard_dependent_strings,
                discard_manual_layout=discard_manual_layout, dry_run=dry_run, change_summary=summary)
        conflicts = []
        if kind in {"edit_elevation", "edit_plane"} and targets[0][0] == "surfaces":
            definitions = self._component_definitions(bundle, "modules")
            before = {(c["module_instance_id"], c["other_id"]) for c in
                      validate_scene_layout(bundle["scene"], definitions)["conflicts"]
                      if c["code"] == "module_obstacle_overlap"}
            conflicts = [c for c in validate_scene_layout(draft, definitions)["conflicts"]
                         if c["code"] == "module_obstacle_overlap"
                         and (c["module_instance_id"], c["other_id"]) not in before]
        if dry_run:
            return {"dry_run": True, "conflicts": conflicts}
        if conflicts:
            raise GeometryConflictError("Plane change creates module–obstacle overlaps." if kind == "edit_plane" else "Elevation change creates module–obstacle overlaps.", conflicts)
        return self._commit_layout_edit(bundle, draft, [], change_summary=summary)

    def _copy_surface_fields(self, bundle, draft, source_id, clone_id, dx, dy):
        """UX3 paste: the PV fields on `source_id`, re-created on its clone. Generated fields are re-filled with the
        source's packing parameters; explicit tables on that roof are rebuilt moved by (dx, dy). Strings are not copied."""
        from geometry.pvfield.explicit import create_explicit_field, is_explicit
        definitions = self._component_definitions(bundle, "modules")
        fields = [f for f in bundle["scene"].get("pv_fields", [])
                  if f.get("support_surface_id") == source_id
                  or (is_explicit(f) and any(t.get("support_surface_id") == source_id for t in f.get("tables", [])))]
        session = PVFieldPackingSession(draft, definitions, electrical_design=bundle["electrical_design"])
        created = []
        for field in (f for f in fields if not is_explicit(f)):
            setbacks = field.get("setback_configuration") or {}
            if setbacks.get("edge_specific_setbacks"):
                raise ValueError(f"PV field {field['name']} uses edge-specific setbacks, which can't be copied yet; "
                                 "paste the roof without PV and fill it again")
            packing = field.get("packing_parameters") or {}
            field_id = _token("field")
            session.create_field(
                pv_field_id=field_id, name=f"{field['name']} copy", support_surface_id=clone_id,
                module_definition_revision_id=field["module_definition_revision_id"], orientation=field["orientation"],
                azimuth_deg=field["azimuth_deg"], tilt_deg=field["tilt_deg"], module_gap_x_m=field["module_gap_x_m"],
                module_gap_y_m=field["module_gap_y_m"], row_pitch_m=field["row_pitch_m"],
                mounting_height_m=field["mounting_height_m"],
                perimeter_setback_m=setbacks.get("perimeter_setback_m", 0.0),
                obstacle_setback_m=setbacks.get("obstacle_setback_m", 0.0),
                table_configuration=field.get("table_configuration"), exclusion_rules=field.get("exclusion_rules"),
                row_alignment=packing.get("row_alignment", "start"),
                requested_row_count=packing.get("requested_row_count"),
                requested_modules_per_row=packing.get("requested_modules_per_row"))
            if session.fill_area(field_id)["module_count"] < 1:
                raise ValueError(f"PV field {field['name']} fits no modules on the pasted roof")
            created.append(field_id)
        scene = session.scene
        keys = ("anchor_xyz_m", "anchor_convention", "tilt_deg", "azimuth_deg", "module_definition_revision_id",
                "modules_across", "modules_up", "module_orientation", "module_gap_across_m", "module_gap_up_m", "rectangle")
        for field in (f for f in fields if is_explicit(f)):
            tables = []
            for table in (t for t in field["tables"] if t.get("support_surface_id") == source_id):
                copy = {key: deepcopy(table[key]) for key in keys if key in table}
                x, y, z = table["anchor_xyz_m"]
                copy.update(table_id=_token("table"), anchor_xyz_m=[x + dx, y + dy, z], support_surface_id=clone_id)
                tables.append(copy)
            field_id = _token("field")
            new_field, modules = create_explicit_field(
                scene, definitions, pv_field_id=field_id, name=f"{field['name']} copy", tables=tables,
                provenance={**deepcopy(field.get("provenance") or {}), "copied_from_pv_field_id": field["pv_field_id"]})
            scene["pv_fields"].append(new_field)
            scene["module_instances"].extend(modules)
            created.append(field_id)
        conflicts = [c for c in validate_scene_layout(scene, definitions)["conflicts"]
                     if c["code"] in {"module_module_overlap", "module_obstacle_overlap", "module_exclusion_overlap"}
                     and (c.get("pv_field_id") in created or c.get("other_pv_field_id") in created)]
        if conflicts:
            raise GeometryConflictError("The pasted PV overlaps existing modules, obstacles or keep-outs; "
                                        "paste it somewhere free.", conflicts)
        return scene

    @staticmethod
    def _dependent_surface_fields(bundle, surface_ids):
        return sorted((field for field in bundle["scene"].get("pv_fields", [])
                       if (field.get("support_surface_id") in surface_ids or (field.get("field_kind")=="explicit_layout" and any(t.get("support_surface_id") in surface_ids for t in field.get("tables",[]))))), key=lambda field: field["pv_field_id"])

    def _apply_dependent_scene_edit(self, bundle, fields, kind, ids, parameters, *,
                                    discard_dependent_strings, discard_manual_layout, dry_run):
        before = bundle["scene"]
        explicit=[f["pv_field_id"] for f in fields if f.get("field_kind")=="explicit_layout"]
        if explicit:raise ValueError(f"support surface carries explicit fields {explicit}; delete those fields first")
        definitions = self._component_definitions(bundle, "modules")
        editor = SceneEditorSession(before)
        # All targets must resolve and be editable before any dependent work.
        for entity_id in ids:
            _, entity = editor._find(entity_id)
            editor._assert_editable(entity)
        if kind == "delete":
            # A legacy alias can match more than the first entity returned by
            # _find. Every entity the engine will remove must be editable.
            for collection, key in (("surfaces", "surface_id"), ("obstacles", "obstacle_id"), ("reference_lines", "reference_line_id")):
                for entity in before.get(collection, []):
                    if str(entity.get(key)) in ids or str(entity.get("scene_object_id")) in ids:
                        editor._assert_editable(entity)
        field_ids = {field["pv_field_id"] for field in fields}
        if kind == "delete":
            packing = PVFieldPackingSession(before, definitions, electrical_design=bundle["electrical_design"])
            for field in fields:
                packing.delete_field(field["pv_field_id"])
            editor = SceneEditorSession(packing.scene)
            editor.delete(ids)
            draft = editor.scene
        else:
            if kind in {"move", "rotate", "scale"}:
                getattr(editor, kind)(ids, **parameters)
            else:
                getattr(editor, kind)(ids[0], **parameters)
            draft = editor.scene
            self._validate_changed_scene_bounds(before, draft)
            packing = PVFieldPackingSession(draft, definitions, electrical_design=bundle["electrical_design"])
            for field in fields:
                try:
                    packing.rebuild_field(field["pv_field_id"])
                except (ValueError, KeyError) as exc:
                    raise DependentFieldError(f"Cannot re-fill PV field {field['pv_field_id']}: {exc}", []) from exc
            draft = packing.scene
        self._validate_changed_scene_bounds(before, draft)
        conflicts = self._layout_edit_conflicts(draft, definitions, field_ids)
        previews = []
        for field in fields:
            field_id = field["pv_field_id"]
            if kind == "delete":
                modules = [item for item in before["module_instances"] if item["pv_field_id"] == field_id]
                removed = {item["module_instance_id"] for item in modules}
                strings = sorted(item["string_id"] for item in bundle["electrical_design"]["strings"]
                                 if removed.intersection(item["module_instance_ids"]))
                preview = {"pv_field_id": field_id, "module_count_before": len(modules), "module_count_after": 0,
                           "stc_power_w_before": sum(module_nameplate_w(definitions[item["module_definition_revision_id"]]) for item in modules),
                           "stc_power_w_after": 0, "string_ids": strings,
                           "requires_discard_dependent_strings": bool(strings),
                           "requires_discard_manual_layout": field.get("layout_status") == "manual"}
            else:
                impact = layout_impact_report(before, draft, field_id, electrical_design=bundle["electrical_design"])
                preview = self._pv_field_preview(bundle, before, draft, field_id, impact)
                preview.pop("dry_run")
            preview.update(name=field.get("name", field_id), action="delete" if kind == "delete" else "refill",
                           conflicts=[item for item in conflicts if field_id in {item.get("pv_field_id"), item.get("other_pv_field_id")}])
            previews.append(preview)
        if dry_run:
            return {"dry_run": True, "dependent_fields": previews, "conflicts": []}
        if any(preview["requires_discard_manual_layout"] for preview in previews) and not discard_manual_layout:
            raise DependentFieldError("Dependent fields require discard_manual_layout=true.", previews)
        if kind != "delete" and any(preview["module_count_after"] == 0 for preview in previews):
            raise DependentFieldError("Re-filled dependent field would have zero modules.", previews)
        if conflicts:
            raise DependentFieldError("Re-filled dependent fields have geometry conflicts.", previews)
        string_ids = sorted({string_id for preview in previews for string_id in preview["string_ids"]})
        if string_ids and not discard_dependent_strings:
            raise DependentFieldError(f"Dependent fields require discard_dependent_strings=true for string_ids: {string_ids}.", previews)
        return self._commit_layout_edit(bundle, draft, string_ids,
            change_summary=f"Scene command {kind} on {ids}; {len(fields)} dependent fields {'deleted' if kind == 'delete' else 're-filled'}.")

    def add_polygon_obstacle(
        self, project_id, *, name="Obstacle", vertices, base_elevation_m=0,
        height_m, on_module_conflict="reject", discard_dependent_strings=False,
        discard_manual_layout=False, dry_run=False,
    ):
        bundle = self.get_bundle(project_id)
        editor = SceneEditorSession(bundle["scene"])
        obstacle_id = _token("obstacle")
        editor.draw_polygon_extrusion(obstacle_id=obstacle_id, scene_object_id=f"obj-{obstacle_id}",
            name=str(name).strip() or "Obstacle", vertices=vertices,
            base_elevation_m=base_elevation_m, height_m=height_m, geometry_source="user_override")
        return self._commit_obstacle_edit(bundle, editor.scene, obstacle_id,
            on_module_conflict=on_module_conflict, discard_dependent_strings=discard_dependent_strings,
            discard_manual_layout=discard_manual_layout, dry_run=dry_run,
            change_summary=f"Added obstacle {obstacle_id}.")

    def add_box_obstacle(
        self,
        project_id: str,
        *,
        name: str,
        origin_x_m: float,
        origin_y_m: float,
        width_m: float,
        depth_m: float,
        base_elevation_m: float,
        height_m: float,
        on_module_conflict: str = "reject",
        discard_dependent_strings: bool = False,
        discard_manual_layout: bool = False,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        editor = SceneEditorSession(bundle["scene"])
        obstacle_id = _token("obstacle")
        editor.draw_box_obstacle(
            obstacle_id=obstacle_id,
            scene_object_id=f"obj-{obstacle_id}",
            name=str(name).strip() or "Obstacle",
            origin_x_m=_number(origin_x_m, "origin_x_m"),
            origin_y_m=_number(origin_y_m, "origin_y_m"),
            width_m=_number(width_m, "width_m"),
            depth_m=_number(depth_m, "depth_m"),
            base_elevation_m=_number(base_elevation_m, "base_elevation_m"),
            height_m=_number(height_m, "height_m"),
            geometry_source="user_override",
        )
        return self._commit_obstacle_edit(
            bundle, editor.scene, obstacle_id,
            on_module_conflict=on_module_conflict,
            discard_dependent_strings=discard_dependent_strings,
            discard_manual_layout=discard_manual_layout,
            dry_run=dry_run,
            change_summary=f"Added obstacle {obstacle_id}.",
        )

    def _commit_obstacle_edit(
        self, bundle, draft_scene, obstacle_id, *, on_module_conflict,
        discard_dependent_strings, discard_manual_layout, dry_run, change_summary,
        entity_kind="obstacle",
    ) -> dict[str, Any]:
        if on_module_conflict not in {"reject", "remove_modules", "refill_field"}:
            raise ValueError("on_module_conflict must be reject, remove_modules, or refill_field")
        definitions = self._component_definitions(bundle, "modules")
        keepout = entity_kind == "keepout"
        overlap_code = "module_exclusion_overlap" if keepout else "module_obstacle_overlap"
        codes = {overlap_code} if keepout else {overlap_code, "module_obstacle_setback"}
        conflicts = [
            item for item in validate_scene_layout(draft_scene, definitions)["conflicts"]
            if item["code"] in codes
            and item["other_id"] == obstacle_id
        ]
        affected_fields = {
            item["pv_field_id"] for item in conflicts
            if item["code"] == overlap_code
        }
        explicit=[f['pv_field_id'] for f in draft_scene.get('pv_fields',[]) if f.get('field_kind')=='explicit_layout' and f['pv_field_id'] in affected_fields]
        if explicit:
            raise GeometryConflictError(f"Explicit tables in fields {explicit} are read-only; delete and recreate those fields before placing an intersecting obstacle.",conflicts)
        removal_ids = sorted({
            item["module_instance_id"] for item in conflicts
            if item["pv_field_id"] in affected_fields
        })
        removal_set = set(removal_ids)
        string_ids = sorted(
            str(item["string_id"])
            for item in bundle["electrical_design"].get("strings", [])
            if removal_set.intersection(item.get("module_instance_ids", []))
        )
        power = sum(
            module_nameplate_w(definitions[module["module_definition_revision_id"]])
            for module in draft_scene.get("module_instances", [])
            if module["module_instance_id"] in removal_set
        )
        options = {
            "remove_modules": {
                "module_instance_ids": removal_ids, "module_count": len(removal_ids),
                "stc_power_w": power, "string_ids": string_ids,
                "requires_discard_dependent_strings": bool(string_ids),
            },
            "refill_field": {"available": True, "fields": [], "string_ids": [],
                             "requires_discard_dependent_strings": False,
                             "requires_discard_manual_layout": False},
        }
        refill = PVFieldPackingSession(draft_scene, definitions, electrical_design=bundle["electrical_design"])
        refill_strings = set()
        refill_conflicts = []
        try:
            for field_id in sorted(affected_fields):
                result = refill.rebuild_field(field_id)
                preview = self._pv_field_preview(bundle, draft_scene, refill.scene, field_id, result["layout_impact"])
                options["refill_field"]["fields"].append({key: preview[key] for key in (
                    "pv_field_id", "module_count_before", "module_count_after", "removed_module_count",
                    "added_module_count", "stc_power_w_before", "stc_power_w_after",
                )})
                refill_strings.update(preview["string_ids"])
                options["refill_field"]["requires_discard_manual_layout"] |= preview["requires_discard_manual_layout"]
            options["refill_field"]["string_ids"] = sorted(refill_strings)
            options["refill_field"]["requires_discard_dependent_strings"] = bool(refill_strings)
            refill_conflicts = self._layout_edit_conflicts(refill.scene, definitions, affected_fields)
            remaining = [item for item in refill_conflicts if item["code"] == overlap_code]
            if remaining:
                options["refill_field"].update(
                    available=False, reason="field_exclusion_rules_ignore_keepout" if keepout else "field_exclusion_rules_ignore_obstacle", remaining_conflicts=remaining,
                )
            if refill_conflicts:
                options["refill_field"]["available"] = False
                options["refill_field"]["conflicts"] = refill_conflicts
        except (ValueError, KeyError) as exc:
            # A failed optional rebuild must not disable S1's rejection or
            # removal paths, or allow a partially rebuilt draft to be saved.
            options["refill_field"] = {"available": False, "reason": "refill_unavailable", "message": str(exc)}
        if dry_run:
            preview = {"dry_run": True, "conflicts": conflicts, "options": options}
            if keepout:
                # Informational only: use the packer's support-intersection
                # filter and actual selection, including explicit-id overrides.
                ignored = []
                surfaces = {item["surface_id"]: item for item in draft_scene.get("surfaces", [])}
                excluded = surfaces[obstacle_id]["boundary_2d"]["vertices"]
                for field in sorted(draft_scene.get("pv_fields", []), key=lambda item: item["pv_field_id"]):
                    support = surfaces.get(field.get("support_surface_id"))
                    if support is None or support["surface_id"] == obstacle_id:
                        continue
                    try:
                        resolved, _ = _resolved_exclusions({**draft_scene, "obstacles": []}, field, support)
                        selected = any(entity_id == obstacle_id for entity_id, _ in resolved)
                        if not selected and polygons_overlap_or_touch(support["boundary_2d"]["vertices"], excluded):
                            ignored.append({"pv_field_id": field["pv_field_id"],
                                            "reason": "field_exclusion_rules_ignore_keepout"})
                    except (KeyError, ValueError, TypeError, AttributeError, IndexError):
                        continue
                preview["ignored_by_fields"] = ignored
            return preview
        if on_module_conflict == "refill_field" and affected_fields:
            if options["refill_field"].get("reason") == "refill_unavailable":
                raise GeometryConflictError(options["refill_field"]["message"], conflicts, options)
            if refill_conflicts:
                raise GeometryConflictError("Re-filled fields have geometry conflicts; exclusion rules are unchanged.", refill_conflicts, options)
            if options["refill_field"]["requires_discard_manual_layout"] and not discard_manual_layout:
                raise GeometryConflictError("Re-fill requires discard_manual_layout=true.", conflicts, options)
            if refill_strings and not discard_dependent_strings:
                raise GeometryConflictError(f"Re-fill requires discard_dependent_strings=true for string_ids: {sorted(refill_strings)}.", conflicts, options)
            return self._commit_layout_edit(
                bundle, refill.scene, refill_strings, change_summary=change_summary,
            )
        if affected_fields and (
            on_module_conflict == "reject"
            or (string_ids and not discard_dependent_strings)
        ):
            raise GeometryConflictError(
                f"{'Keep-out' if keepout else 'Obstacle'} conflicts with modules {removal_ids} in fields "
                f"{sorted(affected_fields)}; affected string_ids: {string_ids}. "
                "Choose remove_modules and, when strings are affected, explicitly "
                "set discard_dependent_strings=true.", conflicts, options,
            )
        if affected_fields:
            packing = PVFieldPackingSession(draft_scene, definitions)
            packing.remove_modules(removal_ids)
            draft_scene = packing.scene
        return self._commit_layout_edit(bundle, draft_scene, string_ids if affected_fields else [], change_summary=change_summary)

    def _commit_layout_edit(self, bundle, draft_scene, string_ids, *, change_summary):
        if string_ids:
            electrical = ElectricalTopologyEditorSession(
                draft_scene, bundle["electrical_design"],
                project_revision_id=self._project_revision_id(bundle),
                module_definitions=self._component_definitions(bundle, "modules"),
                inverter_definitions=self._component_definitions(bundle, "inverters"),
            )
            for string_id in sorted(set(string_ids)):
                electrical.delete_string(string_id)
            number = int(bundle["electrical_design"].get("revision_number") or 1) + 1
            design_id = str(bundle["electrical_design"]["project_id"])
            bundle["electrical_design"] = electrical.commit_revision(
                electrical_revision_id=f"{design_id}-electrical-r{number}", revision_number=number,
                change_summary=change_summary, created_by="browser-api", status="active",
            )
        self._commit_scene(bundle, draft_scene, change_summary=change_summary)
        self._save(bundle)
        return self.project_view(str(bundle["project"]["project_id"]))

    @staticmethod
    def _layout_edit_conflicts(scene, definitions, field_ids):
        return [item for item in validate_scene_layout(scene, definitions)["conflicts"]
                if (item["code"] == "module_module_overlap"
                    and item["pv_field_id"] != item["other_pv_field_id"]
                    and (item["pv_field_id"] in field_ids or item["other_pv_field_id"] in field_ids))
                or (item["code"] in {"module_obstacle_overlap", "module_obstacle_clearance", "module_exclusion_overlap", "module_over_hole"} and item["pv_field_id"] in field_ids)]

    def _pv_field_preview(self, bundle, before, after, field_id, impact):
        old = {m["module_instance_id"]: m for m in before["module_instances"] if m["pv_field_id"] == field_id}
        new = {m["module_instance_id"]: m for m in after["module_instances"] if m["pv_field_id"] == field_id}
        definitions = self._component_definitions(bundle, "modules")
        def power(modules):
            return sum(module_nameplate_w(definitions[m["module_definition_revision_id"]]) for m in modules.values())
        strings = sorted(item["string_id"] for item in impact["affected_strings"])
        field = next(item for item in before["pv_fields"] if item["pv_field_id"] == field_id)
        return {
            "dry_run": True, "pv_field_id": field_id,
            "module_count_before": len(old), "module_count_after": len(new),
            "retained_module_count": len(impact["retained_module_ids"]),
            "added_module_count": len(new.keys() - old.keys()),
            "removed_module_count": len(old.keys() - new.keys()),
            "stc_power_w_before": power(old), "stc_power_w_after": power(new),
            "string_ids": strings, "requires_discard_dependent_strings": bool(strings),
            "requires_discard_manual_layout": field.get("layout_status") == "manual",
            "conflicts": [], "layout_impact": impact,
        }

    @staticmethod
    def _module_move_conflicts(scene, definitions, ids, field_ids):
        from geometry.pvfield.packing import validate_field_layout
        findings = []
        native={**scene,"obstacles":[o for o in scene.get("obstacles",[]) if o.get("obstacle_type")!="imported_mesh"]}
        for field_id in field_ids:
            findings.extend({**item, "pv_field_id": field_id, "other_id": item.get("related_entity_id")}
                            for item in validate_field_layout(native, field_id)["conflicts"])
        findings.extend(validate_scene_layout(scene, definitions)["conflicts"])
        moved = set(ids)
        unique = {(item["code"], item.get("module_instance_id"), item.get("other_id"), item.get("pv_field_id")): item
                  for item in findings if item.get("module_instance_id") in moved or item.get("other_id") in moved}
        return [unique[key] for key in sorted(unique, key=lambda key: tuple(str(v or "") for v in key))]

    @staticmethod
    def _module_command_reasons(scene, conflicts, ids):
        fields = {f["pv_field_id"]: f for f in scene["pv_fields"]}
        surfaces = {s["surface_id"]: s for s in scene["surfaces"]}
        entities = {**surfaces, **{o["obstacle_id"]: o for o in scene["obstacles"]}}
        moved = set(ids)
        grouped = {}
        for conflict in conflicts:
            code = conflict["code"]
            field = fields.get(conflict.get("pv_field_id"), {})
            other = conflict.get("other_id")
            params = {}
            if code in {"module_outside_support_or_setback", "module_over_hole"}:
                other = field.get("support_surface_id")
            if code != "module_module_overlap":
                params["name"] = entities.get(other, {}).get("name") or str(other or "")
            if code in {"module_obstacle_setback", "module_outside_support_or_setback"}:
                params["setback"] = float(field.get("setback_configuration", {}).get(
                    "obstacle_setback_m" if code == "module_obstacle_setback" else "perimeter_setback_m", 0))
            key = (code, tuple(params.items()))
            group = grouped.setdefault(key, set())
            group.update(moved.intersection({conflict.get("module_instance_id"), conflict.get("other_id")}))
        reasons = []
        for (code, values), members in grouped.items():
            params = dict(values)
            count = len(members)
            subject = f"{count} module" + ("s" if count != 1 else "")
            verb = {
                "module_module_overlap": "overlap other modules",
                "module_obstacle_overlap": f"overlap obstacle {params.get('name')}",
                "module_obstacle_setback": f"be closer than {params.get('setback'):g} m to obstacle {params.get('name')}" if "setback" in params else "",
                "module_outside_support_or_setback": f"leave roof {params.get('name')} or its {params.get('setback'):g} m edge setback" if "setback" in params else "",
                "module_over_hole": f"cover a hole in {params.get('name')}",
                "module_exclusion_overlap": f"enter keep-out {params.get('name')}",
            }.get(code)
            reasons.append({"code": code, "count": count, "message": f"{subject} would {verb}" if verb else code, **params})
        return reasons

    def module_commands(self, project_id, *, command, module_instance_ids, dx_m=None, dy_m=None,
                        discard_dependent_strings=False, dry_run=False, on_conflict="reject"):
        """Preview or atomically apply explicit manual placement edits."""
        ids = list(module_instance_ids)
        if not 1 <= len(ids) <= 10000 or len(set(ids)) != len(ids):
            raise ValueError("module_instance_ids must contain 1 to 10000 unique ids")
        if command not in {"delete_modules", "move_modules"}:
            raise ValueError("unsupported module command")
        if command == "delete_modules" and (dx_m is not None or dy_m is not None):
            raise ValueError("dx_m and dy_m are forbidden for delete_modules")
        if command == "move_modules" and (dx_m is None or dy_m is None or
                not all(math.isfinite(float(v)) and abs(float(v)) <= 10000 for v in (dx_m, dy_m))):
            raise ValueError("move_modules requires finite dx_m and dy_m within ±10000 m")
        if on_conflict not in {"reject", "fill"} or (command != "move_modules" and on_conflict != "reject"):
            raise ValueError("on_conflict is only supported for move_modules and must be reject or fill")
        bundle = self.get_bundle(project_id)
        before = bundle["scene"]
        by_id = {m["module_instance_id"]: m for m in before["module_instances"]}
        unknown = set(ids) - by_id.keys()
        if unknown:
            raise ValueError(f"module instances not found: {sorted(unknown)}")
        field_ids = sorted({by_id[mid]["pv_field_id"] for mid in ids})
        from geometry.pvfield.explicit import assert_generated_layout
        for field in before["pv_fields"]:
            if field["pv_field_id"] in field_ids:assert_generated_layout(field)
        definitions = self._component_definitions(bundle, "modules")
        session = PVFieldPackingSession(before, definitions, electrical_design=bundle["electrical_design"])
        if command == "move_modules":
            from geometry.pvfield.drop_fill import DropFillError

            session.move_modules(ids, dx_m, dy_m)
            draft = session.scene
            conflicts = self._module_move_conflicts(draft, definitions, ids, field_ids)
            reasons = self._module_command_reasons(before, conflicts, ids)
            if conflicts and on_conflict == "fill":
                session = PVFieldPackingSession(before, definitions, electrical_design=bundle["electrical_design"])
                try:
                    plan = session.fill_move_modules(ids, dx_m, dy_m)
                except DropFillError as exc:
                    error = GeometryConflictError(str(exc), conflicts)
                    error.reasons = [{"code": exc.code, "count": len(ids), "message": str(exc), **exc.parameters}, *reasons]
                    raise error from exc
                draft = session.scene
                post = self._module_move_conflicts(draft, definitions, plan["placed_ids"], field_ids)
                if post:
                    error = GeometryConflictError("Fill post-check failed; no changes saved. Engine consistency requires review.", post)
                    error.reasons = [{"code": "drop_fill_postcheck", "count": len(plan["placed_ids"]), "message": str(error)}]
                    raise error
                removed = set(plan["removed_ids"])
                strings = sorted(s["string_id"] for s in bundle["electrical_design"]["strings"]
                                 if removed.intersection(s["module_instance_ids"]))
                power = lambda members: sum(module_nameplate_w(definitions[by_id[mid]["module_definition_revision_id"]]) for mid in members)
                preview = {"dry_run": True, "mode": "fill", "placed_count": len(plan["placed_ids"]),
                           "removed_count": len(removed), "placed_ids": plan["placed_ids"], "removed_ids": plan["removed_ids"],
                           "string_ids": strings, "requires_discard_dependent_strings": bool(strings),
                           "stc_power_w_before": power(ids), "stc_power_w_after": power(plan["placed_ids"]),
                           "reasons": reasons, "conflicts": conflicts}
                if dry_run:
                    return preview
                if strings and not discard_dependent_strings:
                    error = GeometryConflictError("Fill removes modules and requires discard_dependent_strings=true for strings: " + ", ".join(strings), conflicts)
                    error.reasons = reasons
                    raise error
                return self._commit_layout_edit(bundle, draft, strings, change_summary=f"Moved and fitted {len(ids)} PV modules.")
            if dry_run:
                return {"dry_run": True, "command": command, "moved_count": len(ids), "conflicts": conflicts, "reasons": reasons}
            if conflicts:
                error = GeometryConflictError("Module move refused because it creates layout conflicts.", conflicts)
                error.reasons = reasons
                raise error
            return self._commit_layout_edit(bundle, draft, [], change_summary=f"Moved {len(ids)} PV modules.")

        session.remove_modules(ids)
        draft = session.scene
        fields = []
        for field_id in field_ids:
            impact = layout_impact_report(before, draft, field_id, electrical_design=bundle["electrical_design"])
            preview = self._pv_field_preview(bundle, before, draft, field_id, impact)
            fields.append({
                **{key: preview[key] for key in ("pv_field_id", "module_count_before", "module_count_after",
                                                "stc_power_w_before", "stc_power_w_after", "string_ids")},
                "name": next(f["name"] for f in before["pv_fields"] if f["pv_field_id"] == field_id),
                "field_becomes_empty": preview["module_count_after"] == 0,
            })
        strings = sorted({sid for field in fields for sid in field["string_ids"]})
        preview = {"dry_run": True, "command": command, "fields": fields,
                   "module_count": len(ids), "string_ids": strings, "requires_discard_dependent_strings": bool(strings), "reasons": []}
        if dry_run:
            return preview
        if strings and not discard_dependent_strings:
            raise DependentFieldError(f"Delete requires discard_dependent_strings=true for string_ids: {strings}.", fields)
        return self._commit_layout_edit(bundle, draft, strings, change_summary=f"Deleted {len(ids)} PV modules.")

    def update_pv_field(
        self, project_id, field_id, *, name=None, discard_dependent_strings=False,
        discard_manual_layout=False, dry_run=False, **parameters,
    ):
        bundle = self.get_bundle(project_id)
        field = next((item for item in bundle["scene"]["pv_fields"] if item["pv_field_id"] == field_id), None)
        if field is None:
            raise ValueError(f"PV field not found: {field_id}")
        from geometry.pvfield.explicit import assert_generated_layout
        assert_generated_layout(field)
        parameters = {key: value for key, value in parameters.items() if value is not None}
        revision = parameters.get("module_definition_revision_id")
        module_changed = revision is not None and revision != field["module_definition_revision_id"]
        if revision == field["module_definition_revision_id"]:
            parameters.pop("module_definition_revision_id")
        if "azimuth_deg" in parameters:
            self._validate_azimuth(parameters["azimuth_deg"])
        if name is None and not parameters:
            raise ValueError("field update requires at least one change")
        definitions = self._component_definitions(bundle, "modules")
        if module_changed and revision not in definitions:
            raise ValueError(f"unknown modules component revision {revision!r}")
        session = PVFieldPackingSession(bundle["scene"], definitions, electrical_design=bundle["electrical_design"])
        if parameters:
            result = session.update_field(field_id, **parameters)
            if result["module_count"] < 1:
                raise ValueError("PV field packing produced zero modules; adjust surface, setback, orientation, row pitch, or module selection")
            draft = session.scene
            impact = result["layout_impact"]
        else:
            draft = session.scene
            impact = layout_impact_report(bundle["scene"], draft, field_id, electrical_design=bundle["electrical_design"])
        if name is not None:
            next(item for item in draft["pv_fields"] if item["pv_field_id"] == field_id)["name"] = str(name).strip() or "PV field"
        preview = self._pv_field_preview(bundle, bundle["scene"], draft, field_id, impact)
        if module_changed:
            old_ids = {m["module_instance_id"] for m in bundle["scene"]["module_instances"] if m["pv_field_id"] == field_id}
            preview["string_ids"] = sorted(s["string_id"] for s in bundle["electrical_design"]["strings"]
                                           if old_ids.intersection(s["module_instance_ids"]))
            preview["requires_discard_dependent_strings"] = bool(preview["string_ids"])
        preview["requires_discard_manual_layout"] &= bool(parameters)
        if parameters:
            preview["conflicts"] = self._layout_edit_conflicts(draft, definitions, {field_id})
        if dry_run:
            return preview
        if preview["requires_discard_manual_layout"] and not discard_manual_layout:
            raise ValueError("Re-fill requires discard_manual_layout=true.")
        if preview["conflicts"]:
            raise GeometryConflictError("Updated PV field has geometry conflicts.", preview["conflicts"])
        if preview["string_ids"] and not discard_dependent_strings:
            raise ValueError(f"Re-fill requires discard_dependent_strings=true for string_ids: {preview['string_ids']}.")
        if module_changed:
            self._pin_component(bundle, "modules", revision)
        return self._commit_layout_edit(bundle, draft, preview["string_ids"], change_summary=f"Updated PV field {field_id}.")

    def delete_pv_field(self, project_id, field_id, *, discard_dependent_strings=False, dry_run=False):
        bundle = self.get_bundle(project_id)
        field=next((f for f in bundle["scene"]["pv_fields"] if f["pv_field_id"]==field_id),None)
        if field is not None and field.get("field_kind")=="explicit_layout":
            editor=SceneEditorSession(bundle["scene"])
            result=editor.geometry_batch([{"operation_id":"delete-field","operation_type":"delete_explicit_field","pv_field_id":field_id}],self._component_definitions(bundle,"modules"))[0]
            draft=editor.scene;removed=set(result["removed_module_ids"])
        else:
            session = PVFieldPackingSession(bundle["scene"], self._component_definitions(bundle, "modules"))
            result = session.delete_field(field_id)
            removed = set(result["removed_module_instance_ids"])
            draft=session.scene
        strings = sorted(item["string_id"] for item in bundle["electrical_design"]["strings"]
                         if removed.intersection(item["module_instance_ids"]))
        definitions = self._component_definitions(bundle, "modules")
        preview = {"pv_field_id": field_id, "module_count": len(removed),
                   "stc_power_w": sum(module_nameplate_w(definitions[m["module_definition_revision_id"]])
                                      for m in bundle["scene"]["module_instances"] if m["module_instance_id"] in removed),
                   "string_ids": strings, "requires_discard_dependent_strings": bool(strings)}
        if dry_run:
            return preview
        if strings and not discard_dependent_strings:
            raise ValueError(f"Delete requires discard_dependent_strings=true for string_ids: {strings}.")
        return self._commit_layout_edit(bundle, draft, strings, change_summary=f"Deleted PV field {field_id}.")

    def create_pv_field(
        self,
        project_id: str,
        *,
        name: str,
        support_surface_id: str,
        module_definition_revision_id: str,
        orientation: str = "portrait",
        azimuth_deg: float = 0.0,
        tilt_deg: float = 10.0,
        module_gap_x_m: float = 0.02,
        module_gap_y_m: float = 0.02,
        row_pitch_m: float = 2.6,
        mounting_height_m: float = 0.2,
        perimeter_setback_m: float = 0.3,
        obstacle_setback_m: float = 0.3,
        rows_per_table: int = 1,
        leftover_depth: str = "smaller_table",
        row_alignment: str = "start",
        depth_alignment: str | None = None,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        self._validate_azimuth(azimuth_deg)
        self._pin_component(
            bundle,
            "modules",
            module_definition_revision_id,
        )
        definitions = self._component_definitions(bundle, "modules")
        session = PVFieldPackingSession(
            bundle["scene"],
            definitions,
            electrical_design=bundle["electrical_design"],
        )
        field_id = _token("field")
        session.create_field(
            pv_field_id=field_id,
            rows_per_table=rows_per_table, leftover_depth=leftover_depth,
            row_alignment=row_alignment, depth_alignment=depth_alignment,
            name=str(name).strip() or "PV field",
            support_surface_id=support_surface_id,
            module_definition_revision_id=module_definition_revision_id,
            orientation=orientation,
            azimuth_deg=_number(azimuth_deg, "azimuth_deg"),
            tilt_deg=_number(tilt_deg, "tilt_deg"),
            module_gap_x_m=_number(module_gap_x_m, "module_gap_x_m"),
            module_gap_y_m=_number(module_gap_y_m, "module_gap_y_m"),
            row_pitch_m=_number(row_pitch_m, "row_pitch_m"),
            mounting_height_m=_number(mounting_height_m, "mounting_height_m"),
            perimeter_setback_m=_number(
                perimeter_setback_m, "perimeter_setback_m"
            ),
            obstacle_setback_m=_number(
                obstacle_setback_m, "obstacle_setback_m"
            ),
        )
        result = session.fill_area(field_id)
        if result["module_count"] < 1:
            raise ValueError(
                "PV field packing produced zero modules; adjust surface, setback, "
                "orientation, row pitch, or module selection"
            )
        conflicts = [
            item for item in validate_scene_layout(session.scene, definitions)["conflicts"]
            if item["code"] == "module_module_overlap"
            and field_id in {item["pv_field_id"], item["other_pv_field_id"]}
        ]
        if conflicts:
            existing_fields = sorted({
                value for item in conflicts
                for value in (item["pv_field_id"], item["other_pv_field_id"])
                if value != field_id
            })
            raise GeometryConflictError(
                f"New field overlaps existing PV fields {existing_fields}; "
                "update that field instead.", conflicts,
            )
        self._commit_scene(
            bundle,
            session.scene,
            change_summary=(
                f"Created PV field {field_id} with {result['module_count']} modules."
            ),
        )
        self._save(bundle)
        return self.project_view(project_id)

    def add_inverter(
        self,
        project_id: str,
        *,
        inverter_definition_revision_id: str,
        name: str,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        self._pin_component(
            bundle,
            "inverters",
            inverter_definition_revision_id,
        )
        session = ElectricalTopologyEditorSession(
            bundle["scene"],
            bundle["electrical_design"],
            project_revision_id=self._project_revision_id(bundle),
            module_definitions=self._component_definitions(bundle, "modules"),
            inverter_definitions=self._component_definitions(bundle, "inverters"),
        )
        inverter_id = _token("inverter")
        session.add_inverter(
            inverter_instance_id=inverter_id,
            inverter_definition_revision_id=inverter_definition_revision_id,
            name=str(name).strip() or "Inverter",
            enabled=True,
            connect_to_pcc=True,
        )
        self._commit_electrical(
            bundle,
            session,
            change_summary=f"Added inverter {inverter_id}.",
        )
        self._save(bundle)
        return self.project_view(project_id)

    def _electrical_session(self, bundle: dict[str, Any]) -> ElectricalTopologyEditorSession:
        return ElectricalTopologyEditorSession(
            bundle["scene"], bundle["electrical_design"],
            project_revision_id=self._project_revision_id(bundle),
            module_definitions=self._component_definitions(bundle, "modules"),
            inverter_definitions=self._component_definitions(bundle, "inverters"),
        )

    def remove_inverter(self, project_id: str, inverter_instance_id: str) -> dict[str, Any]:
        """USE1: remove an inverter; its strings stay, unassigned. One undo step."""
        bundle = self.get_bundle(project_id)
        session = self._electrical_session(bundle)
        result = session.remove_inverter(inverter_instance_id)
        self._commit_electrical(bundle, session, change_summary=(
            f"Removed inverter {inverter_instance_id}; {len(result['unassigned_string_ids'])} strings unassigned."))
        self._save(bundle)
        return {**self.project_view(project_id), "command_results": [result]}

    def change_inverter_definition(self, project_id: str, inverter_instance_id: str, *,
                                   inverter_definition_revision_id: str) -> dict[str, Any]:
        """USE1: change an inverter's model or revision in place, keeping strings where the MPPT index exists."""
        bundle = self.get_bundle(project_id)
        self._pin_component(bundle, "inverters", inverter_definition_revision_id)
        session = self._electrical_session(bundle)
        result = session.change_inverter_definition(inverter_instance_id, inverter_definition_revision_id)
        self._commit_electrical(bundle, session, change_summary=(
            f"Changed inverter {inverter_instance_id} to {inverter_definition_revision_id}; "
            f"{len(result['unassigned_string_ids'])} strings unassigned."))
        self._save(bundle)
        return {**self.project_view(project_id), "command_results": [result]}

    def shading_free_pitch(self, project_id: str, *, module_definition_revision_id: str, **geometry: Any) -> dict[str, Any]:
        """USE1: the row pitch at which a row casts no shadow on the next at a design sun position (read-only)."""
        from geometry.pvfield.pitch import shading_free_row_pitch

        definitions = self._component_definitions(self.get_bundle(project_id), "modules")
        if module_definition_revision_id not in definitions:
            raise ValueError(f"module component revision not available: {module_definition_revision_id}")
        return shading_free_row_pitch(definitions[module_definition_revision_id], **geometry)

    def inverter_sizing(self, project_id: str, inverter_instance_id: str):
        from .inverter_sizing import inverter_sizing
        return inverter_sizing(self.get_bundle(project_id), inverter_instance_id)

    def suggest_mppt_layout(self, project_id: str, inverter_instance_id: str,
                            pv_field_ids: list[str] | None = None) -> dict[str, Any]:
        """USE1: an engine-sized MPPT layout for one inverter (read-only), verified by the design validation."""
        from .stringing_suggestion import suggest_mppt_layout

        return suggest_mppt_layout(self, self.get_bundle(project_id), inverter_instance_id, pv_field_ids)

    def create_strings(
        self,
        project_id: str,
        *,
        string_length: int,
        pv_field_id: str | None = None,
        allow_shorter_remainder: bool = False,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        used = {
            str(module_id)
            for string in bundle["electrical_design"].get("strings", [])
            for module_id in string.get("module_instance_ids", [])
        }
        module_ids = [
            str(module["module_instance_id"])
            for module in bundle["scene"].get("module_instances", [])
            if module.get("enabled") is True
            and str(module["module_instance_id"]) not in used
            and (
                pv_field_id is None
                or str(module.get("pv_field_id")) == str(pv_field_id)
            )
        ]
        if not module_ids:
            raise ValueError("no enabled unstrung modules are available")

        session = ElectricalTopologyEditorSession(
            bundle["scene"],
            bundle["electrical_design"],
            project_revision_id=self._project_revision_id(bundle),
            module_definitions=self._component_definitions(bundle, "modules"),
            inverter_definitions=self._component_definitions(bundle, "inverters"),
        )
        generated = session.create_strings(
            module_ids,
            string_length=int(string_length),
            id_prefix="S",
            ordering="row_major",
            remainder_policy=(
                "allow_shorter" if allow_shorter_remainder else "error"
            ),
        )
        self._commit_electrical(
            bundle,
            session,
            change_summary=f"Created {len(generated)} strings.",
        )
        self._save(bundle)
        return self.project_view(project_id)

    def assign_strings(
        self,
        project_id: str,
        *,
        inverter_instance_id: str,
        string_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        ids = list(string_ids or [])
        if not ids:
            ids = [
                str(item["string_id"])
                for item in bundle["electrical_design"].get("strings", [])
                if item.get("target_mppt_instance_id") is None
            ]
        if not ids:
            raise ValueError("no unassigned strings are available")

        session = ElectricalTopologyEditorSession(
            bundle["scene"],
            bundle["electrical_design"],
            project_revision_id=self._project_revision_id(bundle),
            module_definitions=self._component_definitions(bundle, "modules"),
            inverter_definitions=self._component_definitions(bundle, "inverters"),
        )
        session.assign_strings(
            ids,
            inverter_instance_id=inverter_instance_id,
            compatibility_keys=self._assignment_keys(bundle["scene"], session, ids),
        )
        self._commit_electrical(
            bundle,
            session,
            change_summary=(
                f"Assigned {len(ids)} strings to inverter {inverter_instance_id}."
            ),
        )
        self._save(bundle)
        return self.project_view(project_id)

    @staticmethod
    def _assignment_keys(scene, session, string_ids=None, inverter_instance_id=None):
        from engine.simulation.execution_groups import string_compatibility_keys
        design = session.electrical_design
        if string_ids is None:
            targets = {m["mppt_instance_id"] for m in design["mppt_instances"]
                       if m["inverter_instance_id"] == inverter_instance_id}
            string_ids = [s["string_id"] for s in design["strings"]
                          if s.get("target_mppt_instance_id") in targets]
        selected = set(string_ids)
        from .orientation_policy import tolerance_deg
        return string_compatibility_keys(scene,
            [s for s in design["strings"] if s["string_id"] in selected], orientation_tolerance_deg=tolerance_deg(design))

    @staticmethod
    def _next_electrical_string_id(session: ElectricalTopologyEditorSession) -> str:
        design = session.electrical_design
        used = {
            str(item[key])
            for collection, key in (
                ("inverter_instances", "inverter_instance_id"),
                ("mppt_instances", "mppt_instance_id"),
                ("strings", "string_id"), ("connections", "connection_id"),
            )
            for item in design.get(collection, []) if item.get(key) is not None
        }
        counter = 1
        while f"S{counter:03d}" in used:
            counter += 1
        return f"S{counter:03d}"

    def electrical_commands(
        self, project_id: str, commands: Iterable[dict[str, Any]], *, dry_run: bool = False,
    ) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        session = ElectricalTopologyEditorSession(
            bundle["scene"], bundle["electrical_design"],
            project_revision_id=self._project_revision_id(bundle),
            module_definitions=self._component_definitions(bundle, "modules"),
            inverter_definitions=self._component_definitions(bundle, "inverters"),
        )
        before_hash = session.canonical_hash()
        before_errors = {(f["code"], f["entity_id"]) for f in session.consistency_report()["findings"]
                         if f["severity"] == "error"}
        results = []
        # The route validates lazily, so parameter and engine failures are both
        # reported at the first failing command in execution order.
        for index, command in enumerate(commands):
            kind = command["command_type"]
            parameters = dict(command["parameters"])
            try:
                if kind == "create_string" and "string_id" not in parameters:
                    parameters["string_id"] = self._next_electrical_string_id(session)
                if kind == "split_string" and not parameters.get("new_string_id"):
                    parameters["new_string_id"] = self._next_electrical_string_id(session)
                if kind in {"assign_strings", "balance_mppt"}:
                    parameters["compatibility_keys"] = self._assignment_keys(
                        bundle["scene"], session, parameters.get("string_ids"),
                        parameters.get("inverter_instance_id"))
                result = getattr(session, kind)(**parameters)
            except (ValueError, KeyError) as exc:
                raise ValueError(f"command {index} ({command['command_id']}, {kind}): {exc}") from exc
            if kind in {"assign_strings", "balance_mppt"}:
                result = [{"mppt_index": i, "string_ids": list(ids)} for i, ids in sorted(result.items())]
            elif isinstance(result, tuple):
                result = list(result)
            entry = {"command_id": command["command_id"], "command_type": kind, "result": result}
            if kind in {"suggest_string_length", "inspect_inverter"}:
                return entry
            results.append(entry)
        report = session.consistency_report()
        if dry_run:
            # USE1: the engine's live checks for the trial design, so a draft layout is checked before Apply.
            trial = {**bundle, "electrical_design": session.electrical_design}
            return {"dry_run": True, "command_results": results,
                    "topology_view": session.topology_view(), "topology_consistency": report,
                    "topology_checks": topology_checks(trial)}
        if session.canonical_hash() != before_hash:
            errors = [
                {**f, "origin": "pre-existing" if (f["code"], f["entity_id"]) in before_errors else "introduced"}
                for f in report["findings"] if f["severity"] == "error"
            ]
            if errors:
                raise TopologyConsistencyError(
                    "Electrical design has structural consistency errors; repair them in this batch "
                    "(for example with delete_string or unassign_strings) before committing "
                    f"({len(errors)} errors).", errors,
                )
            kinds = [r["command_type"] for r in results]
            ids = [r["command_id"] for r in results]
            summary = f"Electrical commands: {kinds} ({ids})."[:500]
            self._commit_electrical(bundle, session, change_summary=summary)
            self._save(bundle)
        return {**self.project_view(project_id), "command_results": results}

    def save_project(self, project_id: str) -> dict[str, Any]:
        bundle = self.get_bundle(project_id)
        self._save(bundle)
        return {
            "project_id": project_id,
            "updated_at": bundle["updated_at"],
            "scene_hash": canonical_scene_hash(bundle["scene"]),
            "electrical_hash": canonical_electrical_hash(
                bundle["electrical_design"]
            ),
            "project_revision_id": self._project_revision_id(bundle),
        }

    @staticmethod
    def _closed_ring(points: list[list[float]]) -> list[list[float]]:
        if not points:
            return points
        if points[0] == points[-1]:
            return points
        return [*points, list(points[0])]

    def _module_polygon(
        self,
        bundle: dict[str, Any],
        module: dict[str, Any],
        fields: dict[str, dict[str, Any]],
    ) -> list[list[float]]:
        field = fields[str(module["pv_field_id"])]
        definition_id = str(module["module_definition_revision_id"])
        definition = self._component_definitions(bundle, "modules")[definition_id]
        footprint = ModuleFootprint.from_definition(
            definition,
            str(field["orientation"]),
            float(field.get("tilt_deg", 0.0)),
        )
        transform = module["transform"]
        polygon = rectangle_polygon(
            (
                float(transform["position_x_m"]),
                float(transform["position_y_m"]),
            ),
            footprint.plan_projection_width_m,
            footprint.plan_projection_height_m,
            float(transform.get("rotation_z_deg", field.get("azimuth_deg", 0.0))),
        )
        return [[float(x), float(y)] for x, y in polygon]

    def scene_view(self, bundle: dict[str, Any]) -> dict[str, Any]:
        local_features: list[dict[str, Any]] = []
        geometry_objects=[]
        for surface in bundle["scene"].get("surfaces", []):
            local_features.append(
                {
                    "id": str(surface["surface_id"]),
                    "category": "surface",
                    "subtype": str(surface["surface_type"]),
                    "name": str(surface["name"]),
                    "polygon": deepcopy(surface["boundary_2d"]["vertices"]),
                }
            )
        for obstacle in bundle["scene"].get("obstacles", []):
            if obstacle.get("obstacle_type")=="imported_mesh":
                geometry_objects.append({"id":obstacle["obstacle_id"],"kind":"mesh","name":obstacle["name"],"plan_geometry":None})
                continue
            local_features.append(
                {
                    "id": str(obstacle["obstacle_id"]),
                    "category": "obstacle",
                    "subtype": str(obstacle["obstacle_type"]),
                    "name": str(obstacle["name"]),
                    "polygon": deepcopy(obstacle["footprint"]["vertices"]),
                }
            )

        fields = {
            str(item["pv_field_id"]): item
            for item in bundle["scene"].get("pv_fields", [])
        }
        for module in bundle["scene"].get("module_instances", []):
            field=fields.get(str(module.get("pv_field_id")))
            if field is not None and field.get("field_kind")=="explicit_layout":
                from geometry.pvfield.explicit import explicit_module_geometry
                from shapely.geometry import Polygon
                item={"id":module["module_instance_id"],"kind":"explicit_module","name":module["module_instance_id"],"pv_field_id":module["pv_field_id"]}
                try:
                    _,corners,_=explicit_module_geometry(module,field,bundle["scene"]["surfaces"])
                    points=[list(p[:2]) for p in corners]
                    if Polygon(points).area>1e-10:
                        item["plan_geometry"]={"type":"Polygon","coordinates":[self._closed_ring(points)]}
                        local_features.append({"id":item["id"],"category":"module","subtype":"pv_module","name":item["name"],"pv_field_id":item["pv_field_id"],"polygon":points})
                    else:
                        first,last=max(((a,b) for a in points for b in points),key=lambda pair:math.dist(*pair))
                        item["plan_geometry"]={"type":"LineString","coordinates":[first,last]} if first!=last else {"type":"Point","coordinates":first}
                    item["status"]="resolved"
                except (ValueError,KeyError,TypeError,AttributeError,IndexError,OverflowError) as exc:
                    item.update(status="unresolved",message=str(exc),plan_geometry=None)
                geometry_objects.append(item)
                continue
            local_features.append(
                {
                    "id": str(module["module_instance_id"]),
                    "category": "module",
                    "subtype": "pv_module",
                    "name": str(module["module_instance_id"]),
                    "pv_field_id": str(module["pv_field_id"]),
                    "polygon": self._module_polygon(bundle, module, fields),
                }
            )

        lcs = LocalCoordinateSystem.from_mapping(
            bundle["project"]["site"]["local_coordinate_system"]
        )
        geo_features: list[dict[str, Any]] = []
        for feature in local_features:
            coordinates: list[list[float]] = []
            for x_m, y_m in feature["polygon"]:
                point = lcs.local_to_geographic(
                    LocalPoint(float(x_m), float(y_m), 0.0)
                )
                coordinates.append(
                    [float(point.longitude_deg), float(point.latitude_deg)]
                )
            properties = {
                key: value
                for key, value in feature.items()
                if key != "polygon"
            }
            geo_features.append(
                {
                    "type": "Feature",
                    "id": feature["id"],
                    "properties": properties,
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [self._closed_ring(coordinates)],
                    },
                }
            )

        return {
            "local_features": local_features,
            **({"geometry_objects":geometry_objects} if geometry_objects else {}),
            "geojson": {
                "type": "FeatureCollection",
                "features": geo_features,
            },
            "site": {
                "latitude_deg": bundle["project"]["site"]["latitude_deg"],
                "longitude_deg": bundle["project"]["site"]["longitude_deg"],
                "elevation_m": bundle["project"]["site"].get("elevation_m"),
                "timezone": bundle["project"]["site"]["timezone"],
                "north_reference": "geodetic_true_north",
            },
        }

    def project_view(self, project_id: str) -> dict[str, Any]:
        with self.store._lock:
            bundle = self.get_bundle(project_id)
            history = self.history.view(project_id)
            fingerprint = design_fingerprint(bundle)
        loader = getattr(self, "run_result_loader", None)
        if loader is not None:
            bundle["simulation_runs"] = loader(project_id, bundle.get("simulation_runs") or [])
        topology = ElectricalTopologyEditorSession(
            bundle["scene"],
            bundle["electrical_design"],
            project_revision_id=self._project_revision_id(bundle),
            module_definitions=self._component_definitions(bundle, "modules"),
            inverter_definitions=self._component_definitions(bundle, "inverters"),
        )
        loss_binding_findings = []
        from engine.losses.settings import has_circuit_extensions, resolve_circuit_loss_settings
        if has_circuit_extensions(bundle.get("loss_settings")):
            try:
                resolve_circuit_loss_settings(bundle["loss_settings"], bundle["scene"], bundle["electrical_design"],
                    {**bundle["pinned_components"]["modules"], **bundle["pinned_components"]["inverters"]})
            except (ValueError, KeyError, TypeError) as exc:
                loss_binding_findings.append({"rule_id": "LOSS_SETTINGS_INVALID", "message": str(exc)})
        return {
            **({"loss_binding_findings": loss_binding_findings} if loss_binding_findings else {}),
            "bundle": bundle,
            "history": history,
            "design_fingerprint": fingerprint,
            "resolved_loss_settings": resolve_loss_settings(bundle.get("loss_settings", {**default_loss_settings(), "defaults_id": "recommended_defaults.v1"})),
            "resolved_shading_accuracy": resolve_shading_accuracy(bundle.get("shading_accuracy", default_shading_accuracy())),
            "resolved_optics_thermal_settings": resolve_optics_thermal_settings(bundle.get("optics_thermal_settings", default_optics_thermal_settings())),
            "scene_view": self.scene_view(bundle),
            "topology_view": topology.topology_view(),
            "topology_consistency": topology.consistency_report(),
            "topology_checks": topology_checks(bundle),
            "identity": {
                "scene_hash": canonical_scene_hash(bundle["scene"]),
                "electrical_hash": canonical_electrical_hash(
                    bundle["electrical_design"]
                ),
            },
            "catalog": self._project_catalog_view(bundle),
        }
