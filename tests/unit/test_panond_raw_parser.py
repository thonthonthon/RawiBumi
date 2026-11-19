from components.ond import parse_ond_text
from components.pan import parse_pan_bytes, parse_pan_text


def test_pan_parser_preserves_raw_text_order_duplicates_and_equals():
    text = (
        "PVObject_=pvModule\r\n"
        "  Manufacturer=OpenSIMPV\r\n"
        "  Note=a=b=c\r\n"
        "  Section=parent\r\n"
        "    Value=42\r\n"
        "Duplicate=one\r\n"
        "Duplicate=two"
    )
    document = parse_pan_text(text)

    assert document.raw_text == text
    assert document.newline == "crlf"
    assert [field.key for field in document.fields][-2:] == ["Duplicate", "Duplicate"]
    assert document.fields[2].value_raw == "a=b=c"
    assert document.fields[4].path == ("PVObject_", "Section", "Value")
    assert document.fields[-1].value_raw == "two"


def test_pan_raw_field_map_is_ordered_and_json_ready():
    document = parse_pan_text("Root=value\n  Child=1\n  Child=2")
    raw = document.raw_field_map()

    assert [item["line_number"] for item in raw] == [1, 2, 3]
    assert raw[1]["path"] == ["Root", "Child"]
    assert raw[2]["path"] == ["Root", "Child"]


def test_pan_parser_preserves_non_key_text_and_blank_lines():
    document = parse_pan_text("Header without equals\n\nKey=Value")
    assert [line.kind for line in document.lines] == ["text", "blank", "key_value"]
    assert document.fields[0].line_number == 3


def test_pan_bytes_accept_utf8_bom():
    data = b"\xef\xbb\xbfKey=Value\n"
    document = parse_pan_bytes(data)
    assert document.fields[0].key == "Key"
    assert document.fields[0].value_raw == "Value"


def test_invalid_indentation_is_preserved_and_warned_not_discarded():
    document = parse_pan_text("Root=value\n   OddIndent=still-here")
    assert document.fields[1].key == "OddIndent"
    assert document.fields[1].indent_valid is False
    assert document.warnings


def test_ond_wrapper_sets_format_without_semantic_mapping():
    document = parse_ond_text("OndObject=inverter\n  PNomConv=100")
    assert document.format == "ond"
    assert document.fields[1].value_raw == "100"
    assert document.fields[1].path == ("OndObject", "PNomConv")
