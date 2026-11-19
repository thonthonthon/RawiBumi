"""C1: identifier formats and path containment for RawiBumi's file stores (apps/api/safe_paths.py)."""
from pathlib import Path

import pytest

from apps.api.safe_paths import InvalidStorePath, contained, relative_member, reference_uri, safe_component
from weather.providers.snapshot_store import FileSystemWeatherSnapshotStore

# Values that must never be accepted as a single storage-path component, whatever the kind.
MALFORMED = [
    "", ".", "..", "../x", "x/..", "a/../b", "a/b", "a\\b", "/abs", "C:\\x", "C:x", "\\\\server\\share",
    "%2e%2e%2f", "..%2fx", "a\x00b", "abc\n", "a\nb", "\t", " x", "x ", "．．／x", "a" * 300,
]

# Every kind with the identifiers the product generates today (Step A survey), all of which must keep working.
VALID = {
    "project": ["project-0123456789", "proj-ref-001", "project-example-001", "a" * 128],
    "weather": ["wx-project-0123456789-0123456789ab-r1", "wx-ref-001-r1",
                f"wx-{'a' * 128}-0123456789ab-r1"],
    "run": ["run-project-0123456789-0123456789ab", "fixture-run", f"run-{'a' * 128}-0123456789ab"],
    "component": ["mod-rawibumi-uat-550-r1", "inv-rawibumi-uat-150k-r1", "independent-r1"],
    "library_revision": ["lib-mod-jinko-abc123-r1", "lib-inv-huawei-sun2000-0a1b2c-r12"],
    "hash": ["0" * 64, "0123456789abcdef" * 4],
    "imagery": ["img-" + "0" * 24, "img-0123456789abcdef01234567"],
    "backup": ["20261117T123456123456Z-r3", "20261117T123456123456Z-rx",
               "20261117T123456123456Z-r12-protected-import-replace"],
    "member": ["project.json", ".hidden", "weather-series.parquet", "chunk-00000001.json"],
}


@pytest.mark.parametrize("kind,value", [(k, v) for k, values in VALID.items() for v in values])
def test_generated_identifiers_are_accepted(kind, value):
    assert safe_component(value, kind) == value


@pytest.mark.parametrize("kind", sorted(VALID))
@pytest.mark.parametrize("value", MALFORMED)
def test_malformed_identifiers_are_rejected_for_every_kind(kind, value):
    with pytest.raises(InvalidStorePath):
        safe_component(value, kind)


@pytest.mark.parametrize("value", [None, 7, b"project", ["project"]])
def test_non_text_identifiers_are_rejected(value):
    with pytest.raises(InvalidStorePath):
        safe_component(value, "project")


def test_rejection_message_never_contains_the_value():
    with pytest.raises(InvalidStorePath) as caught:
        safe_component("../secret-name", "weather")
    assert "secret-name" not in str(caught.value) and ".." not in str(caught.value)


def test_contained_keeps_paths_inside_their_root(tmp_path):
    root = tmp_path / "root"
    (root / "inner").mkdir(parents=True)
    assert contained(root, root / "inner" / "file.json") == root / "inner" / "file.json"
    for outside in (root / ".." / "elsewhere", tmp_path, Path("/"), root):
        with pytest.raises(InvalidStorePath):
            contained(root, outside)


def test_contained_follows_links_to_their_real_location(tmp_path):
    root, elsewhere = tmp_path / "root", tmp_path / "elsewhere"
    root.mkdir(); elsewhere.mkdir()
    (root / "link").symlink_to(elsewhere, target_is_directory=True)
    with pytest.raises(InvalidStorePath):
        contained(root, root / "link" / "file.json")


@pytest.mark.parametrize("value", ["../x", "a/../b", "/abs", "a//b", "a/./b", "", "a\\b", "a/b\x00"])
def test_relative_member_paths_are_checked_component_by_component(value):
    with pytest.raises(InvalidStorePath):
        relative_member(value)


def test_relative_member_accepts_ordinary_nested_paths():
    assert relative_member("detailed-electrical-intervals/chunk-00000001.json").as_posix() == \
        "detailed-electrical-intervals/chunk-00000001.json"


@pytest.mark.parametrize("value", [
    "weather-snapshot://sha256/" + "0" * 64,
    "file:///srv/rawibumi/runs/project-0123456789/run-x/timeseries.parquet",
])
def test_structured_references_are_accepted(value):
    assert reference_uri(value) == value


@pytest.mark.parametrize("value", [
    "weather-snapshot://sha256/../" + "0" * 62, "weather-snapshot://md5/" + "0" * 64,
    "file:///srv/../etc/x", "file://host/srv/x", "http://example.invalid/x", "file:///srv/x\x00",
])
def test_malformed_structured_references_are_rejected(value):
    with pytest.raises(InvalidStorePath):
        reference_uri(value)


@pytest.mark.parametrize("digest,suffix", [("0" * 63, ".json"), ("../" + "0" * 61, ".json"),
                                           ("0" * 64, "/../x"), ("0" * 64, ".JSON"), ("0" * 64 + "\n", ".json")])
def test_weather_snapshot_store_rejects_malformed_names(tmp_path, digest, suffix):
    with pytest.raises(ValueError):
        FileSystemWeatherSnapshotStore(tmp_path).path_for(digest, suffix=suffix)


def test_weather_snapshot_store_keeps_valid_names(tmp_path):
    path = FileSystemWeatherSnapshotStore(tmp_path).path_for("ab" + "0" * 62, suffix=".weather")
    assert path == tmp_path / "sha256" / "ab" / ("ab" + "0" * 62 + ".weather")
