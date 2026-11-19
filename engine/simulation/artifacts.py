"""Canonical Phase-3.8E result packaging and deterministic hashing."""

from __future__ import annotations

from collections import OrderedDict
from hashlib import sha256
import json
import struct
from math import isclose, isfinite, isnan, isinf
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine.simulation.unshaded import UnshadedFixedTiltSimulationResult


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize JSON-compatible data deterministically for stable hashing."""
    if _has_electrical_store(value):
        return "".join(json.JSONEncoder(sort_keys=True, separators=(",", ":"),
            ensure_ascii=False, allow_nan=False).iterencode(value)).encode("utf-8")
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_object_sha256(value: Any) -> str:
    if _has_electrical_store(value):
        digest = sha256()
        for part in json.JSONEncoder(sort_keys=True, separators=(",", ":"),
                ensure_ascii=False, allow_nan=False).iterencode(value):
            digest.update(part.encode("utf-8"))
        return digest.hexdigest()
    return sha256(canonical_json_bytes(value)).hexdigest()



class ElectricalIntervalStore(list):
    """Read-isolated, hash-checked JSON chunks; never caches decoded history.

    The list protocol preserves the existing JSON/schema replay contract. Storage
    policy is outside the logical scientific payload. Writers must seal before
    reading; a missing seal is never a valid execution result.
    """
    VERSION = "detailed-electrical-interval-store.v1"

    def __init__(self, chunk_size=1):
        from tempfile import TemporaryDirectory
        if isinstance(chunk_size, bool) or not isinstance(chunk_size, int) or chunk_size < 1:
            raise ValueError("electrical_chunk_size must be a positive integer")
        super().__init__()
        self._owner = TemporaryDirectory(prefix="rawibumi-electrical-")
        self.directory = Path(self._owner.name)
        self.chunk_size = chunk_size
        self.entries = []
        self.pending = []
        self.count = 0
        self.sealed = False
        self.closed = False
        self.failed = False
        self.previous_end = None
        self.peak_buffered_records = 0
        self.persistence_seconds = 0.0

    def append(self, value):
        if self.closed or self.failed or self.sealed:
            raise ValueError("electrical interval store is closed, failed, or immutable")
        if isinstance(value, dict) and "interval_end" in value and "interval_start" in value:
            start, end = pd.Timestamp(value["interval_start"]), pd.Timestamp(value["interval_end"])
            if not start < end or (self.previous_end is not None and start != self.previous_end):
                raise ValueError("electrical interval order/coverage mismatch")
            self.previous_end = end
        self.pending.append(value)
        self.count += 1
        self.peak_buffered_records = max(self.peak_buffered_records, len(self.pending))
        if len(self.pending) == self.chunk_size:
            self._flush()

    def _flush(self):
        from time import perf_counter
        if not self.pending:
            return
        started = perf_counter()
        ordinal = len(self.entries)
        name = f"chunk-{ordinal:08d}.json"
        raw = canonical_json_bytes(self.pending)
        path = self.directory / name
        # A failed write leaves no index entry and cannot produce a sealed store.
        try:
            with path.open("xb") as stream:
                stream.write(raw)
        except OSError:
            self.failed = True
            raise
        self.entries.append({"ordinal": ordinal, "path": name,
            "first_index": self.count - len(self.pending), "count": len(self.pending),
            "sha256": sha256(raw).hexdigest(), "byte_size": len(raw)})
        self.pending.clear()
        self.persistence_seconds += perf_counter() - started

    def seal(self):
        if self.closed or self.failed:
            raise ValueError("electrical interval store is closed or failed")
        if not self.sealed:
            self._flush()
            self.sealed = True
            self._check_index()
        return self

    def close(self):
        """Release owned temporary files; package-backed readers never delete files."""
        if not self.closed:
            self.pending.clear()
            if self._owner is not None:
                self._owner.cleanup()
            self.closed = True

    def reference(self):
        from copy import deepcopy
        self._check_index()
        return {"storage_contract": self.VERSION, "interval_count": self.count,
                "chunk_size": self.chunk_size, "chunks": deepcopy(self.entries)}

    @classmethod
    def open(cls, directory, reference):
        if reference.get("storage_contract") != cls.VERSION:
            raise ValueError("unsupported electrical interval storage contract")
        result = cls.__new__(cls)
        list.__init__(result)
        result._owner = None
        result.directory = Path(directory)
        result.chunk_size = reference["chunk_size"]
        if isinstance(result.chunk_size, bool) or not isinstance(result.chunk_size, int) or result.chunk_size < 1:
            raise ValueError("invalid electrical chunk size")
        result.entries = reference["chunks"]
        result.count = reference["interval_count"]
        result.pending = []
        result.sealed = True
        result.closed = False
        result.failed = False
        result.previous_end = None
        result.peak_buffered_records = 0
        result.persistence_seconds = 0.0
        result._check_index()
        return result

    def _check_index(self):
        if self.closed or self.failed or not self.sealed:
            raise ValueError("electrical interval store is incomplete or closed")
        if isinstance(self.count, bool) or not isinstance(self.count, int) or self.count < 0 or not isinstance(self.entries, list):
            raise ValueError("invalid electrical chunk count/index")
        count = 0
        for ordinal, entry in enumerate(self.entries):
            required = {"ordinal", "first_index", "count", "path", "sha256", "byte_size"}
            if (not isinstance(entry, dict) or not required <= entry.keys()
                or any(isinstance(entry[k], bool) or not isinstance(entry[k], int)
                       for k in ("ordinal", "first_index", "count", "byte_size"))
                or entry["byte_size"] < 1
                or not isinstance(entry["sha256"], str) or len(entry["sha256"]) != 64
                or any(c not in "0123456789abcdef" for c in entry["sha256"])):
                raise ValueError("invalid electrical chunk metadata")
            if (entry["ordinal"] != ordinal or entry["first_index"] != count
                or entry["path"] != f"chunk-{ordinal:08d}.json"
                or isinstance(entry["count"], bool) or not isinstance(entry["count"], int)
                or not 0 < entry["count"] <= self.chunk_size):
                raise ValueError("electrical chunk order/coverage mismatch")
            count += entry["count"]
        if count != self.count:
            raise ValueError("electrical chunk coverage is incomplete")
        if not self.directory.is_dir() or {p.name for p in self.directory.iterdir()} != {e["path"] for e in self.entries}:
            raise ValueError("electrical chunk files/coverage mismatch")

    def _read_chunk(self, entry):
        try:
            raw = (self.directory / entry["path"]).read_bytes()
        except OSError as exc:
            raise ValueError("electrical chunk is missing/unreadable") from exc
        if len(raw) != entry["byte_size"] or sha256(raw).hexdigest() != entry["sha256"]:
            raise ValueError("electrical chunk hash mismatch")
        records = json.loads(raw)
        if not isinstance(records, list) or len(records) != entry["count"]:
            raise ValueError("electrical chunk record count mismatch")
        return records

    def __iter__(self):
        self._check_index()
        previous_end = None
        for entry in self.entries:
            records = self._read_chunk(entry)
            for record in records:
                if isinstance(record, dict) and "interval_end" in record and "interval_start" in record:
                    start, end = pd.Timestamp(record["interval_start"]), pd.Timestamp(record["interval_end"])
                    if not start < end or (previous_end is not None and start != previous_end):
                        raise ValueError("electrical interval order/coverage mismatch")
                    previous_end = end
                yield record
            del records

    def __len__(self):
        return self.count

    def __bool__(self):
        return bool(self.count)

    def __getitem__(self, index):
        from bisect import bisect_right
        from operator import index as integer_index
        if self.closed or self.failed or not self.sealed:
            raise ValueError("electrical interval store is incomplete or closed")
        if isinstance(index, slice):
            return [self[i] for i in range(*index.indices(self.count))]
        index = integer_index(index)
        if index < 0:
            index += self.count
        if not 0 <= index < self.count:
            raise IndexError(index)
        # Schema validation indexes arrays; resolve directly rather than replaying
        # every earlier record. Sealed/opened indexes are checked at the boundary.
        ordinal = bisect_right(self.entries, index, key=lambda e: e["first_index"]) - 1
        entry = self.entries[ordinal]
        return self._read_chunk(entry)[index - entry["first_index"]]

    def __eq__(self, other):
        if not isinstance(other, list) or len(self) != len(other):
            return False
        return all(a == b for a, b in zip(self, other))

    def __ne__(self, other):
        return not self == other


class StoredElectricalPayload:
    """Small immutable header plus a sealed interval store."""
    def __init__(self, payload, field="intervals"):
        self.field = field
        self.intervals = payload[field]
        self.header = canonical_json_bytes({k: v for k, v in payload.items() if k != field})

    def replay(self):
        return {**json.loads(self.header), self.field: self.intervals}

    def bytes(self):
        # Explicit compatibility/export boundary; internal execution streams.
        return "".join(json.JSONEncoder(sort_keys=True, separators=(",", ":"),
            allow_nan=False).iterencode(self.replay())).encode()


    def __eq__(self, other):
        if isinstance(other, StoredElectricalPayload):
            return self.field == other.field and self.header == other.header and self.intervals == other.intervals
        if isinstance(other, bytes):
            return self.replay() == json.loads(other)
        return NotImplemented


def electrical_payload(value):
    return value.replay() if isinstance(value, StoredElectricalPayload) else json.loads(value)


def freeze_electrical_payload(payload, field="intervals"):
    if isinstance(payload.get(field), ElectricalIntervalStore):
        payload[field].seal()
        return StoredElectricalPayload(payload, field)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def electrical_payload_bytes(value):
    return value.bytes() if isinstance(value, StoredElectricalPayload) else value


def _has_electrical_store(value):
    if isinstance(value, ElectricalIntervalStore):
        return True
    if isinstance(value, dict):
        return any(_has_electrical_store(v) for v in value.values())
    return False


def persist_electrical_interval_result(run_directory, result):
    """Persist physical verification evidence even when diagnostics are off."""
    import shutil
    stored = result._canonical_payload
    if not isinstance(stored, StoredElectricalPayload):
        return
    destination = run_directory / "detailed-electrical-intervals"
    destination.mkdir(exist_ok=False)
    for entry in stored.intervals.entries:
        shutil.copyfile(stored.intervals.directory / entry["path"], destination / entry["path"])
    # Index is written only after all chunks. The package manifest is still last.
    index = {"storage_contract": ElectricalIntervalStore.VERSION,
        "physical_header": json.loads(stored.header),
        "numerical_result_sha256": result.numerical_result_sha256,
        "intervals": stored.intervals.reference()}
    index["index_payload_sha256"] = canonical_object_sha256(index)
    persist_json_artifact(run_directory / "detailed-electrical-interval-index.json", index)


def load_electrical_interval_result(run_directory):
    from .detailed_backend import DetailedMPPTBackendResult
    path = run_directory / "detailed-electrical-interval-index.json"
    index = json.loads(path.read_text())
    body = dict(index)
    digest = body.pop("index_payload_sha256", None)
    if digest != canonical_object_sha256(body) or index.get("storage_contract") != ElectricalIntervalStore.VERSION:
        raise ValueError("electrical interval index identity mismatch")
    intervals = ElectricalIntervalStore.open(run_directory / "detailed-electrical-intervals", index["intervals"])
    result = DetailedMPPTBackendResult.freeze({**index["physical_header"], "intervals": intervals})
    if result.numerical_result_sha256 != index["numerical_result_sha256"]:
        raise ValueError("electrical interval source hash mismatch")
    return result



def persist_attribution_diagnostic_store(run_directory, attribution):
    import shutil
    rows = attribution.diagnostic_rows()
    if not isinstance(rows, ElectricalIntervalStore):
        return
    destination = run_directory / "detailed-attribution-diagnostic-chunks"
    destination.mkdir(exist_ok=False)
    for entry in rows.entries:
        shutil.copyfile(rows.directory / entry["path"], destination / entry["path"])
    index = {"attribution_result_sha256": attribution.attribution_result_sha256,
             "rows": rows.reference()}
    index["index_payload_sha256"] = canonical_object_sha256(index)
    persist_json_artifact(run_directory / "detailed-attribution-diagnostic-index.json", index)


def load_attribution_diagnostic_store(run_directory, attribution):
    index = json.loads((run_directory / "detailed-attribution-diagnostic-index.json").read_text())
    body = dict(index)
    digest = body.pop("index_payload_sha256", None)
    if digest != canonical_object_sha256(body) or index["attribution_result_sha256"] != attribution.attribution_result_sha256:
        raise ValueError("attribution diagnostic interval index source mismatch")
    rows = ElectricalIntervalStore.open(run_directory / "detailed-attribution-diagnostic-chunks", index["rows"])
    return {"attribution_result_sha256": attribution.attribution_result_sha256, "curves": rows}


def _persisted_json_sha256(value):
    digest = sha256()
    for part in json.JSONEncoder(indent=2, sort_keys=True, ensure_ascii=False,
                                 allow_nan=False).iterencode(value):
        digest.update(part.encode("utf-8"))
    digest.update(b"\n")
    return digest.hexdigest()

def _logical_scalar(value: Any) -> str:
    if type(value) is str:
        return value
    if value is None or value is pd.NA:
        return "null"
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.datetime64):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (bool, np.bool_)):
        return "true" if bool(value) else "false"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if isnan(number):
            return "nan"
        if isinf(number):
            return "+inf" if number > 0 else "-inf"
        return format(number, ".17g")
    return str(value)


class _LogicalTokenCache:
    """Bounded exact tokens; unknown/temporal values keep canonical fallback.

    Keys distinguish binary64 bits (including signed zero and NaN payloads)
    after the same conversion as _logical_scalar. FIFO eviction affects cost,
    never the byte stream. Exact strings need no conversion or retained cache.
    """
    def __init__(self, *, max_entries=4096, max_bytes=1024*1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.retained_bytes = 0
        self._entries = OrderedDict()

    def token(self, value):
        kind = type(value)
        if kind is str:
            return value
        if kind is float or isinstance(value, np.floating):
            value = float(value)
            key = ('float', struct.pack('>d', value))
            key_bytes = 9
        elif kind is int or isinstance(value, np.integer):
            value = int(value)
            key_bytes = (value.bit_length()+7)//8 + 2
            if key_bytes > self.max_bytes:
                return _logical_scalar(value)
            key = ('int', value)
        else:
            return _logical_scalar(value)
        cached = self._entries.get(key)
        if cached is not None:
            return cached[0]
        token = _logical_scalar(value)
        size = key_bytes + len(token.encode('utf-8'))
        if size > self.max_bytes or self.max_entries < 1:
            return token
        while self._entries and (len(self._entries) >= self.max_entries or self.retained_bytes+size > self.max_bytes):
            _, (_, old_size) = self._entries.popitem(last=False)
            self.retained_bytes -= old_size
        self._entries[key] = (token, size)
        self.retained_bytes += size
        return token


def dataframe_logical_sha256(frame: pd.DataFrame) -> str:
    """Hash a DataFrame's logical content independently of Parquet encoding bytes."""
    digest = sha256()
    _update_dataframe_logical_digest(digest, frame, include_header=True)
    return digest.hexdigest()


