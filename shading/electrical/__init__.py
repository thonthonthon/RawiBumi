"""Electrical-shading contract boundary for Development Phase 6."""

from .contract import (
    BYPASS_MODEL_TYPES,
    ELECTRICAL_SHADING_CONTRACT_VERSION,
    FIDELITY_LEVELS,
    MODULE_LOCAL_COORDINATE_CONVENTION,
    REGION_RESOLUTIONS,
    THERMAL_STATE_SCOPE,
    BypassModelEvidence,
    ElectricalShadingContractError,
    ResolvedModuleCapabilitySnapshot,
    TopologyValidationResult,
    ValidatedParameterizationEvidence,
    electrical_shading_execution_sha256,
    electrical_shading_scientific_identity_payload,
    electrical_shading_scientific_sha256,
    assert_electrical_iv_curve,
    assert_bypass_model_contract,
    assert_electrical_parameterization_evidence,
    assert_module_topology_definition,
    assert_requested_fidelity_available,
    assert_resolved_module_capability_evidence,
    resolve_bypass_model_evidence,
    resolve_electrical_shading_capability,
    resolve_module_capability_snapshot,
    resolve_region_geometry_execution_readiness,
    validate_parameterization_for_electrical_shading,
    validate_topology_for_electrical_shading,
    validate_normalized_uv_polygon,
)

from .region_map import (
    ELECTRICAL_REGION_MAPPER_ID,
    ELECTRICAL_REGION_MAPPER_VERSION,
    LANDSCAPE_ROTATION_CONVENTION,
    ElectricalRegionMapError,
    derive_electrical_region_map,
)
from .local_irradiance import (
    LOCAL_IRRADIANCE_MAPPER_ID,
    LOCAL_IRRADIANCE_MAPPER_VERSION,
    REGION_VISIBILITY_ORCHESTRATOR_ID,
    REGION_VISIBILITY_ORCHESTRATOR_VERSION,
    LocalElectricalIrradianceError,
    build_electrical_region_query_geometry,
    build_local_electrical_irradiance_state,
    evaluate_electrical_region_visibility,
)

from .module_approximation import (
    LEVEL1_MODULE_SOLVER_ID,
    LEVEL1_MODULE_SOLVER_VERSION,
    MODULE_RECEIVER_EQUIVALENT_METHOD,
    MODULE_VISIBILITY_ORCHESTRATOR_ID,
    MODULE_VISIBILITY_ORCHESTRATOR_VERSION,
    REGIONAL_EQUIVALENT_METHOD,
    Level1ModuleApproximationError,
    Level1ModuleApproximationResult,
    build_module_equivalent_irradiance_from_module_shading,
    collapse_local_irradiance_to_module_equivalent,
    evaluate_level1_module_approximation,
    evaluate_module_receiver_visibility,
)

__all__ = [
    "LEVEL1_MODULE_SOLVER_ID",
    "LEVEL1_MODULE_SOLVER_VERSION",
    "MODULE_RECEIVER_EQUIVALENT_METHOD",
    "MODULE_VISIBILITY_ORCHESTRATOR_ID",
    "MODULE_VISIBILITY_ORCHESTRATOR_VERSION",
    "REGIONAL_EQUIVALENT_METHOD",
    "Level1ModuleApproximationError",
    "Level1ModuleApproximationResult",
    "build_module_equivalent_irradiance_from_module_shading",
    "collapse_local_irradiance_to_module_equivalent",
    "evaluate_level1_module_approximation",
    "evaluate_module_receiver_visibility",
    "ELECTRICAL_REGION_MAPPER_ID",
    "ELECTRICAL_REGION_MAPPER_VERSION",
    "LANDSCAPE_ROTATION_CONVENTION",
    "ElectricalRegionMapError",
    "derive_electrical_region_map",
    "LOCAL_IRRADIANCE_MAPPER_ID",
    "LOCAL_IRRADIANCE_MAPPER_VERSION",
    "REGION_VISIBILITY_ORCHESTRATOR_ID",
    "REGION_VISIBILITY_ORCHESTRATOR_VERSION",
    "LocalElectricalIrradianceError",
    "build_electrical_region_query_geometry",
    "build_local_electrical_irradiance_state",
    "evaluate_electrical_region_visibility",
    "BYPASS_MODEL_TYPES",
    "ELECTRICAL_SHADING_CONTRACT_VERSION",
    "FIDELITY_LEVELS",
    "MODULE_LOCAL_COORDINATE_CONVENTION",
    "REGION_RESOLUTIONS",
    "THERMAL_STATE_SCOPE",
    "BypassModelEvidence",
    "ElectricalShadingContractError",
    "ResolvedModuleCapabilitySnapshot",
    "TopologyValidationResult",
    "ValidatedParameterizationEvidence",
    "electrical_shading_execution_sha256",
    "electrical_shading_scientific_identity_payload",
    "electrical_shading_scientific_sha256",
    "assert_electrical_iv_curve",
    "assert_bypass_model_contract",
    "assert_electrical_parameterization_evidence",
    "assert_module_topology_definition",
    "assert_requested_fidelity_available",
    "assert_resolved_module_capability_evidence",
    "resolve_bypass_model_evidence",
    "resolve_electrical_shading_capability",
    "resolve_module_capability_snapshot",
    "resolve_region_geometry_execution_readiness",
    "validate_parameterization_for_electrical_shading",
    "validate_topology_for_electrical_shading",
    "validate_normalized_uv_polygon",
]
# Phase 6.5 analytical substring/bypass reference API
from .substring_reference import (
    PHASE65_ANALYTICAL_REGION_MODEL_ID,
    PHASE65_REFERENCE_SOLVER_ID,
    AnalyticalRegionReferenceState,
    SubstringReferenceError,
    build_analytical_region_reference_states,
    evaluate_protected_substring_at_current,
    evaluate_series_branch_voltage,
    solve_parallel_branches_at_current,
)

