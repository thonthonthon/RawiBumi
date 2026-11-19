"""Read-only presentation of completed, verified compact run artifacts."""
from copy import deepcopy
import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from engine.simulation.artifacts import canonical_object_sha256, _file_sha256
from engine.simulation.detailed_dispatch import verify_detailed_context

ROOT = Path(__file__).resolve().parents[2]


def _read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"run artifact is missing or unreadable: {path.name}") from exc


def _schema(payload, name):
    errors = list(Draft202012Validator(_read(ROOT / "schemas" / name), format_checker=FormatChecker()).iter_errors(payload))
    if errors:
        raise ValueError(f"invalid persisted {name}: {errors[0].message}")


def _presentation_package(run_directory):
    """Verify completed artifact bytes, without physics or energy replay.

    Scientific arithmetic is validated by backend record persistence.
    This read boundary checks persisted hashes and references, never rebuilds
    the energy summary and never loads diagnostic curve JSON.
    """
    manifest = _read(run_directory / "run-package-manifest.json")
    _schema(manifest, "run-package-manifest.schema.json")
    body = dict(manifest)
    digest = body.pop("manifest_payload_sha256")
    if canonical_object_sha256(body) != digest or manifest["artifact_count"] != len(manifest["artifacts"]):
        raise ValueError("run package completion manifest mismatch")
    seen = set()
    root = run_directory.resolve()
    for artifact in manifest["artifacts"]:
        name = artifact["relative_path"]
        path = run_directory / name
        if not name or name in seen or Path(name).is_absolute() or ".." in Path(name).parts or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError("run package artifact is missing or invalid")
        seen.add(name)
        sha, size = _file_sha256(path)
        if sha != artifact["sha256"] or size != artifact["byte_size"]:
            raise ValueError(f"run package artifact hash mismatch: {name}")
    files = {p.relative_to(run_directory).as_posix() for p in run_directory.rglob("*") if p.is_file() and p.name != "run-package-manifest.json"}
    if files != seen:
        raise ValueError("run package contains unmanifested artifacts")
    run = _read(run_directory / "simulation-run.json")
    if run["simulation_run_id"] != manifest["simulation_run_id"]:
        raise ValueError("run package identity mismatch")
    return run, digest


def _compact_record(run_directory, artifact, hash_key, expected_hash, schema):
    record = _read(run_directory / artifact)
    payload = record["payload"]
    if record[hash_key] != expected_hash or canonical_object_sha256(payload) != expected_hash:
        raise ValueError(f"compact artifact identity mismatch: {artifact}")
    _schema(payload, schema)
    return payload


