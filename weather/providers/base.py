"""Provider-neutral weather acquisition contracts for RawiBumi Phase 6.0B."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import math
from typing import Any, Protocol

import pandas as pd

from weather.core import CanonicalWeather


class WeatherAcquisitionError(RuntimeError):
    """Explicit provider/source acquisition failure.

    RawiBumi never turns this error into an implicit request to another source.
    """

    def __init__(
        self,
        message: str,
        *,
        provider_id: str | None = None,
        source_id: str | None = None,
        finding_code: str = "WX_ACQUISITION_FAILED",
    ) -> None:
        super().__init__(message)
        self.provider_id = provider_id
        self.source_id = source_id
        self.finding_code = finding_code

    def finding(self) -> dict[str, Any]:
        return {
            "code": self.finding_code,
            "severity": "error",
            "provider_id": self.provider_id,
            "source_id": self.source_id,
            "message": str(self),
        }


@dataclass(frozen=True)
class WeatherAcquisitionRequest:
    """One explicit meteorological source-product request."""

    source_id: str
    latitude_deg: float
    longitude_deg: float
    timezone: str
    start_date: str
    end_date: str
    elevation_m: float | None = None
    cell_selection: str = "land"

    def __post_init__(self) -> None:
        if not self.source_id:
            raise ValueError("source_id is required")
        if not -90.0 <= float(self.latitude_deg) <= 90.0:
            raise ValueError("latitude_deg must be within [-90, 90]")
        if not -180.0 <= float(self.longitude_deg) <= 180.0:
            raise ValueError("longitude_deg must be within [-180, 180]")
        if not self.timezone:
            raise ValueError("timezone is required")
        try:
            start = date.fromisoformat(self.start_date)
            end = date.fromisoformat(self.end_date)
        except ValueError as exc:
            raise ValueError("start_date and end_date must be ISO yyyy-mm-dd") from exc
        if end < start:
            raise ValueError("end_date must be on or after start_date")
        if self.elevation_m is not None and not math.isfinite(float(self.elevation_m)):
            raise ValueError("elevation_m must be finite when provided")
        if self.cell_selection not in {"land", "sea", "nearest"}:
            raise ValueError("cell_selection must be land, sea, or nearest")


@dataclass
class WeatherAcquisitionResult:
    """Pinned result of one provider/source acquisition."""

    weather: CanonicalWeather
    manifest: dict[str, Any]
    raw_response: bytes
    qc_report: dict[str, Any]


class WeatherProviderAdapter(Protocol):
    """Transport/source adapter boundary.

    An adapter may expose several source products, but each request names exactly one
    source_id. Adapters must fail closed when a source is unknown or unavailable.
    """

    provider_id: str
    adapter_id: str
    adapter_version: str

    def supported_source_ids(self) -> tuple[str, ...]:
        ...

    def acquire(self, request: WeatherAcquisitionRequest, **kwargs: Any) -> WeatherAcquisitionResult:
        ...


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        return _json_safe(value.item())
    return value


def fingerprint_canonical_weather(weather: CanonicalWeather) -> str:
    """Return a deterministic SHA-256 for canonical metadata plus series.

    Column order is normalized for hashing so renderer/importer ordering does not
    affect identity. Values are represented as JSON scalars; missing/non-finite
    values become null.
    """
    payload = {
        "dataset": _json_safe(weather.dataset),
        "columns": sorted(str(column) for column in weather.series.columns),
        "rows": [],
    }
    columns = payload["columns"]
    for timestamp, row in weather.series.iterrows():
        payload["rows"].append(
            [
                pd.Timestamp(timestamp).isoformat(),
                *[_json_safe(row[column]) for column in columns],
            ]
        )
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
