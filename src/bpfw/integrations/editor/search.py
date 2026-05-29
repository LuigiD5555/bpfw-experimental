"""Search index for BPFW Editor — build records, match queries, format rows."""

from dataclasses import dataclass
from typing import Any

from bpfw.core.catalog.domain import BlueprintDocument


@dataclass(slots=True)
class SearchRecord:
    """Flat searchable record for one blueprint block."""

    responsibility_id: str
    lifecycle: str
    domain: str
    name: str
    path: str
    symbol: str
    location: str
    start_line: int | None
    end_line: int | None
    purpose: str
    searchable_text: str


def build_search_records(blueprint_data: dict[str, Any]) -> list[SearchRecord]:
    """Build searchable records from blueprint blocks."""

    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return []

    records: list[SearchRecord] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue

        record = _build_single_record(block)
        records.append(record)

    return records


def build_search_records_from_document(document: BlueprintDocument) -> list[SearchRecord]:
    """Build searchable records from domain document blocks."""

    records: list[SearchRecord] = []
    for responsibility in document.blocks:
        block = responsibility.model_dump(by_alias=True, exclude_none=True)
        if not isinstance(block, dict):
            continue
        records.append(_build_single_record(block))
    return records


def _build_single_record(block: dict[str, Any]) -> SearchRecord:
    """Build one search record from a block dict."""

    block_id = _str_or_empty(block.get("id"))
    status = _str_or_empty(block.get("status"))
    domain = _str_or_empty(block.get("domain"))
    name = _str_or_empty(block.get("name") or block.get("canonical_name"))
    purpose = _str_or_empty(block.get("purpose"))

    code_data = block.get("code", {})
    if not isinstance(code_data, dict):
        code_data = {}
    raw_path = _str_or_empty(code_data.get("path"))
    symbol = _str_or_empty(code_data.get("symbol"))
    start_line = _int_or_none(code_data.get("start_line"))
    end_line = _int_or_none(code_data.get("end_line"))

    location = _short_location(raw_path)

    detected = block.get("detected")
    qualified_name = ""
    if isinstance(detected, dict):
        qualified_name = _str_or_empty(detected.get("qualified_name"))

    notes = _str_or_empty(block.get("notes"))

    searchable_parts = [
        block_id,
        status,
        domain,
        name,
        raw_path,
        symbol,
        qualified_name,
        purpose,
        notes,
    ]
    searchable_text = " ".join(searchable_parts).lower()

    return SearchRecord(
        responsibility_id=block_id,
        lifecycle=status,
        domain=domain,
        name=name,
        path=raw_path,
        symbol=symbol,
        location=location,
        start_line=start_line,
        end_line=end_line,
        purpose=purpose,
        searchable_text=searchable_text,
    )


def search_records(
    records: list[SearchRecord],
    query: str,
) -> list[SearchRecord]:
    """Filter records by search query using case-insensitive substring match."""

    if not query.strip():
        return list(records)

    query_lower = query.strip().lower()

    return [
        record
        for record in records
        if query_lower in record.searchable_text
    ]


def _str_or_empty(value: Any) -> str:
    """Convert a value to string, returning empty string for None."""

    if value is None:
        return ""
    return str(value).strip()


def _int_or_none(value: Any) -> int | None:
    """Convert a line value to int, returning None when unavailable."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _short_location(raw_path: str) -> str:
    """Strip common prefixes for a compact code path display."""

    for prefix in ("src/bpfw/", "bpfw/"):
        if raw_path.startswith(prefix):
            return raw_path[len(prefix):]

    return raw_path
