"""OpenSIMPV native weather CSV import/export.

The format is intentionally simple and human-editable. Metadata lines use "# key=value".
The data table uses canonical OpenSIMPV variable names.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from typing import Any

import pandas as pd

from weather.core import (
    CANONICAL_VARIABLES,
    CanonicalWeather,
    build_weather_dataset,
    fingerprint_source_bytes,
    transformation,
)


_METADATA_RE = re.compile(r"^#\s*([^=]+?)\s*=\s*(.*?)\s*$")
_EXPLICIT_OFFSET_RE = re.compile(r"(?:Z|[+-]\d{2}:?\d{2})$")


def _parse_metadata_and_csv(text: str) -> tuple[dict[str, str], str]:
    metadata: dict[str, str] = {}
    data_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("#"):
            match = _METADATA_RE.match(line)
            if match:
                metadata[match.group(1).strip()] = match.group(2).strip()
            continue
        if line.strip():
            data_lines.append(line)
    if not data_lines:
        raise ValueError("OpenSIMPV weather CSV has no data table")
    return metadata, "\n".join(data_lines) + "\n"


def _parse_timestamps(values: pd.Series, timezone: str) -> pd.DatetimeIndex:
    strings = values.astype(str).str.strip()
    if strings.empty:
        raise ValueError("weather CSV contains no timestamps")

    has_offsets = strings.map(lambda value: bool(_EXPLICIT_OFFSET_RE.search(value))).all()
    has_no_offsets = strings.map(lambda value: not bool(_EXPLICIT_OFFSET_RE.search(value))).all()

    if not (has_offsets or has_no_offsets):
        raise ValueError(
            "timestamp column mixes offset-aware and naive values; use one convention"
        )

    if has_offsets:
        parsed = pd.to_datetime(strings, utc=True, errors="raise")
        try:
            return pd.DatetimeIndex(parsed).tz_convert(timezone)
        except Exception as exc:
            raise ValueError(f"invalid timezone {timezone!r}") from exc

    parsed = pd.DatetimeIndex(pd.to_datetime(strings, errors="raise"))
    try:
        return parsed.tz_localize(timezone, ambiguous="raise", nonexistent="raise")
    except Exception as exc:
        raise ValueError(
            f"cannot localize weather timestamps to timezone {timezone!r}"
        ) from exc


def _normalize_interval_start(
    index: pd.DatetimeIndex,
    *,
    source_timestamp_convention: str,
    duration_seconds: int,
) -> tuple[pd.DatetimeIndex, list[dict[str, Any]]]:
    transformations: list[dict[str, Any]] = []
    if source_timestamp_convention == "interval_start":
        return index, transformations
    if source_timestamp_convention == "interval_end":
        normalized = index - pd.Timedelta(seconds=duration_seconds)
        shift = -duration_seconds
    elif source_timestamp_convention == "interval_midpoint":
        normalized = index - pd.Timedelta(seconds=duration_seconds / 2)
        shift = -duration_seconds / 2
    else:
        raise ValueError(
            "source_timestamp_convention must be interval_start, interval_end, "
            "or interval_midpoint"
        )

    transformations.append(
        transformation(
            "timezone_normalization",
            algorithm="timestamp_convention_to_interval_start",
            algorithm_version="0.1",
            parameters={
                "source_timestamp_convention": source_timestamp_convention,
                "shift_seconds": shift,
            },
        )
    )
    return normalized, transformations


def read_opensimpv_weather_csv_bytes(
    data: bytes,
    *,
    weather_dataset_id: str,
    revision_id: str,
    name: str,
    site_id: str,
    filename: str,
    source_id: str | None = None,
    source_url: str | None = None,
    encoding: str = "utf-8-sig",
) -> CanonicalWeather:
    text = data.decode(encoding)
    metadata, table_text = _parse_metadata_and_csv(text)

    timezone = metadata.get("timezone")
    if not timezone:
        raise ValueError("OpenSIMPV weather CSV requires '# timezone=...' metadata")

    native_resolution = int(metadata.get("native_resolution_seconds", "0"))
    if native_resolution <= 0:
        raise ValueError(
            "OpenSIMPV weather CSV requires positive '# native_resolution_seconds=...'"
        )
    series_resolution = int(
        metadata.get("series_resolution_seconds", str(native_resolution))
    )
    if series_resolution <= 0:
        raise ValueError("series_resolution_seconds must be positive")

    source_timestamp_convention = metadata.get(
        "source_timestamp_convention",
        metadata.get("timestamp_convention", "interval_start"),
    )

    frame = pd.read_csv(io.StringIO(table_text))
    if "timestamp" not in frame.columns:
        raise ValueError("OpenSIMPV weather CSV requires a timestamp column")

    index = _parse_timestamps(frame.pop("timestamp"), timezone)
    index, transformations = _normalize_interval_start(
        index,
        source_timestamp_convention=source_timestamp_convention,
        duration_seconds=series_resolution,
    )

    unknown_columns = [
        column for column in frame.columns if column not in CANONICAL_VARIABLES
    ]
    if unknown_columns:
        raise ValueError(
            "unknown OpenSIMPV weather columns: " + ", ".join(unknown_columns)
        )

    for column in frame.columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isin([math.inf, -math.inf]).any():
            raise ValueError(f"OpenSIMPV weather CSV contains an infinite numeric value in {column}")
        frame[column] = numeric
    frame.index = index

    source_file = fingerprint_source_bytes(
        data,
        file_id=f"{weather_dataset_id}:source:0",
        filename=filename,
        media_type="text/csv",
        source_url=source_url,
    )

    location: dict[str, Any] | None = None
    if any(
        key in metadata
        for key in ("latitude_deg", "longitude_deg", "elevation_m")
    ):
        location = {
            "latitude_deg": (
                float(metadata["latitude_deg"])
                if metadata.get("latitude_deg")
                else None
            ),
            "longitude_deg": (
                float(metadata["longitude_deg"])
                if metadata.get("longitude_deg")
                else None
            ),
            "elevation_m": (
                float(metadata["elevation_m"])
                if metadata.get("elevation_m")
                else None
            ),
        }

    time_semantics = None
    if "time_semantics_json" in metadata:
        try:
            parsed_time_semantics = json.loads(metadata["time_semantics_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("invalid time_semantics_json metadata") from exc
        if parsed_time_semantics is not None and not isinstance(
            parsed_time_semantics, dict
        ):
            raise ValueError("time_semantics_json must contain an object or null")
        time_semantics = parsed_time_semantics

    native_series_origin = metadata.get("native_series_origin", "unknown")
    series_origin = metadata.get("series_origin", native_series_origin)
    upstream_generation = None
    if "upstream_generation_json" in metadata:
        try:
            parsed_upstream = json.loads(metadata["upstream_generation_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("invalid upstream_generation_json metadata") from exc
        if parsed_upstream is not None and not isinstance(parsed_upstream, dict):
            raise ValueError("upstream_generation_json must contain an object or null")
        upstream_generation = parsed_upstream

    extra_metadata: dict[str, Any] = {
        "source_metadata": {
            key: value
            for key, value in metadata.items()
            if key
            not in {
                "timezone",
                "native_resolution_seconds",
                "series_resolution_seconds",
                "timestamp_convention",
                "source_timestamp_convention",
                "native_series_origin",
                "series_origin",
                "upstream_generation_json",
                "time_semantics_json",
                "latitude_deg",
                "longitude_deg",
                "elevation_m",
            }
        }
    }
    if "transformations_json" in metadata:
        try:
            earlier = json.loads(metadata["transformations_json"])
            if isinstance(earlier, list):
                transformations = [*earlier, *transformations]
        except json.JSONDecodeError as exc:
            raise ValueError("invalid transformations_json metadata") from exc

    return build_weather_dataset(
        frame,
        weather_dataset_id=weather_dataset_id,
        revision_id=revision_id,
        name=name,
        site_id=site_id,
        timezone=timezone,
        native_resolution_seconds=native_resolution,
        series_resolution_seconds=series_resolution,
        source_id=source_id,
        source_format="opensimpv_csv_v0.1",
        source_timestamp_convention=source_timestamp_convention,
        source_files=[source_file],
        location=location,
        transformations=transformations,
        native_series_origin=native_series_origin,
        series_origin=series_origin,
        upstream_generation=upstream_generation,
        time_semantics=time_semantics,
        extra_metadata=extra_metadata,
    )


def write_opensimpv_weather_csv(weather: CanonicalWeather) -> str:
    """Serialize canonical weather to a portable human-readable CSV."""
    dataset = weather.dataset
    lines = [
        "# format=OpenSIMPV Weather CSV v0.1",
        f"# timezone={dataset['timezone']}",
        f"# native_resolution_seconds={dataset['native_resolution_seconds']}",
        f"# series_resolution_seconds={dataset['series_resolution_seconds']}",
        f"# native_series_origin={dataset.get('native_series_origin', 'unknown')}",
        f"# series_origin={dataset.get('series_origin', 'unknown')}",
        "# timestamp_convention=interval_start",
        "# source_timestamp_convention=interval_start",
    ]

    location = dataset.get("location") or {}
    for key in ("latitude_deg", "longitude_deg", "elevation_m"):
        if location.get(key) is not None:
            lines.append(f"# {key}={location[key]}")

    if dataset.get("time_semantics") is not None:
        lines.append(
            "# time_semantics_json="
            + json.dumps(dataset["time_semantics"], separators=(",", ":"))
        )

    if dataset.get("upstream_generation") is not None:
        lines.append(
            "# upstream_generation_json="
            + json.dumps(dataset["upstream_generation"], separators=(",", ":"))
        )

    if dataset.get("transformations"):
        lines.append(
            "# transformations_json="
            + json.dumps(dataset["transformations"], separators=(",", ":"))
        )

    output = io.StringIO()
    frame = weather.series.copy()
    frame.insert(
        0,
        "timestamp",
        [pd.Timestamp(value).isoformat() for value in frame.index],
    )
    frame.to_csv(output, index=False, quoting=csv.QUOTE_MINIMAL)
    return "\n".join(lines) + "\n" + output.getvalue()
