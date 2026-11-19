"""Independent integer, nominal-power and HTTP safety oracles on fictional data."""
from copy import deepcopy
from types import SimpleNamespace
import pytest

from validation.pvsyst_benchmark.headline_electrical import (
    balanced_counts, spatial_module_order, topology_commands, reference_power, loss_patch,
)
from validation.pvsyst_benchmark.headline_assembly import AssemblyHTTP, AssemblyError, assert_complete_readiness


def synthetic_plan():
    sub=[]
    for i,strings,inverters in [(1,3,2),(2,2,1)]:
        sub.append({"index":i,"module_ref":"fictional.pan","strings":strings,"inverters":inverters,
                    "modules_per_string":2,"lid_fraction":0.,"module_mismatch_fraction":.02,
                    "string_mismatch_fraction":.001,"dc_wiring_stc_fraction":.01*i,"quality_fraction":-.01*i})
    return SimpleNamespace(label="P2",subarrays=sub,settings={"soiling_fraction":.03})


def layout():
    fields=[];modules=[]
    for field,n in [("f1",6),("f2",4)]:
        table={"table_id":"table-1","anchor_xyz_m":[0,0,2],"anchor_convention":"lower_left",
               "rectangle":{"width_m":n,"height_m":1},"tilt_deg":0.,"azimuth_deg":180.}
        fields.append({"pv_field_id":field,"tables":[table]})
        modules.extend({"module_instance_id":field+str(i),"pv_field_id":field,"table_id":"table-1",
                        "row_index":0,"column_index":i,"enabled":True} for i in range(n))
    return {"pv_fields":fields,"module_instances":list(reversed(modules))}


def topology():
    return {"electrical_revision_id":"e1","mppt_instances":[
        {"mppt_instance_id":f"{i}-m{j}","inverter_instance_id":i,"index":j,"enabled":True}
        for i in ["i1","i2","i3"] for j in [2,1]]}


def test_balanced_two_subarray_assignment_and_exact_module_path():
    s=layout();e=topology();p=synthetic_plan();g={1:["i1","i2"],2:["i3"]}
    assert balanced_counts(3,2)==[2,1] and balanced_counts(2,2)==[1,1]
    assert spatial_module_order(s,"f1")==["f1"+str(i) for i in range(6)]
    commands,rows=topology_commands(s,e,p,{"f1":1,"f2":2},g)
    assert len(commands)==10 and len(rows)==5
    assert [r["inverter_id"] for r in rows]==["i1","i1","i2","i3","i3"]
    assert [r["mppt_index"] for r in rows]==[1,2,1,1,2]
    assert rows[0]["module_ids"]==["f10","f11"]
    assert {m for r in rows for m in r["module_ids"]}=={m["module_instance_id"] for m in s["module_instances"]}
    assert topology_commands(deepcopy(s),deepcopy(e),p,{"f1":1,"f2":2},g)==(commands,rows)
    s["module_instances"].pop()
    with pytest.raises(ValueError,match="counts"):topology_commands(s,e,p,{"f1":1,"f2":2},g)


def test_spatial_order_precedes_creation_order_without_snapping():
    s=layout();f=s["pv_fields"][0];t=deepcopy(f["tables"][0]);t.update(table_id="table-2",anchor_xyz_m=[0,5,2]);f["tables"].append(t)
    s["module_instances"].append({"module_instance_id":"upper","pv_field_id":"f1","table_id":"table-2","row_index":0,"column_index":0,"enabled":True})
    assert spatial_module_order(s,"f1")[0]=="upper"


def test_p_ref_uses_nominal_and_hand_curve_without_clipping_or_quality():
    p=synthetic_plan();g={1:["i1","i2"],2:["i3"]}
    modules={"fictional.pan":{"stc":{"nominal_power_w":100.,"pmp_w":900.,"vmp_v":10.}}}
    inv={"ac_limits":{"nominal_ac_power_w":100.},"efficiency_model":{"curves":[
        {"dc_voltage_v":v,"points":[{"dc_power_w":0.,"ac_power_w":0.},{"dc_power_w":2000.,"ac_power_w":1800.}]} for v in [10.,20.,30.]]}}
    r=reference_power(p,modules,inv,g)
    assert r["reference_power_w"]==pytest.approx(900.)
    assert [i["dc_ac_ratio"] for i in r["inverters"]]==[4.,2.,4.]
    assert r["inverters"][0]["unclipped_stc_ac_w"]>inv["ac_limits"]["nominal_ac_power_w"]
    patch=loss_patch(p,{"electrical_design":{"electrical_revision_id":"e1"}},g,r["reference_power_w"],.01)
    o=patch["overrides"]
    assert o["circuit_overrides"]["inverters"]=={
        "i1":{"dc_wiring_stc_fraction":.01,"module_quality_fraction":-.01},
        "i2":{"dc_wiring_stc_fraction":.01,"module_quality_fraction":-.01},
        "i3":{"dc_wiring_stc_fraction":.02,"module_quality_fraction":-.02}}
    assert o["plant_ac_wiring"]["reference_power_w"]==pytest.approx(900.)
    assert o["annual_degradation_fraction"]==o["unavailability_fraction"]==o["ac_wiring_nominal_fraction"]==0.
    assert o["transformer"]=={"enabled":False}


def test_readiness_must_account_for_every_placed_module_once():
    s=layout();ids=[m["module_instance_id"] for m in s["module_instances"]]
    ready={"ready":True,"findings":[],"execution_plan":{"groups":[{"module_instance_ids":ids}]}}
    assert assert_complete_readiness(ready,s)["excluded_module_count"]==0
    for bad in [dict(ready,ready=False),dict(ready,findings=[{"severity":"blocking_error"}]),
                dict(ready,findings=[{"rule_id":"MODULES_NOT_SIMULATED","severity":"warning"}]),
                dict(ready,execution_plan={"groups":[{"module_instance_ids":ids[:-1]}]}),
                dict(ready,execution_plan={"groups":[{"module_instance_ids":ids+ids[:1]}]})]:
        with pytest.raises(AssemblyError):assert_complete_readiness(bad,s)


def test_assembly_http_never_dispatches_simulation():
    class ForbiddenClient:
        app=None
        def request(self,*args,**kwargs):raise AssertionError("must not fetch")
    with pytest.raises(AssemblyError,match="not authorized"):
        AssemblyHTTP(ForbiddenClient(),{"http":[]}).post("/api/projects/fictional/simulate",json={})
