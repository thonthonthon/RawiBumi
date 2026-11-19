"""Conservative PAN semantic mapper."""

from __future__ import annotations

from pathlib import Path

from components.mapping import SemanticMappingResult, load_mapping_ledger, semantic_map_document
from components.panond_raw import RawPanOndDocument

LEDGER_PATH = Path(__file__).with_name("mapping-ledger.yaml")


def map_pan(document: RawPanOndDocument) -> SemanticMappingResult:
    if document.format != "pan":
        raise ValueError("PAN mapper requires a PAN document")
    ledger_format, rules = load_mapping_ledger(LEDGER_PATH)
    if ledger_format != "pan":
        raise RuntimeError("PAN ledger has wrong format marker")
    return semantic_map_document(document, rules)
