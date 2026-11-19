"""Bounded, explicitly injected synthetic lifecycle evidence; no disposal protocol.

Only CREATE and OWNER_RETURN are supported. Neither proves owner termination.
All identities, metadata and clock readings are test declarations, unauthenticated.
No production caller enables this seam. No object under observation is accepted.
"""

import json
import math


MAX_EVENTS = 4096
MAX_METADATA_BYTES = 4096


class LifecycleContractError(Exception):
    """Invalid opt-in instrumentation; deliberately not a ValueError."""


def _token(value):
    if type(value) is not str or not value.strip() or len(value) > 128:
        raise LifecycleContractError("identity tokens must be nonblank bounded strings")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise LifecycleContractError("identity token is not UTF-8") from exc
    return value


def _metadata_copy(value):
    """Accept only bounded exact JSON types; never invoke user copy hooks."""
    remaining = 256

    def visit(item, depth):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 8:
            raise LifecycleContractError("metadata nesting or item limit exceeded")
        kind = type(item)
        if item is None or kind is bool:
            return item
        if kind is int:
            if item.bit_length() > 64:
                raise LifecycleContractError("metadata integer is too large")
            return item
        if kind is float and math.isfinite(item):
            return item
        if kind is str:
            try:
                encoded = item.encode("utf-8")
            except UnicodeError as exc:
                raise LifecycleContractError("metadata is not UTF-8") from exc
            if len(encoded) > MAX_METADATA_BYTES:
                raise LifecycleContractError("metadata string is too large")
            return item
        if kind is list:
            if len(item) > 256:
                raise LifecycleContractError("metadata list is too large")
            return [visit(child, depth + 1) for child in item]
        if kind is dict:
            if len(item) > 256:
                raise LifecycleContractError("metadata object is too large")
            result = {}
            for key, child in item.items():
                if type(key) is not str:
                    raise LifecycleContractError("metadata keys must be strings")
                result[visit(key, depth + 1)] = visit(child, depth + 1)
            return result
        raise LifecycleContractError("metadata must contain only finite JSON values")

    if type(value) is not dict:
        raise LifecycleContractError("identity_metadata must be a JSON object")
    result = visit(value, 0)
    if len(json.dumps(result, ensure_ascii=False).encode("utf-8")) > MAX_METADATA_BYTES:
        raise LifecycleContractError("metadata byte limit exceeded")
    return result


