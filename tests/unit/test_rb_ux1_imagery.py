"""UX1: overlay image assets, the persisted imagery section, undo, and its isolation from the scene and RES1."""
import json
import struct
import zlib

import pytest

from apps.api.history import design_fingerprint, projection
from apps.api.imagery import MAX_IMAGE_BYTES, ImageryError, image_header
from geometry.scene.serialization import canonical_scene_hash
from tests.unit.test_rb_fix_s2_honest_preflight import Project


def png(width, height, pad=0):
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + ihdr
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + chunk + struct.pack(">I", zlib.crc32(chunk)) + b"\0" * pad


def jpeg(width, height):
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\0\x01\x01\0\0\x01\0\x01\0\0"
    return b"\xff\xd8" + app0 + b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, height, width, 1) + b"\x01\x11\0" + b"\xff\xd9"


def webp(width, height):
    body = b"VP8X" + struct.pack("<I", 10) + b"\0\0\0\0" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WEBP" + body


@pytest.fixture
def p(tmp_path):
    return Project(tmp_path, 18, weather=False, strings=False)


def upload(p, data, name="roof.png"):
    return p.client.post(p.url + "/imagery/assets", params={"filename": name}, content=data)


def overlay(asset, *, width=400, height=300, opacity=0.7, locked=True, points=None):
    return {
        "schema_name": "MapLayerConfiguration", "schema_version": "0.1", "map_configuration_id": "project-imagery",
        "engineering_geometry_authority": "local_metric", "map_measurement_role": "context_only",
        "providers": [{"provider_id": "overlay", "provider_kind": "uploaded_asset", "name": "roof.png", "attribution_required": False}],
        "layers": [{"layer_id": "overlay", "layer_type": "orthophoto", "provider_id": "overlay", "imported_asset_id": asset,
                    "opacity": opacity, "locked": locked,
                    "orthophoto_georeference": {"method": "affine_control_points", "image_width_px": width, "image_height_px": height,
                                                "control_points": points or [
                                                    {"pixel_x": 0, "pixel_y": 0, "local_x_m": -2, "local_y_m": 12},
                                                    {"pixel_x": width, "pixel_y": 0, "local_x_m": 38, "local_y_m": 12},
                                                    {"pixel_x": 0, "pixel_y": height, "local_x_m": -2, "local_y_m": -18}]}}]}


def satellite(template="https://tiles.example.com/{z}/{x}/{y}.jpg?key={key}", reference="browser-key:custom-imagery"):
    return {
        "schema_name": "MapLayerConfiguration", "schema_version": "0.1", "map_configuration_id": "project-imagery",
        "engineering_geometry_authority": "local_metric", "map_measurement_role": "context_only",
        "providers": [{"provider_id": "custom", "provider_kind": "xyz_raster", "name": "My imagery", "tile_url_template": template,
                       "credential_reference": reference, "attribution_required": True, "attribution": "© Example"}],
        "layers": [{"layer_id": "satellite", "layer_type": "aerial_imagery", "provider_id": "custom", "opacity": 0.8}]}


@pytest.mark.parametrize("data,expected", [(png(400, 300), ("image/png", 400, 300)), (jpeg(640, 480), ("image/jpeg", 640, 480)),
                                           (webp(8192, 2), ("image/webp", 8192, 2))])
def test_headers_are_read_without_decoding(data, expected):
    assert image_header(data) == expected


def test_upload_limits_and_formats(p):
    record = upload(p, png(400, 300)).json()
    assert record["asset_id"].startswith("img-") and (record["width_px"], record["height_px"], record["mime"]) == (400, 300, "image/png")
    assert upload(p, png(400, 300)).json()["asset_id"] == record["asset_id"]
    fetched = p.client.get(p.url + f"/imagery/assets/{record['asset_id']}")
    assert fetched.status_code == 200 and fetched.headers["content-type"] == "image/png" and fetched.headers["x-content-type-options"] == "nosniff"
    assert fetched.content == png(400, 300)
    exact = png(8192, 8192, pad=MAX_IMAGE_BYTES - len(png(8192, 8192)))
    assert len(exact) == MAX_IMAGE_BYTES and upload(p, exact).status_code == 200
    assert upload(p, exact + b"\0").status_code == 413
    assert upload(p, png(8193, 10)).json()["detail"]["code"] == "imagery_too_large_px"
    for bad in (b"GIF89a" + b"\0" * 20, b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"\x89PNG\r\n\x1a\n\0\0", b"\xff\xd8\xff\xe0\0\x10"):
        response = upload(p, bad, "bad.bin")
        assert response.status_code == 422, bad
    assert p.client.get(p.url + "/imagery/assets/img-000000000000000000000000").status_code == 404
    assert p.client.get(p.url + "/imagery/assets/..%2Fx").status_code == 404


