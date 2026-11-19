from pathlib import Path

import pandas as pd
import pytest
import yaml

from validation.attribution import (
    common_input_logical_sha256,
    extract_pvsyst_hourly_oracle_metrics,
    infer_subhourly_clipping_correction,
    parse_pvsyst_detailed_output,
    pvsyst_output_to_canonical_weather,
    validate_hourly_oracle_balance,
)


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tests/benchmarks/phase39_hourly_detailed_oracle_20260923.yaml"


def _csv(include_ilpmxsh=True, include_mixloss=False, il_pmin=0.0):
    columns = [
        "date","HSol","AzSol","AngInc","AngProf","GlobHor","DiffHor","BeamHor",
        "T_Amb","WindVel","GlobHorCS","DiffHorCS","BeamTrp","DifITrp","CircTrp",
        "HBndTrp","AlbTrp","GlobTrp","GincThr","GlobInc","BeamInc","CircInc",
        "DifSInc","Alb_Inc","Bm_Gl","DifA_Gl","DifS_Gl","Alb_Gl","GlobIAM",
        "IAMLoss","IAMBLss","IAMCLss","IAMDLss","IAMALss","GlobEff","BeamEff",
        "CircEff","DiffEff","Alb_Eff","FTransp","FIAMGl","FIAMBm","FIAMCrc",
        "FIAMDif","FIAMAlb","FIAMShd","FEffDif","FEffAlb","EArrRef","EArrNom",
        "GIncLss","TempLss","ModQual","MisLoss"
    ]
    if include_mixloss:
        columns.append("MixLoss")
    columns += [
        "OhmLoss","EArrMPP","EArray",
        "TExtON","TArrSS","TArray","TArrWtd","DTArr","DTArrGl","IArray","UArray",
        "ArrayON","InvLoss","IL_Oper","IL_Pmin","IL_Vmin","IL_Pmax"
    ]
    if include_ilpmxsh:
        columns.append("ILPmxSH")
    columns += ["IL_Vmax","IL_Imax","IL_Nigh","InvTemp","Syst_ON","EOutInv","E_Grid"]

    units = {c:"kW" for c in columns}
    units.update({
        "date":"",
        "HSol":"°","AzSol":"°","AngInc":"°","AngProf":"°",
        "GlobHor":"W/m²","DiffHor":"W/m²","BeamHor":"W/m²","T_Amb":"°C",
        "WindVel":"m/s","GlobInc":"W/m²","GlobIAM":"W/m²","GlobEff":"W/m²",
        "TArray":"°C","TExtON":"°C","TArrSS":"°C","TArrWtd":"°C","DTArr":"°C",
        "DTArrGl":"°C","IArray":"A","UArray":"V","ArrayON":"Hour",
        "InvTemp":"°C","Syst_ON":"Hour"
    })

    base = {c:0.0 for c in columns if c != "date"}
    base.update({
        "HSol":45.0,"AzSol":0.0,"AngInc":20.0,"GlobHor":800.0,"DiffHor":200.0,
        "BeamHor":600.0,"T_Amb":30.0,"WindVel":1.5,"GlobInc":850.0,
        "BeamInc":650.0,"CircInc":25.0,"DifSInc":150.0,"Alb_Inc":25.0,
        "GlobIAM":845.0,"GlobEff":845.0,"EArrRef":100.0,"EArrNom":99.5,
        "GIncLss":0.1,"TempLss":9.0,"ModQual":-0.7,"MisLoss":1.8,"OhmLoss":0.9,
        "EArrMPP":88.4,"EArray":87.9,"TArray":45.0,"IArray":100.0,"UArray":879.0,
        "InvLoss":2.5,"IL_Oper":1.9,"IL_Pmax":0.3,"IL_Nigh":0.0,
        "EOutInv":85.9,"E_Grid":85.9
    })
    if include_mixloss:
        base["MixLoss"] = 0.4
        base["EArrMPP"] = 88.0
        base["EArray"] = 87.5
        base["EOutInv"] = 85.5
        base["E_Grid"] = 85.5

    ilpmxsh = 0.2
    if include_ilpmxsh:
        base["ILPmxSH"] = ilpmxsh

    # Make inverter identity exact: 2.5 = 1.9 + 0.3 + 0.2 + 0.1 night
    base["IL_Nigh"] = 0.1

    # IL_Pmin is an inverter low-power loss. It changes InvLoss / inverter
    # output but not the EArrMPP -> EArray DC operating-point displacement.
    if il_pmin:
        base["IL_Pmin"] = float(il_pmin)
        base["InvLoss"] += float(il_pmin)
        base["EOutInv"] -= float(il_pmin)
        base["E_Grid"] -= float(il_pmin)

    # DC displacement: 88.4 - 87.9 = 0.3 + 0.2

    rows=[]
    for hour in range(3):
        row=dict(base)
        row["date"]=f"01/01/90 0{hour}:00"
        rows.append(row)

    header = [
        "PVSYST 8.1.6",
        ",File,File date,Description",
        "Project,Sample.PRJ,23/09/26 12h00,Sample,",
        "Geographical Site,Home.SIT,23/09/26 12h00,Home;Indonesia;Asia;,",
        "Weather data,Home_MN90_SYN_1MIN.MET,23/09/26 11h42,Home;Meteonorm 9.0 dll;Synthetic,",
        "Simulation variant,Sample.VC0,23/09/26 20h00,NoLoss-Hourly,",
        "Simulation date,,23/09/26 20h03",
        "",
        "Simulation:,Hourly values, from 01/01/90, to 31/12/90 ",
        "",
        ",".join(columns),
        ",".join(units[c] for c in columns),
        "",
    ]
    body=[",".join(str(row[c]) for c in columns) for row in rows]
    return ("\n".join(header+body)+"\n").encode()


