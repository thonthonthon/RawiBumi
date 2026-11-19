from pathlib import Path
import pytest
from validation.pvsyst_benchmark.reference import (
    read_reference,
    ReferenceError,
    Basis,
    canonical_azimuth,
)
from tests.fixtures.val1.synthetic import csv_bytes


def read(data):
    return read_reference(data, expected_rows=3)


def test_named_columns_encoding_and_absent_columns():
    data = csv_bytes(
        columns=[
            "date",
            "AzSol",
            "HSol",
            "WindVel",
            "T_Amb",
            "BeamHor",
            "DiffHor",
            "GlobHor",
            "E_Grid",
        ]
    )
    r = read(data)
    assert r.frame.GlobHor.tolist() == [120] * 3
    assert any("café" in cell for row in r.metadata for cell in row)
    assert r.timestamp_convention == "interval_start" and r.frame.index[0].hour == 0
    assert r.basis("E_Grid") == Basis.PLANT and r.basis("CircEff") == Basis.UNAVAILABLE
    assert read(csv_bytes(optional=["CircEff"])).basis("CircEff") == Basis.ORIENTATION_2
    assert r.basis("GlobShd") == Basis.UNAVAILABLE
    assert canonical_azimuth([-90, 0, 90], southern=True).tolist() == [90, 0, 270]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.replace("date;GlobHor", "date;GlobHor;GlobHor").replace(
            ";W/m²;", ";W/m²;W/m²;", 1
        ),
        lambda s: s.rsplit("\n", 1)[0],
        lambda s: s.replace("01/01/90 01:00", "01/01/90 00:00"),
        lambda s: s.replace("01/01/90 01:00", "01/01/90 04:00"),
        lambda s: s.replace("W/m²", "MJ/day"),
        lambda s: s.replace("GlobHor", "Mystery"),
        lambda s: s.replace(";120;", ";nan;", 1),
        lambda s: s.replace("01/01/90 00:00", "not-a-date"),
        lambda s: s.replace("7.4.8", "8.1.0"),
    ],
)
def test_reader_fails_closed(change):
    with pytest.raises(ReferenceError):
        read(change(csv_bytes().decode("latin-1")).encode("latin-1"))


def test_default_requires_full_year():
    with pytest.raises(ReferenceError, match="rows"):
        read_reference(csv_bytes())


def test_comma_export_and_units_separator_are_structural_not_missing_data():
    text = csv_bytes().decode("latin-1").replace(";", ",")
    lines = text.splitlines()
    header = next(i for i, s in enumerate(lines) if s.startswith("date,"))
    lines.insert(header + 2, "")
    assert len(read(("\n".join(lines) + "\n\n").encode("latin-1")).frame) == 3
    lines.insert(header + 4, "")
    with pytest.raises(ReferenceError):
        read("\n".join(lines).encode("latin-1"))


def test_variant_identity_is_metadata_not_an_inferred_filename():
    assert read(csv_bytes()).variant_filename == "invented.VC0"
    assert (
        read(
            csv_bytes().replace(b"Simulation variant", b"Unproved identity")
        ).variant_filename
        is None
    )
