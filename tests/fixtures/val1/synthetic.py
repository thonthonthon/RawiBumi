"""Wholly invented miniature sources; not excerpts of any reference file."""

from datetime import datetime, timedelta


def csv_bytes(*, rows=3, columns=None, optional=None):
    names = columns or [
        "date",
        "GlobHor",
        "DiffHor",
        "BeamHor",
        "T_Amb",
        "WindVel",
        "HSol",
        "AzSol",
        "E_Grid",
    ]
    units = {
        "date": "",
        "GlobHor": "W/m²",
        "DiffHor": "W/m²",
        "BeamHor": "W/m²",
        "T_Amb": "°C",
        "WindVel": "m/s",
        "HSol": "°",
        "AzSol": "°",
        "E_Grid": "kW",
        "LIDLoss": "kW",
        "CircEff": "W/m²",
    }
    values = {
        "GlobHor": "120",
        "DiffHor": "60",
        "BeamHor": "60",
        "T_Amb": "22",
        "WindVel": "1",
        "HSol": "30",
        "AzSol": "-90",
        "E_Grid": "2",
        "LIDLoss": "0",
        "CircEff": "5",
    }
    if optional:
        names = names + list(optional)
    lines = [
        "PVSYST V7.4.8",
        "Project;P2 Fictional café",
        "Simulation variant;invented.VC0",
    ]
    lines += [";".join(names), ";".join(units[n] for n in names)]
    for i in range(rows):
        day = datetime(1990, 1, 1) + timedelta(hours=i)
        lines.append(
            ";".join(
                day.strftime("%d/%m/%y %H:%M") if n == "date" else values[n]
                for n in names
            )
        )
    return "\n".join(lines).encode("latin-1")


def project_sources(extra=""):
    site = """  PVObject_SiteSimul=pvSite
    Latitude=-10
    Longitude=100
    Altitude=20
    TimeZone=7
  End of PVObject pvSite
"""
    plane = """  PVObject_Plane=pvCollPlane
    NOrient=2
    InclPlMulti=0,0,
    AzimPlMulti=0,90,
  End of PVObject pvCollPlane
"""
    arrays = ""
    for i in (1, 2):
        arrays += f"""  PVObject_Array{i}=pvSubArray
    PVModule=invented.pan
    GInverter=invented.ond
    NModSerie=2
    NStringCh=1
    NInverter=1
    NInvMPPT=1
    NoOrientation={i}
    PowerSharingInverterId=-1
    PQualityModP=-0.5
    PMismMPP=1
    PMismString=0.1
    RSCablagePC={i}
    LIDLoss=0
    {extra}
  End of PVObject pvSubArray
"""
    main = """  PVObject_Main=pvMainArray
    UFactor=20
    SoilingLoss=0.03
  End of PVObject pvMainArray
"""
    vc = (
        "PVObject_=pvVCalcul\n"
        + site
        + plane
        + main
        + arrays
        + "End of PVObject pvVCalcul\n"
    )
    prj = (
        "PVObject_=pvProject\n"
        + site.replace("PVObject_SiteSimul", "PVObject_SitePrj")
        + "End of PVObject pvProject\n"
    )
    return vc.encode(), prj.encode()


def box_node(*, raised=False, open_mesh=False):
    z = [1, 1, 2, 2] if raised else [0, 0, 0, 0]
    points = [
        (0, 0, -1),
        (2, 0, -1),
        (2, -1, -1),
        (0, -1, -1),
        (0, 0, z[0]),
        (2, 0, z[1]),
        (2, -1, z[2]),
        (0, -1, z[3]),
    ]
    faces = [
        [0, 1, 2, 3],
        [4, 7, 6, 5],
        [0, 4, 5, 1],
        [1, 5, 6, 2],
        [2, 6, 7, 3],
        [3, 7, 4, 0],
    ]
    if open_mesh:
        faces.pop()
    stream = [v for face in faces for v in [-1, *face]]
    body = "\n".join(
        f"    Point_{i}=" + ",".join(map(str, p)) for i, p in enumerate(points, 1)
    )
    return f"""  PVObject_Object=pvShdGenObject
    NoObjCreated=3
    DOrigine=0,0,0
    DInclin=0
    DAzimut=0
    NElements={len(faces)}
    NPElements={len(stream)}
{body}
    Faces={','.join(map(str,stream))},
  End of PVObject pvShdGenObject
"""


def scene_bytes(*, mode="foLinear", extra="", raised=False, open_mesh=False):
    tables = ""
    for i, az in [(1, 0), (2, 90)]:
        tables += f"""  PVObject_Table{i}=pvShdArrayTable
    NoObjCreated={i}
    DOrigine={0 if i==1 else 4},0,0.2
    DInclin=0
    DAzimut={az}
    LongShed=2
    LargShed=1
    TypeOrigine=1
    NModInWidth=2
    NModInHeight=1
    ModSpacingX=0
    ModSpacingY=0
    ModuleOrient=moPortrait
    {extra}
  End of PVObject pvShdArrayTable
"""
    factors = ""
    for i, az in [(1, 0), (2, 90)]:
        factors += f"""  PVObject_TableOmbrLin#{i}=pvShdFTable
    FOCalcul={mode}
    InclP=0
    AzimP={az}
    NoOrientPC={i}
  End of PVObject pvShdFTable
"""
    return (
        "\ufeffPVObject_=pvShading\n  Version=7.4.8\n  DisplayedRef=refGeographical\n  NOrient_Shd=2\n  NOrientTables=2\n"
        + tables
        + box_node(raised=raised, open_mesh=open_mesh)
        + factors
        + "End of PVObject pvShading\n"
    ).encode("utf-8")