def _update_dataframe_logical_digest(
    digest: Any,
    frame: pd.DataFrame,
    *,
    include_header: bool,
    _token_cache: _LogicalTokenCache | None = None,
) -> None:
    token = (_token_cache if _token_cache is not None else _LogicalTokenCache()).token
    if include_header:
        digest.update(b"opensimpv.dataframe.logical.v0.1\n")
        digest.update(
            ("|".join(str(column) for column in frame.columns) + "\n").encode()
        )
    for row in frame.itertuples(index=False, name=None):
        digest.update(
            ("\x1f".join(token(value) for value in row) + "\n").encode(
                "utf-8"
            )
        )


def weather_series_logical_sha256(series: pd.DataFrame) -> str:
    normalized = series.copy()
    normalized.insert(0, "interval_start", series.index)
    return dataframe_logical_sha256(normalized.reset_index(drop=True))


def build_standard_timeseries(
    result: UnshadedFixedTiltSimulationResult,
) -> pd.DataFrame:
    """Project the detailed engine frame into the canonical standard result surface."""
    source = result.timeseries
    columns: dict[str, Any] = {
        "timestamp": source.index,
        "interval_seconds": pd.to_numeric(
            source["duration_seconds"], errors="raise"
        ).astype(float).to_numpy(),
    }

    passthrough = (
        "solar_zenith_deg",
        "solar_azimuth_deg",
        "ghi_w_m2",
        "dni_w_m2",
        "dhi_w_m2",
        "ambient_temperature_c",
        "wind_speed_m_s",
        "poa_beam_w_m2",
        "poa_beam_unshaded_w_m2",
        "beam_visibility_factor_group",
        "poa_beam_shaded_w_m2",
        "near_shading_beam_loss_w_m2",
        "poa_sky_diffuse_unshaded_w_m2",
        "sky_visibility_factor_group",
        "circumsolar_visibility_factor_group",
        "horizon_visibility_factor_group",
        "poa_isotropic_unshaded_w_m2",
        "poa_isotropic_shaded_w_m2",
        "near_shading_isotropic_loss_w_m2",
        "poa_circumsolar_unshaded_w_m2",
        "poa_circumsolar_shaded_w_m2",
        "near_shading_circumsolar_loss_w_m2",
        "poa_horizon_unshaded_w_m2",
        "poa_horizon_shaded_w_m2",
        "near_shading_horizon_delta_w_m2",
        "poa_sky_diffuse_shaded_w_m2",
        "near_shading_sky_diffuse_loss_w_m2",
        "poa_sky_diffuse_w_m2",
        "poa_ground_diffuse_unshaded_w_m2",
        "ground_visibility_factor_group",
        "poa_ground_diffuse_shaded_w_m2",
        "near_shading_ground_diffuse_loss_w_m2",
        "poa_ground_diffuse_w_m2",
        "poa_global_unshaded_w_m2",
        "poa_global_w_m2",
        "iam_beam",
        "iam_sky",
        "iam_horizon",
        "iam_ground",
        "effective_irradiance_w_m2",
        "module_temperature_c",
        "cell_temperature_c",
        "orientation_mismatch_loss_w",
        "after_orientation_mismatch_w",
        "module_quality_loss_w",
        "module_mismatch_loss_w",
        "string_mismatch_loss_w",
        "dc_wiring_loss_w",
        "inverter_conversion_loss_w",
        "inverter_clipping_loss_w",
        "inverter_self_consumption_w",
        "pcc_power_w",
    )
    for column in passthrough:
        if column in source:
            columns[column] = source[column].to_numpy()

    if "lid_loss_w" in source:
        for column in source:
            if column in {"post_iam_pre_soiling_w_m2", "soiling_loss_w_m2", "soiling_fraction"} or column.endswith("_w") and not column.endswith("residual_w"):
                if column not in columns:
                    columns[column] = source[column].to_numpy()

    aliases = {
        "gross_dc_power_w": "raw_array_mpp_w",
        "net_dc_power_w": "array_virtual_mpp_w",
        "inverter_input_power_w": "dc_to_converter_w",
        "conversion_loss_w": "inverter_conversion_loss_w",
        "clipping_loss_w": "inverter_clipping_loss_w",
        "inverter_output_power_w": "ac_net_output_w",
    }
    for target, source_column in aliases.items():
        if source_column in source:
            columns[target] = source[source_column].to_numpy()

    if {
        "module_mismatch_loss_w",
        "string_mismatch_loss_w",
    }.issubset(source.columns):
        columns["mismatch_loss_w"] = (
            source["module_mismatch_loss_w"].to_numpy(dtype=float)
            + source["string_mismatch_loss_w"].to_numpy(dtype=float)
        )

    interval_energy = result.energy.interval
    if "pcc_power_wh" in interval_energy:
        columns["interval_energy_wh"] = interval_energy[
            "pcc_power_wh"
        ].to_numpy(dtype=float)

    output = pd.DataFrame(columns, index=source.index.copy())
    output.index.name = "interval_start"

    if output["timestamp"].isna().any():
        raise RuntimeError("standard result contains missing timestamps")
    numeric = output.drop(columns=["timestamp"])
    for column in numeric.columns:
        values = pd.to_numeric(numeric[column], errors="coerce")
        if values.isna().any() or not np.isfinite(values.to_numpy(dtype=float)).all():
            raise RuntimeError(
                f"standard result column {column!r} contains non-finite values"
            )
    return output


