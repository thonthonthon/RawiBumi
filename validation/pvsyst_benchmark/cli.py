"""One-command VAL1a evidence preparation. This command never calls simulate."""

import argparse
from collections import Counter
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from .reference import read_reference
from .source import read_objects, SourceError
from .project import extract_project
from .scene import (
    read_scene,
    reconstruction_counts,
    scene_equivalence,
    resolve_anchor_hypotheses,
)
from .weather_adapter import recover_weather, attach_weather
from .completion import require_external, complete_inverter
from .report import blocked_report, write_reports

REPOSITORY = Path(__file__).resolve().parents[2]


def prepare(manifest, *, scratch, output):
    destination = Path(output).resolve()
    if destination.is_relative_to(REPOSITORY):
        relative = destination.relative_to(REPOSITORY)
        if (
            relative.parts[:2] != (".ai", "validation")
            or subprocess.run(
                ["git", "check-ignore", str(relative)],
                cwd=REPOSITORY,
                capture_output=True,
            ).returncode
        ):
            raise ValueError(
                "private output must be ignored evidence or outside the repository"
            )
    root = require_external(scratch, REPOSITORY)
    if root.exists() and any(root.iterdir()):
        raise ValueError("use a fresh empty disposable root")
    if set(manifest) != {"P2", "P3"}:
        raise ValueError("only the two active labels are authorized")
    # Imports after safety checks: the default application is never operated on.
    from fastapi.testclient import TestClient
    from apps.api.server import create_app
    from apps.api.execution_readiness import phase5_module_definition_readiness

    app = create_app(store_root=root / "projects", library_root=root / "library")
    reports = []
    with TestClient(app) as client:
        for label, paths in sorted(manifest.items()):
            reasons = [
                {"public_code": "mesh_pending", "code": "MESH1_REQUIRED"},
                {"public_code": "circuit_settings_pending", "code": "S18C_REQUIRED"},
                {
                    "public_code": "ac_inputs_pending",
                    "code": "USER_AC_TRANSFORMER_INPUTS_REQUIRED",
                },
            ]
            evidence = {
                "thermal_basis": "effective",
                "headline_fidelity": "standard",
                "source_sha256": {
                    k: sha256(Path(paths[k]).read_bytes()).hexdigest()
                    for k in ("csv", "vc", "prj", "shd")
                },
                "tool_commit": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, text=True
                ).strip(),
            }
            reference = read_reference(Path(paths["csv"]))
            evidence["variant_identity"] = {
                "matches": reference.variant_filename is not None
                and reference.variant_filename.casefold()
                == Path(paths["vc"]).name.casefold(),
                "version": reference.version,
            }
            if not evidence["variant_identity"]["matches"]:
                reasons.append(
                    {
                        "public_code": "source_unknown",
                        "code": "REFERENCE_VARIANT_IDENTITY_UNPROVED",
                    }
                )
            vc, prj, shd = (read_objects(Path(paths[k])) for k in ("vc", "prj", "shd"))
            project = extract_project(vc, prj, label=label)
            evidence["project_plan"] = {
                "orientations": project.orientations,
                "subarrays": project.subarrays,
                "settings": project.settings,
                "unsupported": [f.record() for f in project.unsupported],
                "source_ledger": project.source_ledger,
            }
            for f in project.unsupported:
                reasons.append(
                    {"public_code": "source_unknown", "code": f.code, "path": f.path}
                )
            saved, embedded = read_scene(shd), read_scene(vc, require_layout=False)
            counts = reconstruction_counts(saved, project)
            equivalence = scene_equivalence(saved, embedded)
            dimensions = {}
            imported_modules = []
            for filename in paths["modules"]:
                p = Path(filename)
                response = client.post(
                    "/api/component-library/imports",
                    params={"filename": p.name},
                    content=p.read_bytes(),
                )
                if response.status_code != 200:
                    raise ValueError("real module import refused")
                rev = response.json()["entry"]["revision_id"]
                entry = next(
                    e
                    for e in app.state.project_service.library.entries(
                        include_hidden=True
                    )
                    if e["definition"]["revision_id"] == rev
                )
                d = entry["definition"]
                ready = phase5_module_definition_readiness(d)
                missing = sorted(
                    {
                        k
                        for model in d.get("electrical_models", [])
                        for phase in ("stc", "off_stc")
                        for k in (model.get("validation", {}).get(phase, {}) or {}).get(
                            "missing_parameters", []
                        )
                    }
                )
                imported_modules.append(
                    {
                        "revision_id": rev,
                        "readiness": ready,
                        "missing_parameters": missing,
                    }
                )
                if not ready["ready"]:
                    reasons.append(
                        {
                            "public_code": "module_not_ready",
                            "code": "STANDARD_SDM_REQUIRED",
                            "missing_parameters": missing,
                        }
                    )
                # Module dimensions are shared where the source table lacks a
                # component link; only assign when every supplied type agrees.
                dimensions[rev] = (
                    d["mechanical"]["width_m"],
                    d["mechanical"]["height_m"],
                )
            unique_dimensions = set(dimensions.values())
            table_dimensions = (
                {t.object_id: next(iter(unique_dimensions)) for t in saved.tables}
                if len(unique_dimensions) == 1
                else None
            )
            supports = [f for mesh in saved.meshes for f in mesh.support_faces()]
            extent_checks = []
            if table_dimensions is not None:
                for t in saved.tables:
                    width, height = table_dimensions[t.object_id]
                    w, h = (height, width) if t.landscape else (width, height)
                    occupied = (
                        t.columns * w + (t.columns - 1) * t.gap_x,
                        t.rows * h + (t.rows - 1) * t.gap_y,
                    )
                    extent_checks.append(
                        {
                            "object_id": t.object_id,
                            "fits": t.fits_module_dimensions(width, height),
                            "occupied_width_m": occupied[0],
                            "occupied_upslope_m": occupied[1],
                            "table_width_m": t.width,
                            "table_upslope_m": t.upslope,
                        }
                    )
            anchor = resolve_anchor_hypotheses(
                saved.tables, supports, dimensions=table_dimensions
            )
            if table_dimensions is None:
                anchor.update(
                    status="unavailable",
                    accepted_anchor=None,
                    reason="table_to_module_dimensions_unresolved",
                )
            if any(not e["fits"] for e in extent_checks):
                reasons.append(
                    {
                        "public_code": "mesh_pending",
                        "code": "PHYSICAL_MODULE_EXTENTS_EXCEED_DECLARED_TABLE",
                    }
                )
            evidence["scene"] = {
                "counts": counts,
                "equivalence": equivalence,
                "anchor": anchor,
                "topology_classes": dict(
                    Counter(mesh.topology() for mesh in saved.meshes)
                ),
                "tables": len(saved.tables),
                "meshes": len(saved.meshes),
                "mesh_facts": [m.facts() for m in saved.meshes],
                "extent_checks": extent_checks,
                "unsupported": [f.record() for f in saved.unsupported],
            }
            evidence["module_readiness"] = imported_modules
            if not counts["counts_match"] or not counts["orientations_match"]:
                reasons.append(
                    {
                        "public_code": "counts_mismatch",
                        "code": "SCENE_COUNTS_OR_ORIENTATIONS",
                    }
                )
            if not equivalence["world_equivalent_all_anchors"]:
                reasons.append(
                    {
                        "public_code": "scene_mismatch",
                        "code": "SAVED_EMBEDDED_WORLD_MISMATCH",
                    }
                )
            if anchor["status"] != "resolved":
                reasons.append(
                    {
                        "public_code": "origin_unresolved",
                        "code": "TYPE_ORIGINE_NOT_UNIQUE",
                    }
                )
            for f in saved.unsupported:
                reasons.append(
                    {"public_code": "source_unknown", "code": f.code, "path": f.path}
                )
            completed = complete_inverter(
                client, Path(paths["inverter"]), paths["completion"]
            )
            evidence["inverter_completion"] = {
                k: v for k, v in completed.items() if k != "definition"
            }
            if not completed["readiness"]["ready"]:
                reasons.append(
                    {
                        "public_code": "source_unknown",
                        "code": "COMPLETED_INVERTER_NOT_READY",
                    }
                )
            site = project.site
            offset = site["utc_offset_hours"]
            if offset != int(offset):
                raise ValueError(
                    "explicit site timezone required for noninteger fixed offset"
                )
            zone = "UTC" if offset == 0 else f"Etc/GMT{-int(offset):+d}"
            response = client.post(
                "/api/projects",
                json={
                    "name": label + " benchmark tooling",
                    "latitude_deg": site["latitude_deg"],
                    "longitude_deg": site["longitude_deg"],
                    "elevation_m": site["elevation_m"],
                    "timezone": zone,
                },
            )
            if response.status_code != 201:
                raise ValueError("real project creation refused")
            body = response.json()
            pid = body["bundle"]["project"]["project_id"]
            weather, receipt = recover_weather(
                reference,
                site=site,
                label=label,
                uv=project.settings["thermal_uv"],
                omit_wind=label == "P3",
            )
            from engine.solar import solar_position_from_weather
            from weather.validation import run_solar_aware_weather_qc

            receipt["solar_qc"] = run_solar_aware_weather_qc(
                weather, solar_position_from_weather(weather)
            )
            evidence["weather"] = receipt
            if receipt["solar_qc"]["status"] == "failed":
                reasons.append(
                    {"public_code": "weather_failed", "code": "SOLAR_WEATHER_QC_FAILED"}
                )
            if receipt["qc"]["status"] == "failed":
                reasons.append(
                    {"public_code": "weather_failed", "code": "WEATHER_QC_FAILED"}
                )
            else:
                evidence["weather_attachment"] = attach_weather(
                    app, pid, weather, receipt
                )
            evidence["basis_register"] = {
                k: reference.basis(k).value for k in reference.frame
            }
            evidence["requests"] = extract_project(
                vc,
                prj,
                label=label,
                components={
                    project.subarrays[0]["inverter_ref"]: completed[
                        "completed_revision_id"
                    ]
                },
            ).requests
            reports.append(blocked_report(label, reasons=reasons, evidence=evidence))
    summary = write_reports(output, reports)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                json.loads(args.manifest.read_text()),
                scratch=args.scratch,
                output=args.output,
            )
        )
    )


if __name__ == "__main__":
    main()
