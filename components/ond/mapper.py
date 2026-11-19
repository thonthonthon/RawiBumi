"""Conservative OND semantic mapper."""

from __future__ import annotations

from pathlib import Path
from dataclasses import replace

from components.mapping import SemanticMappingResult, load_mapping_ledger, semantic_map_document
from components.panond_raw import RawPanOndDocument

LEDGER_PATH = Path(__file__).with_name("mapping-ledger.yaml")


def map_ond(document: RawPanOndDocument) -> SemanticMappingResult:
    if document.format != "ond":
        raise ValueError("OND mapper requires an OND document")
    ledger_format, rules = load_mapping_ledger(LEDGER_PATH)
    if ledger_format != "ond":
        raise RuntimeError("OND ledger has wrong format marker")
    result = semantic_map_document(document, rules)
    # PVsyst writes a zero summary when that metric was not supplied. Keep the
    # source record, but do not expose zero as an actual measured efficiency.
    absent = {
        path for path in (
            "efficiency_model.reference_metrics.european_efficiency_fraction",
            "efficiency_model.reference_metrics.max_efficiency_fraction",
        ) if result.values_by_canonical_path.get(path) == 0
    }
    if not absent:
        return result
    return replace(
        result,
        values_by_canonical_path={
            path: None if path in absent else value
            for path, value in result.values_by_canonical_path.items()
        },
        mapped_fields=tuple(
            {**record, "canonical_value": None} if record["canonical_path"] in absent else record
            for record in result.mapped_fields
        ),
    )
