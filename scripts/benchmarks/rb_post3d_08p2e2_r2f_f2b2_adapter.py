"""Pure, bounded adapter for explicitly injected artificial observations.

Public API: adapt(provider_input: JSON object) -> sealed JSON object.
SCHEMA versions both the provider and result contract. See the companion document
for every required field. No discovery, instruments, clock calls or entry point.
The original provider object is copied into evidence, including failed captures
and withheld ownership events. SHA-256 establishes content integrity only.
"""

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2a_observer as observer


SCHEMA = "rawibumi.fake-observation-adapter.f2b2.v1"
MAX_EVENTS = 4096
MAX_READINGS_PER_FRAME = 256
MAX_SOURCES = 512
MAX_DEPTH = 32
MAX_NODES = 200000
MAX_TEXT_BYTES = 262144
MAX_TOTAL_TEXT_BYTES = 8388608
MAX_INTEGER_BITS = 256
ENVELOPE = {
    "production_memory_qualification": "INCONCLUSIVE",
    "production_chronological_peak": "NOT_OBSERVED",
    "input_kind": "FAKE_INPUT_ONLY",
}
RELEASE_BASES = ("explicit_owner_disposal", "explicit_ownership_transfer")


class _Failure(ValueError):
    def __init__(self, code, outcome="INVALID_EVIDENCE"):
        super().__init__(code)
        self.code = code
        self.outcome = outcome


def _need(condition, code="ADAPTER_SCHEMA_INVALID"):
    if not condition:
        raise _Failure(code)


def _copy(value):
    """Reject coercions, cycles, surrogates and unbounded input before mapping."""
    budget = [0, 0]
    active = set()

    def string(text):
        _need(len(text) <= MAX_TEXT_BYTES, "ADAPTER_CAP_EXCEEDED")
        size = len(text.encode("utf-8"))
        _need(size <= MAX_TEXT_BYTES, "ADAPTER_CAP_EXCEEDED")
        budget[1] += size
        _need(budget[1] <= MAX_TOTAL_TEXT_BYTES, "ADAPTER_CAP_EXCEEDED")
        return text

    def visit(item, depth):
        budget[0] += 1
        _need(depth <= MAX_DEPTH and budget[0] <= MAX_NODES,
              "ADAPTER_CAP_EXCEEDED")
        kind = type(item)
        if kind in (dict, list):
            _need(id(item) not in active, "ADAPTER_NON_JSON")
            # Check size before allocating a copy or traversing wide containers.
            _need(len(item) <= MAX_NODES - budget[0], "ADAPTER_CAP_EXCEEDED")
            active.add(id(item))
            if kind is dict:
                result = {}
                for key, child in item.items():
                    _need(type(key) is str, "ADAPTER_NON_JSON")
                    result[string(key)] = visit(child, depth + 1)
            else:
                result = [visit(child, depth + 1) for child in item]
            active.remove(id(item))
            return result
        if kind is str:
            return string(item)
        if kind is int:
            _need(item.bit_length() <= MAX_INTEGER_BITS, "ADAPTER_CAP_EXCEEDED")
            return item
        _need(item is None or kind in (bool, float), "ADAPTER_NON_JSON")
        if kind is float:
            _need(item == item and abs(item) != float("inf"), "ADAPTER_NON_JSON")
        return item

    return visit(value, 0)


def _object(value):
    _need(type(value) is dict)
    return value


def _list(value):
    _need(type(value) is list)
    return value


def _label(value):
    _need(type(value) is str and bool(value.strip()))
    return value


def _ns(value):
    _need(type(value) is int and value >= 0, "ADAPTER_TIME_INVALID")
    return value


def _window(item, frame=None):
    # Every injected capture needs an explicit envelope. Do not let F2-A's
    # process-window fallback conceal an unbounded FRAME or cgroup capture.
    start, end = item.get("read_start_ns"), item.get("read_end_ns")
    if start is None and end is None:
        raise _Failure("ALIGNMENT_NOT_ESTABLISHED", "INCONCLUSIVE")
    _need(_ns(start) <= _ns(end), "INVALID_READ_WINDOW")
    if frame is not None and frame.get("read_start_ns") is not None:
        _need(frame["read_start_ns"] <= start <= end <= frame["read_end_ns"],
              "INVALID_READ_WINDOW")


