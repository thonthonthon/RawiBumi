"""OpenSIMPV canonical weather foundation."""

from .importer import (
    DETECTABLE_UNSUPPORTED_WEATHER_FORMATS,
    SUPPORTED_WEATHER_FORMATS,
    detect_weather_format,
    read_weather_bytes,
)
from .core import (
    CANONICAL_VARIABLES,
    IRRADIANCE_VARIABLES,
    SERIES_ORIGINS,
    SOURCE_REFERENCE_KINDS,
    CanonicalWeather,
    build_time_semantics,
    build_weather_dataset,
    fingerprint_source_bytes,
    interval_energy_wh_m2,
    transformation,
    utc_offset_name,
)

__all__ = [
    "SUPPORTED_WEATHER_FORMATS",
    "DETECTABLE_UNSUPPORTED_WEATHER_FORMATS",
    "detect_weather_format",
    "read_weather_bytes",
    "CANONICAL_VARIABLES",
    "IRRADIANCE_VARIABLES",
    "SERIES_ORIGINS",
    "SOURCE_REFERENCE_KINDS",
    "CanonicalWeather",
    "build_time_semantics",
    "build_weather_dataset",
    "fingerprint_source_bytes",
    "interval_energy_wh_m2",
    "transformation",
    "utc_offset_name",
]


from .providers import (
    FileSystemWeatherSnapshotStore,
    OpenMeteoHistoricalAdapter,
    WeatherAcquisitionError,
    WeatherAcquisitionRequest,
    WeatherAcquisitionResult,
    fingerprint_canonical_weather,
)

__all__ += [
    "WeatherAcquisitionError",
    "WeatherAcquisitionRequest",
    "WeatherAcquisitionResult",
    "OpenMeteoHistoricalAdapter",
    "FileSystemWeatherSnapshotStore",
    "fingerprint_canonical_weather",
]
