"""Bounded assembly of supplied bytes and facts; never acquisition or authentication.

Only successful read digest/count placeholders may be filled. Verification
summaries are caller assertions and are never repaired. See the companion
document for the exact input grammar, custody API and accounting formula.
"""

from dataclasses import dataclass, field
import hashlib
import json
import re

from scripts.benchmarks import rb_post3d_08p2e2_r2f_f2b4_native_semantic_correlation as semantic

integration = semantic.integration
SCHEMA = "rawibumi.native-evidence-assembly.f2b4.d2b2b3b4.v1"
MAX_READ_BYTES = 65536
MAX_PAYLOAD_BYTES = 8388608
MAX_REPORT_BYTES = 8388608
MAX_READS = 2 * 32 * 64 * 3
READ_ENTRY_OVERHEAD = 64
REPORT_ENTRY_OVERHEAD = 64
INVALID_CODES = semantic.INVALID_CODES + (
    "RAW_READ_UNEXPECTED", "RAW_CLAIM_CONFLICT", "FAILED_READ_BYTES",
    "UPSTREAM_BINDING_CONFLICT", "DUPLICATE_REPORT", "DUPLICATE_FRAME",
    "PREDECESSOR_REPORT_CONFLICT",
)
INCOMPLETE_CODES = semantic.INCOMPLETE_CODES + (
    "RAW_READ_MISSING", "SEMANTIC_NOT_CORRELATED", "SEMANTIC_NOT_EVALUATED",
)


@dataclass(frozen=True)
class ByteEvidence:
    """Immutable admitted exact bytes. Keys contain symbolic identifiers only."""

    key: tuple
    sha256: str
    payload: bytes = field(repr=False)

    @property
    def byte_count(self):
        return len(self.payload)

    def exact_bytes(self):
        integration._need(type(self.payload) is bytes and
                          hashlib.sha256(self.payload).hexdigest() == self.sha256, "DIGEST_INVALID")
        return self.payload  # Exact bytes are immutable, so sharing is safe.


@dataclass(frozen=True)
class ByteCustody:
    """Tuple indexes and frozen records; no filesystem or authenticity claim."""

    reads: tuple = field(default=(), repr=False)
    upstream_reports: tuple = field(default=(), repr=False)

    @property
    def read_keys(self):
        return tuple(record.key for record in self.reads)

    @property
    def upstream_keys(self):
        return tuple(record.key for record in self.upstream_reports)

    def read_bytes(self, route_index, frame_index, pid, path_id):
        key = (route_index, frame_index, pid, path_id)
        for record in self.reads:
            if record.key == key:
                return record.exact_bytes()
        raise KeyError(key)

    def upstream_bytes(self, route_index, kind):
        for record in self.upstream_reports:
            if record.key == (route_index, kind):
                return record.exact_bytes()
        raise KeyError((route_index, kind))


@dataclass(frozen=True)
class AssemblyReport:
    serialized: str = field(repr=False)
    custody: ByteCustody = field(repr=False)
    _request_serialized: str | None = field(default=None, repr=False)

    def to_dict(self):
        return json.loads(self.serialized)

    def to_request(self):
        """Detached supplied request, or None when binding was not possible."""
        return None if self._request_serialized is None else json.loads(self._request_serialized)

    @property
    def sha256(self):
        return hashlib.sha256(self.serialized.encode("utf-8")).hexdigest()


def _no_aliases(value, seen):
    """Check original containers before copying, with bounded traversal."""
    nodes = 0

    def visit(item, depth):
        nonlocal nodes
        nodes += 1
        integration._need(nodes <= integration.MAX_NODES and depth <= integration.MAX_DEPTH,
                          "INPUT_CAP_EXCEEDED")
        kind = type(item)
        if kind in (dict, list):
            integration._need(id(item) not in seen, "INPUT_ALIAS")
            integration._need(len(item) <= integration.MAX_NODES - nodes, "INPUT_CAP_EXCEEDED")
            seen.add(id(item))
            if kind is dict:
                for key, child in item.items():
                    integration._need(type(key) is str, "INPUT_NOT_JSON")
                    visit(key, depth + 1)
                    visit(child, depth + 1)
            else:
                for child in item:
                    visit(child, depth + 1)
        elif kind is str:
            integration._need(len(item) <= integration.MAX_STRING, "INPUT_CAP_EXCEEDED")
        else:
            integration._need(kind in (bytes, int, bool, type(None)), "INPUT_NOT_JSON")

    visit(value, 0)


def _read_key(route, frame, pid, path):
    integration._integer(route, 0, 1)
    integration._integer(frame, 0, 31)
    integration._integer(pid, 1, 2147483647)
    integration._need(type(path) is str and
                      re.fullmatch(r"pids/[1-9][0-9]*/(?:identity|ns_link|ns_target)", path) is not None and
                      path.split("/")[1] == str(pid), "PATH_POLICY_VIOLATION")
    return (route, frame, pid, path)


