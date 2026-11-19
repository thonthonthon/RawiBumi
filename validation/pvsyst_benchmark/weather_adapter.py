"""Approved input recovery, without replacing execution solar geometry."""

from datetime import timedelta, timezone
from hashlib import sha256
import json

import numpy as np
import pandas as pd
from weather.core import build_time_semantics, build_weather_dataset
from weather.validation import attach_weather_qc
from .reference import Reference


def recover_weather(
    reference: Reference, *, site: dict, label: str, uv: float, omit_wind: bool = False
):
    if label not in {"P2", "P3"}:
        raise ValueError("only active case labels are allowed")
    if not np.isfinite(uv) or uv < 0 or omit_wind and uv != 0:
        raise ValueError("wind omission requires an explicitly verified Uv = 0")
    f = reference.frame
    beam = f.BeamHor.to_numpy()
    sine = np.sin(np.deg2rad(f.HSol.to_numpy()))
    if (beam < 0).any() or ((beam > 0) & (sine <= 0)).any():
        raise ValueError("positive beam requires positive source solar height")
    dni = np.divide(beam, sine, out=np.zeros(len(f)), where=beam > 0)
    offset = float(site["utc_offset_hours"])
    if not np.isfinite(offset) or abs(offset) > 14 or offset * 60 != round(offset * 60):
        raise ValueError("invalid fixed UTC offset")
    tz = timezone(timedelta(hours=offset))
    total_minutes = abs(round(offset * 60))
    sign = "+" if offset >= 0 else "-"
    tz_name = f"UTC{sign}{total_minutes//60:02d}:{total_minutes%60:02d}"
    data = {
        "ghi_w_m2": f.GlobHor.to_numpy(copy=True),
        "dhi_w_m2": f.DiffHor.to_numpy(copy=True),
        "dni_w_m2": dni,
        "ambient_temperature_c": f.T_Amb.to_numpy(copy=True),
    }
    if not omit_wind:
        data["wind_speed_m_s"] = f.WindVel.to_numpy(copy=True)
    series = pd.DataFrame(data, index=f.index.tz_localize(tz))
    method = {
        "method": "pvsyst_hourly_results_export",
        "source_sha256": reference.source_sha256,
        "dni_recovery": "BeamHor/sin(HSol); zero only for zero BeamHor",
        "execution_solar_geometry": "independent_canonical_SPA",
        "timestamp_convention": "interval_start",
        "source_year_preserved": True,
        "wind_omitted": omit_wind,
        "verified_uv": uv,
        "wind_omission_reason": (
            "Uv=0; source values preserved, column omitted" if omit_wind else None
        ),
    }
    digest = sha256(json.dumps(method, sort_keys=True).encode()).hexdigest()
    weather = build_weather_dataset(
        series,
        weather_dataset_id=f"wx-{label}-{digest[:12]}",
        revision_id=f"wx-{label}-{digest[:12]}-r1",
        name=f"{label} reference weather",
        site_id=label,
        timezone=tz_name,
        native_resolution_seconds=3600,
        source_format="pvsyst_hourly_results_export",
        source_timestamp_convention="interval_start",
        location={k: site[k] for k in ("latitude_deg", "longitude_deg", "elevation_m")},
        series_origin="opensimpv_derived",
        time_semantics=build_time_semantics(
            canonical_timezone=tz_name,
            source_timezone=tz_name,
            source_utc_offset_hours=offset,
            source_timestamp_convention="interval_start",
            native_interval_seconds=3600,
            current_interval_seconds=3600,
        ),
    )
    weather, qc = attach_weather_qc(weather)
    return weather, {
        **method,
        "qc": qc,
        "weather_revision_id": weather.dataset["revision_id"],
    }


def attach_weather(app, project_id, weather, receipt):
    """Validation-only weather bootstrap; no other project content is edited."""
    if receipt["qc"]["status"] == "failed":
        raise ValueError("weather QC failed; attachment refused")
    study, projects = app.state.study_service, app.state.project_service
    selection = study.weather.save(project_id, weather, acquisition_manifest=receipt)
    bundle = projects.get_bundle(project_id)
    bundle["weather_selection"] = selection
    bundle["project"]["project_revision"]["weather_dataset_revision_id"] = selection[
        "revision_id"
    ]
    projects.save_bundle(bundle)
    return {
        "project_id": project_id,
        "selection": selection,
        "method": receipt["method"],
    }
