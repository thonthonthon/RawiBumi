import pytest
from validation.pvsyst_benchmark.source import read_objects, SourceError
from validation.pvsyst_benchmark.project import extract_project
from tests.fixtures.val1.synthetic import project_sources


def test_two_arrays_produce_exact_pinned_request_plan_and_unsupported_ledger():
    vc, prj = project_sources("BrandNewPhysics=1")
    p = extract_project(
        read_objects(vc),
        read_objects(prj),
        label="P2",
        components={"invented.ond": "invented-r2"},
    )
    assert [s["module_count"] for s in p.subarrays] == [2, 2]
    assert [s["orientation"] for s in p.subarrays] == [1, 2]
    assert [o["azimuth_deg"] for o in p.orientations] == [0, 270]
    assert len(p.requests) == 2 and all(
        r["json"]["inverter_definition_revision_id"] == "invented-r2"
        for r in p.requests
    )
    assert any(
        f.path == "pvSubArray.BrandNewPhysics" and f.blocking for f in p.unsupported
    )
    assert any(
        x.get("source") == "pvSubArray[1].RSCablagePC" and x["value"] == 0.01
        for x in p.source_ledger
    )
    assert p.settings["headline_fidelity"] == "standard"
    assert (
        p.settings["optics_thermal"]["overrides"]["thermal"]["irradiance_basis"]
        == "effective"
    )


@pytest.mark.parametrize(
    "edit",
    [
        lambda x: x.replace(b"NOrient=2", b"NOrient=3"),
        lambda x: x.replace(b"NModSerie=2", b"NModSerie=0"),
        lambda x: x.replace(b"End of PVObject pvVCalcul", b"End of PVObject pvSite"),
        lambda x: x.replace(b"UFactor=20", b"UFactor=nan"),
    ],
)
def test_structural_or_scientific_mismatch_refused(edit):
    vc, prj = project_sources()
    with pytest.raises(SourceError):
        extract_project(read_objects(edit(vc)), read_objects(prj), label="P2")


def test_deferred_case_and_site_mismatch():
    vc, prj = project_sources()
    with pytest.raises(SourceError):
        extract_project(read_objects(vc), read_objects(prj), label="P1")
    p = extract_project(
        read_objects(vc),
        read_objects(prj.replace(b"Longitude=100", b"Longitude=101")),
        label="P3",
    )
    assert any(f.code == "site_mismatch" for f in p.unsupported)
