"""PVsyst weather-format probing without decoding internal .MET payloads."""

from __future__ import annotations

import re
from typing import Any


_PVSYST_STANDARD_TAGS = {
    "#weather data hourly data",
    "#tmy hourly data",
}


def _first_nonempty_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _looks_binary(data: bytes) -> bool:
    sample = data[:8192]
    if not sample:
        return False
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8-sig")
    except UnicodeDecodeError:
        return True
    control = sum(
        byte < 32 and byte not in {9, 10, 13}
        for byte in sample
    )
    return control / len(sample) > 0.02


def _extract_text_met_metadata(text: str) -> dict[str, Any]:
    first = _first_nonempty_line(text)
    object_match = re.match(r"PVObject_\s*=\s*([^\s]+)", first)
    version_match = re.search(
        r"(?mi)^\s*Version\s*=\s*([^\r\n]+?)\s*$",
        text,
    )
    day_matches = re.findall(r"(?mi)^\s*Day_\d{4}\s*=", text)
    variable_matches = re.findall(
        r"(?mi)^\s*PVObject_[^=]*=\s*pvMeteoVar\b",
        text,
    )
    return {
        "object_type": object_match.group(1) if object_match else None,
        "version": version_match.group(1).strip() if version_match else None,
        "has_encoded_daily_payload": bool(day_matches),
        "encoded_day_record_count_in_probe_window": len(day_matches),
        "meteo_variable_object_count_in_probe_window": len(variable_matches),
    }


def probe_pvsyst_weather_bytes(data: bytes, *, filename: str) -> dict[str, Any]:
    """Classify PVsyst weather containers without interpreting internal weather values.

    The probe deliberately distinguishes the documented Standard CSV interchange format
    from internal .MET containers. Internal text/binary containers remain unsupported for
    direct weather-series decoding.
    """
    lower_name = filename.lower()
    extension_is_met = lower_name.endswith(".met")
    binary = _looks_binary(data)

    if not binary:
        text = data[:131072].decode("utf-8-sig", errors="strict")
        first = _first_nonempty_line(text)
        first_lower = first.lower()

        if first_lower in _PVSYST_STANDARD_TAGS:
            return {
                "format_id": "pvsyst_standard_csv",
                "is_pvsyst_weather": True,
                "import_supported": True,
                "container": "text",
                "confidence": "high",
                "reason": "documented PVsyst Standard weather header detected",
                "filename_extension": ".met" if extension_is_met else None,
                "internal_object": None,
            }

        metadata = _extract_text_met_metadata(text)
        if metadata["object_type"] == "pvMeteo":
            return {
                "format_id": "pvsyst_internal_met_text",
                "is_pvsyst_weather": True,
                "import_supported": False,
                "container": "text",
                "confidence": "high",
                "reason": "PVObject_=pvMeteo text object detected",
                "filename_extension": ".met" if extension_is_met else None,
                "internal_object": metadata,
            }

        if extension_is_met:
            return {
                "format_id": "pvsyst_met_unrecognized",
                "is_pvsyst_weather": True,
                "import_supported": False,
                "container": "text",
                "confidence": "low",
                "reason": (
                    ".MET extension detected but content does not match the documented "
                    "Standard CSV header or a PVObject_=pvMeteo text object"
                ),
                "filename_extension": ".met",
                "internal_object": metadata,
            }

    if extension_is_met and binary:
        return {
            "format_id": "pvsyst_internal_met_binary",
            "is_pvsyst_weather": True,
            "import_supported": False,
            "container": "binary",
            "confidence": "medium",
            "reason": (
                ".MET extension with binary/non-text content detected; payload semantics "
                "are intentionally not reverse-engineered"
            ),
            "filename_extension": ".met",
            "internal_object": None,
        }

    return {
        "format_id": None,
        "is_pvsyst_weather": False,
        "import_supported": False,
        "container": "binary" if binary else "text",
        "confidence": "high",
        "reason": "no PVsyst weather signature detected",
        "filename_extension": None,
        "internal_object": None,
    }
