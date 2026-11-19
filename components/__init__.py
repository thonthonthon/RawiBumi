"""OpenSIMPV component-library code."""

from .candidates import build_inverter_candidate, build_module_candidate, finalize_candidate
from .design_integration import (
    COMPONENT_INTEGRATION_VERSION,
    ComponentDesignSession,
    inverter_design_snapshot,
    module_design_snapshot,
)
from .source_overlay import (
    ComponentSourceFragment,
    build_candidate_from_fragments,
    merge_component_fragments,
)
from .user_csv import (
    parse_inverter_component_csv,
    parse_inverter_efficiency_curve_csv,
    parse_module_component_csv,
)
from .user_yaml import parse_component_overlay_yaml
from .iv_reference import (
    IVReferenceValidationConfig,
    attach_reference_validation,
    fingerprint_source_bytes,
    load_iv_reference_dataset,
    parse_iv_summary_csv,
    parse_iv_summary_csv_bytes,
    parse_pvlib_pvsyst_demo_bytes,
    validate_pvsyst_sdm_against_reference,
)

__all__ = [
    "COMPONENT_INTEGRATION_VERSION",
    "ComponentDesignSession",
    "inverter_design_snapshot",
    "module_design_snapshot",
    "IVReferenceValidationConfig",
    "attach_reference_validation",
    "ComponentSourceFragment",
    "build_candidate_from_fragments",
    "merge_component_fragments",
    "parse_module_component_csv",
    "parse_inverter_component_csv",
    "parse_inverter_efficiency_curve_csv",
    "parse_component_overlay_yaml",
    "build_inverter_candidate",
    "build_module_candidate",
    "finalize_candidate",
    "fingerprint_source_bytes",
    "load_iv_reference_dataset",
    "parse_iv_summary_csv",
    "parse_iv_summary_csv_bytes",
    "parse_pvlib_pvsyst_demo_bytes",
    "validate_pvsyst_sdm_against_reference",
]
