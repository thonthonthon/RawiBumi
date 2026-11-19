"""Global immutable PAN/OND revisions; parsing and engineering rules stay canonical."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from threading import RLock
import unicodedata
from typing import Any, Annotated

from pydantic import BaseModel, ConfigDict, Field, StrictStr, ValidationError
from components.source_overlay import ComponentSourceFragment, build_candidate_from_fragments
from components.validation import validate_inverter

from components.candidates import build_inverter_candidate, build_module_candidate
from components.ond import map_ond, parse_ond_text
from components.pan import map_pan, parse_pan_text
from validation.engineering.electrical import inverter_design_capability_issues
from .execution_readiness import phase5_inverter_definition_readiness, phase5_module_definition_readiness
from .safe_paths import PATTERNS, safe_component, contained

MAX_IMPORT_BYTES = 2 * 1024 * 1024
IMPORTER_VERSION = 8
_LOCK = RLock()
_LEGACY_MESSAGE = "This file is in the old binary PVsyst format. Export it again from PVsyst 6 or later as a text file."
_SAFE_REVISION = re.compile(PATTERNS["library_revision"])


class ComponentLibraryError(ValueError):
    def __init__(self, message: str, code: str, *, status: int = 422, findings=None):
        super().__init__(message)
        self.status = status
        self.detail = {"message": message, "code": code}
        if findings is not None:
            self.detail["findings"] = findings


def definition_readiness(kind: str, definition: dict[str, Any]) -> dict[str, Any]:
    """Use shared project predicates, never reimplement capability gating."""
    if kind == "modules":
        return phase5_module_definition_readiness(definition)
    design = inverter_design_capability_issues(definition)
    phase5 = phase5_inverter_definition_readiness(definition)
    findings = [{**issue, "entity_id": definition["revision_id"]} for issue in design]
    findings.extend(phase5["findings"])
    return {"ready": phase5["ready"] and not any(issue["classification"] == "INVALID" for issue in design),
            "findings": findings}


def preview_parameters(kind: str, definition: dict[str, Any]) -> dict[str, Any]:
    if kind == "modules":
        stc = definition.get("stc") or {}
        mechanical = definition.get("mechanical") or {}
        coefficients = definition.get("temperature_coefficients") or {}
        basis = coefficients.get("coefficient_basis")
        gamma = coefficients.get("gamma_pmp_per_c")
        relative = None
        if gamma is not None:
            if basis == "absolute" and stc.get("pmp_w") and stc["pmp_w"] > 0:
                relative = 100 * gamma / stc["pmp_w"]
            elif basis == "relative":
                relative = 100 * gamma
        return {**{key: stc.get(key) for key in ("pmp_w", "voc_v", "isc_a", "vmp_v", "imp_a")},
                **{key: mechanical.get(key) for key in ("width_m", "height_m")},
                "cell_count": (definition.get("cell_architecture") or {}).get("physical_cell_count"),
                "gamma_pmp_pct_per_c": relative,
                "mu_voc_v_per_c": coefficients.get("beta_voc_per_c") if basis == "absolute" else None,
                "technology": definition.get("technology")}
    template = definition.get("mppt_template") or {}
    dc = definition.get("dc_limits") or {}
    metrics = (definition.get("efficiency_model") or {}).get("reference_metrics") or {}
    metric = "european" if metrics.get("european_efficiency_fraction") is not None else (
        "maximum" if metrics.get("max_efficiency_fraction") is not None else None)
    efficiency = metrics.get("european_efficiency_fraction" if metric == "european" else "max_efficiency_fraction") if metric else None
    return {"nominal_ac_power_w": (definition.get("ac_limits") or {}).get("nominal_ac_power_w"),
            "max_dc_power_w": dc.get("max_dc_power_w"),
            "mppt_count": len(definition["mppts"]) if definition.get("mppts") else template.get("count"),
            "mppt_v_min": template.get("min_operating_voltage_v"), "mppt_v_max": template.get("max_operating_voltage_v"),
            "max_dc_voltage_v": dc.get("max_dc_voltage_v"), "max_input_current_a": dc.get("max_dc_current_a"),
            "mppt_max_operating_current_a": template.get("max_operating_current_a"),
            "efficiency_fraction": efficiency, "efficiency_metric": metric}


def _reasons(definition, readiness):
    reasons = []
    missing_current = (definition.get("mppt_template") or {}).get("max_operating_current_a") is None
    causes = [f["rule_id"] for f in validate_inverter(definition)
              if f["severity"] in {"error", "blocking_error"}] if definition.get("schema_name") == "InverterDefinition" else []
    for finding in readiness["findings"]:
        rule = finding["rule_id"]
        if rule == "INVERTER_BASIC_DESIGN_READY_FALSE":
            if missing_current and not causes:
                reasons.append({"code": "basic_design_incomplete_due_to_mppt", "message":
                    "Electrical design is incomplete because maximum operating current per MPPT is not in the file."})
            else:
                ids = causes or [f["rule_id"] for f in readiness["findings"]]
                reasons.append({"code": "basic_design_not_ready", "rule_ids": ids, "message":
                    "Electrical design capability is not ready: " + ", ".join(ids) + "."})
        elif rule == "INVERTER_MPPT_DESIGN_READY_FALSE" and missing_current:
            reasons.append({"code": "mppt_operating_current_missing", "message":
                "MPPT design data is incomplete: maximum operating current per MPPT is not in the file."})
        else:
            code = ("efficiency_curve_unavailable" if rule == "EXECUTION_INVERTER_EFFICIENCY_NOT_READY"
                    else "module_sdm_not_ready" if rule == "EXECUTION_MODULE_SDM_NOT_READY" else "finding")
            reasons.append({"code": code, "message": finding["message"], "rule_id": rule})
    return reasons


COMPLETION_LIMITS = {
    "mppt_template.max_operating_current_a": (200, "A"),
    "mppt_template.max_short_circuit_current_a": (300, "A"),
    "ac_limits.nominal_frequency_hz": (60, "Hz"),
    "dc_limits.max_dc_current_a": (5000, "A"),
}


class CompletionSource(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    document: Annotated[StrictStr, Field(min_length=1, max_length=200)]
    page_or_section: Annotated[StrictStr, Field(min_length=1, max_length=100)]
    url: StrictStr | None = None


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fields: dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False)]]
    source: CompletionSource
    dry_run: Annotated[bool, Field(strict=True)] = False


def completion_request(payload):
    try:
        request = CompletionRequest.model_validate(payload)
    except ValidationError as exc:
        source_errors = [e for e in exc.errors() if e["loc"] and e["loc"][0] == "source"]
        code = "completion_source_required" if source_errors else "completion_invalid"
        message = ("A datasheet document and page or section are required." if source_errors
                   else "Completion requires finite numeric values and no extra fields.")
        raise ComponentLibraryError(message, code) from exc
    if not request.fields:
        raise ComponentLibraryError("Enter at least one missing datasheet value.", "completion_invalid")
    if request.source.url:
        from urllib.parse import urlsplit
        try:
            parsed = urlsplit(request.source.url)
            valid = parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not any(c.isspace() for c in request.source.url)
        except ValueError:
            valid = False
        if not valid:
            raise ComponentLibraryError("The citation URL must be an http(s) URL.", "completion_invalid")
    return request


def _missing_completion_fields(kind, definition):
    if kind != "inverters":
        return []
    return [{"path": path, "unit": unit, "max": maximum}
            for path, (maximum, unit) in COMPLETION_LIMITS.items()
            if (definition.get(path.split('.')[0]) or {}).get(path.split('.')[1]) is None]


def _decode(data: bytes) -> tuple[str, str]:
    if data.startswith(b"pvModule;"):
        raise ComponentLibraryError(_LEGACY_MESSAGE, "legacy_binary_pan_unsupported")
    header = b"PVObject_" in data[:4096]
    try:
        text = data.decode("utf-8-sig")
        encoding = "utf-8"
    except UnicodeDecodeError:
        if not header:
            raise ComponentLibraryError(_LEGACY_MESSAGE, "legacy_binary_pan_unsupported") from None
        try:
            text = data.decode("cp1252")
            encoding = "cp1252"
        except UnicodeDecodeError as exc:
            raise ComponentLibraryError("The component text could not be decoded.", "component_parse_failed") from exc
    if not header and any(ord(char) < 32 and char not in "\t\r\n" for char in text):
        raise ComponentLibraryError(_LEGACY_MESSAGE, "legacy_binary_pan_unsupported")
    return text, encoding


class ComponentLibraryStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self._lock = _LOCK

    def entries(self, *, include_hidden=False):
        with self._lock:
            entries = []
            for kind in ("modules", "inverters"):
                directory = contained(self.root, self.root / kind)
                for path in sorted(directory.glob("*.json")):
                    safe_component(path.stem, "component")
                    entry = json.loads(contained(directory, path).read_text(encoding="utf-8"))
                    safe_component(entry["kind"], "collection")
                    safe_component(entry["definition"]["revision_id"], "component")
                    safe_component(entry["library"]["definition_id"], "component")
                    safe_component(entry["library"]["source_sha256"], "hash")
                    entries.append(entry)
            return [entry for entry in entries if include_hidden or not entry["library"]["hidden"]]

    @staticmethod
    def preview(entry, *, duplicate_of=None):
        definition, metadata = entry["definition"], entry["library"]
        readiness = definition_readiness(entry["kind"], definition)
        return {"kind": entry["kind"], "manufacturer": definition.get("manufacturer"), "model": definition.get("model"),
                "revision_id": definition["revision_id"], "duplicate_of": duplicate_of,
                "parameters": preview_parameters(entry["kind"], definition), "findings": deepcopy(metadata["findings"]),
                "schema_ready": metadata["schema_ready"], "simulation_ready": readiness["ready"],
                "readiness_findings": readiness["findings"], "reasons": _reasons(definition, readiness),
                "remapped_from": metadata.get("remapped_from"),
                "completion_fields": _missing_completion_fields(entry["kind"], definition),
                "completed_from": metadata.get("completed_from"),
                "completed_fields": [{"path": path, "value": value, "unit": COMPLETION_LIMITS[path][1],
                    "source": metadata["completion"]["source"]}
                    for path, value in metadata.get("completion", {}).get("fields", {}).items()]}

    def view_entries(self, *, include_hidden=False):
        entries = self.entries(include_hidden=include_hidden)
        for entry in entries:
            # Readiness is a view of the current shared rules; the stored revision is immutable.
            entry["library"]["readiness"] = definition_readiness(entry["kind"], entry["definition"])
            entry["completion_preview"] = self.preview(entry)
        return entries

    @staticmethod
    def _atomic(path: Path, data: bytes):
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".import-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def import_bytes(self, filename: str, data: bytes, *, dry_run=False):
        filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
        extension = Path(filename).suffix.lower()
        if extension not in (".pan", ".ond"):
            raise ComponentLibraryError("Choose a .pan module or .ond inverter file.", "unsupported_component_format")
        if len(data) > MAX_IMPORT_BYTES:
            raise ComponentLibraryError("Component files must be no larger than 2 MiB.", "component_file_too_large", status=413)
        if not data:
            raise ComponentLibraryError("The file is empty. Copy it again from its source.", "component_file_empty")
        kind = "modules" if extension == ".pan" else "inverters"
        digest = hashlib.sha256(data).hexdigest()
        with self._lock:
            entries = self.entries(include_hidden=True)
            same_source = [e for e in entries if e["kind"] == kind and e["library"]["source_sha256"] == digest
                           and not e["library"].get("completed_from")]
            duplicate = next((e for e in same_source if e["library"].get("importer_version", 1) == IMPORTER_VERSION), None)
            if duplicate:
                return {"entry": self.preview(duplicate, duplicate_of=duplicate["definition"]["revision_id"]), "created": False}
            previous = max(
                (e for e in same_source if e["library"].get("importer_version", 1) < IMPORTER_VERSION),
                key=lambda e: e["library"]["revision_number"], default=None,
            )
            text, encoding = _decode(data)
            try:
                mapping = map_pan(parse_pan_text(text, encoding=encoding)) if kind == "modules" else map_ond(parse_ond_text(text, encoding=encoding))
                manufacturer = str(mapping.values_by_canonical_path.get("manufacturer") or "")
                model = str(mapping.values_by_canonical_path.get("model") or "")
                slug = unicodedata.normalize("NFKD", f"{manufacturer}-{model}").encode("ascii", "ignore").decode().lower()
                slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")[:48].rstrip("-") or "component"
                suffix = hashlib.sha256(f"{manufacturer}|{model}".encode()).hexdigest()[:6]
                definition_id = f"lib-{'mod' if kind == 'modules' else 'inv'}-{slug}-{suffix}"
                if previous:
                    assert previous["library"]["definition_id"] == definition_id, "Remapped component identity collision"
                same_identity = [e for e in entries if e["library"]["definition_id"] == definition_id]
                assert all((e["definition"].get("manufacturer"), e["definition"].get("model")) == (manufacturer, model)
                           for e in same_identity), "Component definition identity collision"
                revision_number = 1 + max((e["library"]["revision_number"] for e in entries
                                           if e["library"]["definition_id"] == definition_id), default=0)
                revision_id = f"{definition_id}-r{revision_number}"
                args = dict(candidate_id=f"candidate-{revision_id}", revision_id=revision_id, source_id=f"src-lib-sha256-{digest}")
                candidate = (build_module_candidate(mapping, module_definition_id=definition_id, **args) if kind == "modules"
                             else build_inverter_candidate(mapping, inverter_definition_id=definition_id, **args))
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                raise ComponentLibraryError(f"The component text could not be parsed: {exc}", "component_parse_failed") from exc
            entry = {"kind": kind, "definition": candidate["canonical_data"], "library": {
                "definition_id": definition_id, "revision_number": revision_number, "source_filename": filename,
                "source_sha256": digest, "source_format": extension[1:], "source_encoding": encoding,
                "importer_version": IMPORTER_VERSION,
                "imported_at": datetime.now(timezone.utc).isoformat(), "hidden": False,
                "findings": candidate["validation_findings"], "derivations": candidate["derivations"],
                "schema_ready": candidate["definition_schema_ready"],
                "readiness": definition_readiness(kind, candidate["canonical_data"])}}
            if previous:
                entry["library"]["remapped_from"] = previous["definition"]["revision_id"]
            try:
                payload = (json.dumps(entry, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
                preview = self.preview(entry)
                json.dumps(preview, allow_nan=False)
            except (ValueError, TypeError) as exc:
                raise ComponentLibraryError("The component contains a value that cannot be represented as finite JSON data.", "component_parse_failed") from exc
            if dry_run:
                return {"entry": preview, "created": False}
            if not candidate["definition_schema_ready"]:
                raise ComponentLibraryError("The file is missing required component data; review the findings.",
                                            "component_schema_incomplete", findings=candidate["validation_findings"])
            safe_component(revision_id, "library_revision")
            safe_component(digest, "hash")
            path = contained(self.root, self.root / kind / f"{revision_id}.json")
            assert not path.exists(), "Component library revision collision"
            source = contained(self.root, self.root / "sources" / "sha256" / f"{digest}{extension}")
            if source.exists():
                assert source.read_bytes() == data, "Component source hash collision"
            else:
                self._atomic(source, data)
            self._atomic(path, payload)
            if previous:
                try:
                    self.set_hidden(previous["definition"]["revision_id"], True)
                except OSError:
                    # A failed visibility write must not leave a half-committed remap.
                    path.unlink(missing_ok=True)
                    raise
            return {"entry": preview, "created": True}

    def complete(self, revision_id: str, payload):
        safe_component(revision_id, "component")
        request = completion_request(payload)
        fields = request.fields
        source = request.source.model_dump(exclude_none=True)
        canonical = json.dumps({"fields": fields, "source": source}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        with self._lock:
            entries = self.entries(include_hidden=True)
            base = next((e for e in entries if e["definition"]["revision_id"] == revision_id), None)
            if base is None:
                raise ComponentLibraryError("Library revision not found.", "component_revision_not_found", status=404)
            if base["kind"] != "inverters":
                raise ComponentLibraryError("Only missing inverter datasheet fields can be completed.", "completion_field_not_allowed")
            data = deepcopy(base["definition"])
            for path, value in fields.items():
                if path not in COMPLETION_LIMITS:
                    raise ComponentLibraryError(f"Completion field is not allowed: {path}.", "completion_field_not_allowed")
                section, key = path.split('.')
                if (data.get(section) or {}).get(key) is not None:
                    raise ComponentLibraryError(f"The file already provides {path}; completion cannot overwrite it.", "completion_conflicts_with_file")
                maximum, _ = COMPLETION_LIMITS[path]
                if not (0 < value <= maximum) or (path == "ac_limits.nominal_frequency_hz" and value not in (50, 60)):
                    raise ComponentLibraryError(f"Datasheet value is out of range: {path}.", "completion_invalid")
            template = data.get("mppt_template") or {}
            operating = fields.get("mppt_template.max_operating_current_a", template.get("max_operating_current_a"))
            short = fields.get("mppt_template.max_short_circuit_current_a", template.get("max_short_circuit_current_a"))
            if operating is not None and short is not None and short < operating:
                raise ComponentLibraryError("Short-circuit current must be at least the operating current per MPPT.", "completion_invalid")
            duplicate = next((e for e in entries if e["library"].get("completed_from") == revision_id
                              and e["library"].get("completion_hash") == digest), None)
            if duplicate:
                return {"entry": self.preview(duplicate, duplicate_of=duplicate["definition"]["revision_id"]), "created": False}
            metadata = deepcopy(base["library"])
            definition_id = metadata["definition_id"]
            number = 1 + max(e["library"]["revision_number"] for e in entries if e["library"]["definition_id"] == definition_id)
            new_id = f"{definition_id}-r{number}"
            data.pop("capability_flags", None)
            overlay = {}
            for path, value in fields.items():
                section, key = path.split('.')
                data.setdefault(section, {}).pop(key, None)  # Only verified-absent leaves.
                overlay.setdefault(section, {})[key] = value
            candidate = build_candidate_from_fragments("inverter", [
                ComponentSourceFragment(source_id=f"src-lib-sha256-{metadata['source_sha256']}", data=data,
                    source_kind="manufacturer_component_file"),
                ComponentSourceFragment(source_id=f"src-user-datasheet-{digest[:16]}", data=overlay, source_kind="user_supplied",
                    source_url=source.get("url"), notes=json.dumps(source, ensure_ascii=False, sort_keys=True))],
                candidate_id=f"candidate-{new_id}", definition_id=definition_id, revision_id=new_id)
            # Assembly warnings describe the unchanged source curve, not repaired engineering gaps.
            candidate["validation_findings"].extend(deepcopy([f for f in metadata["findings"]
                if f["rule_id"] in {"INVERTER_SINGLE_EFFICIENCY_CURVE", "INVERTER_OND_SEMANTIC_ASSEMBLY_WARNING"}]))
            metadata.update(revision_number=number, hidden=False, completed_from=revision_id, completion_hash=digest,
                completion={"fields": fields, "source": source, "entered_at": datetime.now(timezone.utc).isoformat()},
                findings=candidate["validation_findings"], schema_ready=candidate["definition_schema_ready"],
                readiness=definition_readiness("inverters", candidate["canonical_data"]),
                field_provenance={**candidate["field_provenance"], **metadata.get("field_provenance", {}),
                    **{path: candidate["field_provenance"][path] for path in fields}},
                sources=metadata.get("sources", []) + candidate["sources"])
            metadata.pop("remapped_from", None)
            entry = {"kind": "inverters", "definition": candidate["canonical_data"], "library": metadata}
            preview = self.preview(entry)
            if request.dry_run:
                return {"entry": preview, "created": False}
            if not candidate["definition_schema_ready"]:
                raise ComponentLibraryError("The completed definition is missing required component data; review the findings.",
                    "component_schema_incomplete", findings=candidate["validation_findings"])
            safe_component(new_id, "library_revision")
            path = contained(self.root, self.root / "inverters" / f"{new_id}.json")
            assert not path.exists(), "Component library revision collision"
            self._atomic(path, (json.dumps(entry, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
            try:
                self.set_hidden(revision_id, True)
            except OSError:
                path.unlink(missing_ok=True)
                raise
            return {"entry": preview, "created": True}

    def set_hidden(self, revision_id: str, hidden: bool):
        if not _SAFE_REVISION.fullmatch(revision_id):
            raise ComponentLibraryError("Library revision not found.", "component_revision_not_found", status=404)
        with self._lock:
            entry = next((e for e in self.entries(include_hidden=True) if e["definition"]["revision_id"] == revision_id), None)
            if entry is None:
                raise ComponentLibraryError("Library revision not found.", "component_revision_not_found", status=404)
            if entry["library"]["hidden"] != hidden:
                entry["library"]["hidden"] = hidden
                path = contained(self.root, self.root / safe_component(entry["kind"], "collection") / f"{revision_id}.json")
                self._atomic(path, (json.dumps(entry, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())
            return entry