_LOSS_STAGE = {
    "orientation_mismatch": "array_dc",
    "soiling": "optical",
    "module_operating_effects": "module_dc",
    "lid": "module_dc",
    "degradation": "array_dc",
    "ac_wiring": "pcc",
    "plant_ac_wiring": "pcc",
    "transformer_iron": "pcc",
    "transformer_copper": "pcc",
    "unavailability": "pcc",
    "module_quality": "module_dc",
    "module_mismatch": "array_dc",
    "string_mismatch": "array_dc",
    "dc_wiring": "array_dc",
    "mppt_current_limit": "mppt_dc",
    "mppt_voltage_threshold": "mppt_dc",
    "inverter_power_threshold": "inverter_conversion",
    "inverter_conversion": "inverter_conversion",
    "inverter_clipping": "inverter_conversion",
    "inverter_self_consumption": "pcc",
}


def build_summary_result(
    result: UnshadedFixedTiltSimulationResult,
    *,
    simulation_run_id: str,
    data_quality_summary: dict[str, Any],
) -> dict[str, Any]:
    total_energy_wh = float(result.energy.annual["pcc_power_kwh"]) * 1000.0
    installed_dc_kwp = float(result.metadata["installed_dc_kwp"])
    installed_dc_w = installed_dc_kwp * 1000.0
    duration_h = float(
        result.timeseries["duration_seconds"].sum()
    ) / 3600.0
    period_start = pd.Timestamp(result.timeseries.index[0])
    final_duration_s = float(result.timeseries.iloc[-1]["duration_seconds"])
    period_end = pd.Timestamp(result.timeseries.index[-1]) + pd.Timedelta(
        seconds=final_duration_s
    )
    is_complete_year = isclose(duration_h, 8760.0, abs_tol=1e-9) or isclose(
        duration_h,
        8784.0,
        abs_tol=1e-9,
    )
    annual_energy_wh = total_energy_wh if is_complete_year else None

    monthly_energy = [
        {
            "month": str(month),
            "energy_wh": float(row["pcc_power_kwh"]) * 1000.0,
        }
        for month, row in result.energy.monthly.iterrows()
    ]

    loss_summary: list[dict[str, Any]] = []
    method = str(result.electrical.ledger.metadata["model_id"])
    for _, row in result.electrical.ledger.summary.iterrows():
        reference_wh = float(row["upstream_energy_kwh"]) * 1000.0
        loss_wh = float(row["loss_energy_kwh"]) * 1000.0
        loss_fraction = loss_wh / reference_wh if reference_wh != 0.0 else 0.0
        channel = str(row["channel"])
        loss_summary.append(
            {
                "loss_type": channel,
                "stage": _LOSS_STAGE[channel],
                "reference_energy_wh": reference_wh,
                "lost_energy_wh": loss_wh,
                "loss_fraction": loss_fraction,
                "method": method,
                "notes": "positive loss; negative value represents gain",
            }
        )

    capacity_factor = (
        total_energy_wh / (installed_dc_w * duration_h)
        if installed_dc_w > 0 and duration_h > 0
        else 0.0
    )

    return {
        "schema_name": "SummaryResult",
        "schema_version": "0.1",
        "simulation_run_id": simulation_run_id,
        "period_start_time": period_start.isoformat(),
        "period_end_time": period_end.isoformat(),
        "period_duration_hours": duration_h,
        "total_energy_wh": total_energy_wh,
        "annual_energy_wh": annual_energy_wh,
        # kWh/kWp and Wh/Wp are numerically identical.
        "specific_yield_wh_per_wp": float(
            result.kpis["specific_yield_kwh_per_kwp"]
        ),
        "performance_ratio": float(result.kpis["performance_ratio"]),
        "capacity_factor": float(capacity_factor),
        "capacity_factor_basis": "installed_dc_nameplate_over_executed_period",
        "monthly_energy": monthly_energy,
        "loss_summary": loss_summary,
        "peak_dc_power_w": float(
            result.timeseries["array_virtual_mpp_w"].max()
        ),
        "peak_ac_power_w": float(result.timeseries["pcc_power_w"].max()),
        "clipping_energy_wh": float(
            result.energy.annual["inverter_clipping_loss_kwh"]
        )
        * 1000.0,
        "shading_energy_loss_wh": (
            float(
                result.metadata["shading_energy_counterfactual"][
                    "shading_energy_loss_wh"
                ]
            )
            if result.metadata.get("shading_energy_counterfactual") is not None
            else (
                0.0
                if result.metadata.get("electrical_shading_loss_quantified") is True
                else None
            )
        ),
        "shading_energy_loss_basis": (
            dict(result.metadata["shading_energy_counterfactual"])
            if result.metadata.get("shading_energy_counterfactual") is not None
            else None
        ),
        "data_quality_summary": data_quality_summary,
        **({"resolved_loss_settings": result.electrical.ledger.metadata["resolved_loss_settings"]}
           if "resolved_loss_settings" in result.electrical.ledger.metadata else {}),
    }


