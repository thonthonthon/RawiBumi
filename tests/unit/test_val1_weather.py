import numpy as np
import pytest
from validation.pvsyst_benchmark.reference import read_reference
from validation.pvsyst_benchmark.weather_adapter import recover_weather, attach_weather
from tests.fixtures.val1.synthetic import csv_bytes

SITE = {
    "latitude_deg": -10,
    "longitude_deg": 100,
    "elevation_m": 20,
    "utc_offset_hours": 7,
}


def test_literal_dni_preservation_fixed_time_provenance_and_wind_omission():
    r = read_reference(csv_bytes(), expected_rows=3)
    r.frame.loc[r.frame.index[1], "WindVel"] = -0.01
    before = r.frame.copy(deep=True)
    w, receipt = recover_weather(r, site=SITE, label="P3", uv=0, omit_wind=True)
    np.testing.assert_allclose(w.series.dni_w_m2, 120, rtol=0, atol=1e-12)
    assert (
        w.series.index[0].hour == 0
        and w.series.index[0].utcoffset().total_seconds() == 7 * 3600
    )
    assert (
        "wind_speed_m_s" not in w.series
        and receipt["wind_omitted"]
        and receipt["verified_uv"] == 0
    )
    assert (
        receipt["source_sha256"] == r.source_sha256
        and w.dataset["source_format"] == "pvsyst_hourly_results_export"
    )
    assert r.frame.equals(before)
    with pytest.raises(ValueError, match="Uv"):
        recover_weather(r, site=SITE, label="P3", uv=1, omit_wind=True)


def test_night_zero_low_sun_no_floor_and_bad_inputs():
    r = read_reference(csv_bytes(), expected_rows=3)
    r.frame.loc[r.frame.index[0], ["BeamHor", "HSol"]] = [0, -10]
    r.frame.loc[r.frame.index[1], ["BeamHor", "HSol"]] = [1, 0.5]
    w, _ = recover_weather(r, site=SITE, label="P2", uv=0)
    assert w.series.dni_w_m2.iloc[0] == 0
    assert w.series.dni_w_m2.iloc[1] == pytest.approx(1 / np.sin(np.deg2rad(0.5)))
    r.frame.loc[r.frame.index[1], "HSol"] = 0
    with pytest.raises(ValueError, match="solar height"):
        recover_weather(r, site=SITE, label="P2", uv=0)


def test_real_weather_store_receipt_only_changes_weather_selection(tmp_path):
    from fastapi.testclient import TestClient
    from apps.api.server import create_app

    app = create_app(
        store_root=tmp_path / "projects", library_root=tmp_path / "library"
    )
    with TestClient(app) as c:
        response = c.post(
            "/api/projects",
            json={
                "name": "P2 synthetic",
                "latitude_deg": -10,
                "longitude_deg": 100,
                "timezone": "Etc/GMT-7",
            },
        )
        assert response.status_code == 201, response.text
        body = response.json()
        pid = body["bundle"]["project"]["project_id"]
        before = app.state.project_service.get_bundle(pid)
        w, receipt = recover_weather(
            read_reference(csv_bytes(), expected_rows=3), site=SITE, label="P2", uv=0
        )
        attached = attach_weather(app, pid, w, receipt)
        after = app.state.project_service.get_bundle(pid)
        assert (
            after["scene"] == before["scene"]
            and after["electrical_design"] == before["electrical_design"]
        )
        assert (
            after["weather_selection"]["revision_id"]
            == attached["selection"]["revision_id"]
        )
        assert (
            app.state.study_service.weather.manifest(pid, w.dataset["revision_id"])[
                "source_sha256"
            ]
            == receipt["source_sha256"]
        )
