"""Provider-agnostic map-layer configuration validation.

This module intentionally contains no renderer dependency. MapLibre or another future client
may consume the same canonical provider/layer configuration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


_PROVIDER_KINDS = {"xyz_raster", "maplibre_style", "uploaded_asset", "none"}
_LAYER_TYPES = {"base_map", "aerial_imagery", "orthophoto", "engineering_grid"}


@dataclass(frozen=True)
class MapProvider:
    provider_id: str
    provider_kind: str
    name: str
    attribution_required: bool
    attribution: str | None = None
    tile_url_template: str | None = None
    style_url: str | None = None
    credential_reference: str | None = None
    license_note: str | None = None


@dataclass(frozen=True)
class MapLayer:
    layer_id: str
    layer_type: str
    provider_id: str | None
    source_record_id: str | None = None
    imported_asset_id: str | None = None
    orthophoto_georeference: Mapping[str, Any] | None = None
    notes: str | None = None


@dataclass(frozen=True)
class MapLayerConfiguration:
    map_configuration_id: str
    providers: tuple[MapProvider, ...]
    layers: tuple[MapLayer, ...]
    engineering_geometry_authority: str = "local_metric"
    map_measurement_role: str = "context_only"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MapLayerConfiguration":
        if value.get("engineering_geometry_authority") != "local_metric":
            raise ValueError("engineering_geometry_authority must be local_metric")
        if value.get("map_measurement_role") != "context_only":
            raise ValueError("map_measurement_role must be context_only")

        providers = tuple(
            MapProvider(
                provider_id=str(item["provider_id"]),
                provider_kind=str(item["provider_kind"]),
                name=str(item["name"]),
                attribution_required=bool(item["attribution_required"]),
                attribution=item.get("attribution"),
                tile_url_template=item.get("tile_url_template"),
                style_url=item.get("style_url"),
                credential_reference=item.get("credential_reference"),
                license_note=item.get("license_note"),
            )
            for item in value.get("providers", ())
        )
        layers = tuple(
            MapLayer(
                layer_id=str(item["layer_id"]),
                layer_type=str(item["layer_type"]),
                provider_id=(
                    str(item["provider_id"])
                    if item.get("provider_id") is not None
                    else None
                ),
                source_record_id=item.get("source_record_id"),
                imported_asset_id=item.get("imported_asset_id"),
                orthophoto_georeference=item.get("orthophoto_georeference"),
                notes=item.get("notes"),
            )
            for item in value.get("layers", ())
        )
        result = cls(
            map_configuration_id=str(value["map_configuration_id"]),
            providers=providers,
            layers=layers,
        )
        result.validate()
        return result

    def validate(self) -> None:
        if not self.map_configuration_id:
            raise ValueError("map_configuration_id must not be empty")

        provider_ids = [item.provider_id for item in self.providers]
        if len(provider_ids) != len(set(provider_ids)):
            raise ValueError("map provider IDs must be unique")

        layer_ids = [item.layer_id for item in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("map layer IDs must be unique")

        providers = {item.provider_id: item for item in self.providers}
        for provider in self.providers:
            if provider.provider_kind not in _PROVIDER_KINDS:
                raise ValueError(
                    f"unsupported provider_kind: {provider.provider_kind}"
                )
            if provider.attribution_required and not provider.attribution:
                raise ValueError(
                    f"provider {provider.provider_id} requires attribution text"
                )
            if (
                provider.provider_kind == "xyz_raster"
                and not provider.tile_url_template
            ):
                raise ValueError(
                    f"provider {provider.provider_id} requires tile_url_template"
                )
            if (
                provider.provider_kind == "maplibre_style"
                and not provider.style_url
            ):
                raise ValueError(
                    f"provider {provider.provider_id} requires style_url"
                )

        for layer in self.layers:
            if layer.layer_type not in _LAYER_TYPES:
                raise ValueError(f"unsupported layer_type: {layer.layer_type}")
            if (
                layer.provider_id is not None
                and layer.provider_id not in providers
            ):
                raise ValueError(
                    f"layer {layer.layer_id} references unknown provider "
                    f"{layer.provider_id}"
                )
            if layer.layer_type == "orthophoto":
                if layer.provider_id is None:
                    raise ValueError(
                        f"orthophoto layer {layer.layer_id} requires provider_id"
                    )
                provider = providers[layer.provider_id]
                if provider.provider_kind != "uploaded_asset":
                    raise ValueError(
                        f"orthophoto layer {layer.layer_id} requires uploaded_asset provider"
                    )
                if not layer.imported_asset_id:
                    raise ValueError(
                        f"orthophoto layer {layer.layer_id} requires imported_asset_id"
                    )
                georeference = layer.orthophoto_georeference
                if not isinstance(georeference, Mapping):
                    raise ValueError(
                        f"orthophoto layer {layer.layer_id} requires georeference"
                    )
                if georeference.get("method") != "affine_control_points":
                    raise ValueError(
                        "Phase 4.1 orthophotos require affine_control_points"
                    )
                if len(georeference.get("control_points") or ()) < 3:
                    raise ValueError(
                        f"orthophoto layer {layer.layer_id} needs >=3 control points"
                    )

    def required_attributions(self) -> tuple[str, ...]:
        """Return deduplicated attribution strings required by configured providers."""
        values: list[str] = []
        for provider in self.providers:
            if provider.attribution_required and provider.attribution:
                if provider.attribution not in values:
                    values.append(provider.attribution)
        return tuple(values)
