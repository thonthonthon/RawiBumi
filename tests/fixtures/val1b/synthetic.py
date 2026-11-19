"""Generate all weather/source data in-test; no private files are read."""
from pathlib import Path
import csv

import numpy as np
import pandas as pd
import pvlib

from tests.fixtures.val1.synthetic import project_sources, scene_bytes


def assembly_sources(root):
    root.mkdir()
    vc, prj = project_sources()
    vc = vc.replace(b"NModSerie=2", b"NModSerie=18")
    scene = scene_bytes().replace(b"LongShed=2\n", b"LongShed=30\n").replace(
        b"LargShed=1\n", b"LargShed=3\n").replace(b"NModInWidth=2\n", b"NModInWidth=18\n").replace(
        b"DOrigine=4,0,0.2", b"DOrigine=100,0,0.2")
    for name, data in [("invented.VC0", vc), ("invented.PRJ", prj), ("invented.SHD", scene)]:
        (root/name).write_bytes(data)
    repo = Path(__file__).resolve().parents[3]
    pan = (repo/"tests/fixtures/panond/synthetic_module.pan").read_text()
    profile = """  PVObject_IAM=pvIAM
    IAMMode=UserProfile
    IAMProfile=TCubicProfile
      NPtsMax=5
      NPtsEff=5
      Mode=1
      Point_1=0,1
      Point_2=20,0.999
      Point_3=40,0.98
      Point_4=60,0.9
      Point_5=90,0
    End of TCubicProfile
  End of PVObject pvIAM
"""
    (root/"invented.pan").write_text(pan.replace("End of PVObject pvModule", profile+"End of PVObject pvModule"))
    # Fictional current completion, explicitly sufficient for the synthetic module.
    specification = {
        "model_token":"FICT-10", "identity_checks":{"mppt_template.count":2},
        "fields":{"mppt_template.max_operating_current_a":30.,"mppt_template.max_short_circuit_current_a":40.},
        "source":{"document":"Fictional test datasheet", "page_or_section":"Inputs", "url":"https://example.com/fictional"},
    }
    index = pd.date_range("1990-01-01", periods=8760, freq="h", tz="Etc/GMT-7")
    solar = pvlib.solarposition.get_solarposition(index+pd.Timedelta(minutes=30), -10.,100.,altitude=20.)
    height = solar["elevation"].to_numpy()
    beam = np.where(height>0,500*np.sin(np.deg2rad(height)),0.)
    diffuse = np.where(height>0,30*np.sin(np.deg2rad(height)),0.)
    with (root/"invented.CSV").open("w",encoding="latin-1",newline="") as stream:
        stream.write("PVSYST V7.4.8\nProject;P2 Fictional\nSimulation variant;invented.VC0\n")
        writer=csv.writer(stream,delimiter=";",lineterminator="\n")
        writer.writerow(["date","GlobHor","DiffHor","BeamHor","T_Amb","WindVel","HSol","AzSol","E_Grid"])
        writer.writerow(["","W/m²","W/m²","W/m²","°C","m/s","°","°","kW"])
        for i,t in enumerate(index):
            writer.writerow([t.strftime("%d/%m/%y %H:%M"),beam[i]+diffuse[i],diffuse[i],beam[i],20.,1.,height[i],0.,0.])
    return {"csv":str(root/"invented.CSV"),"vc":str(root/"invented.VC0"),"prj":str(root/"invented.PRJ"),
            "shd":str(root/"invented.SHD"),"modules":[str(root/"invented.pan")],
            "inverter":str(repo/"tests/fixtures/val1/invented.ond"),"completion":specification}
