"""Open-Meteo Historical Weather acquisition adapter.

Phase 6.0B deliberately supports explicit source products only. The provider's
"default Best Match" and ERA5-Seamless products are not accepted because they
combine multiple meteorological sources and would violate the frozen source
isolation contract.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd

from weather.core import (
    build_time_semantics,
    build_weather_dataset,
    fingerprint_source_bytes,
    transformation,
)
from weather.providers.base import (
    WeatherAcquisitionError,
    WeatherAcquisitionRequest,
    WeatherAcquisitionResult,
    fingerprint_canonical_weather,
)
from weather.providers.snapshot_store import FileSystemWeatherSnapshotStore
from weather.validation import attach_weather_qc


OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Requested in canonical-friendly units where the API offers a unit switch.
_OPEN_METEO_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "dew_point_2m",
    "surface_pressure",
    "wind_speed_10m",
    "shortwave_radiation",
    "direct_normal_irradiance",
    "diffuse_radiation",
)


@dataclass(frozen=True)
class OpenMeteoSourceProduct:
    source_id: str
    model_parameter: str
    display_name: str
    method_id: str
    spatial_basis: str
    temporal_basis: str
    attribution: str
    license_url: str


OPEN_METEO_SOURCE_PRODUCTS: dict[str, OpenMeteoSourceProduct] = {
    "open_meteo_archive_era5": OpenMeteoSourceProduct(
        source_id="open_meteo_archive_era5",
        model_parameter="era5",
        display_name="ERA5 via Open-Meteo Historical Weather API",
        method_id="era5_reanalysis_via_open_meteo",
        spatial_basis=(
            "ERA5 reanalysis grid exposed by Open-Meteo; requested cell-selection "
            "and elevation/downscaling parameters remain provider-owned semantics."
        ),
        temporal_basis=(
            "Hourly source labels. Open-Meteo documents solar-radiation fields as "
            "preceding-hour means; meteorological state fields such as temperature "
            "and wind are instantaneous at the returned source label."
        ),
        attribution="Open-Meteo; ERA5 upstream data from ECMWF/Copernicus",
        license_url="https://open-meteo.com/en/features#terms",
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_real_instant(day: date, timezone_name: str) -> pd.Timestamp:
    """Resolve a calendar boundary without modifying any source timestamps."""
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        # Preserve accepted pandas fixed-offset names such as UTC+07:00.
        return pd.Timestamp(day).tz_localize(timezone_name)
    midnight = datetime.combine(day, datetime.min.time())
    wall_midnight = pd.Timestamp(midnight)
    candidates = [
        pd.Timestamp(midnight.replace(tzinfo=zone, fold=fold)).tz_convert("UTC")
        for fold in (0, 1)
    ]
    real_midnights = [
        instant for instant in candidates
        if instant.tz_convert(zone).tz_localize(None) == wall_midnight
    ]
    if real_midnights:
        # Repeated midnight belongs to this date from its earlier occurrence.
        return min(real_midnights).tz_convert(zone)

    # Midnight is in a forward clock gap. The two folds bracket the transition.
    # Locate its exact instant: rounding forward to a whole hour would be wrong
    # for quarter-hour changes and for a wholly skipped date (e.g. Apia).
    lower, upper = min(t.value for t in candidates), max(t.value for t in candidates)
    while lower < upper:
        middle = (lower + upper) // 2
        wall_time = pd.Timestamp(middle, unit="ns", tz="UTC").tz_convert(zone).tz_localize(None)
        if wall_time >= wall_midnight:
            upper = middle
        else:
            lower = middle + 1
    return pd.Timestamp(lower, unit="ns", tz="UTC").tz_convert(zone)


def _local_window(request: WeatherAcquisitionRequest) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = _first_real_instant(date.fromisoformat(request.start_date), request.timezone)
    end = _first_real_instant(
        date.fromisoformat(request.end_date) + timedelta(days=1), request.timezone
    )
    if end <= start:
        raise ValueError(
            f"Requested local weather window contains no real instants in "
            f"{request.timezone}: {request.start_date}..{request.end_date}"
        )
    return start, end


def _normalize_unit_text(value: str | None) -> str:
    if value is None:
        return ""
    return (
        str(value)
        .replace("²", "2")
        .replace("°", "deg")
        .replace(" ", "")
        .lower()
    )


def _require_unit(
    units: dict[str, Any],
    source_name: str,
    allowed: set[str],
) -> str:
    raw = units.get(source_name)
    normalized = _normalize_unit_text(raw)
    if normalized not in allowed:
        raise WeatherAcquisitionError(
            f"unexpected Open-Meteo unit for {source_name}: {raw!r}",
            provider_id="open_meteo",
            finding_code="WX_PROVIDER_UNIT_UNSUPPORTED",
        )
    return normalized


def _numeric_series(values: Any, *, name: str, expected_length: int) -> pd.Series:
    if not isinstance(values, list):
        raise WeatherAcquisitionError(
            f"Open-Meteo hourly field {name!r} is not an array",
            provider_id="open_meteo",
            finding_code="WX_PROVIDER_SCHEMA_INVALID",
        )
    if len(values) != expected_length:
        raise WeatherAcquisitionError(
            f"Open-Meteo hourly field {name!r} length {len(values)} does not match "
            f"time length {expected_length}",
            provider_id="open_meteo",
            finding_code="WX_PROVIDER_SCHEMA_INVALID",
        )
    return pd.to_numeric(pd.Series(values, dtype="object"), errors="coerce")


class OpenMeteoHistoricalAdapter:
    provider_id = "open_meteo"
    adapter_id = "open_meteo_historical"
    adapter_version = "0.1"

    def __init__(self, *, base_url: str = OPEN_METEO_ARCHIVE_URL) -> None:
        self.base_url = base_url

    def supported_source_ids(self) -> tuple[str, ...]:
        return tuple(sorted(OPEN_METEO_SOURCE_PRODUCTS))

    def source_product(self, source_id: str) -> OpenMeteoSourceProduct:
        try:
            return OPEN_METEO_SOURCE_PRODUCTS[source_id]
        except KeyError as exc:
            raise WeatherAcquisitionError(
                (
                    f"unsupported Open-Meteo source_id {source_id!r}; explicit source "
                    f"selection is required and no fallback will be attempted. "
                    f"Supported: {', '.join(self.supported_source_ids())}"
                ),
                provider_id=self.provider_id,
                source_id=source_id,
                finding_code="WX_SOURCE_UNSUPPORTED",
            ) from exc

    def build_request_parameters(
        self,
        request: WeatherAcquisitionRequest,
    ) -> dict[str, str]:
        source = self.source_product(request.source_id)
        # Refuse wholly skipped local dates before building a URL or transport.
        _local_window(request)
        padded_start = date.fromisoformat(request.start_date) - timedelta(days=1)
        padded_end = min(
            date.fromisoformat(request.end_date) + timedelta(days=1),
            datetime.now(timezone.utc).date(),
        )
        parameters: dict[str, str] = {
            "latitude": format(float(request.latitude_deg), ".8f").rstrip("0").rstrip("."),
            "longitude": format(float(request.longitude_deg), ".8f").rstrip("0").rstrip("."),
            "start_date": padded_start.isoformat(),
            "end_date": padded_end.isoformat(),
            "hourly": ",".join(_OPEN_METEO_HOURLY_VARIABLES),
            "temperature_unit": "celsius",
            "wind_speed_unit": "ms",
            "timeformat": "unixtime",
            # Unix timestamps are UTC regardless, but GMT is explicit and prevents a
            # provider-local calendar label from becoming canonical authority.
            "timezone": "GMT",
            "models": source.model_parameter,
            "cell_selection": request.cell_selection,
        }
        if request.elevation_m is not None:
            parameters["elevation"] = format(float(request.elevation_m), ".3f").rstrip(
                "0"
            ).rstrip(".")
        return parameters

    def build_request_url(self, request: WeatherAcquisitionRequest) -> str:
        return f"{self.base_url}?{urlencode(self.build_request_parameters(request))}"

    def _get_bytes(self, url: str, *, timeout_seconds: float) -> bytes:
        req = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "RawiBumi/0.1 weather acquisition",
            },
        )
        try:
            with urlopen(req, timeout=timeout_seconds) as response:
                status = getattr(response, "status", 200)
                if status != 200:
                    raise WeatherAcquisitionError(
                        f"Open-Meteo returned HTTP {status}",
                        provider_id=self.provider_id,
                        finding_code="WX_PROVIDER_HTTP_ERROR",
                    )
                return response.read()
        except HTTPError as exc:
            raise WeatherAcquisitionError(
                f"Open-Meteo returned HTTP {exc.code}: {exc.reason}",
                provider_id=self.provider_id,
                finding_code="WX_PROVIDER_HTTP_ERROR",
            ) from exc
        except URLError as exc:
            raise WeatherAcquisitionError(
                f"Open-Meteo request failed: {exc.reason}",
                provider_id=self.provider_id,
                finding_code="WX_PROVIDER_UNAVAILABLE",
            ) from exc

    def acquire(
        self,
        request: WeatherAcquisitionRequest,
        *,
        weather_dataset_id: str,
        revision_id: str,
        name: str,
        site_id: str,
        timeout_seconds: float = 30.0,
        snapshot_store: FileSystemWeatherSnapshotStore | None = None,
        requested_at: str | None = None,
        retrieved_at: str | None = None,
    ) -> WeatherAcquisitionResult:
        # Resolve before transport. Unknown sources fail here; there is no
        # provider-default, best-match, or cross-source fallback.
        self.source_product(request.source_id)
        url = self.build_request_url(request)
        requested_at = requested_at or _utc_now_iso()
        raw = self._get_bytes(url, timeout_seconds=timeout_seconds)
        return self._parse_response(
            raw,
            request=request,
            weather_dataset_id=weather_dataset_id,
            revision_id=revision_id,
            name=name,
            site_id=site_id,
            request_url=url,
            snapshot_store=snapshot_store,
            requested_at=requested_at,
            retrieved_at=retrieved_at or _utc_now_iso(),
            network_retrieval=True,
        )

    def parse_response(
        self,
        raw_response: bytes,
        *,
        request: WeatherAcquisitionRequest,
        weather_dataset_id: str,
        revision_id: str,
        name: str,
        site_id: str,
        request_url: str | None = None,
        snapshot_store: FileSystemWeatherSnapshotStore | None = None,
        requested_at: str | None = None,
        retrieved_at: str | None = None,
        synthetic: bool = False,
        evidence_detail: str | None = None,
    ) -> WeatherAcquisitionResult:
        """Parse supplied bytes without asserting provider transport or origin.

        For ordinary replay, legacy URL/time arguments are retained as unverified
        caller declarations in the manifest request, never as retrieval evidence.
        Callers injecting test data must explicitly set synthetic=True; retrieval
        URL/time arguments are discarded for synthetic data.
        """
        result = self._parse_response(
            raw_response,
            request=request,
            weather_dataset_id=weather_dataset_id,
            revision_id=revision_id,
            name=name,
            site_id=site_id,
            snapshot_store=snapshot_store,
            requested_at=requested_at,
            synthetic=synthetic,
            evidence_detail=evidence_detail,
        )
        if not synthetic and (request_url is not None or retrieved_at is not None):
            result.manifest["request"]["unverified_retrieval_declaration"] = {
                "source_url": request_url,
                "retrieved_at": retrieved_at,
            }
        return result

    def _parse_response(
        self,
        raw_response: bytes,
        *,
        request: WeatherAcquisitionRequest,
        weather_dataset_id: str,
        revision_id: str,
        name: str,
        site_id: str,
        request_url: str | None = None,
        snapshot_store: FileSystemWeatherSnapshotStore | None = None,
        requested_at: str | None = None,
        retrieved_at: str | None = None,
        network_retrieval: bool = False,
        synthetic: bool = False,
        evidence_detail: str | None = None,
    ) -> WeatherAcquisitionResult:
        source = self.source_product(request.source_id)
        local_start, local_end = _local_window(request)
        # Only acquire(), after successful transport, supplies retrieval evidence.
        effective_url = request_url if network_retrieval else None
        retrieved_at = retrieved_at if network_retrieval else None
        acquisition = {
            "method": "provider_transport" if network_retrieval else "supplied_payload",
            "network_retrieval": network_retrieval,
            "data_origin": (
                "provider_generated" if network_retrieval
                else "synthetic_test_fixture" if synthetic else "unknown"
            ),
            "evidence": (
                "provider_transport" if network_retrieval
                else "user_declared" if synthetic else "unknown"
            ),
            "evidence_detail": (
                "Response bytes returned by the selected Open-Meteo provider transport."
                if network_retrieval else evidence_detail or (
                    "Caller-declared synthetic provider-shaped test data emulating the "
                    "selected Open-Meteo/ERA5 product; not actual ERA5 observations. "
                    "No provider retrieval occurred."
                    if synthetic else
                    "Caller-supplied provider-shaped payload parsed without transport; "
                    "upstream data origin and prior provider retrieval are unverified."
                )
            ),
        }

        try:
            payload = json.loads(raw_response.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeatherAcquisitionError(
                "Open-Meteo response is not valid UTF-8 JSON",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_SCHEMA_INVALID",
            ) from exc
        if not isinstance(payload, dict):
            raise WeatherAcquisitionError(
                "Open-Meteo response root must be an object",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_SCHEMA_INVALID",
            )
        if payload.get("error") is True:
            raise WeatherAcquisitionError(
                f"Open-Meteo API error: {payload.get('reason', 'unknown reason')}",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_API_ERROR",
            )

        hourly = payload.get("hourly")
        units = payload.get("hourly_units")
        if not isinstance(hourly, dict) or not isinstance(units, dict):
            raise WeatherAcquisitionError(
                "Open-Meteo response requires hourly and hourly_units objects",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_SCHEMA_INVALID",
            )

        raw_times = hourly.get("time")
        if not isinstance(raw_times, list) or not raw_times:
            raise WeatherAcquisitionError(
                "Open-Meteo response contains no hourly time array",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_SCHEMA_INVALID",
            )
        if _normalize_unit_text(units.get("time")) not in {"unixtime", "s"}:
            raise WeatherAcquisitionError(
                f"Open-Meteo time unit must be unixtime, got {units.get('time')!r}",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_UNIT_UNSUPPORTED",
            )

        try:
            source_labels = pd.DatetimeIndex(
                pd.to_datetime(raw_times, unit="s", utc=True, errors="raise")
            )
        except Exception as exc:
            raise WeatherAcquisitionError(
                "Open-Meteo unix timestamps could not be parsed",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_SCHEMA_INVALID",
            ) from exc

        if len(source_labels) < 2:
            raise WeatherAcquisitionError(
                "Open-Meteo response must contain at least two hourly records",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_CADENCE_INVALID",
            )
        deltas = source_labels[1:] - source_labels[:-1]
        if any(delta != pd.Timedelta(hours=1) for delta in deltas):
            raise WeatherAcquisitionError(
                "Open-Meteo Phase 6.0B adapter requires a continuous 1-hour source cadence",
                provider_id=self.provider_id,
                source_id=request.source_id,
                finding_code="WX_PROVIDER_CADENCE_INVALID",
            )

        count = len(source_labels)
        _require_unit(units, "temperature_2m", {"degc", "c"})
        _require_unit(units, "dew_point_2m", {"degc", "c"})
        _require_unit(units, "relative_humidity_2m", {"%"})
        pressure_unit = _require_unit(units, "surface_pressure", {"hpa", "pa"})
        _require_unit(units, "wind_speed_10m", {"m/s", "ms-1", "m/s"})
        for name_ in (
            "shortwave_radiation",
            "direct_normal_irradiance",
            "diffuse_radiation",
        ):
            _require_unit(units, name_, {"w/m2"})

        frame = pd.DataFrame(
            {
                "ambient_temperature_c": _numeric_series(
                    hourly.get("temperature_2m"),
                    name="temperature_2m",
                    expected_length=count,
                ),
                "relative_humidity_fraction": _numeric_series(
                    hourly.get("relative_humidity_2m"),
                    name="relative_humidity_2m",
                    expected_length=count,
                )
                / 100.0,
                "dew_point_temperature_c": _numeric_series(
                    hourly.get("dew_point_2m"),
                    name="dew_point_2m",
                    expected_length=count,
                ),
                "pressure_pa": _numeric_series(
                    hourly.get("surface_pressure"),
                    name="surface_pressure",
                    expected_length=count,
                ),
                "wind_speed_m_s": _numeric_series(
                    hourly.get("wind_speed_10m"),
                    name="wind_speed_10m",
                    expected_length=count,
                ),
                "ghi_w_m2": _numeric_series(
                    hourly.get("shortwave_radiation"),
                    name="shortwave_radiation",
                    expected_length=count,
                ),
                "dni_w_m2": _numeric_series(
                    hourly.get("direct_normal_irradiance"),
                    name="direct_normal_irradiance",
                    expected_length=count,
                ),
                "dhi_w_m2": _numeric_series(
                    hourly.get("diffuse_radiation"),
                    name="diffuse_radiation",
                    expected_length=count,
                ),
            }
        )
        if pressure_unit == "hpa":
            frame["pressure_pa"] *= 100.0

        # Solar values are preceding-hour means at the provider label. Canonical
        # RawiBumi weather is interval-start indexed. State values remain the source
        # instantaneous values at the original end label; no interpolation is invented.
        canonical_index = (source_labels - pd.Timedelta(hours=1)).tz_convert(
            request.timezone
        )
        frame.index = canonical_index

        # Preserve only existing interval starts inside the local calendar window.
        rows_before = len(frame)
        dropped_start = int((frame.index < local_start).sum())
        dropped_end = int((frame.index >= local_end).sum())
        frame = frame.loc[
            (frame.index >= local_start) & (frame.index < local_end)
        ].copy()
        # UTC midnight can pass during transport. Record the parameters actually
        # sent, rather than recomputing today's padding clamp after the fetch.
        request_parameters = (
            dict(parse_qsl(urlsplit(effective_url).query, keep_blank_values=True))
            if effective_url else self.build_request_parameters(request)
        )

        variable_metadata = {
            "ghi_w_m2": {
                "source_variable": "shortwave_radiation",
                "source_temporal_semantics": "preceding_hour_mean",
            },
            "dni_w_m2": {
                "source_variable": "direct_normal_irradiance",
                "source_temporal_semantics": "preceding_hour_mean",
            },
            "dhi_w_m2": {
                "source_variable": "diffuse_radiation",
                "source_temporal_semantics": "preceding_hour_mean",
            },
            "ambient_temperature_c": {
                "source_variable": "temperature_2m",
                "source_temporal_semantics": "instant_at_source_label",
                "canonical_alignment": "assigned_to_preceding_hour_interval_without_interpolation",
            },
            "relative_humidity_fraction": {
                "source_variable": "relative_humidity_2m",
                "source_temporal_semantics": "instant_at_source_label",
                "canonical_alignment": "assigned_to_preceding_hour_interval_without_interpolation",
            },
            "dew_point_temperature_c": {
                "source_variable": "dew_point_2m",
                "source_temporal_semantics": "instant_at_source_label",
                "canonical_alignment": "assigned_to_preceding_hour_interval_without_interpolation",
            },
            "pressure_pa": {
                "source_variable": "surface_pressure",
                "source_temporal_semantics": "instant_at_source_label",
                "canonical_alignment": "assigned_to_preceding_hour_interval_without_interpolation",
            },
            "wind_speed_m_s": {
                "source_variable": "wind_speed_10m",
                "source_temporal_semantics": "instant_at_source_label",
                "canonical_alignment": "assigned_to_preceding_hour_interval_without_interpolation",
            },
        }

        transformations = [
            transformation(
                "timezone_normalization",
                algorithm="open_meteo_hour_label_to_canonical_interval_start",
                algorithm_version="0.1",
                parameters={
                    "source_timezone": "UTC",
                    "canonical_timezone": request.timezone,
                    "interval_shift_seconds": -3600,
                    "reason": "solar fields are preceding-hour means",
                    "state_interpolation_applied": False,
                },
            ),
            transformation(
                "unit_conversion",
                algorithm="open_meteo_units_to_rawibumi_canonical",
                algorithm_version="0.1",
                parameters={
                    "relative_humidity_percent_to_fraction": True,
                    "surface_pressure_to_pa": pressure_unit != "pa",
                    "wind_speed_requested_unit": "m/s",
                    "temperature_requested_unit": "celsius",
                },
            ),
        ]
        transformations.append(transformation(
            "timezone_normalization",
            algorithm="local_window_trim",
            algorithm_version="0.1",
            parameters={
                "local_start": local_start.isoformat(),
                "local_end_exclusive": local_end.isoformat(),
                "requested_start_date": request.start_date,
                "requested_end_date": request.end_date,
                "fetched_utc_dates": {
                    key: request_parameters[key] for key in ("start_date", "end_date")
                },
                "rows_before": rows_before,
                "rows_after": len(frame),
                "rows_dropped_start": dropped_start,
                "rows_dropped_end": dropped_end,
            },
        ))

        raw_digest = sha256(raw_response).hexdigest()
        snapshot_reference = None
        if snapshot_store is not None:
            snapshot_reference = snapshot_store.put(raw_response, suffix=".json")
            if snapshot_reference.sha256 != raw_digest:
                raise RuntimeError("snapshot store returned a different content hash")

        source_file = fingerprint_source_bytes(
            raw_response,
            file_id=f"{weather_dataset_id}:provider-response:0",
            filename=(
                f"open-meteo-{source.model_parameter}-"
                f"{request.start_date}-{request.end_date}.json"
            ),
            media_type="application/json",
            source_url=effective_url,
            attribution=source.attribution if network_retrieval else None,
            license_url=source.license_url if network_retrieval else None,
        )

        response_latitude = payload.get("latitude")
        response_longitude = payload.get("longitude")
        response_elevation = payload.get("elevation")
        provider_location = {
            "latitude_deg": (
                float(response_latitude) if response_latitude is not None else None
            ),
            "longitude_deg": (
                float(response_longitude) if response_longitude is not None else None
            ),
            "elevation_m": (
                float(response_elevation) if response_elevation is not None else None
            ),
            "grid_identifier": None,
            "notes": (
                "Provider-returned location preserved without treating it as project geometry."
                if network_retrieval else
                "Location declared in supplied payload; provider origin is unverified."
            ),
        }

        time_semantics = build_time_semantics(
            canonical_timezone=request.timezone,
            source_timestamp_convention=(
                "mixed_open_meteo_hourly_label:solar_preceding_hour_mean;"
                "state_instant_at_label"
            ),
            native_interval_seconds=3600,
            current_interval_seconds=3600,
            source_timezone="UTC",
            source_utc_offset_hours=0.0,
        )

        request_start_date = date.fromisoformat(request.start_date)
        request_end_date = date.fromisoformat(request.end_date)
        is_complete_single_year = (
            request_start_date.year == request_end_date.year
            and request_start_date.month == 1
            and request_start_date.day == 1
            and request_end_date.month == 12
            and request_end_date.day == 31
        )
        calendar_classification = (
            "actual_year"
            if is_complete_single_year
            else (
                "multi_year_time_series"
                if request_start_date.year != request_end_date.year
                else "partial_time_series"
            )
        )
        source_metadata = {
            "provider_id": self.provider_id,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "source_product_name": source.display_name,
            "provider_model_parameter": source.model_parameter,
            "requested_coordinate": {
                "latitude_deg": float(request.latitude_deg),
                "longitude_deg": float(request.longitude_deg),
                "elevation_m": (
                    float(request.elevation_m)
                    if request.elevation_m is not None
                    else None
                ),
            },
            "provider_location": provider_location,
            "cell_selection": request.cell_selection,
            "calendar_classification": calendar_classification,
            "raw_response_sha256": raw_digest,
            "request_url": effective_url,
            "source_method": {
                "projection_authority": "source_product",
                "rawibumi_resource_projection_applied": False,
                "opensimpv_resource_projection_applied": False,
                "method_id": source.method_id,
                "method_version": None,
                "evidence": "provider_documentation",
                "description": (
                    "RawiBumi preserves the selected ERA5/Open-Meteo resource product "
                    "and does not apply a cross-source meteorological projection method."
                ),
                "spatial_basis": source.spatial_basis,
                "temporal_basis": source.temporal_basis,
            },
        }

        upstream_generation = {
            "provider": source.display_name,
            "synthetic": None,
            "base_resolution_seconds": 3600,
            "method": source.method_id,
            "evidence": "source_metadata",
            "evidence_detail": (
                "Historical reanalysis acquired through an explicitly selected "
                "Open-Meteo model parameter; RawiBumi performs semantic mapping only."
            ),
        }
        if not network_retrieval:
            # Keep the transport dataset contract unchanged, including its hash.
            # Supplied bytes need explicit origin metadata and no retrieval claims.
            source_metadata["acquisition"] = acquisition
            upstream_generation = {
                "provider": None,
                "synthetic": True if synthetic else None,
                "base_resolution_seconds": 3600,
                "method": "synthetic_provider_shaped_test_fixture" if synthetic else None,
                "evidence": "user_declared" if synthetic else "unknown",
                "evidence_detail": acquisition["evidence_detail"],
            }
            source_metadata["source_method"]["description"] = (
                "Selected ERA5/Open-Meteo product semantics are emulated by synthetic "
                "test data; this is not evidence of ERA5 observations or retrieval."
                if synthetic else
                "Selected ERA5/Open-Meteo product semantics guide payload mapping; "
                "the supplied bytes' upstream generation is unverified."
            )

        weather = build_weather_dataset(
            frame,
            weather_dataset_id=weather_dataset_id,
            revision_id=revision_id,
            name=name,
            site_id=site_id,
            timezone=request.timezone,
            native_resolution_seconds=3600,
            source_id=request.source_id,
            source_format="open_meteo_historical_json_v0.1",
            source_timestamp_convention=(
                "mixed_open_meteo_hourly_label:solar_preceding_hour_mean;"
                "state_instant_at_label"
            ),
            source_files=[source_file],
            location={
                "latitude_deg": float(request.latitude_deg),
                "longitude_deg": float(request.longitude_deg),
                "elevation_m": (
                    float(request.elevation_m)
                    if request.elevation_m is not None
                    else None
                ),
            },
            variable_metadata=variable_metadata,
            transformations=transformations,
            calendar_type="gregorian",
            leap_year_handling="source_preserved",
            native_series_origin="provider_generated" if network_retrieval else "unknown",
            series_origin="provider_generated" if network_retrieval else "unknown",
            upstream_generation=upstream_generation,
            time_semantics=time_semantics,
            extra_metadata={"source_metadata": source_metadata},
            start_time=local_start,
            end_time=local_end,
        )
        weather, qc_report = attach_weather_qc(weather)
        weather_hash = fingerprint_canonical_weather(weather)

        status = {
            "passed": "qc_passed",
            "warning": "qc_warning",
            "failed": "failed",
        }.get(qc_report["status"], "normalized")

        manifest = {
            "schema_name": "WeatherSourceAcquisitionManifest",
            "schema_version": "0.1",
            "acquisition_id": (
                f"{weather_dataset_id}:{revision_id}:{raw_digest[:16]}"
            ),
            "provider_id": self.provider_id,
            "source_id": request.source_id,
            "source_product_name": source.display_name,
            "source_product_version": None,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "acquisition": acquisition,
            "requested_site": {
                "latitude_deg": float(request.latitude_deg),
                "longitude_deg": float(request.longitude_deg),
                "elevation_m": (
                    float(request.elevation_m)
                    if request.elevation_m is not None
                    else None
                ),
                "timezone": request.timezone,
            },
            "request": {
                "requested_at": requested_at,
                "start_time": local_start.isoformat(),
                "end_time": local_end.isoformat(),
                "endpoint_family": "historical_weather_archive",
                "parameters": request_parameters,
            },
            "provider_location": provider_location,
            "source_method": {
                "projection_authority": "source_product",
                "rawibumi_resource_projection_applied": False,
                "opensimpv_resource_projection_applied": False,
                "method_id": source.method_id,
                "method_version": None,
                "evidence": "provider_documentation",
                "description": (
                    "Selected source-product semantics are preserved. RawiBumi "
                    "performs no cross-source weather projection, blending, ranking, "
                    "bias correction, or fallback."
                ),
                "spatial_basis": source.spatial_basis,
                "temporal_basis": source.temporal_basis,
                "notes": (
                    "The term projection here refers to meteorological resource "
                    "generation, not cartographic coordinate projection."
                ),
            },
            "raw_response": {
                "sha256": raw_digest,
                "byte_size": len(raw_response),
                "media_type": "application/json",
                "storage_reference": (
                    snapshot_reference.storage_reference
                    if snapshot_reference is not None
                    else None
                ),
                "retrieved_at": retrieved_at,
                "source_url": effective_url,
                "attribution": source.attribution if network_retrieval else None,
                "license_url": source.license_url if network_retrieval else None,
            },
            "canonical_mapping": {
                "mapping_id": "open_meteo_historical_to_weather_dataset",
                "mapping_version": "0.1",
                "source_projection_preserved": True,
                "unit_conversion_applied": True,
                "timestamp_normalization_applied": True,
                "notes": (
                    "Solar preceding-hour labels are normalized to interval starts; "
                    "instantaneous state variables are not interpolated."
                ),
            },
            "result": {
                "weather_dataset_id": weather_dataset_id,
                "weather_dataset_revision_id": revision_id,
                "weather_dataset_sha256": weather_hash,
            },
            "status": status,
            "findings": qc_report.get("findings", []),
        }
        if not network_retrieval:
            manifest["source_method"]["description"] = source_metadata["source_method"][
                "description"
            ]

        return WeatherAcquisitionResult(
            weather=weather,
            manifest=manifest,
            raw_response=raw_response,
            qc_report=qc_report,
        )
