"""Coordinate-driven weather provider adapters."""

from .base import (
    WeatherAcquisitionError,
    WeatherAcquisitionRequest,
    WeatherAcquisitionResult,
    WeatherProviderAdapter,
    fingerprint_canonical_weather,
)
from .open_meteo import (
    OPEN_METEO_ARCHIVE_URL,
    OPEN_METEO_SOURCE_PRODUCTS,
    OpenMeteoHistoricalAdapter,
    OpenMeteoSourceProduct,
)
from .snapshot_store import (
    FileSystemWeatherSnapshotStore,
    RawWeatherSnapshot,
)

__all__ = [
    "WeatherAcquisitionError",
    "WeatherAcquisitionRequest",
    "WeatherAcquisitionResult",
    "WeatherProviderAdapter",
    "fingerprint_canonical_weather",
    "OPEN_METEO_ARCHIVE_URL",
    "OPEN_METEO_SOURCE_PRODUCTS",
    "OpenMeteoHistoricalAdapter",
    "OpenMeteoSourceProduct",
    "FileSystemWeatherSnapshotStore",
    "RawWeatherSnapshot",
]
