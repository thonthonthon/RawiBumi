"""Stage-by-stage cross-software attribution."""

from .pvsyst import (
    DEFAULT_PHASE39_CAMPAIGN_PATH,
    assess_pvsyst_case_readiness,
    build_pvsyst_attribution_report,
    extract_opensimpv_attribution_metrics,
    load_pvsyst_attribution_campaign,
    pvsyst_reference_metrics,
    validate_pvsyst_reference_campaign,
)

__all__ = [
    "DEFAULT_PHASE39_CAMPAIGN_PATH",
    "assess_pvsyst_case_readiness",
    "build_pvsyst_attribution_report",
    "extract_opensimpv_attribution_metrics",
    "load_pvsyst_attribution_campaign",
    "pvsyst_reference_metrics",
    "validate_pvsyst_reference_campaign",
    "PVSYST_COMMON_INPUT_COLUMNS",
    "PVSYST_DETAILED_OUTPUT_FORMAT",
    "PVsystDetailedOutput",
    "common_input_logical_sha256",
    "extract_pvsyst_hourly_oracle_metrics",
    "infer_subhourly_clipping_correction",
    "parse_pvsyst_detailed_output",
    "pvsyst_output_to_canonical_weather",
    "validate_hourly_oracle_balance",
    "DETAILED_HOURLY_REPORT_SCHEMA_NAME",
    "DETAILED_HOURLY_REPORT_SCHEMA_VERSION",
    "build_pvsyst_detailed_hourly_attribution_report",
    "detailed_hourly_case_from_output",
    "detailed_hourly_interval_statistics",
    "detailed_hourly_grid_residual_decomposition",
    "pvsyst_azimuth_to_canonical",
    "pvsyst_detailed_hourly_reference_metrics",
]

from .pvsyst_output import (
    PVSYST_COMMON_INPUT_COLUMNS,
    PVSYST_DETAILED_OUTPUT_FORMAT,
    PVsystDetailedOutput,
    common_input_logical_sha256,
    extract_pvsyst_hourly_oracle_metrics,
    infer_subhourly_clipping_correction,
    parse_pvsyst_detailed_output,
    pvsyst_output_to_canonical_weather,
    validate_hourly_oracle_balance,
)

from .pvsyst_detailed import (
    DETAILED_HOURLY_REPORT_SCHEMA_NAME,
    DETAILED_HOURLY_REPORT_SCHEMA_VERSION,
    build_pvsyst_detailed_hourly_attribution_report,
    detailed_hourly_case_from_output,
    detailed_hourly_interval_statistics,
    detailed_hourly_grid_residual_decomposition,
    pvsyst_azimuth_to_canonical,
    pvsyst_detailed_hourly_reference_metrics,
)
