"""Unified weather import dispatch for supported Phase-2 formats."""

from __future__ import annotations

from pathlib import Path

from weather.core import CanonicalWeather
from weather.csv import read_opensimpv_weather_csv_bytes
from weather.epw import read_epw_weather_bytes
from weather.meteonorm import read_meteonorm_dat_bytes
from weather.pvsyst import (
    probe_pvsyst_weather_bytes,
    read_pvsyst_standard_weather_bytes,
)
from weather.tmy3 import read_tmy3_weather_bytes


SUPPORTED_WEATHER_FORMATS = {
    "opensimpv_csv",
    "tmy3",
    "epw",
    "meteonorm_dat",
    "pvsyst_standard_csv",
}

DETECTABLE_UNSUPPORTED_WEATHER_FORMATS = {
    "pvsyst_internal_met_text",
    "pvsyst_internal_met_binary",
    "pvsyst_met_unrecognized",
}


def detect_weather_format(data: bytes, *, filename: str) -> str:
    text = data[:8192].decode("utf-8-sig", errors="ignore")
    stripped = text.lstrip()
    lower_name = filename.lower()

    if stripped.startswith("# format=OpenSIMPV Weather CSV"):
        return "opensimpv_csv"

    pvsyst_probe = probe_pvsyst_weather_bytes(data, filename=filename)
    if pvsyst_probe["is_pvsyst_weather"]:
        return pvsyst_probe["format_id"]

    if lower_name.endswith(".epw") or stripped.startswith("LOCATION,"):
        return "epw"
    lines = text.splitlines()
    if (
        len(lines) >= 3
        and "[timezone h]" in lines[1]
        and "[time ref. min]" in lines[1]
        and {"m", "dm", "dy", "h", "mi"}.issubset(
            set(lines[2].replace("\t", " ").split())
        )
    ):
        return "meteonorm_dat"
    if len(lines) >= 2 and "Date (MM/DD/YYYY)" in lines[1] and "Time (HH:MM)" in lines[1]:
        return "tmy3"
    raise ValueError(
        "unable to detect weather format; specify one of: "
        + ", ".join(sorted(SUPPORTED_WEATHER_FORMATS))
    )


def read_weather_bytes(
    data: bytes,
    *,
    weather_dataset_id: str,
    revision_id: str,
    name: str,
    site_id: str,
    filename: str,
    source_id: str | None = None,
    source_url: str | None = None,
    source_format: str | None = None,
) -> CanonicalWeather:
    selected = source_format or detect_weather_format(data, filename=filename)

    common = {
        "weather_dataset_id": weather_dataset_id,
        "revision_id": revision_id,
        "name": name,
        "site_id": site_id,
        "filename": filename,
        "source_id": source_id,
        "source_url": source_url,
    }

    if selected == "opensimpv_csv":
        return read_opensimpv_weather_csv_bytes(data, **common)
    if selected == "tmy3":
        return read_tmy3_weather_bytes(data, **common)
    if selected == "epw":
        return read_epw_weather_bytes(data, **common)
    if selected == "meteonorm_dat":
        return read_meteonorm_dat_bytes(data, **common)
    if selected == "pvsyst_standard_csv":
        return read_pvsyst_standard_weather_bytes(data, **common)
    if selected in DETECTABLE_UNSUPPORTED_WEATHER_FORMATS:
        probe = probe_pvsyst_weather_bytes(data, filename=filename)
        detail = probe.get("internal_object") or {}
        version = detail.get("version")
        version_text = f" version={version}" if version else ""
        raise NotImplementedError(
            f"Detected {selected}{version_text}, but direct PVsyst internal .MET "
            "weather-series decoding is intentionally deferred. The container can be "
            "probed without interpreting its encoded payload; use/export the documented "
            "PVsyst Standard weather CSV for canonical import."
        )
    raise ValueError(f"unsupported weather format {selected!r}")