def _admit_indexes(raw_reads, upstream_reports):
    """Atomic admission under the combined raw+overhead budget."""
    integration._list(raw_reads, MAX_READS)
    integration._list(upstream_reports, 2)
    reads, reports, used, seen_routes = {}, {}, 0, set()
    for item in raw_reads:
        integration._object(item, ("route_index", "frame_index", "pid", "path_id", "payload"))
        key = _read_key(item["route_index"], item["frame_index"], item["pid"], item["path_id"])
        integration._need(key not in reads, "DUPLICATE_READ")
        raw = item["payload"]
        integration._need(type(raw) is bytes, "INPUT_NOT_JSON")
        integration._need(len(raw) <= MAX_READ_BYTES, "INPUT_CAP_EXCEEDED")
        used += len(raw) + READ_ENTRY_OVERHEAD + len(key[3].encode("ascii"))
        integration._need(used <= MAX_PAYLOAD_BYTES, "INPUT_CAP_EXCEEDED")
        reads[key] = ByteEvidence(key, hashlib.sha256(raw).hexdigest(), raw)
    for item in upstream_reports:
        integration._object(item, ("route_index", "kind", "payload"))
        route, kind, raw = item["route_index"], item["kind"], item["payload"]
        integration._integer(route, 0, 1)
        integration._need(type(kind) is str and kind in integration.VERIFIERS)
        integration._need(route not in seen_routes, "DUPLICATE_REPORT")
        seen_routes.add(route)
        integration._need(type(raw) is bytes, "INPUT_NOT_JSON")
        integration._need(len(raw) <= integration.MAX_BYTES, "INPUT_CAP_EXCEEDED")
        used += len(raw) + REPORT_ENTRY_OVERHEAD + len(kind.encode("ascii"))
        integration._need(used <= MAX_PAYLOAD_BYTES, "INPUT_CAP_EXCEEDED")
        key = (route, kind)
        reports[key] = ByteEvidence(key, hashlib.sha256(raw).hexdigest(), raw)
    return ByteCustody(tuple(reads[k] for k in sorted(reads)),
                       tuple(reports[k] for k in sorted(reports))), used


def _template_reads(data):
    """Validate the binding grammar; scientific comparisons stay in B3-B2."""
    integration._object(data, ("schema", "mode", "native_opt_in", "reference", "routes", "limits"))
    integration._need(data["mode"] == "SUPPLIED_ONLY" and data["native_opt_in"] is False,
                      "NATIVE_MODE_DENIED")
    integration._need(data["schema"] == integration.SCHEMA)
    reference = data["reference"]
    integration._object(reference, ("boot_id", "namespace", "procfs", "nsfs", "clock_kind", "roster", "window", "frame_count"))
    integration._roster(reference["roster"])
    integration._integer(reference["frame_count"], 2, 32)
    integration._list(data["routes"], 2, 2)
    indexed = {}
    for route_index, route in enumerate(data["routes"]):
        integration._object(route, ("provenance", "capture", "verification"))
        cap = route["capture"]
        integration._object(cap, ("schema", "source_state", "source_kind", "origin_attestation", "clock_kind",
                                  "boot_id", "namespace", "procfs", "nsfs", "roster", "frames"))
        integration._need(cap["schema"] == integration.CAPTURE_SCHEMA)
        integration._object(route["verification"], ("schema", "validator", "upstream_schema", "outcome", "reason_codes",
            "invalid_reason_codes", "incomplete_reason_codes", "report_sha256", "capture_sha256"))
        integration._list(cap["frames"], 32)
        frame_indices = set()
        for frame in cap["frames"]:
            integration._object(frame, ("index", "start_ns", "end_ns", "observed_pids", "processes", "read_complete", "reason_codes"))
            integration._integer(frame["index"], 0, 31)
            integration._need(frame["index"] not in frame_indices, "DUPLICATE_FRAME")
            frame_indices.add(frame["index"])
            integration._list(frame["processes"], 64)
            pids = set()
            for process in frame["processes"]:
                integration._object(process, ("identity", "descriptors", "reads"))
                integration._identity(process["identity"])
                pid = process["identity"]["pid"]
                integration._need(pid not in pids, "DUPLICATE_IDENTITY")
                pids.add(pid)
                integration._list(process["reads"], 3)
                for read in process["reads"]:
                    integration._object(read, ("path_id", "start_ns", "end_ns", "status", "sha256", "byte_count", "reason_codes"))
                    key = _read_key(route_index, frame["index"], pid, read["path_id"])
                    integration._need(key not in indexed, "DUPLICATE_READ")
                    codes = integration._codes(read["reason_codes"], integration.READ_CODES)
                    integration._need(read["status"] == ("FAILED" if codes else "OK"), "OUTCOME_CONFLICT")
                    if codes:
                        integration._need(read["sha256"] is None and type(read["byte_count"]) is int and
                                          read["byte_count"] == 0, "FAILED_READ_BYTES")
                    else:
                        integration._need((read["sha256"] is None) == (read["byte_count"] is None),
                                          "RAW_CLAIM_CONFLICT")
                        if read["sha256"] is not None:
                            integration._hash(read["sha256"])
                            integration._integer(read["byte_count"], 0, MAX_READ_BYTES)
                    indexed[key] = read
    return indexed


