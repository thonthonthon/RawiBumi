"""Phase-5.8 exact shading acceleration/cache context.

This module keeps exact query preparation separate from approximate angular
sampling.  A bounded process-local static-result cache is identity-safe: cache
keys bind compiled geometry, the complete shading configuration, receiver set,
solver/acceleration versions, and channel.

The cache contains only derived shading results. Canonical Scene/Electrical
authority is never stored or mutated here.
"""

from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from threading import RLock
from typing import Any, Iterable, Mapping

from .beam import BEAM_SOLVER_ID, BEAM_SOLVER_VERSION
from .contract import (
    CONTRACT_VERSION,
    ShadingContractError,
    assert_shading_result_storage_consistency,
)
from .directional import (
    DIRECTIONAL_VISIBILITY_SOLVER_ID,
    DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
)
from .ground import GROUND_VISIBILITY_SOLVER_ID, GROUND_VISIBILITY_SOLVER_VERSION
from .prepared import (
    PREPARED_DIRECTIONAL_ENGINE_ID,
    PREPARED_DIRECTIONAL_ENGINE_VERSION,
    PreparedDirectionalError,
    PreparedDirectionalReceiver,
    prepare_directional_receiver,
)
from .sky import SKY_VISIBILITY_SOLVER_ID, SKY_VISIBILITY_SOLVER_VERSION


SHADING_ACCELERATION_ID = "rawibumi.shading_acceleration.exact_prepared"
SHADING_ACCELERATION_VERSION = "0.1"
STATIC_CACHE_ID = "rawibumi.shading_cache.process_local_exact"
STATIC_CACHE_VERSION = "0.1"

_STATIC_CHANNELS = {"sky_visibility", "ground_visibility"}


class ShadingAccelerationError(ValueError):
    """Raised when exact acceleration/cache identity cannot be established."""