def _map(provider):
    _object(provider)
    _need(provider["schema"] == SCHEMA)
    _need(provider["input_kind"] == "FAKE_INPUT_ONLY")
    clock = _object(provider["clock"])
    _need(clock["kind"] == "monotonic" and clock["unit"] == "ns",
          "ADAPTER_CLOCK_INVALID")
    domain = _label(clock["domain_id"])
    sources = _list(provider["sources"])
    _need(len(sources) <= MAX_SOURCES, "ADAPTER_CAP_EXCEEDED")
    registry = {}
    for source in sources:
        _object(source)
        key = _label(source["source_id"])
        _need(key not in registry)
        _need(source["clock_id"] == domain, "ADAPTER_CLOCK_INVALID")
        _need(source["kind"] in ("fake_events", "fake_proc", "fake_cgroup"))
        _object(source["metadata"])
        registry[key] = source

    def provenance(item, kind):
        _object(item)
        _need(item["clock_id"] == domain, "ADAPTER_CLOCK_INVALID")
        _need(item["source_id"] in registry, "ADAPTER_SOURCE_INVALID")
        _need(registry[item["source_id"]]["kind"] == kind, "ADAPTER_SOURCE_INVALID")
        _object(item["metadata"])

    capture_last = [-1]
    capture_end = [-1]

    def capture(item, kind, frame):
        provenance(item, kind)
        seq = _ns(item["capture_sequence"])
        _need(seq > capture_last[0], "OUT_OF_ORDER")
        if seq != capture_last[0] + 1:
            raise _Failure("SEQUENCE_GAP", "INCONCLUSIVE")
        capture_last[0] = seq
        _window(item, frame)
        _need(item["read_end_ns"] >= capture_end[0], "OUT_OF_ORDER")
        capture_end[0] = item["read_end_ns"]

    config = _object(provider["configuration"])
    topology = _object(config["topology"])
    mode = topology["execution_mode"]
    _need(mode in ("inline", "spawned"))
    workers = _list(topology["workers"])
    _need(mode != "inline" or not workers, "ADAPTER_INLINE_WORKER")
    roster = {observer.identity_key(value) for value in _list(topology["parents"])}
    roster.update(observer.identity_key(_object(worker)["identity"]) for worker in workers)

    events = _list(provider["events"])
    _need(len(events) <= MAX_EVENTS, "ADAPTER_CAP_EXCEEDED")
    # Validate identities across ALL captures before a missing window or a
    # capture-sequence gap can return an inconclusive diagnostic. In particular,
    # withholding a failed read must never erase invalid or duplicate metadata.
    for event in events:
        _object(event)
        if event.get("kind") != "FRAME":
            continue
        readings = _list(event["readings"])
        _need(len(readings) <= MAX_READINGS_PER_FRAME, "ADAPTER_CAP_EXCEEDED")
        seen, expected = set(), None
        for reading in readings:
            _object(reading)
            try:
                key = observer.identity_key(reading.get("identity"))
            except observer.EvidenceError as exc:
                raise _Failure("ADAPTER_CAPTURE_IDENTITY_INVALID") from exc
            _need(key not in seen, "ADAPTER_DUPLICATE_CAPTURE_IDENTITY")
            seen.add(key)
            if "read_failure" in reading:
                _need(key in roster, "ADAPTER_FAILED_CAPTURE_NOT_ROSTERED")
                if expected is None:
                    try:
                        identities = [observer.identity_key(value)
                                      for value in _list(event["expected_live"])]
                    except (KeyError, observer.EvidenceError) as exc:
                        raise _Failure("ADAPTER_EXPECTED_LIVE_INVALID") from exc
                    expected = set(identities)
                    _need(len(expected) == len(identities), "ADAPTER_EXPECTED_LIVE_INVALID")
                _need(key in expected, "ADAPTER_FAILED_CAPTURE_NOT_EXPECTED")
        # Successful-only expected_live/lifecycle contradictions stay with
        # F2-A, including its distinct late-START classifications.

    records, withheld, affected = [], [], set()
    previous_time, previous_seq = -1, -1
    for event in events:
        provenance(event, "fake_events")
        now, seq = _ns(event["time_ns"]), _ns(event["sequence"])
        _need(now >= previous_time and seq > previous_seq, "OUT_OF_ORDER")
        previous_time, previous_seq = now, seq
        kind = event["kind"]
        _need(kind in ("START", "PHASE", "CREATE", "RELEASE", "FRAME", "EXIT"))
        # Preserve fields and sequences verbatim, never sort or renumber events.
        record = dict(event)
        if kind == "START":
            _need(mode != "inline" or event["role"] != "worker", "ADAPTER_INLINE_WORKER")
        if kind == "CREATE":
            _need(event.get("initialization_succeeded") is True, "ADAPTER_CREATE_UNCONFIRMED")
            _need(type(event.get("slots")) is int and event["slots"] >= 0,
                  "ADAPTER_CREATE_SLOTS_INVALID")
        if kind == "RELEASE":
            termination = event.get("ownership_termination")
            termination = {} if termination is None else _object(termination)
            justified = (termination.get("explicit") is True
                         and termination.get("basis") in RELEASE_BASES
                         and type(termination.get("evidence_id")) is str
                         and bool(termination["evidence_id"].strip()))
            if not justified:
                owner = observer.identity_key(event["identity"])
                _need(owner in roster, "ADAPTER_RELEASE_OWNER_UNKNOWN")
                observer.phase(event["phase"])
                observer.label(event["holder_id"], "holder_id")
                observer.integer(event["slots"], "slots")
                affected.add(owner)
                withheld.append({"sequence": seq, "code": "ADAPTER_RELEASE_UNJUSTIFIED"})
                continue
        if kind == "FRAME":
            _window(event)
            readings = event["readings"]
            record["readings"] = []
            for reading in readings:
                capture(reading, "fake_proc", event)
                if "read_failure" in reading:
                    _label(reading["read_failure"])
                    # Identity was checked independently, before any windows.
                    # The entire failed bundle stays in provider_input, while
                    # expected_live is untouched for F2-A's missing-read checks.
                    continue
                # A proc capture bundles supplied text files. Each successful
                # file has explicit bounds within that bundle; no raw string
                # is parsed or repaired by the adapter.
                files = _object(reading["file_read_bounds"])
                for name in ("status", "stat", "smaps_rollup"):
                    if type(reading.get(name)) is str:
                        bounds = _object(files[name])
                        _need(bounds.get("read_start_ns") is not None
                              and bounds.get("read_end_ns") is not None,
                              "INVALID_READ_WINDOW")
                        _window(bounds, reading)
                        _need(bounds["read_end_ns"] <= now, "INVALID_READ_WINDOW")
                record["readings"].append(reading)
            cgroup = event.get("cgroup")
            if cgroup is not None:
                capture(cgroup, "fake_cgroup", event)
                _ns(cgroup["time_ns"])
                if cgroup.get("read_end_ns") is not None:
                    _need(cgroup["read_end_ns"] <= cgroup["time_ns"] <= now,
                          "INVALID_READ_WINDOW")
                if "read_failure" in cgroup:
                    _label(cgroup["read_failure"])
                    record["cgroup"] = None
        records.append(_copy(record))

    coverage = []
    for declaration in _list(provider["holder_coverage"]):
        item = dict(_object(declaration))
        _need(type(item["events_complete"]) is bool)
        if observer.identity_key(item["identity"]) in affected:
            # Conservatively invalidate this owner's supplied coverage. Missing
            # declarations remain missing; none are synthesized.
            item["events_complete"] = False
        coverage.append(item)
    evidence = {key: provider[key] for key in (
        "input_id", "workload_id", "independent_run_id", "conditions",
        "declared_record_count", "declared_frame_count", "truncated")}
    evidence.update(records=records, holder_coverage=coverage,
                    provider_input=provider, withheld_events=withheld)
    return config, evidence