def test_parser_preserves_pvsyst_metadata_units_and_interval_start_semantics():
    output=parse_pvsyst_detailed_output(_csv())

    assert output.metadata["pvsyst_version"]=="8.1.6"
    assert output.metadata["variant_id"]=="VC0"
    assert output.metadata["weather_filename"]=="Home_MN90_SYN_1MIN.MET"
    assert output.metadata["interval_seconds"]==3600
    assert output.metadata["timestamp_convention"]=="interval_start"
    assert output.metadata["solar_representative_time_policy"]=="interval_midpoint"
    assert output.units["GlobHor"]=="W/m²"
    assert len(output.frame)==3


def test_ilpmxsh_direct_and_inferred_paths_reconcile():
    direct=parse_pvsyst_detailed_output(_csv(True))
    inferred=parse_pvsyst_detailed_output(_csv(False))

    direct_values,direct_meta=infer_subhourly_clipping_correction(direct)
    inferred_values,inferred_meta=infer_subhourly_clipping_correction(inferred)

    assert direct_meta["method"]=="source_column"
    assert inferred_meta["method"]=="inferred_from_inverter_loss_identity"
    assert direct_values.to_list()==pytest.approx([0.2,0.2,0.2])
    assert inferred_values.to_list()==pytest.approx([0.2,0.2,0.2])


def test_hourly_balance_and_metric_extraction_are_loss_explicit():
    output=parse_pvsyst_detailed_output(_csv())
    balance=validate_hourly_oracle_balance(output)
    assert balance["status"]=="passed"

    metrics=extract_pvsyst_hourly_oracle_metrics(output)
    assert metrics["glob_hor_kwh_m2"]==pytest.approx(2.4)
    assert metrics["diff_hor_kwh_m2"]==pytest.approx(0.6)
    assert metrics["array_virtual_mpp_kwh"]==pytest.approx(265.2)
    assert metrics["e_array_kwh"]==pytest.approx(263.7)
    assert metrics["inverter_subhourly_clipping_correction_kwh"]==pytest.approx(0.6)
    assert metrics["e_grid_kwh"]==pytest.approx(257.7)


def test_il_pmin_is_inverter_loss_not_dc_operating_displacement():
    output = parse_pvsyst_detailed_output(_csv(il_pmin=0.4))
    balance = validate_hourly_oracle_balance(output)

    assert balance["status"] == "passed"
    assert balance["max_residuals"][
        "dc_operating_displacement_balance_max_abs_kw"
    ] == pytest.approx(0.0, abs=1e-12)


def test_mixed_orientation_loss_is_explicit_in_array_balance_and_metrics():
    output=parse_pvsyst_detailed_output(_csv(include_mixloss=True))
    balance=validate_hourly_oracle_balance(output)

    assert balance["status"]=="passed"
    assert balance["mixed_orientation_loss"]=={
        "source_column_present": True,
        "column": "MixLoss",
        "signed_loss_convention": "positive_loss",
    }

    metrics=extract_pvsyst_hourly_oracle_metrics(output)
    assert metrics["mixed_orientation_loss_kwh"]==pytest.approx(1.2)
    assert metrics["array_virtual_mpp_kwh"]==pytest.approx(264.0)
    assert metrics["e_grid_kwh"]==pytest.approx(256.5)


def test_weather_adapter_keeps_horizontal_inputs_and_does_not_inject_dni():
    output=parse_pvsyst_detailed_output(_csv())
    weather=pvsyst_output_to_canonical_weather(
        output,
        weather_dataset_id="wx-p39h",
        revision_id="wx-p39h-r1",
        site_id="home",
        timezone="UTC+07:00",
        location={"latitude_deg":-6.4245,"longitude_deg":106.8307,"elevation_m":82},
        source_utc_offset_hours=7.0,
        upstream_weather_resolution_seconds=60,
    )

    assert list(weather.series.columns)==[
        "ghi_w_m2","dhi_w_m2","ambient_temperature_c","wind_speed_m_s"
    ]
    assert "dni_w_m2" not in weather.series
    assert weather.series.index.tz is not None
    assert weather.dataset["native_resolution_seconds"]==3600
    assert weather.dataset["series_resolution_seconds"]==3600
    assert weather.dataset["upstream_generation"]["base_resolution_seconds"]==60
    assert weather.dataset["time_semantics"]["representative_time"]["policy"]=="interval_midpoint"


def test_frozen_hourly_oracle_manifest_records_four_external_source_hashes():
    manifest=yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))

    assert manifest["oracle_id"]=="P39-HR1-PVSYST816-20260923"
    assert manifest["source_weather"]["underlying_resolution_seconds"]==60
    assert set(manifest["cases"])=={"VC0","VC2","VC4","VC6"}
    assert manifest["common_weather_geometry_optical_logical_sha256"]==(
        "894a678a78de755352a5acb2d3433466c473ba221ad888412611d256f91e0ea4"
    )
    assert manifest["cases"]["VC0"]["direct_ilpmxsh"] is True
    assert manifest["cases"]["VC6"]["annual"]["ilpmxsh_inferred_kwh"]==pytest.approx(3824.6276)
