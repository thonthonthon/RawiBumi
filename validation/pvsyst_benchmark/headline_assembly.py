"""Complete DEC-160 HTTP assembly and readiness receipts; no simulation entry point."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .completion import complete_inverter, require_external
from .headline_electrical import topology_commands, reference_power, loss_patch
from .headline_scene import build_geometry
from .project import extract_project
from .reference import read_reference
from .source import read_objects, SourceError
from .weather_adapter import recover_weather, attach_weather


class AssemblyError(ValueError):
    pass


class AssemblyHTTP:
    """Record the actual requests, and prohibit simulation before approval."""

    def __init__(self, client, receipt):
        self.client, self.receipt = client, receipt
        self.app = client.app

    def request(self, method, path, **kwargs):
        if "/simulate" in path:
            raise AssemblyError("annual execution is not authorized by assembly")
        response = self.client.request(method, path, **kwargs)
        item = {"method": method, "path": path, "status": response.status_code}
        if "json" in kwargs:
            item["request_json_sha256"] = sha256(json.dumps(
                kwargs["json"], sort_keys=True, allow_nan=False).encode()).hexdigest()
        self.receipt["http"].append(item)
        if response.status_code >= 400:
            self.receipt["http_refusal"] = response.json()
            raise AssemblyError(f"HTTP assembly refused: {method} {path}: {response.status_code}")
        return response

    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)

    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)

    def patch(self, path, **kwargs):
        return self.request("PATCH", path, **kwargs)


def assert_complete_readiness(readiness, scene):
    blockers = [f for f in readiness.get("findings", [])
                if f.get("severity") in {"blocking_error", "error", "fatal"}]
    if not readiness.get("ready") or blockers:
        raise AssemblyError("complete-project readiness blocks: " + repr(blockers))
    excluded = [f for f in readiness.get("findings", [])
                if f.get("rule_id") == "MODULES_NOT_SIMULATED"]
    groups = readiness["execution_plan"]["groups"]
    actual = [mid for g in groups for mid in g["module_instance_ids"]]
    expected = {m["module_instance_id"] for m in scene["module_instances"]}
    if excluded or len(actual) != len(set(actual)) or set(actual) != expected:
        raise AssemblyError("placed and execution-plan modules differ")
    return {"ready": True, "blocker_count": 0, "excluded_module_count": 0,
            "placed_modules": len(expected), "simulated_modules": len(actual),
            "execution_groups": len(groups)}


def assert_settings(view, plan, inverter_groups, pref, plant_fraction):
    """Check persisted HTTP readback plus real, non-running configuration resolution."""
    from apps.api.study import BrowserStudyService, _phase5_configuration, build_project_revision_from_design
    from engine.losses.settings import resolve_circuit_loss_settings
    from engine.simulation.optics_thermal import configure_optics_thermal, run_optics_snapshot

    b = view["bundle"]
    losses = view["resolved_loss_settings"]["values"]
    expected = loss_patch(plan, b, inverter_groups, pref, plant_fraction)["overrides"]
    for key in ("soiling", "lid_fraction", "module_mismatch_fraction", "string_mismatch_fraction",
                "annual_degradation_fraction", "operating_year", "unavailability_fraction", "ac_wiring_nominal_fraction"):
        if losses[key] != expected[key]:
            raise AssemblyError("persisted loss setting differs: " + key)
    if losses["transformer"]["enabled"] or view.get("loss_binding_findings"):
        raise AssemblyError("transformer or stale circuit binding")
    optical = view["resolved_optics_thermal_settings"]["values"]
    if (optical["transposition"] != "perez_hourly" or optical["iam"]["selection"] != "module_auto"
            or optical["thermal"]["irradiance_basis"] != "effective"
            or optical["thermal"]["u_c_w_m2k"] != 20.
            or optical["thermal"]["u_v_w_m2k_per_ms"] != 0.
            or optical["albedo"]["monthly_values"] != [.2]*12):
        raise AssemblyError("optics/thermal readback differs from approved inputs")
    components = {**b["pinned_components"]["modules"], **b["pinned_components"]["inverters"]}
    circuits = resolve_circuit_loss_settings(b["loss_settings"], b["scene"], b["electrical_design"], components)
    by_inv = {iid: sub for sub in plan.subarrays for iid in inverter_groups[sub["index"]]}
    for row in circuits["circuits"].values():
        sub = by_inv[row["inverter_instance_id"]]
        if row["dc_wiring_stc_fraction"] != sub["dc_wiring_stc_fraction"]:
            raise AssemblyError("DC circuit is bound to the wrong sub-array override")
        if set(row["module_quality_by_module"].values()) != {sub["quality_fraction"]}:
            raise AssemblyError("module quality is bound to the wrong sub-array override")
    for row in circuits["inverters"].values():
        if row["ac_wiring"]["quadratic_coefficient_per_w"] != 0:
            raise AssemblyError("per-inverter AC segment must be zero")
    plant = circuits["plant_ac_wiring"]
    if (plant["reference_power_w"] != pref or plant["loss_fraction"] != plant_fraction
            or plant["quadratic_coefficient_per_w"] != plant_fraction/pref):
        raise AssemblyError("plant AC custom reference differs")
    electrical_snapshot = BrowserStudyService._simulation_electrical_snapshot(
        b["electrical_design"], project_revision_id="val1b-settings-check",
        snapshot_id="val1b-settings-check-electrical")
    project = build_project_revision_from_design(
        b["scene"], electrical_snapshot, project_revision_id="val1b-settings-check", revision_number=1,
        weather_dataset_revision_id=b["weather_selection"]["revision_id"])
    configuration = _phase5_configuration(project, configuration_id="val1b-settings-check",
                                         scene=b["scene"], shading_accuracy=b["shading_accuracy"])
    configure_optics_thermal(configuration, b["optics_thermal_settings"])
    configuration["numerical_options"]["loss_settings"] = deepcopy(b["loss_settings"])
    snapshot = run_optics_snapshot(configuration, b["scene"], b["electrical_design"], components)
    modules = snapshot["modules"]
    if (len(modules) != len(b["scene"]["module_instances"])
            or {m["alpha_absorption"] for m in modules.values()} != {.9}
            or {m["iam_source"] for m in modules.values()} != {"module_table"}):
        raise AssemblyError("alpha or module IAM source differs from approved inputs")
    for revision in {m["module_revision_id"] for m in modules.values()}:
        iam = components[revision]["optical"]["iam"]
        if "cubic" not in iam["interpolation_method"]:
            raise AssemblyError("module IAM must execute the source cubic profile")
    shading = configuration["shading_configuration"]
    accuracy = view["resolved_shading_accuracy"]
    if (accuracy["level"] != "standard" or not shading["self_shading_enabled"]
            or shading["electrical_shading_method"] is not None
            or shading["sky_dome_resolution"] != accuracy["sky_dome_resolution"]
            or shading["ground_dome_resolution"] != accuracy["ground_dome_resolution"]):
        raise AssemblyError("standard-path accuracy/self-shading differs")
    return {"all_assertions_passed": True, "losses": deepcopy(losses),
            "optics_thermal": deepcopy(optical), "shading_accuracy": accuracy,
            "self_shading_enabled": True, "fidelity": "standard_geometry_aware",
            "alpha_absorption": .9, "iam_source": "module_table", "iam_interpolation": "source_cubic",
            "circuit_resolution": circuits, "configuration": configuration}


def assemble_case(client, label, paths, *, plant_loss_fraction, receipt):
    """Fresh project via real HTTP; weather uses the approved VAL1a bootstrap."""
    if label not in {"P2", "P3"}:
        raise SourceError("only active case labels are supported")
    app = client.app
    repository = Path(__file__).resolve().parents[2]
    require_external(app.state.project_service.store.root, repository)
    require_external(app.state.project_service.library.root, repository)
    receipt.update(case=label, status="assembling", http=[], simulation_calls=0)
    api = AssemblyHTTP(client, receipt)
    module_definitions = {}
    for source in paths["modules"]:
        file = Path(source)
        response = api.post("/api/component-library/imports", params={"filename": file.name}, content=file.read_bytes())
        rev = response.json()["entry"]["revision_id"]
        d = next(e["definition"] for e in app.state.project_service.library.entries(include_hidden=True)
                 if e["definition"]["revision_id"] == rev)
        module_definitions[file.name] = d
    inverter = complete_inverter(api, Path(paths["inverter"]), paths["completion"])
    if not inverter["readiness"]["ready"]:
        raise AssemblyError("completed source inverter is not ready")
    receipt["inverter_completion"] = {k: v for k, v in inverter.items() if k != "definition"}
    vc, prj, shd = (read_objects(Path(paths[k])) for k in ("vc", "prj", "shd"))
    plan = extract_project(vc, prj, label=label)
    receipt["source_plan"] = {"site": plan.site, "orientations": plan.orientations,
                              "subarrays": plan.subarrays, "unsupported_register": [f.record() for f in plan.unsupported]}
    # Retain the old extractor's historical register; assembly resolves only the
    # explicitly approved entries, never treats an unsupported quantity as zero.
    operations, facts = build_geometry(shd, plan, module_definitions)
    receipt["geometry"] = facts
    offset = plan.site["utc_offset_hours"]
    if offset != int(offset):
        raise AssemblyError("site needs an approved noninteger timezone mapping")
    zone = "UTC" if offset == 0 else f"Etc/GMT{-int(offset):+d}"
    response = api.post("/api/projects", json={"name": label+" benchmark",
                        **{k: plan.site[k] for k in ("latitude_deg", "longitude_deg", "elevation_m")}, "timezone": zone})
    if response.status_code != 201:
        raise AssemblyError("project creation did not return 201")
    pid = response.json()["bundle"]["project"]["project_id"]
    receipt["project_id"] = pid
    url = "/api/projects/"+pid
    preview = api.post(url+"/scene/geometry", json={"operations": operations, "dry_run": True}).json()
    receipt["geometry_preview"] = preview
    if preview["conflicts"]:
        raise AssemblyError("scene preview has physical conflicts")
    view = api.post(url+"/scene/geometry", json={"operations": operations}).json()
    inverter_groups = {}
    for sub in plan.subarrays:
        group = []
        for i in range(sub["inverters"]):
            before = {v["inverter_instance_id"] for v in view["bundle"]["electrical_design"]["inverter_instances"]}
            view = api.post(url+"/inverters", json={"inverter_definition_revision_id": inverter["completed_revision_id"],
                                                  "name": f"{label} A{sub['index']} I{i+1}"}).json()
            added = {v["inverter_instance_id"] for v in view["bundle"]["electrical_design"]["inverter_instances"]}-before
            if len(added) != 1:
                raise AssemblyError("inverter creation identity mismatch")
            group.append(added.pop())
        inverter_groups[sub["index"]] = group
    b = view["bundle"]
    commands, assignment = topology_commands(b["scene"], b["electrical_design"], plan,
                                            facts["field_subarrays"], inverter_groups)
    for start in range(0, len(commands), 200):
        view = api.post(url+"/electrical/commands", json={"commands": commands[start:start+200]}).json()
    view = api.get(url).json()
    receipt["assignment"] = assignment
    receipt["inverter_groups"] = inverter_groups
    pref = reference_power(plan, module_definitions, inverter["definition"], inverter_groups)
    receipt["reference_power"] = pref
    patch = loss_patch(plan, view["bundle"], inverter_groups, pref["reference_power_w"], plant_loss_fraction)
    api.patch(url+"/losses", json=patch)
    api.patch(url+"/optics-thermal", json={"overrides": {
        "transposition": "perez_hourly", "iam": {"selection": "module_auto"},
        "albedo": {"monthly_values": [.2]*12},
        "thermal": {"irradiance_basis": "effective", "u_c_w_m2k": 20., "u_v_w_m2k_per_ms": 0.}}})
    api.patch(url+"/shading-accuracy", json={"overrides": {"level": "standard"}})
    reference = read_reference(Path(paths["csv"]))
    if reference.variant_filename is None or reference.variant_filename.casefold() != Path(paths["vc"]).name.casefold():
        raise AssemblyError("hourly-export variant identity mismatch")
    weather, weather_receipt = recover_weather(reference, site=plan.site, label=label, uv=0., omit_wind=label == "P3")
    from engine.solar import solar_position_from_weather
    from weather.validation import run_solar_aware_weather_qc
    weather_receipt["solar_qc"] = run_solar_aware_weather_qc(weather, solar_position_from_weather(weather))
    receipt["weather"] = weather_receipt
    if weather_receipt["qc"]["status"] == "failed" or weather_receipt["solar_qc"]["status"] == "failed":
        raise AssemblyError("reference-derived weather QC failed")
    receipt["weather_attachment"] = attach_weather(app, pid, weather, weather_receipt)
    if (label == "P3" and "wind_speed_m_s" in weather.series
            or len(weather.series) != len(reference.frame)):
        raise AssemblyError("weather wind/timeline policy mismatch")
    view = api.get(url).json()
    receipt["asserted_settings"] = assert_settings(view, plan, inverter_groups, pref["reference_power_w"], plant_loss_fraction)
    readiness = api.get(url+"/execution-readiness").json()
    receipt["readiness"] = readiness
    receipt["readiness_assertions"] = assert_complete_readiness(readiness, view["bundle"]["scene"])
    if view["bundle"]["simulation_runs"] or api.get(url+"/runs").json():
        raise AssemblyError("assembly must not create a simulation run")
    receipt.update(status="ready_for_annual_approval", weather_hours=len(weather.series),
                   annual_run_authorized=False)
    return receipt