class BranchMemoLifecycleSink:
    """Single-caller, test-owned recorder with deterministic per-instance IDs.

    A clock, if supplied, returns nonnegative nondecreasing integer test ticks.
    Its unit/meaning is declared by clock_id, never inferred or sampled here.
    It must not capture observed objects. Reports retain only primitive evidence.
    Runtime contract failure latches FAILED; prior evidence remains inspectable,
    and subsequent events fail. Enabled instrumentation may interrupt a factory.
    """

    __slots__ = (
        "_namespace", "_max_events", "_clock", "_clock_id", "_metadata",
        "_events", "_holders", "_owners", "_next_identity", "_last_tick", "_failed", "_busy",
    )

    def __init__(self, *, identity_namespace, max_events=64, clock=None,
                 clock_id=None, identity_metadata=None):
        self._namespace = _token(identity_namespace)
        if len(self._namespace) > 64:
            raise LifecycleContractError("identity namespace is too long")
        if type(max_events) is not int or not 1 <= max_events <= MAX_EVENTS:
            raise LifecycleContractError("invalid event bound")
        if clock is None:
            if clock_id is not None:
                raise LifecycleContractError("clock_id requires an injected clock")
        elif not callable(clock) or clock_id is None:
            raise LifecycleContractError("clock requires a callable and clock_id")
        if clock_id is not None:
            _token(clock_id)
        self._metadata = None if identity_metadata is None else _metadata_copy(identity_metadata)
        self._max_events = max_events
        self._clock = clock
        self._clock_id = clock_id
        self._events = []
        self._holders = {}
        self._owners = {}
        self._next_identity = 1
        self._last_tick = None
        self._failed = False
        self._busy = False

    def _ready(self):
        if self._busy:
            self._failed = True
            raise LifecycleContractError("reentrant instrumentation is forbidden")
        if self._failed:
            raise LifecycleContractError("instrumentation previously failed")

    def _event(self, event, holder_id, owner_id, factory_role, slot_count):
        if len(self._events) >= self._max_events:
            raise LifecycleContractError("event capacity exceeded")
        tick = None
        if self._clock is not None:
            self._busy = True
            try:
                tick = self._clock()
            except Exception as exc:
                raise LifecycleContractError("injected clock failed") from exc
            finally:
                self._busy = False
            self._ready()
            if type(tick) is not int or tick < 0 or tick.bit_length() > 64:
                raise LifecycleContractError("clock tick must be a bounded nonnegative integer")
            if self._last_tick is not None and tick < self._last_tick:
                raise LifecycleContractError("clock ticks decreased")
        return {
            "sequence": len(self._events) + 1,
            "event": event,
            "holder_id": holder_id,
            "owner_id": owner_id,
            "factory_role": factory_role,
            "slot_count": slot_count,
            "clock_tick": tick,
        }

    def holder_created(self, *, factory_role, slot_count, holder_id=None, owner_id=None):
        """Called immediately AFTER allocation; accepts primitive declarations only."""
        self._ready()
        try:
            if type(factory_role) is not str or factory_role not in ("normal", "bypass_off"):
                raise LifecycleContractError("unknown factory role")
            if type(slot_count) is not int or slot_count < 0 or slot_count.bit_length() > 64:
                raise LifecycleContractError("slot_count must be a bounded nonnegative integer")
            if (holder_id is None) != (owner_id is None):
                raise LifecycleContractError("explicit holder and owner IDs must be paired")
            if holder_id is None:
                holder_id = self._namespace + ":holder:" + str(self._next_identity)
                owner_id = self._namespace + ":owner:" + str(self._next_identity)
            _token(holder_id)
            _token(owner_id)
            if holder_id == owner_id or holder_id in self._holders or owner_id in self._owners:
                raise LifecycleContractError("duplicate or ambiguous identity")
            if holder_id in self._owners or owner_id in self._holders:
                raise LifecycleContractError("identity used in another role")
            record = self._event("CREATE", holder_id, owner_id, factory_role, slot_count)
            self._events.append(record)
            self._holders[holder_id] = {
                "owner_id": owner_id, "factory_role": factory_role,
                "slot_count": slot_count, "owner_return_observed": False,
            }
            self._owners[owner_id] = holder_id
            self._next_identity += 1
            self._last_tick = record["clock_tick"]
            return holder_id, owner_id
        except LifecycleContractError:
            self._failed = True
            raise

    def owner_returned(self, holder_id, owner_id):
        """Confirm a built model at the return boundary; never an owner disposal."""
        self._ready()
        try:
            _token(holder_id)
            _token(owner_id)
            holder = self._holders.get(holder_id)
            if holder is None or holder["owner_id"] != owner_id:
                raise LifecycleContractError("unknown or mismatched owner token")
            if holder["owner_return_observed"]:
                raise LifecycleContractError("duplicate owner return")
            record = self._event("OWNER_RETURN", holder_id, owner_id,
                                 holder["factory_role"], holder["slot_count"])
            self._events.append(record)
            holder["owner_return_observed"] = True
            self._last_tick = record["clock_tick"]
        except LifecycleContractError:
            self._failed = True
            raise

    def holder_released(self, holder_id):
        self._failed = True
        raise LifecycleContractError("holder release protocol is not validated")

    def owner_terminated(self, owner_id, *, witness=None):
        self._failed = True
        raise LifecycleContractError("owner termination protocol is not validated")

    def report(self):
        """Independent JSON evidence, even following an instrumentation failure."""
        result = {
            "identity_namespace": self._namespace,
            "identity_provenance": "TEST_SUPPLIED_UNAUTHENTICATED",
            "clock_id": self._clock_id,
            "clock_provenance": (
                "NOT_SUPPLIED" if self._clock is None else "TEST_SUPPLIED_UNAUTHENTICATED"
            ),
            "instrumentation_status": "FAILED" if self._failed else "ACTIVE",
            "coverage_status": "UNRESOLVED",
            "model_owner_provenance": "INCOMPLETE",
            "holder_release": "NOT_OBSERVED",
            "owner_termination": "NOT_OBSERVED",
            "production_memory_qualification": "INCONCLUSIVE",
            "production_chronological_peak": "NOT_OBSERVED",
            "events": self._events,
            "holders": [dict(holder, holder_id=key, coverage_status="UNRESOLVED")
                        for key, holder in self._holders.items()],
        }
        if self._metadata is not None:
            result["declared_identity_metadata"] = self._metadata
        return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))


def validate_lifecycle_sink(sink):
    """Reject duck typing/subclasses before scientific work in enabled mode."""
    if type(sink) is not BranchMemoLifecycleSink:
        raise LifecycleContractError("sink must be an exact BranchMemoLifecycleSink")
    sink._ready()
