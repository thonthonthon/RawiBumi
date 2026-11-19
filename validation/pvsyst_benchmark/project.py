"""Source-backed request plans, never a repair or a headline builder."""

from dataclasses import dataclass, asdict
from .source import Node, SourceError, vector


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    reason: str
    blocking: bool = True

    def record(self):
        return asdict(self)


META = {
    "Comment",
    "Version",
    "Flags",
    "Flags2",
    "Source",
    "SubArrays",
    "DateFMod",
    "DateFInv",
    "DateCalcul",
    "DateDebS",
    "DateFinS",
    "VersionSimul",
    "SimDuration",
    "Simduration",
    "SubArrayId",
}
KNOWN = {
    "pvProject": META
    | set(
        "MeteoFileName MeteoFileDate Albedo DesignTempMin TempOper TempOperMin TempOperMax LimOverloadLoss DiscrOrientDiff SpreadMaxDiff MaxSystem_ShdRatio RegionMeteo CorrAlttemp SiteMeteoMaxDistForList TranspositionAlgorithm ACLossesRef".split()
    ),
    "pvSite": META
    | set(
        "NomF Site Country Region SourceType Latitude Longitude Altitude TimeZone HLeg UnitsDisp Albedo DateBeg DateEnd GlobalH DiffuseH TAmb WindVel Linke RelHum Extraterr YrToYrVar".split()
    ),
    "pvVCalcul": META
    | set("SystemKindCustom SystemKind PRCorrTemp ACLossesRef".split()),
    "pvCollPlane": META
    | set(
        "AzimPlMulti AzimPlR FieldType InclPlMulti InclPlR IsDefined NOrient TranspositionAlgorithm".split()
    ),
    "pvMainArray": META
    | set(
        "UFactor Alpha UFAverEffic SoilingLoss ACWireNoSect ACWireLength ACWireMetal UseSpectralCorr VOutTransfo".split()
    ),
    "pvSubArray": META
    | set(
        "PVModule GInverter NModSerie NStringCh NStrOrient1 NoOrientation NInverter NInvMPPT PowerSharingInverterId PNomAC_InMPPT PQualityModU PQualityModI PQualityModP PMismMPP PMismUFixe PMismString LIDLoss LightSoaking RSCablageCh RSCablagePC VDiodeSerie WiringResistance TypeLayout TypeMetal NGroupS NGroupP NChamp LongString Resistivity TargetLoss NoSect ACWireNoSect VOutTransfo".split()
    ),
    "pvEnIncid": META,
    "pvSystem": META | {"SystemType"},
}


@dataclass
class ProjectPlan:
    label: str
    site: dict
    orientations: list[dict]
    subarrays: list[dict]
    settings: dict
    requests: list[dict]
    unsupported: list[Finding]
    source_ledger: list[dict]