def _diagnostic(code, outcome, provider=None):
    return observer.seal({
        "schema": SCHEMA + ".result", **ENVELOPE,
        "outcome": outcome, "adapter_status": "ADAPTER_DIAGNOSTIC",
        "reasons": [{"code": code, "outcome": outcome}],
        "provider_input": provider, "configuration": None, "evidence": None,
        "observer_report": None,
    })


def adapt(provider_input):
    """Copy, validate and map explicit fake events to frozen F2-A reconciliation.

    Returns a sealed result with configuration, evidence and observer_report;
    adapter failures have those fields null and fixed reason codes. JSON-safe,
    bounded provider input is retained even on schema failures. Unsafe input and
    exception text are never echoed. No caller data is mutated. Comparisons must
    use F2-B1 compare_verified_reports on the embedded observer_report objects.
    """
    provider = None
    try:
        provider = _copy(provider_input)
        config, evidence = _map(provider)
        try:
            report = observer.reconcile(config, evidence)
        except Exception as exc:
            raise _Failure("ADAPTER_RECONCILIATION_FAILED") from exc
        topology = config["topology"]
        if (topology["execution_mode"] == "spawned" and not topology["workers"]
                and report["outcome"] != observer.INVALID):
            # An empty declared roster supplies no observed spawned workers.
            # Retain any stricter F2-A invalidity (e.g. an unrostered START).
            raise _Failure("ADAPTER_SPAWNED_WORKERS_UNOBSERVED", "INCONCLUSIVE")
        return observer.seal({
            "schema": SCHEMA + ".result", **ENVELOPE,
            "outcome": report["outcome"], "adapter_status": "MAPPED_FAKE_INPUT",
            "reasons": report["reasons"], "configuration": config,
            "evidence": evidence, "observer_report": report,
        })
    except _Failure as exc:
        return _diagnostic(exc.code, exc.outcome, provider)
    except observer.EvidenceError as exc:
        return _diagnostic(exc.code, exc.outcome, provider)
    except (KeyError, TypeError, IndexError):
        return _diagnostic("ADAPTER_SCHEMA_INVALID", "INVALID_EVIDENCE", provider)
    except Exception:
        # Covers bad Unicode, recursion and any unforeseen F2-A failure without
        # exposing payload text or allowing a partially derived report through.
        return _diagnostic("ADAPTER_NON_JSON", "INVALID_EVIDENCE", provider)
