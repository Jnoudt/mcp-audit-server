"""Create a value-free schema profile for the supplied audit test-data pack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.ingestion.dataframe_loader import load_csv_dataframe
from src.ingestion.ledger_types import identify_ledger_type
from src.ingestion.type_detection import profile_dataframe

SERVER_ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = (
    SERVER_ROOT
    / "sample_data"
    / "Enterprise_ERP_Ledgers_and_Audit_CAATs_Pack"
)
OUTPUT_PATH = SERVER_ROOT / "docs" / "TEST_DATA_SCHEMA_PROFILE.json"


def _profile_file(path: Path) -> dict[str, Any]:
    frame = load_csv_dataframe(path)
    profiles = profile_dataframe(frame)
    entry: dict[str, Any] = {
        "path": path.relative_to(PACK_ROOT).as_posix(),
        "row_count": len(frame.index),
        "column_count": len(frame.columns),
        "columns": [
            {
                "name": profile.name,
                "inferred_type": profile.kind.value,
                "nullable": profile.nullable,
                "analysis_allowed": profile.analysis_allowed,
            }
            for profile in profiles
        ],
    }
    if path.parent.parent.name == "ledgers":
        entry["ledger_type"] = identify_ledger_type(frame.columns).value
        entry["source_system"] = path.parent.name
    return entry


def build_report() -> dict[str, Any]:
    files = sorted(PACK_ROOT.rglob("*.csv"))
    if not files:
        raise FileNotFoundError(f"No CSV fixtures found under {PACK_ROOT}.")
    return {
        "profile_schema_version": 1,
        "dataset": "Enterprise ERP Ledgers & Audit CAATs Dataset Pack",
        "contains_source_values": False,
        "files": [_profile_file(path) for path in files],
    }


def main() -> None:
    report = build_report()
    OUTPUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Profiled {len(report['files'])} CSV files into {OUTPUT_PATH}.")


if __name__ == "__main__":
    main()
