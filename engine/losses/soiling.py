"""Monthly post-IAM attenuation with retained pre-soiling diagnostics."""

from __future__ import annotations
from typing import Any, Mapping
import numpy as np
import pandas as pd
from engine.optical import OpticalResult


def soiling_fractions(
    index: pd.DatetimeIndex, settings: Mapping[str, Any]
) -> np.ndarray:
    if index.tz is None:
        raise ValueError("soiling requires timezone-aware local interval starts")
    months = np.asarray(settings["values"]["soiling"]["monthly_fractions"], dtype=float)
    return months[index.month.to_numpy() - 1]


def apply_soiling(optical: OpticalResult, settings: Mapping[str, Any]) -> OpticalResult:
    frame = optical.frame.copy()
    fraction = soiling_fractions(frame.index, settings)
    before = frame["effective_irradiance_w_m2"].to_numpy(dtype=float)
    frame["post_iam_pre_soiling_w_m2"] = before
    frame["soiling_fraction"] = fraction
    frame["soiling_loss_w_m2"] = before * fraction
    # Avoid touching the legacy values for a zero schedule.
    if np.any(fraction):
        for column in optical.frame:
            if (
                column.startswith("effective_poa_")
                or column == "effective_irradiance_w_m2"
            ):
                frame[column] = optical.frame[column].to_numpy(dtype=float) * (
                    1 - fraction
                )
    return OpticalResult(
        frame,
        {
            **optical.metadata,
            "soiling_method": "monthly_post_iam",
            "loss_settings_sha256": settings["settings_sha256"],
        },
    )


def optical_reference_channels(
    optical: OpticalResult, raw_mpp: pd.Series, capacity_w: float
) -> dict[str, Any]:
    pre = optical.frame["post_iam_pre_soiling_w_m2"] * (capacity_w / 1000)
    loss = optical.frame["soiling_loss_w_m2"] * (capacity_w / 1000)
    after = pre - loss
    return {
        "optical_reference_w": pre,
        "soiling_reference_loss_w": loss,
        "after_soiling_reference_w": after,
        "module_operating_delta_w": after - raw_mpp,
    }
