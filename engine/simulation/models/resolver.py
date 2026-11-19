"""Combined module/inverter simulation-model resolution."""

from __future__ import annotations

from typing import Any

from .inverter_resolver import resolve_inverter_model
from .module_resolver import resolve_module_model


def resolve_simulation_models(
    module: dict[str, Any],
    inverter: dict[str, Any],
    *,
    resolution_id: str,
    requested_module_model_id: str | None = None,
    requested_inverter_model_id: str | None = None,
    required_inverter_refinements: set[str] | None = None,
) -> dict[str, Any]:
    """Resolve component models without silently relaxing explicit user requirements."""
    module_result = resolve_module_model(
        module,
        resolution_id=f"{resolution_id}:module",
        requested_model_id=requested_module_model_id,
    )
    inverter_result = resolve_inverter_model(
        inverter,
        resolution_id=f"{resolution_id}:inverter",
        requested_model_id=requested_inverter_model_id,
        required_refinements=required_inverter_refinements,
    )
    status = (
        "resolved"
        if module_result["status"] == "resolved"
        and inverter_result["status"] == "resolved"
        else "blocked"
    )
    return {
        "schema_name": "SimulationModelResolution",
        "schema_version": "0.1",
        "resolution_id": resolution_id,
        "status": status,
        "module": module_result,
        "inverter": inverter_result,
        "assumptions": [
            *module_result["assumptions"],
            *inverter_result["assumptions"],
        ],
        "warnings": [
            *module_result["warnings"],
            *inverter_result["warnings"],
        ],
    }