__all__ += [
    "PHASE65_ANALYTICAL_REGION_MODEL_ID",
    "PHASE65_REFERENCE_SOLVER_ID",
    "AnalyticalRegionReferenceState",
    "SubstringReferenceError",
    "build_analytical_region_reference_states",
    "evaluate_protected_substring_at_current",
    "evaluate_series_branch_voltage",
    "solve_parallel_branches_at_current",
]
# Phase 6.6 executable parameterization and module-IV API
from .parameterization import (
    REGION_PARAMETERIZATION_MODEL_ID,
    REGION_PARAMETERIZATION_MODEL_VERSION,
    ElectricalParameterizationError,
    PVSystRegionElectricalState,
    assert_electrical_parameterization_definition,
    assert_parameterization_evidence_binding,
    build_pvsyst_region_electrical_states,
    compute_parameterization_payload_sha256,
    finalize_parameterization_payload,
)
from .module_iv import (
    MODULE_NONUNIFORM_IV_SOLVER_ID,
    MODULE_NONUNIFORM_IV_SOLVER_VERSION,
    NonuniformModuleIVError,
    NonuniformModuleIVResult,
    assemble_nonuniform_module_iv,
)

__all__ += [
    "REGION_PARAMETERIZATION_MODEL_ID",
    "REGION_PARAMETERIZATION_MODEL_VERSION",
    "ElectricalParameterizationError",
    "PVSystRegionElectricalState",
    "assert_electrical_parameterization_definition",
    "assert_parameterization_evidence_binding",
    "build_pvsyst_region_electrical_states",
    "compute_parameterization_payload_sha256",
    "finalize_parameterization_payload",
    "MODULE_NONUNIFORM_IV_SOLVER_ID",
    "MODULE_NONUNIFORM_IV_SOLVER_VERSION",
    "NonuniformModuleIVError",
    "NonuniformModuleIVResult",
    "assemble_nonuniform_module_iv",
]

# Phase 6.7 general series-string IV API
from .string_iv import (
    GENERAL_SERIES_STRING_IV_SOLVER_ID,
    GENERAL_SERIES_STRING_IV_SOLVER_VERSION,
    GeneralSeriesStringIVError,
    GeneralSeriesStringIVResult,
    SeriesModuleOperatingModel,
    assemble_general_series_string_iv,
)

__all__ += [
    "GENERAL_SERIES_STRING_IV_SOLVER_ID",
    "GENERAL_SERIES_STRING_IV_SOLVER_VERSION",
    "GeneralSeriesStringIVError",
    "GeneralSeriesStringIVResult",
    "SeriesModuleOperatingModel",
    "assemble_general_series_string_iv",
]

# Phase 6.7 Phase-6.6 series-module adapter API
from .module_series_adapter import (
    PHASE66_SERIES_MODULE_ADAPTER_ID,
    PHASE66_SERIES_MODULE_ADAPTER_VERSION,
    Phase66SeriesModuleAdapterError,
    build_phase66_series_module_operating_model,
)

__all__ += [
    "PHASE66_SERIES_MODULE_ADAPTER_ID",
    "PHASE66_SERIES_MODULE_ADAPTER_VERSION",
    "Phase66SeriesModuleAdapterError",
    "build_phase66_series_module_operating_model",
]

# Phase 6.8A physical parallel-string IV API
from .mppt_parallel import (
    PARALLEL_RULE,
    PARALLEL_STRING_IV_SOLVER_ID,
    PARALLEL_STRING_IV_SOLVER_VERSION,
    REVERSE_INTERSTRING_CURRENT_POLICY,
    SOURCE_CURVE_INTERPOLATION,
    VOLTAGE_GRID_STRATEGY,
    ParallelStringIVError,
    ParallelStringIVResult,
    assemble_parallel_mppt_iv,
)

__all__ += [
    "PARALLEL_RULE",
    "PARALLEL_STRING_IV_SOLVER_ID",
    "PARALLEL_STRING_IV_SOLVER_VERSION",
    "REVERSE_INTERSTRING_CURRENT_POLICY",
    "SOURCE_CURVE_INTERPOLATION",
    "VOLTAGE_GRID_STRATEGY",
    "ParallelStringIVError",
    "ParallelStringIVResult",
    "assemble_parallel_mppt_iv",
]

# Phase 6.8B explicit MPPT operating-point API
from .mppt_tracker import (
    IDEAL_GLOBAL_MPPT_MODEL_ID,
    IDEAL_GLOBAL_MPPT_MODEL_VERSION,
    MPPT_CONSTRAINT_ENFORCEMENT_POLICY,
    MPPT_POWER_LIMIT_STATUS,
    MPPTTrackerOperatingError,
    MPPTTrackerOperatingResult,
    select_mppt_operating_point,
)

__all__ += [
    "IDEAL_GLOBAL_MPPT_MODEL_ID",
    "IDEAL_GLOBAL_MPPT_MODEL_VERSION",
    "MPPT_CONSTRAINT_ENFORCEMENT_POLICY",
    "MPPT_POWER_LIMIT_STATUS",
    "MPPTTrackerOperatingError",
    "MPPTTrackerOperatingResult",
    "select_mppt_operating_point",
]