def _bind_reads(indexed, custody, codes):
    supplied = {record.key: record for record in custody.reads}
    for key in supplied.keys() - indexed.keys():
        codes.add("RAW_READ_UNEXPECTED")
    for key, read in indexed.items():
        record = supplied.get(key)
        if read["status"] == "FAILED":
            if record is not None:
                codes.add("FAILED_READ_BYTES")
        elif record is None:
            codes.add("RAW_READ_MISSING")
        elif read["sha256"] is None:
            read["sha256"], read["byte_count"] = record.sha256, record.byte_count
        elif (read["sha256"], read["byte_count"]) != (record.sha256, record.byte_count):
            codes.add("RAW_CLAIM_CONFLICT")


def _upstream_summary(route_index, record):
    return {"route_index": route_index, "custody": "NOT_SUPPLIED" if record is None else "EXACT_BYTES_RETAINED",
            "verification_provenance": "CALLER_ASSERTED", "source_authenticated": False,
            "summary_binding": "UNAUTHENTICATED_NOT_CHECKED", "kind": None if record is None else record.key[1],
            "raw_sha256": None if record is None else record.sha256,
            "byte_count": None if record is None else record.byte_count,
            "import_evaluation": "NOT_EVALUATED", "import_report": None, "import_report_sha256": None}


def _upstream(data, custody, codes):
    summaries = []
    supplied = {record.key[0]: record for record in custody.upstream_reports}
    for route_index, route in enumerate(data["routes"]):
        record = supplied.get(route_index)
        summary = _upstream_summary(route_index, record)
        summaries.append(summary)
        if record is None:
            continue
        kind = record.key[1]
        imported = semantic.import_upstream_report(kind, record.exact_bytes())
        report = imported.to_dict()
        summary.update(kind=kind, raw_sha256=record.sha256, byte_count=record.byte_count,
                       import_report=report, import_report_sha256=imported.sha256,
                       import_evaluation="EVALUATED", summary_binding="CONFLICT")
        codes.update(set(report["reason_codes"]) - {"UNSUPPORTED_LOSSLESS_CONVERSION"})
        try:
            original, verification = report["original"], route["verification"]
            integration._need(original is not None and report["conversion"] != "REJECTED", "UPSTREAM_INVALID")
            integration._need(verification["validator"] == kind and
                verification["report_sha256"] == record.sha256 == report["raw_input_sha256"] and
                verification["upstream_schema"] == original["original_schema"] and
                verification["outcome"] == original["original_outcome"] and
                all(verification[key] == original["original_" + key] for key in
                    ("reason_codes", "invalid_reason_codes", "incomplete_reason_codes")), "UPSTREAM_BINDING_CONFLICT")
            origin, state = original["data_origin"], route["capture"]["source_state"]
            integration._need((state == "INJECTED_TEST_ONLY" and origin in
                              ("TEST_INJECTED", "INJECTED_LOCAL_PROBE", "INJECTED_TEST_ONLY")) or
                              (state == "NATIVE_PROCFS_UNVERIFIED" and origin == state), "SOURCE_LABEL_CONFLICT")
            summary["summary_binding"] = "HASH_AND_ENVELOPE_MATCH_CALLER_ASSERTED"
        except integration._Rejected as exc:
            codes.add(exc.code)
    return summaries


def _partitions(codes):
    sealed = set(codes)
    if sealed - set(INVALID_CODES) - set(INCOMPLETE_CODES):
        sealed.add("REASON_CODE_INVALID")
    bad = sorted(sealed & set(INVALID_CODES))
    gaps = sorted(sealed & set(INCOMPLETE_CODES))
    return {"classification": "INVALID" if bad else "INCOMPLETE" if gaps else "ASSEMBLED_NONQUALIFYING",
            "reason_codes": sorted(bad + gaps), "invalid_reason_codes": bad, "incomplete_reason_codes": gaps}