def extract_project(vc: Node, prj: Node, *, label: str, components=None) -> ProjectPlan:
    if label not in {"P2", "P3"}:
        raise SourceError("case is deferred or unknown")

    def exactly(kind):
        nodes = list(vc.walk(kind))
        if len(nodes) != 1:
            raise SourceError(f"expected exactly one {kind}")
        return nodes[0]

    site_nodes = [n for n in vc.walk("pvSite") if n.tag == "PVObject_SiteSimul"]
    if len(site_nodes) != 1:
        raise SourceError("missing unique simulation site")
    site_node = site_nodes[0]
    site = {
        dest: site_node.number(src)
        for src, dest in [
            ("Latitude", "latitude_deg"),
            ("Longitude", "longitude_deg"),
            ("Altitude", "elevation_m"),
            ("TimeZone", "utc_offset_hours"),
        ]
    }
    prj_sites = list(prj.walk("pvSite"))
    findings = []
    if len(prj_sites) != 1 or any(
        abs(prj_sites[0].number(src) - site[dest]) > 1e-8
        for src, dest in [
            ("Latitude", "latitude_deg"),
            ("Longitude", "longitude_deg"),
            ("Altitude", "elevation_m"),
            ("TimeZone", "utc_offset_hours"),
        ]
    ):
        findings.append(
            Finding("site_mismatch", "site", "Project and simulation site differ")
        )
    plane, main = exactly("pvCollPlane"), exactly("pvMainArray")
    tilt = vector(plane.one("InclPlMulti"))
    azimuth = vector(plane.one("AzimPlMulti"))
    if len(tilt) != len(azimuth) or len(tilt) != plane.integer("NOrient"):
        raise SourceError("orientation count mismatch")
    orientations = [
        {
            "index": i + 1,
            "tilt_deg": t,
            "source_azimuth_deg": a,
            "azimuth_deg": (-a if site["latitude_deg"] < 0 else a + 180) % 360,
        }
        for i, (t, a) in enumerate(zip(tilt, azimuth))
    ]
    subarrays, requests, ledger = [], [], []
    components = components or {}
    for i, node in enumerate(vc.walk("pvSubArray"), 1):
        orientation = node.integer("NoOrientation")
        if not 1 <= orientation <= len(orientations):
            raise SourceError("invalid sub-array orientation")
        counts = {
            k: node.integer(src)
            for k, src in [
                ("modules_per_string", "NModSerie"),
                ("strings", "NStringCh"),
                ("inverters", "NInverter"),
                ("mppt_declaration", "NInvMPPT"),
            ]
        }
        if any(counts[k] <= 0 for k in counts):
            raise SourceError("nonpositive sub-array count")
        module, inverter = node.one("PVModule"), node.one("GInverter")
        if not module or not inverter:
            raise SourceError("missing exact component reference")
        item = {
            "index": i,
            "orientation": orientation,
            "module_ref": module,
            "inverter_ref": inverter,
            **counts,
            "module_count": counts["modules_per_string"] * counts["strings"],
            "quality_fraction": node.number("PQualityModP") / 100,
            "dc_wiring_stc_fraction": node.number("RSCablagePC") / 100,
            "module_mismatch_fraction": node.number("PMismMPP") / 100,
            "string_mismatch_fraction": node.number("PMismString") / 100,
            "lid_fraction": node.number("LIDLoss") / 100,
        }
        subarrays.append(item)
        for k, source_key in [
            ("quality_fraction", "PQualityModP"),
            ("dc_wiring_stc_fraction", "RSCablagePC"),
            ("modules_per_string", "NModSerie"),
            ("strings", "NStringCh"),
            ("inverters", "NInverter"),
        ]:
            ledger.append(
                {
                    "path": f"subarrays.{i}.{k}",
                    "source": f"pvSubArray[{i}].{source_key}",
                    "value": item[k],
                }
            )
        if node.number("PowerSharingInverterId") != -1:
            findings.append(
                Finding(
                    "power_sharing_unsupported",
                    f"subarrays.{i}",
                    "Source power sharing is enabled",
                )
            )
        findings.append(
            Finding(
                "circuit_overrides_pending",
                f"subarrays.{i}",
                "Per-circuit quality/DC overrides require the next product slice",
            )
        )
        findings.append(
            Finding(
                "mppt_allocation_unresolved",
                f"subarrays.{i}",
                "Counts alone do not establish exact string-to-MPPT allocation",
            )
        )
        for j in range(counts["inverters"]):
            pin = components.get(inverter)
            if pin:
                requests.append(
                    {
                        "method": "POST",
                        "path": "/api/projects/{project_id}/inverters",
                        "json": {
                            "inverter_definition_revision_id": pin,
                            "name": f"{label} sub-array {i} inverter {j+1}",
                        },
                    }
                )
    if not subarrays:
        raise SourceError("no sub-arrays")
    # Opaque sections remain in the ledger/register; unknown scientific keys are never dropped.
    delegated = {
        "pvShading",
        "pvShdArrayTable",
        "pvShdGenObject",
        "pvShdFTable",
        "pvShdObjectGroup",
    }
    for root in (vc, prj):
        for node in root.walk():
            if node.kind in delegated:
                continue
            for key, value in node.records:
                path = f"{node.kind}.{key}"
                if key not in KNOWN.get(node.kind, set()):
                    findings.append(
                        Finding(
                            "source_key_unmapped",
                            path,
                            "No engineering mapping is established",
                        )
                    )
                ledger.append(
                    {
                        "path": path,
                        "source_line": node.line,
                        "classification": (
                            "known"
                            if key in KNOWN.get(node.kind, set())
                            else "unsupported"
                        ),
                    }
                )
    findings += [
        Finding(
            "mesh_and_placement_pending",
            "scene",
            "Exact mesh obstacles and table placement require the next geometry slice",
        ),
        Finding(
            "ac_inputs_pending",
            "losses",
            "User-provided AC STC percentage and transformer declaration are required",
        ),
        Finding(
            "initial_age_policy_unresolved",
            "losses",
            "Do not silently inherit a degradation setting",
        ),
        Finding(
            "reference_basis_partial",
            "reference",
            "Unproved columns are unavailable, not plant aggregates",
        ),
    ]
    # Zero Uv is the explicit TASK A1 policy, corroborated by the fixed-source
    # heat-balance probe; it is not a decoder default for arbitrary variants.
    ledger.append(
        {
            "path": "thermal_uv",
            "value": 0.0,
            "source": "TASK A1: verified zero-Uv policy for the two active cases",
        }
    )
    settings = {
        "optics_thermal": {
            "overrides": {
                "thermal": {
                    "irradiance_basis": "effective",
                    "u_c_w_m2k": main.number("UFactor"),
                    "u_v_w_m2k_per_ms": 0.0,
                },
                "iam": {"selection": "module_auto"},
                "transposition": "perez_hourly",
            }
        },
        "soiling_fraction": main.number("SoilingLoss"),
        "thermal_uv": 0.0,
        "headline_fidelity": "standard",
    }
    return ProjectPlan(
        label, site, orientations, subarrays, settings, requests, findings, ledger
    )