def detailed_result_fields(run_directory: Path, *, expected_references: dict | None = None) -> dict:
    """Verification checks integrity; presentation never derives physics or energy."""
    run_directory = Path(run_directory)
    run, package_digest = _presentation_package(run_directory)
    if expected_references and expected_references.get("package_manifest_sha256") not in (None, package_digest):
        raise ValueError("run package does not match saved completion reference")
    context_path = run_directory / "detailed-execution-context.json"
    if not context_path.exists():
        if run.get("detailed_execution_identity") is not None or any(p.name.startswith("detailed-") for p in run_directory.iterdir()):
            raise ValueError("detailed run package has no execution context")
        return {}
    context = json.loads(context_path.read_text())
    identity = context["identity"]
    verify_detailed_context(context)
    expected_run_hash = canonical_object_sha256({"canonical_input_hash": context["canonical_input_hash"],
        "detailed_scientific_input_sha256": identity["scientific_input_sha256"],
        "detailed_execution_identity_sha256": identity["execution_identity_sha256"]})
    if run.get("detailed_execution_identity") != identity or run.get("input_hash") != expected_run_hash:
        raise ValueError("run identity does not match detailed context")
    if identity.get("compact_result_sha256"):
        compact = _compact_record(run_directory, "detailed-selected-mppt.json", "compact_result_sha256", identity["compact_result_sha256"], "detailed-selected-mppt.schema.json")
        if compact["scientific_input_sha256"] != identity["scientific_input_sha256"] or compact["diagnostic_result_sha256"] != identity["numerical_result_sha256"]:
            raise ValueError("selected-MPPT source binding mismatch")

    def reference(artifact, digest=None, model_id=None):
        available = (run_directory / artifact).is_file()
        return {"status": "available" if available else "unavailable",
                "artifact": artifact if available else None, "sha256": digest,
                "model_id": model_id,
                "unavailable_reason_codes": [] if available else ["artifact_not_produced"]}

    attribution = context.get("dc_attribution_reference") or {}
    energy = context.get("dc_attribution_energy_reference") or {}
    summary = None
    source = None
    if attribution:
        if attribution["artifact"] != "detailed-dc-attribution.json":
            raise ValueError("unexpected attribution artifact reference")
        source = _compact_record(run_directory, attribution["artifact"], "attribution_result_sha256", attribution["attribution_result_sha256"], "detailed-dc-attribution.schema.json")
        if source["attribution_model_id"] != attribution["model_id"] or source["scientific_input_sha256"] != identity["scientific_input_sha256"] or source["source_numerical_result_sha256"] != identity["numerical_result_sha256"] or source["source_electrical_design_sha256"] != canonical_object_sha256(context["inputs"]["electrical_design"]):
            raise ValueError("attribution scientific source binding mismatch")
    elif (run_directory / "detailed-dc-attribution.json").exists():
        raise ValueError("unbound compact attribution")
    if energy:
        if source is None or energy["artifact"] != "detailed-dc-attribution-energy-summary.json":
            raise ValueError("unbound attribution energy reference")
        summary = _compact_record(run_directory, energy["artifact"], "energy_summary_sha256", energy["energy_summary_sha256"], "detailed-dc-attribution-energy-summary.schema.json")
        if summary["energy_summary_model_id"] != energy["model_id"] or summary["source_attribution_result_sha256"] != attribution["attribution_result_sha256"] or any(value != source[key] for key, value in summary["source_identity"].items()):
            raise ValueError("attribution energy source binding mismatch")
        if len(summary["interval_audit"]) != len(source["intervals"]):
            raise ValueError("attribution interval coverage binding mismatch")
        for audit, interval in zip(summary["interval_audit"], source["intervals"]):
            if any(audit[key] != interval[key] for key in ("interval_start", "interval_end", "evaluation_time", "duration_seconds", "ledger")):
                raise ValueError("attribution interval ledger binding mismatch")
        total = next((p for p in summary["periods"] if p["period_kind"] == "run_total"), None)
        if total is None or any(total["channels"][key]["observed_signed_energy_wh"] != value["available_subtotal_wh"] for key, value in source["energy"].items()):
            raise ValueError("attribution observed total source binding mismatch")
    elif (run_directory / "detailed-dc-attribution-energy-summary.json").exists():
        raise ValueError("unbound attribution energy artifact")
    diagnostics = [name for name in ("detailed-mppt-result.json", "detailed-dc-attribution-diagnostics.json")
                   if (run_directory / name).is_file()]
    fields = {"detailed_electrical_shading": {
        "package_manifest_sha256": package_digest,
        "execution_identity": deepcopy(identity),
        "selected_mppt_result": reference("detailed-selected-mppt.json", identity.get("compact_result_sha256")),
        "dc_attribution_result": reference("detailed-dc-attribution.json", attribution.get("attribution_result_sha256"), attribution.get("model_id")),
        "attribution_energy_result": reference("detailed-dc-attribution-energy-summary.json", energy.get("energy_summary_sha256"), energy.get("model_id")),
        "attribution_energy_summary": summary,
        "diagnostic_artifacts": {"status": "available" if diagnostics else "not_requested_or_not_produced", "artifacts": diagnostics},
    }}
    if expected_references and any(expected_references[key]["sha256"] != fields["detailed_electrical_shading"][key]["sha256"] for key in ("selected_mppt_result", "dc_attribution_result", "attribution_energy_result")):
        raise ValueError("persisted detailed artifact does not match saved run reference")
    return fields


def hydrate_run_records(records: list[dict], run_root: Path, project_id: str) -> list[dict]:
    result = deepcopy(records)
    root = run_root.resolve()
    project_root = (root / project_id).resolve()
    if not project_root.is_relative_to(root):
        raise ValueError("project run storage is outside run storage")
    for record in result:
        # DATA1: an imported run without its package keeps only its saved summary.
        if record.get("package_omitted") is True:
            continue
        from .safe_paths import safe_component
        directory = (project_root / safe_component(record["simulation_run_id"], "run")).resolve()
        if not directory.is_relative_to(project_root):
            raise ValueError("run reference is outside run storage")
        # Legacy imported records may predate run packages. Detailed records must
        # always verify their package again, including after project reopening.
        detailed = bool(record.get("detailed_electrical_shading")) or record.get("detailed_execution_identity") is not None
        if (directory / "run-package-manifest.json").exists() or detailed:
            fields = detailed_result_fields(directory, expected_references=record.get("detailed_electrical_shading"))
            persisted = json.loads((directory / "simulation-run.json").read_text())
            if persisted["simulation_run_id"] != record["simulation_run_id"] or (record.get("input_hash") is not None and persisted.get("input_hash") != record["input_hash"]):
                raise ValueError("run record does not match verified package")
            if detailed and not fields:
                raise ValueError("detailed run record has no detailed package")
            record.update(fields)
    return result
