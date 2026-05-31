"""Search index for BPFW Editor — build records, match queries, format rows."""

from dataclasses import dataclass
from typing import Any

from bpfw.core.catalog.domain import BlueprintDocument
from bpfw.core.catalog.duplicate_profile import (
    CodeUnitKey,
    DuplicateProfile,
    code_unit_key_from_block,
)


@dataclass(slots=True)
class SearchRecord:
    """Flat searchable record for one blueprint block."""

    responsibility_id: str
    lifecycle: str
    domain: str
    technical_label: str
    path: str
    symbol: str
    location: str
    start_line: int | None
    end_line: int | None
    purpose: str
    searchable_text: str
    duplicate_hash: str = ""
    duplicate_key: str = ""
    duplicate_hash_strength: str = ""
    duplicate_group_size: int = 0
    duplicate_status: str = "no"

    @property
    def is_duplicate(self) -> bool:
        """Return whether this record belongs to a blocking duplicate group."""

        return self.duplicate_status == "yes"

    @property
    def needs_duplicate_review(self) -> bool:
        """Return whether this record belongs to a non-blocking duplicate candidate group."""

        return self.duplicate_status == "check"


def build_search_records(
    blueprint_data: dict[str, Any],
    duplicate_profiles: dict[CodeUnitKey, DuplicateProfile] | None = None,
) -> list[SearchRecord]:
    """Build searchable records from blueprint blocks."""

    blocks = blueprint_data.get("blocks", [])
    if not isinstance(blocks, list):
        return []

    records: list[SearchRecord] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue

        record = _build_single_record(block, duplicate_profiles=duplicate_profiles)
        records.append(record)

    return with_duplicate_group_sizes(records)


def build_search_records_from_document(
    document: BlueprintDocument,
    duplicate_profiles: dict[CodeUnitKey, DuplicateProfile] | None = None,
) -> list[SearchRecord]:
    """Build searchable records from domain document blocks."""

    records: list[SearchRecord] = []
    for responsibility in document.blocks:
        block = responsibility.model_dump(by_alias=True, exclude_none=True)
        if not isinstance(block, dict):
            continue
        records.append(_build_single_record(block, duplicate_profiles=duplicate_profiles))
    return with_duplicate_group_sizes(records)


def _build_single_record(
    block: dict[str, Any],
    duplicate_profiles: dict[CodeUnitKey, DuplicateProfile] | None = None,
) -> SearchRecord:
    """Build one search record from a block dict."""

    block_id = _str_or_empty(block.get("id"))
    status = _str_or_empty(block.get("status"))
    domain = _str_or_empty(block.get("domain"))
    purpose = _str_or_empty(block.get("purpose"))

    code_data = block.get("code", {})
    if not isinstance(code_data, dict):
        code_data = {}
    raw_path = _str_or_empty(code_data.get("path"))
    symbol = _str_or_empty(code_data.get("symbol"))
    technical_label = _str_or_empty(symbol or block.get("canonical_name") or block.get("name"))
    start_line = _int_or_none(code_data.get("start_line"))
    end_line = _int_or_none(code_data.get("end_line"))

    location = _short_location(raw_path)

    detected = block.get("detected")
    qualified_name = ""
    if isinstance(detected, dict):
        qualified_name = _str_or_empty(detected.get("qualified_name"))

    notes = _str_or_empty(block.get("notes"))

    duplicate_hash = ""
    duplicate_key = ""
    duplicate_hash_strength = ""
    duplicate_status = "no"
    duplicate_profile = _duplicate_profile_for_block(
        block=block,
        duplicate_profiles=duplicate_profiles or {},
    )
    if duplicate_profile is not None:
        duplicate_hash = _str_or_empty(duplicate_profile.keys.duplicate_hash)
        duplicate_key = _str_or_empty(duplicate_profile.keys.duplicate_key)
        duplicate_hash_strength = _str_or_empty(duplicate_profile.keys.hash_strength)
        duplicate_status = _str_or_empty(duplicate_profile.keys.duplicated) or "no"

    searchable_parts = [
        block_id,
        status,
        domain,
        technical_label,
        raw_path,
        symbol,
        qualified_name,
        purpose,
        notes,
        duplicate_hash,
        duplicate_key,
        duplicate_hash_strength,
        duplicate_status,
    ]
    searchable_text = " ".join(searchable_parts).lower()

    return SearchRecord(
        responsibility_id=block_id,
        lifecycle=status,
        domain=domain,
        technical_label=technical_label,
        path=raw_path,
        symbol=symbol,
        location=location,
        start_line=start_line,
        end_line=end_line,
        purpose=purpose,
        searchable_text=searchable_text,
        duplicate_hash=duplicate_hash,
        duplicate_key=duplicate_key,
        duplicate_hash_strength=duplicate_hash_strength,
        duplicate_status=duplicate_status,
    )


def with_duplicate_group_sizes(records: list[SearchRecord]) -> list[SearchRecord]:
    """Populate duplicate group sizes on search records.

    Args:
        records: Search records with duplicate hashes already attached.

    Returns:
        The same records with duplicate_group_size populated.
    """

    hash_counts: dict[tuple[str, str], int] = {}
    for record in records:
        if record.lifecycle != "active":
            continue
        if record.duplicate_hash_strength not in {"strong", "weak"}:
            continue
        if not record.duplicate_hash:
            continue
        group_key = (record.duplicate_hash, record.duplicate_hash_strength)
        hash_counts[group_key] = hash_counts.get(group_key, 0) + 1

    for record in records:
        group_key = (record.duplicate_hash, record.duplicate_hash_strength)
        record.duplicate_group_size = hash_counts.get(group_key, 0)
        if record.duplicate_group_size > 1 and record.duplicate_hash_strength == "strong":
            record.duplicate_status = "yes"
        elif record.duplicate_group_size > 1 and record.duplicate_hash_strength == "weak":
            record.duplicate_status = "check"
        else:
            record.duplicate_status = "no"

    return records


def sort_duplicate_records(records: list[SearchRecord]) -> list[SearchRecord]:
    """Return records grouped by duplicate hash for duplicate review.

    Args:
        records: Search records already filtered to duplicate candidates.

    Returns:
        Records sorted so blocks in the same duplicate group appear together.
    """

    return sorted(
        records,
        key=lambda record: (
            record.duplicate_hash or "~",
            record.domain,
            record.location,
            record.symbol,
        ),
    )


def _duplicate_profile_for_block(
    block: dict[str, Any],
    duplicate_profiles: dict[CodeUnitKey, DuplicateProfile],
) -> DuplicateProfile | None:
    """Return the duplicate profile for one raw block dictionary."""

    key = code_unit_key_from_block(block)
    if key is None:
        return None
    profile = duplicate_profiles.get(key)
    if isinstance(profile, DuplicateProfile):
        return profile
    return None


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
