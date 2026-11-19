"""Strict hourly reference reader with explicit units and aggregation bases."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from hashlib import sha256
from io import StringIO
from pathlib import Path
import csv
import re

import numpy as np
import pandas as pd


class ReferenceError(ValueError):
    pass


class Basis(str, Enum):
    WEATHER = "weather"
    SOLAR = "solar_state"
    ORIENTATION_1 = "orientation_1"
    ORIENTATION_2 = "orientation_2"
    PLANT = "plant"
    UNAVAILABLE = "unavailable"


WEATHER = {"GlobHor", "DiffHor", "BeamHor", "T_Amb", "WindVel"}
SOLAR = {"HSol", "AzSol"}
ORIENTATION = set(
    "AngInc AngProf BeamTrp DifITrp CircTrp HBndTrp AlbTrp GlobTrp BeamInc CircInc DifSInc Alb_Inc BeamEff CircEff DiffEff Alb_Eff Bm_Gl DifA_Gl DifS_Gl Alb_Gl FShdBm FShdCrc FShdDif FShdAlb FIAMBm FIAMCrc FIAMDif FIAMAlb FSlgBm FSlgCrc FSlgDif FSlgAlb".split()
)
PLANT_POWER = set(
    "EArray E_Grid EArrRef EArrNom GIncLss TempLss ModQual LIDLoss MisLoss OhmLoss MixLoss EArrMPP InvLoss IL_Oper IL_Pmin IL_Vmin IL_Pmax IL_Vmax IL_Imax IL_Nigh EOutInv EACOhmL EUseful".split()
)
PLANT_IRRADIANCE = {"GlobInc", "GlobEff"}
IRRADIANCE = set(
    "GlobInc GlobEff GlobHor DiffHor BeamHor BeamTrp DifITrp CircTrp HBndTrp AlbTrp GlobTrp GincThr BeamInc CircInc DifSInc Alb_Inc GlobShd ShdLoss ShdBLss ShdCLss ShdDLss ShdALss GlobIAM IAMLoss IAMBLss IAMCLss IAMDLss IAMALss GlobSlg SlgLoss SlgBLss SlgCLss SlgDLss SlgALss BeamEff CircEff DiffEff Alb_Eff".split()
)
FACTORS = set(
    "PR Bm_Gl DifA_Gl DifS_Gl Alb_Gl FTransp FShdGl FShdBm FShdCrc FShdDif FShdAlb FIAMGl FIAMBm FIAMCrc FIAMDif FIAMAlb FSlgGl FSlgBm FSlgCrc FSlgDif FSlgAlb FIAMShd FEffDif FEffAlb Lcr Lsr".split()
)
TEMPERATURES = {"T_Amb", "TExtON", "TArray", "TArrWtd", "DTArr", "DTArrGl"}
EFFICIENCIES = set("EffArrR EffArrC EffSysR EffSysC EffInvB EffInvR".split())
FINANCIAL = set(
    "TotInstCost ModuleCost InverterCost BatteryCost OwnFunds TotLoan AvgOpCost_yr LCOE NPV IRR PaybackPeriod ROI".split()
)
UNITS = {k: {"W/m²"} for k in IRRADIANCE}
UNITS.update({k: {"ratio"} for k in FACTORS})
UNITS.update({k: {"°C"} for k in TEMPERATURES})
UNITS.update({k: {"kW"} for k in PLANT_POWER})
UNITS.update({k: {"%"} for k in EFFICIENCIES})
# Auxiliary source fields are retained without assigning physical meaning.
UNITS.update({k: {"ratio", "kW"} for k in FINANCIAL})
UNITS.update(
    {
        "date": {""},
        "HSol": {"°"},
        "AzSol": {"°"},
        "AngInc": {"°"},
        "AngProf": {"°"},
        "WindVel": {"m/s"},
        "IArray": {"A"},
        "UArray": {"V"},
        "ArrayON": {"Hour"},
        "Syst_ON": {"Hour"},
        "Yr": {"kWh/m²/day"},
        **{k: {"kWh/kWp/day"} for k in ("Ya", "Yf", "Lc", "Ls")},
    }
)
REQUIRED = {
    "date",
    "GlobHor",
    "DiffHor",
    "BeamHor",
    "T_Amb",
    "WindVel",
    "HSol",
    "AzSol",
}


def basis_of(column: str, *, proven_bases: dict[str, Basis] | None = None) -> Basis:
    # Raw FIAMAlb is not a bounded physical modifier in these exports.
    if column == "FIAMAlb":
        return Basis.UNAVAILABLE
    if proven_bases is not None:
        return Basis(proven_bases.get(column, Basis.UNAVAILABLE))
    if column == "AngInc":
        return Basis.ORIENTATION_1
    if column in WEATHER:
        return Basis.WEATHER
    if column in SOLAR:
        return Basis.SOLAR
    if column in ORIENTATION:
        return Basis.ORIENTATION_2
    if column in PLANT_POWER | PLANT_IRRADIANCE | {"TArray", "TArrWtd"}:
        return Basis.PLANT
    return Basis.UNAVAILABLE


@dataclass(frozen=True)
class Reference:
    frame: pd.DataFrame
    units: dict[str, str]
    metadata: tuple[tuple[str, ...], ...]
    source_sha256: str
    version: str
    timestamp_convention: str = "interval_start"
    solar_evaluation_policy: str = "midpoint_with_reference_sunlit_boundary_difference"

    @property
    def variant_filename(self):
        rows = [r for r in self.metadata if r and r[0].strip() == "Simulation variant"]
        if len(rows) != 1 or len(rows[0]) < 2:
            return None
        return rows[0][1].strip().replace(chr(92), "/").rsplit("/", 1)[-1]

    def basis(self, column: str, *, proven_bases: dict[str, Basis] | None = None) -> Basis:
        if column not in self.frame:
            return Basis.UNAVAILABLE
        return basis_of(column, proven_bases=proven_bases)


def read_reference(
    source: Path | bytes,
    *,
    expected_rows: int = 8760,
    expected_start: str = "1990-01-01T00:00:00",
) -> Reference:
    data = source if isinstance(source, bytes) else Path(source).read_bytes()
    text = data.decode("iso-8859-1")
    lines = text.splitlines()
    if not lines or not lines[0].strip().upper().startswith("PVSYST"):
        raise ReferenceError("missing version header")
    match = re.search(r"(?<!\d)7\.4\.8(?!\d)", lines[0])
    if not match:
        raise ReferenceError("unsupported reference version")
    header = next(
        (
            (i, sep)
            for i, line in enumerate(lines)
            for sep in (";", ",")
            if line.startswith("date" + sep)
        ),
        None,
    )
    if header is None:
        raise ReferenceError("missing named header")
    offset, separator = header
    rows = list(csv.reader(lines[offset:], delimiter=separator, strict=True))
    if len(rows) < 3:
        raise ReferenceError("missing units or data")
    names, units = [x.strip() for x in rows[0]], [x.strip() for x in rows[1]]
    if len(names) != len(units) or len(names) != len(set(names)):
        raise ReferenceError("duplicate columns or unequal units/header lengths")
    unknown = set(names) - UNITS.keys()
    if unknown:
        raise ReferenceError("unknown columns: " + ", ".join(sorted(unknown)))
    if not REQUIRED <= set(names):
        raise ReferenceError(
            "missing required columns: " + ", ".join(sorted(REQUIRED - set(names)))
        )
    for name, unit in zip(names, units):
        if unit not in UNITS[name]:
            raise ReferenceError(f"unknown unit for {name}")
    body = rows[2:]
    # Export formatting may separate the units from the first observation.
    # Only boundary blanks are structural; an interior blank remains an error.
    while body and not any(v.strip() for v in body[0]):
        body = body[1:]
    while body and not any(v.strip() for v in body[-1]):
        body = body[:-1]
    if len(body) != expected_rows or any(len(row) != len(names) for row in body):
        raise ReferenceError("missing rows or unequal row width")
    date_position = names.index("date")
    try:
        index = pd.DatetimeIndex(
            [
                datetime.strptime(r[date_position].strip(), "%d/%m/%y %H:%M")
                for r in body
            ]
        )
        values = {
            k: [float(r[j]) for r in body] for j, k in enumerate(names) if k != "date"
        }
    except (ValueError, OverflowError) as exc:
        raise ReferenceError("invalid timestamp or numeric cell") from exc
    expected = pd.date_range(expected_start, periods=expected_rows, freq="h")
    if not index.equals(expected):
        raise ReferenceError(
            "timestamps must be complete, unique, ordered interval starts"
        )
    frame = pd.DataFrame(values, index=index)
    if not np.isfinite(frame.to_numpy()).all():
        raise ReferenceError("non-finite numeric cell")
    metadata = tuple(
        tuple(row) for row in csv.reader(lines[:offset], delimiter=separator)
    )
    return Reference(
        frame,
        dict(zip(names, units)),
        metadata,
        sha256(data).hexdigest(),
        match.group(),
    )


def canonical_azimuth(azimuth, *, southern: bool):
    values = np.asarray(azimuth, dtype=float)
    if not np.isfinite(values).all():
        raise ReferenceError("non-finite source azimuth")
    return (-values if southern else values + 180) % 360