def persist_parquet_result(
    frame: pd.DataFrame,
    *,
    output_directory: Path,
    simulation_run_id: str,
    filename: str = "timeseries.parquet",
) -> dict[str, Any]:
    """Persist the standard time series as Parquet and return a content-addressed ref."""
    try:
        import pyarrow  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency failure is explicit
        raise RuntimeError(
            "Phase 3.8E Parquet persistence requires the pyarrow dependency"
        ) from exc

    run_directory = output_directory / simulation_run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    if Path(filename).name != filename or not filename.endswith(".parquet"):
        raise ValueError("result filename must be a Parquet basename")
    path = run_directory / filename
    if path.exists():
        raise FileExistsError(
            "timeseries output already exists for immutable run package"
        )

    serializable = frame.reset_index(drop=True)
    serializable.to_parquet(
        path,
        engine="pyarrow",
        index=False,
        compression="zstd",
    )
    raw = path.read_bytes()

    return {
        "schema_name": "ResultDatasetReference",
        "schema_version": "0.1",
        "format": "parquet",
        "uri": path.resolve().as_uri(),
        "media_type": "application/vnd.apache.parquet",
        "byte_size": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "logical_content_sha256": dataframe_logical_sha256(serializable),
        "row_count": len(serializable),
        "column_count": len(serializable.columns),
        "columns": list(serializable.columns),
        "timestamp_convention": "interval_start",
        "parquet_engine": "pyarrow",
        "parquet_engine_version": pyarrow.__version__,
    }


RECEIVER_FACTOR_REQUIRED_COLUMNS = {
    "interval_start",
    "evaluation_time",
    "receiver_id",
    "receiver_area_m2",
    "beam_visibility_factor",
    "quality_flags_json",
    "shading_result_id",
}

RECEIVER_FACTOR_EXECUTION_IDENTITY_COLUMNS = {
    "shading_result_id",
    "sky_shading_result_id",
    "ground_shading_result_id",
}


def receiver_factor_physical_sha256(frame: pd.DataFrame) -> str:
    """Hash receiver-factor physics while excluding execution/config-derived IDs."""
    physical_columns = [
        column
        for column in frame.columns
        if column not in RECEIVER_FACTOR_EXECUTION_IDENTITY_COLUMNS
    ]
    return dataframe_logical_sha256(frame[physical_columns])


