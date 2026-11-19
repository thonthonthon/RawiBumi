"""Persistence for canonical weather revisions used by the browser product shell."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import pandas as pd

from weather.core import CanonicalWeather
from .safe_paths import safe_component, contained, snapshot_hashes


class WeatherRevisionNotFoundError(KeyError):
    pass


class FileWeatherRevisionStore:
    """Persist canonical weather metadata and series separately from project JSON."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _directory(self, project_id: str, revision_id: str) -> Path:
        project = contained(self.root, self.root / safe_component(project_id, "project"))
        return contained(project, project / safe_component(revision_id, "weather"))

    def save(
        self,
        project_id: str,
        weather: CanonicalWeather,
        *,
        acquisition_manifest: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        revision_id = str(weather.dataset["revision_id"])
        snapshot_hashes(acquisition_manifest)
        directory = self._directory(project_id, revision_id)
        directory.mkdir(parents=True, exist_ok=True)

        metadata_path = contained(directory, directory / "weather-dataset.json")
        series_path = contained(directory, directory / "weather-series.parquet")
        manifest_path = contained(directory, directory / "acquisition-manifest.json")

        metadata_path.write_text(
            json.dumps(weather.dataset, sort_keys=True, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        serializable = weather.series.copy()
        serializable.insert(0, "interval_start", serializable.index)
        serializable.to_parquet(
            series_path,
            engine="pyarrow",
            compression="zstd",
            index=False,
        )
        if acquisition_manifest is not None:
            manifest_path.write_text(
                json.dumps(
                    acquisition_manifest,
                    sort_keys=True,
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

        return {
            "weather_dataset_id": weather.dataset["weather_dataset_id"],
            "revision_id": revision_id,
            "source_id": weather.dataset.get("source_id"),
            "name": weather.dataset.get("name"),
            "start_time": weather.dataset.get("start_time"),
            "end_time": weather.dataset.get("end_time"),
            "timezone": weather.dataset.get("timezone"),
            "data_quality_status": weather.dataset.get("data_quality_status"),
            "manifest": deepcopy(acquisition_manifest),
        }

    def load(self, project_id: str, revision_id: str) -> CanonicalWeather:
        directory = self._directory(project_id, revision_id)
        metadata_path = contained(directory, directory / "weather-dataset.json")
        series_path = contained(directory, directory / "weather-series.parquet")
        if not metadata_path.exists() or not series_path.exists():
            raise WeatherRevisionNotFoundError(revision_id)

        dataset = json.loads(metadata_path.read_text(encoding="utf-8"))
        safe_component(dataset["revision_id"], "weather")
        frame = pd.read_parquet(series_path)
        interval_start = pd.to_datetime(frame.pop("interval_start"), utc=True)
        timezone_name = str(dataset["timezone"])
        index = pd.DatetimeIndex(interval_start).tz_convert(timezone_name)
        frame.index = index
        frame.index.name = "interval_start"
        return CanonicalWeather(dataset, frame)

    def manifest(self, project_id: str, revision_id: str) -> dict[str, Any] | None:
        directory = self._directory(project_id, revision_id)
        path = contained(directory, directory / "acquisition-manifest.json")
        if not path.exists():
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        snapshot_hashes(value)
        return value
