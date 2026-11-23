"""Strict, bounded CSV loading that preserves source values as strings."""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import BinaryIO

import pandas as pd

DEFAULT_MAX_BYTES = 25 * 1024 * 1024
DEFAULT_MAX_ROWS = 250_000
MAX_COLUMNS = 200
MAX_HEADER_LENGTH = 128
SUPPORTED_DELIMITERS = ",;\t|"


class CSVInputError(ValueError):
    """Raised when a CSV is malformed or exceeds configured limits."""


def load_csv_dataframe(
    source: Path | str | bytes | bytearray | BinaryIO,
    *,
    file_name: str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> pd.DataFrame:
    """Read a bounded CSV into a DataFrame without coercing identifiers or money."""
    data, resolved_name = _read_source(source, file_name, max_bytes)
    if Path(resolved_name).suffix.lower() != ".csv":
        raise CSVInputError("Only CSV ledger files can be imported as tabular data.")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CSVInputError("CSV files must use UTF-8 or UTF-8 with a BOM.") from exc

    delimiter = _detect_delimiter(text)
    headers = _validate_records(text, delimiter, max_rows)
    if len(headers) > MAX_COLUMNS:
        raise CSVInputError(f"CSV has more than {MAX_COLUMNS} columns.")

    try:
        frame = pd.read_csv(
            io.BytesIO(data),
            sep=delimiter,
            dtype="string",
            keep_default_na=False,
            encoding="utf-8-sig",
            encoding_errors="strict",
            on_bad_lines="error",
            low_memory=False,
            skip_blank_lines=True,
        )
    except (pd.errors.ParserError, UnicodeDecodeError, ValueError) as exc:
        raise CSVInputError("CSV could not be parsed consistently.") from exc

    if list(frame.columns) != headers:
        raise CSVInputError("CSV headers changed during parsing; verify the delimiter and quoting.")
    if frame.empty:
        raise CSVInputError("CSV must include at least one data row.")
    if len(frame.index) > max_rows:
        raise CSVInputError(f"CSV exceeds the maximum of {max_rows} data rows.")
    return frame


def _read_source(
    source: Path | str | bytes | bytearray | BinaryIO,
    file_name: str | None,
    max_bytes: int,
) -> tuple[bytes, str]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive.")
    if isinstance(source, (str, Path)):
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise CSVInputError("CSV source could not be accessed.") from exc
        if size > max_bytes:
            raise CSVInputError(f"CSV exceeds the maximum size of {max_bytes} bytes.")
        try:
            return path.read_bytes(), file_name or path.name
        except OSError as exc:
            raise CSVInputError("CSV source could not be read.") from exc
    if isinstance(source, (bytes, bytearray)):
        data = bytes(source)
        resolved_name = file_name or "upload.csv"
    else:
        try:
            data = source.read(max_bytes + 1)
        except OSError as exc:
            raise CSVInputError("CSV source could not be read.") from exc
        resolved_name = file_name or "upload.csv"
    if len(data) > max_bytes:
        raise CSVInputError(f"CSV exceeds the maximum size of {max_bytes} bytes.")
    if not data:
        raise CSVInputError("CSV file is empty.")
    return data, resolved_name


def _detect_delimiter(text: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=SUPPORTED_DELIMITERS)
    except csv.Error:
        return ","
    return dialect.delimiter


def _validate_records(text: str, delimiter: str, max_rows: int) -> list[str]:
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    try:
        headers = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise CSVInputError("CSV must start with a valid header row.") from exc

    if len(headers) < 2:
        raise CSVInputError("CSV must contain at least two columns.")
    normalized = [header.strip().casefold() for header in headers]
    if any(not header or len(header) > MAX_HEADER_LENGTH for header in normalized):
        raise CSVInputError("CSV headers must be non-empty and no longer than 128 characters.")
    if len(set(normalized)) != len(normalized):
        raise CSVInputError("CSV contains duplicate headers after case/space normalization.")

    data_rows = 0
    for row in reader:
        if not row:
            continue
        data_rows += 1
        if len(row) != len(headers):
            raise CSVInputError(
                f"CSV row {reader.line_num} has {len(row)} fields; expected {len(headers)}."
            )
        if data_rows > max_rows:
            raise CSVInputError(f"CSV exceeds the maximum of {max_rows} data rows.")
    if data_rows == 0:
        raise CSVInputError("CSV must include at least one data row.")
    return headers