def _sha256_json(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExactStaticShadingCache:
    """Bounded process-local LRU cache for static ShadingResult payloads."""

    def __init__(self, *, max_entries: int = 256):
        if isinstance(max_entries, bool) or int(max_entries) < 1:
            raise ShadingAccelerationError("max_entries must be a positive integer")
        self.max_entries = int(max_entries)
        self._entries: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> dict[str, Any] | None:
        with self._lock:
            value = self._entries.get(key)
            if value is None:
                return None
            self._entries.move_to_end(key)
            return deepcopy(value)

    def put(self, key: str, value: Mapping[str, Any]) -> None:
        with self._lock:
            self._entries[key] = deepcopy(dict(value))
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


GLOBAL_EXACT_STATIC_SHADING_CACHE = ExactStaticShadingCache()


@dataclass
class ShadingAccelerationContext:
    compiled_geometry: Mapping[str, Any]
    shading_configuration: Mapping[str, Any]
    receiver_ids: tuple[str, ...]
    source_execution_plan_id: str | None = None
    source_execution_plan_payload_sha256: str | None = None
    static_store: ExactStaticShadingCache = GLOBAL_EXACT_STATIC_SHADING_CACHE
    _prepared: dict[str, PreparedDirectionalReceiver] = field(
        default_factory=dict,
        init=False,
    )
    _manifest_entries: dict[str, dict[str, Any]] = field(
        default_factory=dict,
        init=False,
    )
    prepared_query_build_count: int = field(default=0, init=False)
    prepared_query_hit_count: int = field(default=0, init=False)
    static_cache_hit_count: int = field(default=0, init=False)
    static_cache_miss_count: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        geometry_hash = str(
            self.compiled_geometry.get("geometry_payload_sha256") or ""
        )
        if (
            len(geometry_hash) != 64
            or any(character not in "0123456789abcdef" for character in geometry_hash)
        ):
            raise ShadingAccelerationError(
                "compiled geometry must provide lowercase geometry_payload_sha256"
            )
        scene_revision = str(
            self.compiled_geometry.get("source_scene_revision_id") or ""
        )
        if not scene_revision:
            raise ShadingAccelerationError(
                "compiled geometry must retain source_scene_revision_id"
            )

        unique = tuple(sorted(set(str(item) for item in self.receiver_ids)))
        if not unique:
            raise ShadingAccelerationError("receiver_ids must not be empty")
        if unique != self.receiver_ids:
            self.receiver_ids = unique

        mode = (self.shading_configuration.get("cache_policy") or {}).get("mode")
        if mode not in {"none", "exact"}:
            raise ShadingAccelerationError(
                "Phase-5.8 exact acceleration context supports cache mode "
                "'none' or 'exact'; angular_bins remains a separate approximation"
            )

        if mode == "exact":
            plan_hash = str(self.source_execution_plan_payload_sha256 or "")
            if (
                len(plan_hash) != 64
                or any(character not in "0123456789abcdef" for character in plan_hash)
            ):
                raise ShadingAccelerationError(
                    "exact cache mode requires full source_execution_plan_payload_sha256"
                )

    @property
    def mode(self) -> str:
        return str((self.shading_configuration.get("cache_policy") or {})["mode"])

    @property
    def compiled_geometry_hash(self) -> str:
        return str(self.compiled_geometry["geometry_payload_sha256"])

    @property
    def source_scene_revision_id(self) -> str:
        return str(self.compiled_geometry["source_scene_revision_id"])

    @property
    def receiver_set_sha256(self) -> str:
        return _sha256_json(list(self.receiver_ids))

    @property
    def shading_configuration_hash(self) -> str:
        return _sha256_json(dict(self.shading_configuration))

    @property
    def solver_identity(self) -> dict[str, Any]:
        return {
            "beam": {
                "solver_id": BEAM_SOLVER_ID,
                "solver_version": BEAM_SOLVER_VERSION,
            },
            "directional": {
                "solver_id": DIRECTIONAL_VISIBILITY_SOLVER_ID,
                "solver_version": DIRECTIONAL_VISIBILITY_SOLVER_VERSION,
            },
            "sky": {
                "solver_id": SKY_VISIBILITY_SOLVER_ID,
                "solver_version": SKY_VISIBILITY_SOLVER_VERSION,
            },
            "ground": {
                "solver_id": GROUND_VISIBILITY_SOLVER_ID,
                "solver_version": GROUND_VISIBILITY_SOLVER_VERSION,
            },
            "prepared_exact_engine": {
                "engine_id": PREPARED_DIRECTIONAL_ENGINE_ID,
                "engine_version": PREPARED_DIRECTIONAL_ENGINE_VERSION,
            },
            "acceleration": {
                "acceleration_id": SHADING_ACCELERATION_ID,
                "acceleration_version": SHADING_ACCELERATION_VERSION,
            },
            "static_cache": {
                "cache_id": STATIC_CACHE_ID,
                "cache_version": STATIC_CACHE_VERSION,
            },
        }

    @property
    def solver_manifest_hash(self) -> str:
        return _sha256_json(self.solver_identity)

    def prepared_query(
        self,
        receiver_id: str,
    ) -> PreparedDirectionalReceiver | None:
        """Return reusable exact query state in exact mode; reference mode gets None."""
        if self.mode == "none":
            return None
        receiver_id = str(receiver_id)
        if receiver_id not in self.receiver_ids:
            raise ShadingAccelerationError(
                f"receiver is outside acceleration context: {receiver_id}"
            )
        existing = self._prepared.get(receiver_id)
        if existing is not None:
            self.prepared_query_hit_count += 1
            return existing
        try:
            prepared = prepare_directional_receiver(
                self.compiled_geometry,
                receiver_id=receiver_id,
                self_shading_enabled=bool(
                    self.shading_configuration["self_shading_enabled"]
                ),
            )
        except PreparedDirectionalError as exc:
            raise ShadingAccelerationError(str(exc)) from exc
        self._prepared[receiver_id] = prepared
        self.prepared_query_build_count += 1
        return prepared

    def prepared_query_map(self) -> Mapping[str, PreparedDirectionalReceiver] | None:
        if self.mode == "none":
            return None
        if not getattr(self, "_parallel_checked", False):
            from .parallel import create_receiver_pool, PreparedReceiverMap
            pool, telemetry = create_receiver_pool(
                self.compiled_geometry, self.shading_configuration, self.receiver_ids,
            )
            self._parallel_pool = pool
            self._parallel_telemetry = telemetry
            self._parallel_checked = True
            self._parallel_map = PreparedReceiverMap(self, pool) if pool is not None else None
            if pool is not None:
                self.prepared_query_build_count += len(self.receiver_ids)
        if self._parallel_map is not None:
            return self._parallel_map
        return {
            receiver_id: self.prepared_query(receiver_id)
            for receiver_id in self.receiver_ids
        }

    @property
    def operational_telemetry(self):
        # Operational evidence never enters the scientific cache/manifest.
        return getattr(self, "_parallel_telemetry", {"mode":"serial","workers":1,"reason":"not_initialized"})

    def close(self):
        pool = getattr(self, "_parallel_pool", None)
        if pool is not None:
            pool.close()
            self._parallel_pool = None
        self._parallel_map = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        self.close()

    def _static_key(self, channel: str) -> str:
        if channel not in _STATIC_CHANNELS:
            raise ShadingAccelerationError(
                f"unsupported static cache channel: {channel!r}"
            )
        return _sha256_json(
            {
                "cache_contract": "phase5.8.static-result.v0.1",
                "channel": channel,
                "compiled_geometry_hash": self.compiled_geometry_hash,
                "shading_configuration_hash": self.shading_configuration_hash,
                "solver_manifest_hash": self.solver_manifest_hash,
                "receiver_set_sha256": self.receiver_set_sha256,
                "source_execution_plan_payload_sha256": (
                    self.source_execution_plan_payload_sha256
                ),
            }
        )

    def _validate_static_result(
        self,
        channel: str,
        result: Mapping[str, Any],
    ) -> dict[str, Any]:
        payload = dict(result)
        try:
            assert_shading_result_storage_consistency(payload)
        except ShadingContractError as exc:
            raise ShadingAccelerationError(str(exc)) from exc

        checks = {
            "compiled_geometry_hash": self.compiled_geometry_hash,
            "receiver_set_sha256": self.receiver_set_sha256,
            "source_scene_revision_id": self.source_scene_revision_id,
            "shading_configuration_hash": self.shading_configuration_hash,
            "source_execution_plan_id": self.source_execution_plan_id,
        }
        for field_name, expected in checks.items():
            if payload.get(field_name) != expected:
                raise ShadingAccelerationError(
                    f"static cache result {field_name} mismatch"
                )

        if payload.get("storage_mode") != "inline":
            raise ShadingAccelerationError(
                "Phase-5.8H static cache accepts inline ShadingResult payloads only"
            )
        expected_channels = (
            ["sky_visibility", "directional_diffuse_visibility"]
            if channel == "sky_visibility"
            else [channel]
        )
        if payload.get("channels") != expected_channels:
            raise ShadingAccelerationError(
                "static cache result channel mismatch"
            )
        return payload

    def get_static_result(self, channel: str) -> dict[str, Any] | None:
        if self.mode != "exact":
            return None
        key = self._static_key(channel)
        result = self.static_store.get(key)
        if result is None:
            self.static_cache_miss_count += 1
            return None
        payload = self._validate_static_result(channel, result)
        self.static_cache_hit_count += 1
        self._record_manifest_entry(channel, key, payload)
        return payload

    def put_static_result(
        self,
        channel: str,
        result: Mapping[str, Any],
    ) -> None:
        if self.mode != "exact":
            return
        key = self._static_key(channel)
        payload = self._validate_static_result(channel, result)
        self.static_store.put(key, payload)
        self._record_manifest_entry(channel, key, payload)

    def _record_manifest_entry(
        self,
        channel: str,
        key: str,
        result: Mapping[str, Any],
    ) -> None:
        result_hash = str(result.get("result_payload_sha256") or "")
        if (
            len(result_hash) != 64
            or any(character not in "0123456789abcdef" for character in result_hash)
        ):
            raise ShadingAccelerationError(
                "cached static result lacks result_payload_sha256"
            )
        self._manifest_entries[key] = {
            "cache_key_sha256": key,
            "channel": channel,
            "receiver_set_sha256": self.receiver_set_sha256,
            "sun_state_sha256": None,
            "result_sha256": result_hash,
            "entry_uri": None,
        }

    def cache_manifest(self) -> dict[str, Any]:
        """Return a schema-valid manifest for exact static result cache entries."""
        entries = [
            self._manifest_entries[key]
            for key in sorted(self._manifest_entries)
        ]
        payload = {
            "schema_name": "ShadingCacheManifest",
            "schema_version": "0.1",
            "contract_version": CONTRACT_VERSION,
            "source_scene_revision_id": self.source_scene_revision_id,
            "compiled_geometry_hash": self.compiled_geometry_hash,
            "shading_configuration_hash": self.shading_configuration_hash,
            "solver_manifest_hash": self.solver_manifest_hash,
            "source_execution_plan_payload_sha256": (
                self.source_execution_plan_payload_sha256
            ),
            "fidelity_level": self.shading_configuration["fidelity_level"],
            "cache_policy": dict(self.shading_configuration["cache_policy"]),
            "deterministic": True,
            "entry_count": len(entries),
            "entries": entries,
            "invalidation_basis": [
                "source_scene_revision",
                "compiled_geometry_hash",
                "shading_configuration_hash",
                "solver_manifest_hash",
                "fidelity_level",
                "sampling_resolution",
                "receiver_set",
                "execution_plan",
            ],
        }
        manifest_hash = _sha256_json(payload)
        return {
            **payload,
            "cache_manifest_id": f"shading-cache:{manifest_hash[:16]}",
        }

    def manifest(self) -> dict[str, Any]:
        """Deterministic acceleration identity suitable for model provenance."""
        return {
            "acceleration_id": SHADING_ACCELERATION_ID,
            "acceleration_version": SHADING_ACCELERATION_VERSION,
            "cache_mode": self.mode,
            "prepared_engine_id": PREPARED_DIRECTIONAL_ENGINE_ID,
            "prepared_engine_version": PREPARED_DIRECTIONAL_ENGINE_VERSION,
            "static_cache_id": STATIC_CACHE_ID,
            "static_cache_version": STATIC_CACHE_VERSION,
            "exact_physics": True,
            "angular_quantization": False,
        }

    def metrics(self) -> dict[str, Any]:
        """Volatile execution telemetry; never part of reproducibility identity."""
        return {
            **self.manifest(),
            "prepared_query_build_count": self.prepared_query_build_count,
            "prepared_query_hit_count": self.prepared_query_hit_count,
            "prepared_receiver_count": len(self._prepared),
            "prepared_face_count": sum(
                item.prepared_face_count for item in self._prepared.values()
            ),
            "static_cache_hit_count": self.static_cache_hit_count,
            "static_cache_miss_count": self.static_cache_miss_count,
            "static_cache_process_entry_count": len(self.static_store),
        }


def build_shading_acceleration_context(
    compiled_geometry: Mapping[str, Any],
    *,
    shading_configuration: Mapping[str, Any],
    receiver_ids: Iterable[str],
    source_execution_plan_id: str | None = None,
    source_execution_plan_payload_sha256: str | None = None,
    static_store: ExactStaticShadingCache = GLOBAL_EXACT_STATIC_SHADING_CACHE,
) -> ShadingAccelerationContext:
    return ShadingAccelerationContext(
        compiled_geometry=compiled_geometry,
        shading_configuration=shading_configuration,
        receiver_ids=tuple(sorted(set(str(item) for item in receiver_ids))),
        source_execution_plan_id=source_execution_plan_id,
        source_execution_plan_payload_sha256=source_execution_plan_payload_sha256,
        static_store=static_store,
    )


def clear_global_exact_shading_cache() -> None:
    """Test/worker maintenance hook; never changes canonical project state."""
    GLOBAL_EXACT_STATIC_SHADING_CACHE.clear()