class ReceiverFactorParquetSink:
    """Deterministic bounded-memory writer for long-form receiver factors."""

    def __init__(
        self,
        *,
        output_directory: Path,
        simulation_run_id: str,
    ) -> None:
        self.output_directory = Path(output_directory)
        self.simulation_run_id = str(simulation_run_id)
        if not self.simulation_run_id:
            raise ValueError("simulation_run_id must not be empty")
        self._temp_directory = self.output_directory / ".rawibumi-tmp"
        self._temp_directory.mkdir(parents=True, exist_ok=True)
        self._temp_path = (
            self._temp_directory
            / f"{self.simulation_run_id}.shading-receiver-factors.parquet.tmp"
        )
        self._final_path = (
            self.output_directory
            / self.simulation_run_id
            / "shading-receiver-factors.parquet"
        )
        if self._temp_path.exists():
            self._temp_path.unlink()
        self._writer = None
        self._schema = None
        self._columns: list[str] | None = None
        self._logical_digest = sha256()
        self._token_cache = _LogicalTokenCache()
        self._logical_header_written = False
        self._physical_digest = sha256()
        self._physical_header_written = False
        self._row_count = 0
        self._max_chunk_rows = 0
        self._chunk_count = 0
        self._pyarrow_version: str | None = None
        self._closed = False

    @property
    def row_count(self) -> int:
        return self._row_count

    @property
    def max_chunk_rows(self) -> int:
        return self._max_chunk_rows

    @property
    def chunk_count(self) -> int:
        return self._chunk_count

    def write(self, frame: pd.DataFrame) -> None:
        if self._closed:
            raise RuntimeError("receiver-factor sink is already closed")
        if frame.empty:
            return

        missing = sorted(RECEIVER_FACTOR_REQUIRED_COLUMNS - set(frame.columns))
        if missing:
            raise ValueError(
                "receiver-factor chunk is missing required columns: "
                + ", ".join(missing)
            )

        serializable = frame.copy()
        serializable = serializable.sort_values(
            ["interval_start", "receiver_id"],
            kind="stable",
        ).reset_index(drop=True)

        columns = [str(column) for column in serializable.columns]
        if self._columns is None:
            self._columns = columns
        elif columns != self._columns:
            raise ValueError(
                "receiver-factor chunk columns changed during streaming"
            )

        try:
            import pyarrow  # type: ignore
            import pyarrow as pa  # type: ignore
            import pyarrow.parquet as pq  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Phase 5.8H streaming receiver-factor persistence requires pyarrow"
            ) from exc

        table = pa.Table.from_pandas(serializable, preserve_index=False)
        if self._writer is None:
            self._schema = table.schema
            self._writer = pq.ParquetWriter(
                self._temp_path,
                self._schema,
                compression="zstd",
            )
            self._pyarrow_version = pyarrow.__version__
        elif not table.schema.equals(self._schema):
            raise ValueError(
                "receiver-factor chunk Arrow schema changed during streaming"
            )

        self._update_digests(serializable)
        self._writer.write_table(table)
        self._row_count += len(serializable)
        self._max_chunk_rows = max(self._max_chunk_rows, len(serializable))
        self._chunk_count += 1

    def _update_digests(self, serializable: pd.DataFrame) -> None:
        _update_dataframe_logical_digest(
            self._logical_digest,
            serializable,
            include_header=not self._logical_header_written,
            _token_cache=self._token_cache,
        )
        self._logical_header_written = True
        physical_columns = [
            column
            for column in serializable.columns
            if column not in RECEIVER_FACTOR_EXECUTION_IDENTITY_COLUMNS
        ]
        _update_dataframe_logical_digest(
            self._physical_digest,
            serializable[physical_columns],
            include_header=not self._physical_header_written,
            _token_cache=self._token_cache,
        )
        self._physical_header_written = True

    def _finish_file(self) -> Path:
        if self._closed:
            raise RuntimeError("receiver-factor sink is already closed")
        if self._writer is None or self._row_count < 1 or self._columns is None:
            self.abort()
            raise RuntimeError("receiver-factor sink has no rows to finalize")

        self._writer.close()
        self._writer = None
        self._final_path.parent.mkdir(parents=True, exist_ok=True)
        if self._final_path.exists():
            self._temp_path.unlink(missing_ok=True)
            self._closed = True
            raise FileExistsError(
                "receiver-factor output already exists for immutable run package"
            )
        self._temp_path.replace(self._final_path)
        self._closed = True

        return self._final_path

    def finalize(self) -> dict[str, Any]:
        self._finish_file()

        file_digest = sha256()
        byte_size = 0
        with self._final_path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                byte_size += len(block)
                file_digest.update(block)

        return {
            "schema_name": "ResultDatasetReference",
            "schema_version": "0.1",
            "format": "parquet",
            "uri": self._final_path.resolve().as_uri(),
            "media_type": "application/vnd.apache.parquet",
            "byte_size": byte_size,
            "sha256": file_digest.hexdigest(),
            "logical_content_sha256": self._logical_digest.hexdigest(),
            "physical_content_sha256": self._physical_digest.hexdigest(),
            "row_count": self._row_count,
            "column_count": len(self._columns),
            "columns": list(self._columns),
            "timestamp_convention": "interval_start",
            "parquet_engine": "pyarrow",
            "parquet_engine_version": self._pyarrow_version,
        }

    def abort(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        self._temp_path.unlink(missing_ok=True)
        self._closed = True

    def telemetry(self) -> dict[str, Any]:
        return {
            "mode": "streaming_parquet",
            "row_count": self._row_count,
            "chunk_count": self._chunk_count,
            "max_chunk_rows": self._max_chunk_rows,
        }


class _ReceiverFactorSpool(ReceiverFactorParquetSink):
    """Private intermediate only: no canonical result reference is published.

    Validation, sorting, Arrow schema, codec, chunks and cleanup are inherited.
    The authoritative final merge still uses ReceiverFactorParquetSink and all
    its hashes/verification. Only unconsumed temporary digest work is omitted.
    """
    def _update_digests(self, serializable: pd.DataFrame) -> None:
        pass

    def finalize(self) -> Path:
        return self._finish_file()


def persist_receiver_factor_result(
    frame: pd.DataFrame,
    *,
    output_directory: Path,
    simulation_run_id: str,
) -> dict[str, Any]:
    """Persist long-form module receiver beam factors as a separate Parquet dataset."""
    try:
        import pyarrow  # type: ignore
    except ImportError as exc:  # pragma: no cover - dependency failure is explicit
        raise RuntimeError(
            "Phase 5.5 receiver-factor persistence requires pyarrow"
        ) from exc

    missing = sorted(RECEIVER_FACTOR_REQUIRED_COLUMNS - set(frame.columns))
    if missing:
        raise ValueError(
            "receiver-factor dataset is missing required columns: "
            + ", ".join(missing)
        )

    serializable = frame.copy()
    serializable = serializable.sort_values(
        ["interval_start", "receiver_id"],
        kind="stable",
    ).reset_index(drop=True)

    run_directory = output_directory / simulation_run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    path = run_directory / "shading-receiver-factors.parquet"
    if path.exists():
        raise FileExistsError(
            "receiver-factor output already exists for immutable run package"
        )
    serializable.to_parquet(
        path,
        engine="pyarrow",
        index=False,
        compression="zstd",
    )
    raw = path.read_bytes()

    return {
        "schema_name": "ResultDatasetReference",
        "schema_version": "0.1",
        "format": "parquet",
        "uri": path.resolve().as_uri(),
        "media_type": "application/vnd.apache.parquet",
        "byte_size": len(raw),
        "sha256": sha256(raw).hexdigest(),
        "logical_content_sha256": dataframe_logical_sha256(serializable),
        "physical_content_sha256": receiver_factor_physical_sha256(serializable),
        "row_count": len(serializable),
        "column_count": len(serializable.columns),
        "columns": list(serializable.columns),
        "timestamp_convention": "interval_start",
        "parquet_engine": "pyarrow",
        "parquet_engine_version": pyarrow.__version__,
    }


def persist_json_artifact(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        for part in json.JSONEncoder(indent=2, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).iterencode(value):
            stream.write(part)
        stream.write("\n")


def _file_sha256(path: Path) -> tuple[str, int]:
    digest = sha256()
    byte_size = 0
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            byte_size += len(block)
            digest.update(block)
    return digest.hexdigest(), byte_size


def _run_package_artifact_role(path: Path) -> str:
    roles = {
        "simulation-run.json": "simulation_run",
        "summary-result.json": "summary_result",
        "reproducibility-manifest.json": "reproducibility_manifest",
        "validation-findings.json": "validation_findings",
        "model-resolution.json": "model_resolution",
        "design-validation-report.json": "design_validation_report",
        "shading-result.json": "shading_result",
        "detailed-execution-context.json": "detailed_execution_context",
        "timeseries.parquet": "standard_timeseries",
        "group-timeseries.parquet": "execution_group_timeseries",
        "inverter-timeseries.parquet": "inverter_timeseries",
        "shading-receiver-factors.parquet": "shading_receiver_factors",
    }
    return roles.get(path.name, "other")


def _build_run_package_manifest(
    run_directory: Path,
    *,
    simulation_run_id: str,
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for path in sorted(
        (
            item
            for item in run_directory.rglob("*")
            if item.is_file() and item.name != "run-package-manifest.json"
        ),
        key=lambda item: item.relative_to(run_directory).as_posix(),
    ):
        file_sha256, byte_size = _file_sha256(path)
        artifacts.append(
            {
                "relative_path": path.relative_to(run_directory).as_posix(),
                "role": _run_package_artifact_role(path),
                "byte_size": byte_size,
                "sha256": file_sha256,
            }
        )

    payload = {
        "schema_name": "RunPackageManifest",
        "schema_version": "0.1",
        "simulation_run_id": str(simulation_run_id),
        "package_state": "complete",
        "completion_rule": (
            "manifest_written_last_after_all_required_run_artifacts"
        ),
        "recovery_rule": (
            "missing_or_invalid_manifest_means_incomplete_package_rebuild_required"
        ),
        "artifact_count": len(artifacts),
        "artifacts": artifacts,
    }
    return {
        **payload,
        "manifest_payload_sha256": canonical_object_sha256(payload),
    }


def verify_run_package(run_directory: Path) -> dict[str, Any]:
    """Fail closed unless a run package has a valid last-write completion manifest."""
    run_directory = Path(run_directory)
    manifest_path = run_directory / "run-package-manifest.json"
    if not manifest_path.is_file():
        raise ValueError(
            "run package is incomplete: run-package-manifest.json is absent"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("run package completion manifest is unreadable") from exc

    if manifest.get("package_state") != "complete":
        raise ValueError("run package completion manifest is not complete")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("run package manifest artifacts must be an array")
    if manifest.get("artifact_count") != len(artifacts):
        raise ValueError("run package manifest artifact_count does not reconcile")

    payload = dict(manifest)
    stored_manifest_hash = payload.pop("manifest_payload_sha256", None)
    expected_manifest_hash = canonical_object_sha256(payload)
    if stored_manifest_hash != expected_manifest_hash:
        raise ValueError("run package manifest payload hash mismatch")

    seen_paths: set[str] = set()
    for artifact in artifacts:
        relative_path = str(artifact.get("relative_path") or "")
        if (
            not relative_path
            or relative_path in seen_paths
            or relative_path.startswith("/")
            or ".." in Path(relative_path).parts
        ):
            raise ValueError("run package manifest contains an invalid artifact path")
        seen_paths.add(relative_path)
        path = run_directory / relative_path
        if not path.is_file():
            raise ValueError(
                f"run package artifact is missing: {relative_path}"
            )
        actual_sha256, actual_size = _file_sha256(path)
        if actual_sha256 != artifact.get("sha256"):
            raise ValueError(
                f"run package artifact hash mismatch: {relative_path}"
            )
        if actual_size != artifact.get("byte_size"):
            raise ValueError(
                f"run package artifact size mismatch: {relative_path}"
            )

    actual_files = {
        path.relative_to(run_directory).as_posix()
        for path in run_directory.rglob("*")
        if path.is_file() and path.name != "run-package-manifest.json"
    }
    if actual_files != seen_paths:
        raise ValueError(
            "run package contains files not covered by the completion manifest"
        )
    detailed_path = run_directory / "detailed-execution-context.json"
    if not detailed_path.is_file() and any((run_directory / name).exists() for name in
        ("detailed-electrical-interval-index.json", "detailed-electrical-intervals",
         "detailed-attribution-diagnostic-index.json", "detailed-attribution-diagnostic-chunks")):
        raise ValueError("unbound electrical interval storage")
    if detailed_path.is_file():
        from .detailed_dispatch import _detailed_verification_transaction
        detailed = json.loads(detailed_path.read_text(encoding="utf-8"))
        with _detailed_verification_transaction(detailed) as context_check:
            run = json.loads((run_directory / "simulation-run.json").read_text(encoding="utf-8"))
            if run.get("detailed_execution_identity") != detailed["identity"]:
                raise ValueError("run detailed execution identity does not match pinned context")
            identity = detailed["identity"]
            expected_run_hash = canonical_object_sha256({
                "canonical_input_hash": detailed["canonical_input_hash"],
                "detailed_scientific_input_sha256": identity["scientific_input_sha256"],
                "detailed_execution_identity_sha256": identity["execution_identity_sha256"],
            })
            if run.get("input_hash") != expected_run_hash:
                raise ValueError("run input hash does not match detailed identity")
            numerical_path = run_directory / "detailed-mppt-result.json"
            if identity.get("numerical_result_sha256") is not None:
                from .detailed_backend import DetailedMPPTBackendResult
                compact_path = run_directory / "detailed-selected-mppt.json"
                if identity.get("compact_result_sha256") is not None:
                    from .detailed_downstream import CompactDetailedMPPTResult
                    if not compact_path.is_file():
                        raise ValueError("compact detailed result is missing")
                    compact_record = json.loads(compact_path.read_text())
                    compact = CompactDetailedMPPTResult.freeze(compact_record["payload"], _decoded=True)
                    if compact.compact_result_sha256 != compact_record["compact_result_sha256"] or compact.compact_result_sha256 != identity["compact_result_sha256"]:
                        raise ValueError("compact detailed result identity mismatch")
                    payload = compact_record["payload"]
                    if payload["scientific_input_sha256"] != identity["scientific_input_sha256"] or payload["diagnostic_result_sha256"] != identity["numerical_result_sha256"]:
                        raise ValueError("compact detailed scientific/diagnostic identity mismatch")
                elif not numerical_path.is_file():
                    raise ValueError("detailed numerical result is missing")
                interval_index = run_directory / "detailed-electrical-interval-index.json"
                if (run_directory / "detailed-electrical-intervals").exists() and not interval_index.is_file():
                    raise ValueError("electrical interval index is missing")
                if interval_index.is_file():
                    result = load_electrical_interval_result(run_directory)
                    record = {"numerical_result_sha256": result.numerical_result_sha256}
                    if numerical_path.is_file() and _persisted_json_sha256(result.record(stream=True)) != _file_sha256(numerical_path)[0]:
                        raise ValueError("detailed diagnostic artifact does not match interval storage")
                else:
                    record = json.loads(numerical_path.read_text()) if numerical_path.is_file() else None
                    result = DetailedMPPTBackendResult.freeze(record["payload"]) if record else None
                if result and (result.numerical_result_sha256 != record["numerical_result_sha256"] or result.numerical_result_sha256 != identity["numerical_result_sha256"]):
                    raise ValueError("detailed numerical result identity mismatch")
                if result and result.replay_stream()["scientific_input_sha256"] != identity["scientific_input_sha256"]:
                    raise ValueError("detailed numerical result scientific input mismatch")
                if result and identity.get("compact_result_sha256") is not None:
                    from .detailed_downstream import compact_selected_states
                    if compact_selected_states(result) != compact:
                        raise ValueError("compact detailed result does not match diagnostic projection")
            elif numerical_path.exists() or (run_directory / "detailed-electrical-interval-index.json").exists() or (run_directory / "detailed-electrical-intervals").exists():
                raise ValueError("unexpected unbound detailed numerical result")
            attribution_path = run_directory / "detailed-dc-attribution.json"
            attribution_ref = detailed.get("dc_attribution_reference")
            if attribution_ref is not None:
                from .attribution_json_stream import open_persisted_attribution
                from .detailed_attribution import (verify_attribution_sources,
                                                  verify_attribution_diagnostics)
                if not attribution_path.is_file():
                    raise ValueError("referenced detailed DC attribution is missing")
                with open_persisted_attribution(attribution_path) as (attribution, payload):
                    if (attribution.attribution_result_sha256 != attribution_ref["attribution_result_sha256"]
                        or attribution_ref["model_id"] != payload["attribution_model_id"]
                        or attribution_ref["artifact"] != attribution_path.name):
                        raise ValueError("attribution reference hash/model binding mismatch")
                    verify_attribution_sources(attribution, detailed,
                        compact if identity.get("compact_result_sha256") is not None else None,
                        result if identity.get("numerical_result_sha256") is not None else None,
                        _context_check=context_check, _payload=payload,
                        _compact_payload=compact_record["payload"] if identity.get("compact_result_sha256") is not None else None)
                    diag_path = run_directory / "detailed-dc-attribution-diagnostics.json"
                    if (run_directory / "detailed-attribution-diagnostic-chunks").exists() and not (run_directory / "detailed-attribution-diagnostic-index.json").is_file():
                        raise ValueError("attribution diagnostic interval index is missing")
                    if diag_path.exists():
                        diag_index = run_directory / "detailed-attribution-diagnostic-index.json"
                        if diag_index.is_file():
                            diagnostic_record = load_attribution_diagnostic_store(run_directory, attribution)
                            if _persisted_json_sha256(diagnostic_record) != _file_sha256(diag_path)[0]:
                                raise ValueError("attribution diagnostic artifact does not match interval storage")
                        else:
                            diagnostic_record = json.loads(diag_path.read_text())
                        verify_attribution_diagnostics(attribution, diagnostic_record, _payload=payload)
                        del diagnostic_record
                    elif (run_directory / "detailed-attribution-diagnostic-index.json").exists() or (run_directory / "detailed-attribution-diagnostic-chunks").exists():
                        raise ValueError("unbound attribution diagnostic interval storage")
                    energy_path = run_directory / "detailed-dc-attribution-energy-summary.json"
                    energy_ref = detailed.get("dc_attribution_energy_reference")
                    if energy_ref is not None:
                        from .attribution_energy import DetailedDCAttributionEnergySummary, verify_energy_summary
                        if not energy_path.is_file():
                            raise ValueError("referenced attribution energy summary is missing")
                        energy_record = json.loads(energy_path.read_text())
                        energy = DetailedDCAttributionEnergySummary.freeze(energy_record["payload"], _decoded=True)
                        if (energy.energy_summary_sha256 != energy_record["energy_summary_sha256"]
                            or energy.energy_summary_sha256 != energy_ref["energy_summary_sha256"]
                            or energy_ref["artifact"] != energy_path.name
                            or energy_ref["model_id"] != energy_record["payload"]["energy_summary_model_id"]):
                            raise ValueError("attribution energy summary reference mismatch")
                        verify_energy_summary(energy, attribution_path, _source=attribution,
                            _payload=payload, _summary_payload=energy_record["payload"])
                    elif energy_path.exists():
                        raise ValueError("unbound attribution energy summary")
            elif attribution_path.exists() or (run_directory / "detailed-dc-attribution-diagnostics.json").exists() or (run_directory / "detailed-attribution-diagnostic-index.json").exists() or (run_directory / "detailed-attribution-diagnostic-chunks").exists():
                raise ValueError("unbound detailed DC attribution artifact")
            elif detailed.get("dc_attribution_energy_reference") is not None or (run_directory / "detailed-dc-attribution-energy-summary.json").exists():
                raise ValueError("attribution energy summary requires compact attribution")
            reproduction = run.get("reproducibility_manifest")
            if reproduction is not None and reproduction.get("detailed_execution_identity") != detailed["identity"]:
                raise ValueError("reproducibility detailed identity mismatch")
            reproduction_path = run_directory / "reproducibility-manifest.json"
            if reproduction is not None:
                if not reproduction_path.is_file() or json.loads(reproduction_path.read_text()) != reproduction:
                    raise ValueError("persisted reproducibility manifest does not match run")
    else:
        if (run_directory / "detailed-dc-attribution-energy-summary.json").exists():
            raise ValueError("unbound attribution energy summary without detailed context")
        run_path = run_directory / "simulation-run.json"
        if run_path.is_file() and json.loads(run_path.read_text()).get("detailed_execution_identity") is not None:
            raise ValueError("detailed execution context is missing")
    summary_path = run_directory / "summary-result.json"
    if summary_path.is_file():
        breakdown = json.loads(summary_path.read_text()).get("execution_breakdown")
        if breakdown is not None:
            from urllib.parse import unquote, urlparse
            for key, filename in (("group_timeseries_reference", "group-timeseries.parquet"),
                                  ("inverter_timeseries_reference", "inverter-timeseries.parquet")):
                reference = breakdown[key]
                path = run_directory / filename
                if Path(unquote(urlparse(reference["uri"]).path)).resolve() != path.resolve():
                    raise ValueError("execution breakdown dataset binding mismatch")
                digest, size = _file_sha256(path)
                frame = pd.read_parquet(path)
                if (digest != reference["sha256"] or size != reference["byte_size"]
                        or dataframe_logical_sha256(frame) != reference["logical_content_sha256"]
                        or len(frame) != reference["row_count"]
                        or list(frame.columns) != reference["columns"]):
                    raise ValueError("execution breakdown dataset reference mismatch")
    return manifest


def persist_run_package(
    *,
    output_directory: Path,
    simulation_run_id: str,
    simulation_run: dict[str, Any],
    summary_result: dict[str, Any] | None,
    reproducibility_manifest: dict[str, Any] | None,
    validation_findings: list[dict[str, Any]],
    model_resolution: dict[str, Any] | None,
    shading_result: dict[str, Any] | None = None,
    detailed_context=None,
    detailed_backend_result=None,
    detailed_compact_result=None,
    detailed_attribution_result=None,
    detailed_diagnostics=False,
) -> Path:
    run_directory = output_directory / simulation_run_id
    run_directory.mkdir(parents=True, exist_ok=True)
    completion_path = run_directory / "run-package-manifest.json"
    if completion_path.exists():
        raise FileExistsError(
            "completed run package is immutable; use a new simulation_run_id"
        )

    if detailed_context is not None:
        from .detailed_dispatch import _detailed_verification_transaction
        from .canonical import _assert_output_schema
        with _detailed_verification_transaction(detailed_context) as context_check:
            identity = detailed_context["identity"]
            detailed_context = dict(detailed_context)
            if detailed_attribution_result is not None:
                from .detailed_attribution import verify_attribution_sources
                verify_attribution_sources(detailed_attribution_result, detailed_context,
                    detailed_compact_result, detailed_backend_result, _context_check=context_check)
                detailed_context["dc_attribution_reference"] = {
                    "model_id": detailed_attribution_result.replay_stream()["attribution_model_id"],
                    "attribution_result_sha256": detailed_attribution_result.attribution_result_sha256,
                    "artifact": "detailed-dc-attribution.json"}
        detailed_context["canonical_input_hash"] = simulation_run["input_hash"]
        simulation_run["detailed_execution_identity"] = identity
        simulation_run["input_hash"] = canonical_object_sha256({
            "canonical_input_hash": simulation_run["input_hash"],
            "detailed_scientific_input_sha256": identity["scientific_input_sha256"],
            "detailed_execution_identity_sha256": identity["execution_identity_sha256"],
        })
        if reproducibility_manifest is not None:
            reproducibility_manifest["detailed_execution_identity"] = identity
            hashes = reproducibility_manifest["input_hashes"]
            hashes["detailed_scientific_input_sha256"] = identity["scientific_input_sha256"]
            hashes["detailed_execution_identity_sha256"] = identity["execution_identity_sha256"]
            hashes["combined_input_sha256"] = simulation_run["input_hash"]
            _assert_output_schema(reproducibility_manifest, "reproducibility-manifest.schema.json")
        _assert_output_schema(simulation_run, "simulation-run.schema.json")
        persist_json_artifact(run_directory / "detailed-execution-context.json", detailed_context)

    if detailed_backend_result is not None:
        persist_electrical_interval_result(run_directory, detailed_backend_result)
        record = detailed_backend_result.record(stream=True)
        if detailed_context is None or detailed_context["identity"].get("numerical_result_sha256") != record["numerical_result_sha256"]:
            raise ValueError("detailed numerical result does not match run identity")
        if detailed_diagnostics or detailed_compact_result is None:
            persist_json_artifact(run_directory / "detailed-mppt-result.json", record)
    if detailed_compact_result is not None:
        record = detailed_compact_result.record()
        if detailed_context is None or detailed_context["identity"].get("compact_result_sha256") != record["compact_result_sha256"]:
            raise ValueError("compact detailed result does not match run identity")
        persist_json_artifact(run_directory / "detailed-selected-mppt.json", record)

    if detailed_attribution_result is not None:
        persist_json_artifact(run_directory / "detailed-dc-attribution.json", detailed_attribution_result.record(stream=True))
        from .attribution_energy import aggregate_persisted_attribution
        energy = aggregate_persisted_attribution(run_directory / "detailed-dc-attribution.json")
        energy_record = energy.record()
        persist_json_artifact(run_directory / "detailed-dc-attribution-energy-summary.json", energy_record)
        detailed_context["dc_attribution_energy_reference"] = {
            "model_id": energy_record["payload"]["energy_summary_model_id"],
            "energy_summary_sha256": energy.energy_summary_sha256,
            "artifact": "detailed-dc-attribution-energy-summary.json"}
        persist_json_artifact(run_directory / "detailed-execution-context.json", detailed_context)
        if detailed_diagnostics and detailed_attribution_result.diagnostic_rows() is not None:
            persist_attribution_diagnostic_store(run_directory, detailed_attribution_result)
            persist_json_artifact(run_directory / "detailed-dc-attribution-diagnostics.json", {
                "attribution_result_sha256": detailed_attribution_result.attribution_result_sha256,
                "curves": detailed_attribution_result.diagnostic_rows()})

    persist_json_artifact(run_directory / "simulation-run.json", simulation_run)
    persist_json_artifact(
        run_directory / "validation-findings.json",
        validation_findings,
    )
    if summary_result is not None:
        persist_json_artifact(run_directory / "summary-result.json", summary_result)
    if reproducibility_manifest is not None:
        persist_json_artifact(
            run_directory / "reproducibility-manifest.json",
            reproducibility_manifest,
        )
    if model_resolution is not None:
        persist_json_artifact(
            run_directory / "model-resolution.json",
            model_resolution,
        )
    if shading_result is not None:
        persist_json_artifact(
            run_directory / "shading-result.json",
            shading_result,
        )

    # The completion manifest is deliberately persisted last. Its absence after
    # interruption means the package is not consumable and must be rebuilt.
    package_manifest = _build_run_package_manifest(
        run_directory,
        simulation_run_id=simulation_run_id,
    )
    persist_json_artifact(completion_path, package_manifest)
    verify_run_package(run_directory)
    return run_directory