def _finish(codes, custody, used, template_hash, request, upstream, predecessor, correlated):
    if not upstream:
        supplied = {record.key[0]: record for record in custody.upstream_reports}
        upstream = [_upstream_summary(index, supplied.get(index)) for index in (0, 1)]
    combined = set(codes)
    if predecessor is not None:
        combined.update(predecessor.to_dict()["reason_codes"])
    if correlated is not None:
        result = correlated.to_dict()
        combined.update(result["reason_codes"])
        classification = result["semantic"]["classification"]
        if classification != "STABLE_IDENTITY_CORRELATED":
            combined.add("SEMANTIC_NOT_CORRELATED" if classification == "NOT_CORRELATED" else "SEMANTIC_NOT_EVALUATED")
    reads = [{"route_index": r.key[0], "frame_index": r.key[1], "pid": r.key[2], "path_id": r.key[3],
              "sha256": r.sha256, "byte_count": r.byte_count} for r in custody.reads]
    routes = []
    if request is not None:
        for index, route in enumerate(request["routes"]):
            state = route["capture"]["source_state"]
            routes.append({"route_index": index, "route_sha256": integration.digest(route),
                "capture_sha256": integration.digest(route["capture"]),
                "provenance_sha256": integration.digest(route["provenance"]),
                "verification_sha256": integration.digest(route["verification"]),
                "source_state": state if type(state) is str and state in integration.ORIGINS else None,
                "verification_provenance": "CALLER_ASSERTED"})
    result = {"schema": SCHEMA + ".report", **semantic._trust(), **_partitions(combined),
        "assembly": _partitions(codes), "template_sha256": template_hash,
        "request_sha256": None if request is None else integration.digest(request), "routes": routes,
        "custody": "IMMUTABLE_IN_MEMORY_SUPPLIED_BYTES_ONLY", "source_authenticity": "NOT_ESTABLISHED",
        "payload_budget_bytes": used, "read_count": len(reads), "reads": reads, "read_summary_omitted": False,
        "upstream_reports": upstream, "integration_evaluation": "NOT_EVALUATED" if predecessor is None else "EVALUATED",
        "integration_report": None if predecessor is None else predecessor.to_dict(),
        "integration_report_sha256": None if predecessor is None else predecessor.sha256,
        "semantic_evaluation": "NOT_EVALUATED" if correlated is None else "EVALUATED",
        "semantic_report": None if correlated is None else correlated.to_dict(),
        "semantic_report_sha256": None if correlated is None else correlated.sha256}
    serialized = integration.canonical_json(result)
    if len(serialized.encode("utf-8")) > MAX_REPORT_BYTES:
        codes.add("INPUT_CAP_EXCEEDED")
        result.update(_partitions(combined | {"INPUT_CAP_EXCEEDED"}))
        result.update(assembly=_partitions(codes), reads=[], read_summary_omitted=True)
        serialized = integration.canonical_json(result)
    return AssemblyReport(serialized, custody, None if request is None else integration.canonical_json(request))


def assemble_supplied_evidence(template, raw_reads, upstream_reports=None):
    """Assemble exact finite lists of supplied byte records; perform no I/O.

    template is an exact JSON dict tree or strict JSON bytes. Index grammars:
    raw_reads: list[{route_index, frame_index, pid, path_id, payload: bytes}]
    upstream_reports: list[{route_index, kind, payload: bytes}], or None.
    Rejected admission retains no partial index; admitted bytes remain in
    custody even when subsequent binding or predecessor validation fails.
    """
    codes, custody, used, template_hash = set(), ByteCustody(), 0, None
    request, predecessor, correlated, upstream = None, None, None, []
    try:
        seen = set()
        _no_aliases(template, seen)
        _no_aliases(raw_reads, seen)
        if upstream_reports is not None:
            _no_aliases(upstream_reports, seen)
        data = integration._decode(template)
        template_hash = integration.digest(data)
        custody, used = _admit_indexes(raw_reads, [] if upstream_reports is None else upstream_reports)
        indexed = _template_reads(data)
        _bind_reads(indexed, custody, codes)
        upstream = _upstream(data, custody, codes)
        if not (codes & {"RAW_READ_MISSING", "RAW_READ_UNEXPECTED", "RAW_CLAIM_CONFLICT", "FAILED_READ_BYTES"}):
            # Reapply predecessor budgets after filling placeholders. Each API
            # gets an independently detached request and no callbacks.
            request = integration._copy(data)
            predecessor = integration.integrate_native_evidence(integration._copy(request), callbacks=())
            correlated = semantic.correlate_native_semantics(integration._copy(request), callbacks=())
            original = correlated.to_dict()
            integration._need(original["predecessor_report_embedded"] == predecessor.to_dict() and
                              original["predecessor_report_sha256"] == predecessor.sha256,
                              "PREDECESSOR_REPORT_CONFLICT")
    except integration._Rejected as exc:
        codes.add(exc.code)
    return _finish(codes, custody, used, template_hash, request, upstream, predecessor, correlated)
