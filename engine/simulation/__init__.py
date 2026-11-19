"""OpenSIMPV simulation orchestration."""

from .geometry_aware import (
    BEAM_VISIBILITY_AGGREGATION_METHOD_ID,
    DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID,
    GROUND_VISIBILITY_AGGREGATION_METHOD_ID,
    GEOMETRY_AWARE_FIXED_TILT_SCOPE,
    GEOMETRY_AWARE_BEAM_SKY_FIXED_TILT_SCOPE,
    GEOMETRY_AWARE_BEAM_SKY_GROUND_FIXED_TILT_SCOPE,
    BeamVerticalSliceError,
    run_beam_shaded_fixed_tilt,
    run_beam_sky_shaded_fixed_tilt,
    run_beam_sky_ground_shaded_fixed_tilt,
)

from .design import (
    DesignSimulationPreparation,
    DesignStatePackage,
    build_design_revision_store,
    build_project_revision_from_design,
    build_simulation_configuration_from_design,
    design_validation_gate,
    prepare_design_simulation,
    persist_design_state_package,
    load_design_state_package,
    referenced_component_revision_ids,
    run_validated_design_simulation,
)
from .execution_groups import (
    EXECUTION_GROUP_BUILDER_ID,
    EXECUTION_GROUP_BUILDER_VERSION,
    EXECUTION_GROUP_PLAN_VERSION,
    build_simulation_execution_plan,
)
from .canonical import (
    CanonicalRevisionStore,
    CanonicalSimulationExecutionResult,
    run_canonical_simulation,
)
from .temporal import (
    V1_TARGET_TIMESTEPS_SECONDS,
    TemporalExecutionContext,
    prepare_temporal_execution,
)
from .unshaded import (
    ResolvedModuleRuntimeInputs,
    UnshadedFixedTiltConfiguration,
    UnshadedFixedTiltSimulationResult,
    resolve_module_runtime_inputs,
    run_unshaded_fixed_tilt,
)

__all__ = [
    "EXECUTION_GROUP_BUILDER_ID",
    "EXECUTION_GROUP_BUILDER_VERSION",
    "EXECUTION_GROUP_PLAN_VERSION",
    "build_simulation_execution_plan",
    "BEAM_VISIBILITY_AGGREGATION_METHOD_ID",
    "DIFFUSE_VISIBILITY_AGGREGATION_METHOD_ID",
    "GROUND_VISIBILITY_AGGREGATION_METHOD_ID",
    "GEOMETRY_AWARE_FIXED_TILT_SCOPE",
    "GEOMETRY_AWARE_BEAM_SKY_FIXED_TILT_SCOPE",
    "GEOMETRY_AWARE_BEAM_SKY_GROUND_FIXED_TILT_SCOPE",
    "BeamVerticalSliceError",
    "run_beam_shaded_fixed_tilt",
    "run_beam_sky_shaded_fixed_tilt",
    "run_beam_sky_ground_shaded_fixed_tilt",
    "CanonicalRevisionStore",
    "CanonicalSimulationExecutionResult",
    "run_canonical_simulation",
    "DesignSimulationPreparation",
    "DesignStatePackage",
    "build_design_revision_store",
    "build_project_revision_from_design",
    "build_simulation_configuration_from_design",
    "design_validation_gate",
    "prepare_design_simulation",
    "persist_design_state_package",
    "load_design_state_package",
    "referenced_component_revision_ids",
    "run_validated_design_simulation",
    "V1_TARGET_TIMESTEPS_SECONDS",
    "TemporalExecutionContext",
    "prepare_temporal_execution",
    "ResolvedModuleRuntimeInputs",
    "UnshadedFixedTiltConfiguration",
    "UnshadedFixedTiltSimulationResult",
    "resolve_module_runtime_inputs",
    "run_unshaded_fixed_tilt",
]
