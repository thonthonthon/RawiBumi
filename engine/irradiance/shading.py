"""Phase-5.5 beam-only POA modification.

The modifier applies one explicit geometric beam visibility series only to the
direct POA component. Sky diffuse and ground-reflected POA are preserved
unchanged. The returned PlaneOfArrayResult exposes pre/post shading channels so
the irradiance ledger reconciles directly.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .poa import PlaneOfArrayResult


BEAM_POA_MODIFIER_ID = "opensimpv.poa_near_shading.beam_only"
BEAM_POA_MODIFIER_VERSION = "0.1"

SKY_DIFFUSE_POA_MODIFIER_ID = "opensimpv.poa_near_shading.component_diffuse"
SKY_DIFFUSE_POA_MODIFIER_VERSION = "0.1"
GROUND_POA_MODIFIER_ID = "opensimpv.poa_near_shading.ground_visibility"
GROUND_POA_MODIFIER_VERSION = "0.1"
SIGNED_HORIZON_POLICY = "linear_scale_signed_perez_horizon_component"


def apply_beam_visibility_to_poa(
    poa: PlaneOfArrayResult,
    beam_visibility_factor: pd.Series | np.ndarray | list[float],
    *,
    aggregation_method_id: str,
    aggregation_metadata: dict[str, Any] | None = None,
) -> PlaneOfArrayResult:
    """Apply direct-beam geometric visibility while preserving other POA channels."""
    index = poa.frame.index

    if isinstance(beam_visibility_factor, pd.Series):
        values = beam_visibility_factor.reindex(index).to_numpy(dtype=float)
    else:
        values = np.asarray(beam_visibility_factor, dtype=float)

    if values.ndim != 1 or len(values) != len(index):
        raise ValueError(
            "beam_visibility_factor must provide one value per POA interval"
        )
    if not np.isfinite(values).all():
        raise ValueError("beam visibility factors must be finite")
    if not ((values >= 0.0) & (values <= 1.0)).all():
        raise ValueError("beam visibility factors must lie within [0, 1]")

    frame = poa.frame.copy()
    beam_unshaded = frame["poa_beam_w_m2"].to_numpy(dtype=float)
    sky = frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
    ground = frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float)
    global_unshaded = frame["poa_global_w_m2"].to_numpy(dtype=float)

    beam_shaded = beam_unshaded * values
    loss = beam_unshaded - beam_shaded
    global_shaded = beam_shaded + sky + ground

    frame["poa_beam_unshaded_w_m2"] = beam_unshaded
    frame["beam_visibility_factor_group"] = values
    frame["poa_beam_shaded_w_m2"] = beam_shaded
    frame["near_shading_beam_loss_w_m2"] = loss
    frame["poa_global_unshaded_w_m2"] = global_unshaded

    # Downstream IAM/thermal/electrical stages consume the canonical POA columns.
    # Replace only beam and total POA; sky/ground/subcomponents remain unchanged.
    frame["poa_beam_w_m2"] = beam_shaded
    frame["poa_global_w_m2"] = global_shaded
    frame["poa_diffuse_w_m2"] = sky + ground

    if not np.allclose(
        frame["poa_beam_unshaded_w_m2"].to_numpy(dtype=float)
        - frame["near_shading_beam_loss_w_m2"].to_numpy(dtype=float),
        frame["poa_beam_shaded_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-10,
    ):
        raise RuntimeError("beam near-shading loss does not reconcile")
    if not np.allclose(
        frame["poa_beam_w_m2"].to_numpy(dtype=float)
        + frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
        + frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
        frame["poa_global_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-8,
    ):
        raise RuntimeError("shaded POA global does not reconcile with components")
    if not np.array_equal(
        frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float),
        poa.frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float),
    ):
        raise RuntimeError("beam-only shading changed sky diffuse POA")
    if not np.array_equal(
        frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
        poa.frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
    ):
        raise RuntimeError("beam-only shading changed ground-reflected POA")

    metadata = dict(poa.metadata)
    metadata.update(
        {
            "unshaded": False,
            "near_shading_model_id": BEAM_POA_MODIFIER_ID,
            "near_shading_model_version": BEAM_POA_MODIFIER_VERSION,
            "near_shading_channels": ["beam"],
            "beam_visibility_aggregation_method_id": aggregation_method_id,
            "beam_visibility_aggregation_metadata": dict(
                aggregation_metadata or {}
            ),
            "beam_shading_factor": "timeseries_execution_group_factor",
            "diffuse_shading_factor": 1.0,
            "ground_shading_factor": 1.0,
            "poa_global_semantics": "after_beam_near_shading",
            "poa_global_unshaded_channel": "poa_global_unshaded_w_m2",
            "beam_loss_channel": "near_shading_beam_loss_w_m2",
        }
    )
    return PlaneOfArrayResult(frame=frame, metadata=metadata)


def _visibility_values(
    value: pd.Series | np.ndarray | list[float] | float,
    *,
    index: pd.DatetimeIndex,
    name: str,
) -> np.ndarray:
    if np.isscalar(value):
        values = np.full(len(index), float(value), dtype=float)
    elif isinstance(value, pd.Series):
        values = value.reindex(index).to_numpy(dtype=float)
    else:
        values = np.asarray(value, dtype=float)

    if values.ndim != 1 or len(values) != len(index):
        raise ValueError(f"{name} must provide one value per POA interval")
    if not np.isfinite(values).all():
        raise ValueError(f"{name} must be finite")
    if not ((values >= 0.0) & (values <= 1.0)).all():
        raise ValueError(f"{name} must lie within [0, 1]")
    return values


def apply_sky_diffuse_visibility_to_poa(
    poa: PlaneOfArrayResult,
    *,
    sky_visibility_factor: pd.Series | np.ndarray | list[float] | float,
    circumsolar_visibility_factor: pd.Series | np.ndarray | list[float] | float,
    horizon_visibility_factor: pd.Series | np.ndarray | list[float] | float,
    aggregation_method_id: str,
    aggregation_metadata: dict[str, Any] | None = None,
) -> PlaneOfArrayResult:
    """Apply component-aware sky obstruction while preserving beam and ground.

    Isotropic sky uses the hemispherical sky visibility factor. Circumsolar uses
    its directional factor. The Perez/Hay-Davies horizon channel uses a separate
    horizon-band factor.

    Perez horizon terms may be signed empirical corrections. Phase 5.6 therefore
    scales that signed term linearly and records the policy explicitly instead of
    clamping it to non-negative radiance.
    """
    index = poa.frame.index
    sky_factor = _visibility_values(
        sky_visibility_factor,
        index=index,
        name="sky_visibility_factor",
    )
    circumsolar_factor = _visibility_values(
        circumsolar_visibility_factor,
        index=index,
        name="circumsolar_visibility_factor",
    )
    horizon_factor = _visibility_values(
        horizon_visibility_factor,
        index=index,
        name="horizon_visibility_factor",
    )

    frame = poa.frame.copy()
    required = (
        "poa_beam_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_global_w_m2",
        "poa_isotropic_w_m2",
        "poa_circumsolar_w_m2",
        "poa_horizon_w_m2",
    )
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(
            "component diffuse shading requires POA columns: "
            + ", ".join(missing)
        )

    beam_before = frame["poa_beam_w_m2"].to_numpy(dtype=float).copy()
    ground_before = frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float).copy()
    sky_unshaded = frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
    isotropic_unshaded = frame["poa_isotropic_w_m2"].to_numpy(dtype=float)
    circumsolar_unshaded = frame["poa_circumsolar_w_m2"].to_numpy(dtype=float)
    horizon_unshaded = frame["poa_horizon_w_m2"].to_numpy(dtype=float)

    isotropic_shaded = isotropic_unshaded * sky_factor
    circumsolar_shaded = circumsolar_unshaded * circumsolar_factor
    horizon_shaded = horizon_unshaded * horizon_factor
    sky_shaded = isotropic_shaded + circumsolar_shaded + horizon_shaded

    frame["poa_sky_diffuse_unshaded_w_m2"] = sky_unshaded
    frame["sky_visibility_factor_group"] = sky_factor
    frame["circumsolar_visibility_factor_group"] = circumsolar_factor
    frame["horizon_visibility_factor_group"] = horizon_factor

    frame["poa_isotropic_unshaded_w_m2"] = isotropic_unshaded
    frame["poa_isotropic_shaded_w_m2"] = isotropic_shaded
    frame["near_shading_isotropic_loss_w_m2"] = (
        isotropic_unshaded - isotropic_shaded
    )

    frame["poa_circumsolar_unshaded_w_m2"] = circumsolar_unshaded
    frame["poa_circumsolar_shaded_w_m2"] = circumsolar_shaded
    frame["near_shading_circumsolar_loss_w_m2"] = (
        circumsolar_unshaded - circumsolar_shaded
    )

    frame["poa_horizon_unshaded_w_m2"] = horizon_unshaded
    frame["poa_horizon_shaded_w_m2"] = horizon_shaded
    frame["near_shading_horizon_delta_w_m2"] = (
        horizon_unshaded - horizon_shaded
    )

    frame["poa_sky_diffuse_shaded_w_m2"] = sky_shaded
    frame["near_shading_sky_diffuse_loss_w_m2"] = (
        sky_unshaded - sky_shaded
    )

    # Canonical component columns consumed by IAM become the post-obstruction
    # values. Beam and ground are deliberately not changed here.
    frame["poa_isotropic_w_m2"] = isotropic_shaded
    frame["poa_circumsolar_w_m2"] = circumsolar_shaded
    frame["poa_horizon_w_m2"] = horizon_shaded
    frame["poa_sky_diffuse_w_m2"] = sky_shaded
    frame["poa_diffuse_w_m2"] = sky_shaded + ground_before
    frame["poa_global_w_m2"] = beam_before + sky_shaded + ground_before

    if not np.array_equal(
        frame["poa_beam_w_m2"].to_numpy(dtype=float),
        beam_before,
    ):
        raise RuntimeError("diffuse sky shading changed direct POA beam")
    if not np.array_equal(
        frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
        ground_before,
    ):
        raise RuntimeError("diffuse sky shading changed ground-reflected POA")
    if not np.allclose(
        frame["poa_isotropic_w_m2"].to_numpy(dtype=float)
        + frame["poa_circumsolar_w_m2"].to_numpy(dtype=float)
        + frame["poa_horizon_w_m2"].to_numpy(dtype=float),
        frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-9,
        equal_nan=True,
    ):
        raise RuntimeError("shaded sky diffuse does not reconcile with subcomponents")
    if not np.allclose(
        frame["poa_beam_w_m2"].to_numpy(dtype=float)
        + frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
        + frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
        frame["poa_global_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-8,
        equal_nan=True,
    ):
        raise RuntimeError("diffuse-shaded POA global does not reconcile")

    metadata = dict(poa.metadata)
    prior_channels = list(metadata.get("near_shading_channels") or [])
    channels = list(prior_channels)
    for channel in (
        "sky_isotropic",
        "circumsolar",
        "horizon",
    ):
        if channel not in channels:
            channels.append(channel)
    metadata.update(
        {
            "unshaded": False,
            "near_shading_model_id": SKY_DIFFUSE_POA_MODIFIER_ID,
            "near_shading_model_version": SKY_DIFFUSE_POA_MODIFIER_VERSION,
            "near_shading_channels": channels,
            "diffuse_visibility_aggregation_method_id": aggregation_method_id,
            "diffuse_visibility_aggregation_metadata": dict(
                aggregation_metadata or {}
            ),
            "diffuse_shading_factor": "component_timeseries_execution_group_factors",
            "ground_shading_factor": 1.0,
            "circumsolar_obstruction_policy": "directional_sun_visibility",
            "horizon_obstruction_policy": SIGNED_HORIZON_POLICY,
            "poa_sky_diffuse_unshaded_channel": "poa_sky_diffuse_unshaded_w_m2",
            "sky_diffuse_loss_channel": "near_shading_sky_diffuse_loss_w_m2",
            "poa_global_semantics": "after_beam_and_sky_diffuse_near_shading",
        }
    )
    return PlaneOfArrayResult(frame=frame, metadata=metadata)


def apply_ground_visibility_to_poa(
    poa: PlaneOfArrayResult,
    ground_visibility_factor: pd.Series | np.ndarray | list[float] | float,
    *,
    aggregation_method_id: str,
    aggregation_metadata: dict[str, Any] | None = None,
) -> PlaneOfArrayResult:
    """Apply receiver-side ground/albedo obstruction after beam/sky shading.

    Only the existing ground-reflected POA component is scaled. Direct beam,
    isotropic/circumsolar/horizon sky components, and total sky diffuse are
    preserved exactly.
    """
    index = poa.frame.index
    factor = _visibility_values(
        ground_visibility_factor,
        index=index,
        name="ground_visibility_factor",
    )
    frame = poa.frame.copy()

    required = (
        "poa_beam_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_global_w_m2",
    )
    missing = [column for column in required if column not in frame]
    if missing:
        raise ValueError(
            "ground shading requires POA columns: " + ", ".join(missing)
        )

    preserved = {
        column: frame[column].to_numpy(dtype=float).copy()
        for column in (
            "poa_beam_w_m2",
            "poa_sky_diffuse_w_m2",
            "poa_isotropic_w_m2",
            "poa_circumsolar_w_m2",
            "poa_horizon_w_m2",
        )
        if column in frame
    }

    ground_unshaded = frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float)
    ground_shaded = ground_unshaded * factor

    frame["poa_ground_diffuse_unshaded_w_m2"] = ground_unshaded
    frame["ground_visibility_factor_group"] = factor
    frame["poa_ground_diffuse_shaded_w_m2"] = ground_shaded
    frame["near_shading_ground_diffuse_loss_w_m2"] = (
        ground_unshaded - ground_shaded
    )
    frame["poa_ground_diffuse_w_m2"] = ground_shaded
    frame["poa_diffuse_w_m2"] = (
        frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
        + ground_shaded
    )
    frame["poa_global_w_m2"] = (
        frame["poa_beam_w_m2"].to_numpy(dtype=float)
        + frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
        + ground_shaded
    )

    for column, before in preserved.items():
        if not np.array_equal(
            frame[column].to_numpy(dtype=float),
            before,
        ):
            raise RuntimeError(
                f"ground near-shading changed preserved channel {column}"
            )

    if not np.allclose(
        frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
        + frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
        frame["poa_diffuse_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-9,
        equal_nan=True,
    ):
        raise RuntimeError("ground-shaded diffuse POA does not reconcile")
    if not np.allclose(
        frame["poa_beam_w_m2"].to_numpy(dtype=float)
        + frame["poa_sky_diffuse_w_m2"].to_numpy(dtype=float)
        + frame["poa_ground_diffuse_w_m2"].to_numpy(dtype=float),
        frame["poa_global_w_m2"].to_numpy(dtype=float),
        rtol=0.0,
        atol=1e-8,
        equal_nan=True,
    ):
        raise RuntimeError("ground-shaded POA global does not reconcile")

    metadata = dict(poa.metadata)
    channels = list(metadata.get("near_shading_channels") or [])
    if "ground" not in channels:
        channels.append("ground")
    metadata.update(
        {
            "unshaded": False,
            "near_shading_model_id": GROUND_POA_MODIFIER_ID,
            "near_shading_model_version": GROUND_POA_MODIFIER_VERSION,
            "near_shading_channels": channels,
            "ground_visibility_aggregation_method_id": aggregation_method_id,
            "ground_visibility_aggregation_metadata": dict(
                aggregation_metadata or {}
            ),
            "ground_shading_factor": "timeseries_execution_group_factor",
            "ground_source_model": (
                "existing_uniform_lambertian_scalar_albedo_poa_component"
            ),
            "poa_ground_diffuse_unshaded_channel": (
                "poa_ground_diffuse_unshaded_w_m2"
            ),
            "ground_diffuse_loss_channel": (
                "near_shading_ground_diffuse_loss_w_m2"
            ),
            "poa_global_semantics": (
                "after_beam_sky_and_ground_near_shading"
            ),
        }
    )
    return PlaneOfArrayResult(frame=frame, metadata=metadata)