def test_imagery_edit_is_undoable_and_never_touches_scene_revision_or_fingerprint(p):
    before = p.bundle()
    asset = upload(p, png(400, 300)).json()["asset_id"]
    response = p.client.put(p.url + "/imagery", json=overlay(asset))
    assert response.status_code == 200, response.text
    view = response.json()
    after = p.bundle()
    assert after["imagery"]["layers"][0]["imported_asset_id"] == asset
    assert after["scene"]["revision_id"] == before["scene"]["revision_id"]
    assert canonical_scene_hash(after["scene"]) == canonical_scene_hash(before["scene"])
    assert after["project"]["project_revision"] == before["project"]["project_revision"]
    assert design_fingerprint(after) == design_fingerprint(before) == view["design_fingerprint"]
    assert projection(after) != projection(before)
    entry = view["history"]["past"][-1]
    assert entry["label"] == "Edit imagery"
    undone = p.client.post(p.url + "/undo", json={"expected_project_revision_id": after["project"]["project_revision"]["project_revision_id"], "expected_entry_id": entry["entry_id"]})
    assert undone.status_code == 200, undone.text
    assert "imagery" not in p.bundle()
    # A context-only restore keeps the scene and electrical revisions and the scene hash.
    assert p.bundle()["scene"] == before["scene"]
    assert p.bundle()["electrical_design"]["electrical_revision_id"] == before["electrical_design"]["electrical_revision_id"]
    redone = p.client.post(p.url + "/redo", json={"expected_project_revision_id": undone.json()["bundle"]["project"]["project_revision"]["project_revision_id"],
                                                  "expected_entry_id": undone.json()["history"]["future"][0]["entry_id"]})
    assert redone.status_code == 200, redone.text
    assert p.bundle()["imagery"] == after["imagery"]
    assert canonical_scene_hash(p.bundle()["scene"]) == canonical_scene_hash(before["scene"])
    cleared = p.client.put(p.url + "/imagery", content=b"null", headers={"Content-Type": "application/json"})
    assert cleared.status_code == 200 and "imagery" not in p.bundle()


def test_bundles_without_imagery_keep_their_projection_bytes(p):
    from apps.api.history import SCENE_ENVELOPE, ELECTRICAL_ENVELOPE
    bundle = p.bundle()
    keys = ('pinned_components', 'pinned_electrical_shading_assets', 'electrical_shading_selections', 'loss_settings',
            'optics_thermal_settings', 'shading_accuracy', 'weather_selection')
    state = {k: bundle[k] for k in keys if k in bundle}
    state['project'] = {k: v for k, v in bundle['project'].items() if k != 'project_revision'}
    state['scene'] = {k: v for k, v in bundle['scene'].items() if k not in SCENE_ENVELOPE}
    state['electrical_design'] = {k: v for k, v in bundle['electrical_design'].items() if k not in ELECTRICAL_ENVELOPE}
    state['site_workspace_bootstrap'] = {k: v for k, v in bundle['site_workspace_bootstrap'].items() if k != 'workspace_context'}
    assert projection(bundle) == json.dumps(state, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()


def test_satellite_provider_keeps_only_the_key_reference(p):
    response = p.client.put(p.url + "/imagery", json=satellite())
    assert response.status_code == 200, response.text
    saved = json.dumps(p.bundle()["imagery"])
    assert "browser-key:custom-imagery" in saved and "{key}" in saved


@pytest.mark.parametrize("config", [
    satellite(template="http://tiles.example.com/{z}/{x}/{y}.jpg"),
    satellite(template="https://tiles.example.com/{z}/{x}.jpg"),
    satellite(template="https://tiles.example.com/{z}/{x}/{y}.jpg?key=sk_live_123456789"),
    satellite(template="https://tiles.example.com/{z}/{x}/{y}.jpg?access_token=pk.abcdef"),
    satellite(reference="sk_live_1234567890abcdef"),
    {**satellite(), "map_measurement_role": "authoritative"},
    {**satellite(), "extra": 1},
])
def test_refused_provider_configs_leave_the_project_unchanged(p, config):
    saved = p.path.read_bytes()
    response = p.client.put(p.url + "/imagery", json=config)
    assert response.status_code == 422, response.text
    assert p.path.read_bytes() == saved


def test_refused_overlays_leave_the_project_unchanged(p):
    asset = upload(p, png(400, 300)).json()["asset_id"]
    saved = p.path.read_bytes()
    two = overlay(asset)["layers"][0]["orthophoto_georeference"]["control_points"][:2]
    cases = [overlay("img-000000000000000000000000"), overlay(asset, width=401), overlay(asset, points=two),
             overlay(asset, opacity=0.05), {**overlay(asset), "layers": [{**overlay(asset)["layers"][0], "locked": "yes"}]}]
    for config in cases:
        assert p.client.put(p.url + "/imagery", json=config).status_code == 422, config
        assert p.path.read_bytes() == saved
    nan = overlay(asset)
    nan["layers"][0]["orthophoto_georeference"]["control_points"][0]["local_x_m"] = float("nan")
    with pytest.raises(ImageryError):
        p.service.update_imagery(p.pid, nan)
    assert p.path.read_bytes() == saved


def test_project_delete_removes_imagery(p):
    upload(p, png(400, 300))
    directory = p.service.imagery.root / p.pid
    assert directory.is_dir()
    response = p.client.request("DELETE", p.url, params={"confirm": p.pid})
    assert response.status_code == 200, response.text
    assert response.json()["removed"]["imagery"] is True
    assert not directory.exists()
