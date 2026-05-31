"""Filter parsing and application for BPFW Editor search results."""

from dataclasses import dataclass, field

from bpfw.integrations.editor.search import SearchRecord, sort_duplicate_records

ALLOWED_FILTER_COLUMNS = (
    "status",
    "domain",
    "path",
    "symbol",
    "id",
    "purpose",
    "duplicate",
    "duplicate_hash",
)


@dataclass
class ActiveFilter:
    """One active filter constraint."""

    column: str
    value: str

    def display(self) -> str:
        """Return the display string for this filter."""

        return f"{self.column}={self.value}"


@dataclass
class FilterState:
    """Mutable collection of active filters."""

    filters: list[ActiveFilter] = field(default_factory=list)

    def add(self, column: str, value: str) -> None:
        """Add or replace a filter for the given column."""

        # Remove existing filter for same column (replace semantics)
        self.filters = [
            active_filter
            for active_filter in self.filters
            if active_filter.column != column
        ]
        self.filters.append(ActiveFilter(column=column, value=value))

    def clear(self) -> None:
        """Remove all active filters."""

        self.filters.clear()

    def is_empty(self) -> bool:
        """Return True when no filters are active."""

        return len(self.filters) == 0

    def display_lines(self) -> list[str]:
        """Return display lines for active filters."""

        if self.is_empty():
            return ["none"]
        return [active_filter.display() for active_filter in self.filters]


def parse_filter_input(raw_input: str) -> tuple[str, str] | str:
    """Parse a filter input string.

    Returns (column, value) on success, or an error message string on failure.
    """

    stripped = raw_input.strip()
    if not stripped:
        return "Empty filter input."

    if "=" not in stripped:
        return (
            "Invalid filter.\n\n"
            "Use:\n"
            "  column=value\n\n"
            "Examples:\n"
            "  status=active\n"
            "  domain=catalog"
        )

    column, _, value = stripped.partition("=")
    column = column.strip().lower()
    value = value.strip()

    if not column:
        return (
            "Invalid filter.\n\n"
            "Use:\n"
            "  column=value\n\n"
            "Examples:\n"
            "  status=active\n"
            "  domain=catalog"
        )

    if not value:
        return (
            "Invalid filter.\n\n"
            "Use:\n"
            "  column=value\n\n"
            "Examples:\n"
            "  status=active\n"
            "  domain=catalog"
        )

    if column not in ALLOWED_FILTER_COLUMNS:
        available = "\n".join(f"  {allowed}" for allowed in ALLOWED_FILTER_COLUMNS)
        return (
            f"Unknown filter column: {column}\n\n"
            f"Available columns:\n"
            f"{available}"
        )

    return (column, value)


def apply_filters(
    records: list[SearchRecord],
    filter_state: FilterState,
) -> list[SearchRecord]:
    """Apply all active filters to a list of search records."""

    result = records
    duplicate_filter_requested = False
    for active_filter in filter_state.filters:
        if active_filter.column == "duplicate" and active_filter.value.lower() in {"yes", "true", "1"}:
            duplicate_filter_requested = True
        result = _apply_single_filter(result, active_filter)

    if duplicate_filter_requested:
        return sort_duplicate_records(result)
    return result


def _apply_single_filter(
    records: list[SearchRecord],
    active_filter: ActiveFilter,
) -> list[SearchRecord]:
    """Apply one filter to a list of records."""

    value_lower = active_filter.value.lower()

    return [
        record
        for record in records
        if _record_matches_filter(record, active_filter.column, value_lower)
    ]


def _record_matches_filter(
    record: SearchRecord,
    column: str,
    value_lower: str,
) -> bool:
    """Check if a record matches a filter value for the given column."""

    if column == "duplicate":
        return _record_matches_duplicate_filter(record, value_lower)

    column_value = _get_record_column_value(record, column)
    return value_lower in column_value.lower()


def _get_record_column_value(record: SearchRecord, column: str) -> str:
    """Get the string value of a record for a filter column."""

    column_map = {
        "status": record.lifecycle,
        "purpose": record.purpose,
        "domain": record.domain,
        "path": record.path,
        "symbol": record.symbol,
        "id": record.responsibility_id,
        "duplicate": record.duplicate_status,
        "duplicate_hash": record.duplicate_hash,
    }
    return column_map.get(column, "")

def _record_matches_duplicate_filter(record: SearchRecord, value_lower: str) -> bool:
    """Return whether a record matches duplicate=yes or duplicate=no.

    Args:
        record: Search record being filtered.
        value_lower: Lowercase requested filter value.

    Returns:
        True when the record matches the requested duplicate state.
    """

    if value_lower in {"yes", "true", "1"}:
        return record.duplicate_status == "yes"
    if value_lower == "check":
        return record.duplicate_status == "check"
    if value_lower == "all":
        return record.duplicate_status in {"yes", "check"}
    if value_lower in {"no", "false", "0"}:
        return record.duplicate_status == "no"
    return value_lower in record.duplicate_status
