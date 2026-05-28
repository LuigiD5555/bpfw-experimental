"""PURPOSE filter parsing and application for BPFW Editor search results
DOMAIN  editor workflow
"""

from dataclasses import dataclass, field

from bpfw.integrations.editor.search import SearchRecord

ALLOWED_FILTER_COLUMNS = ("status", "domain", "name", "path", "symbol", "id", "purpose")


@dataclass
class ActiveFilter:
    """PURPOSE one active filter constraint
    DOMAIN  editor workflow
    """

    column: str
    value: str

    def display(self) -> str:
        """PURPOSE get the display string for this filter
        DOMAIN  editor workflow
        """

        return f"{self.column}={self.value}"


@dataclass
class FilterState:
    """PURPOSE mutable collection of active filters
    DOMAIN  editor workflow
    """

    filters: list[ActiveFilter] = field(default_factory=list)

    def add(self, column: str, value: str) -> None:
        """PURPOSE add or replace a filter for the given column
        DOMAIN  editor workflow
        """

        # Remove existing filter for same column (replace semantics)
        self.filters = [
            active_filter
            for active_filter in self.filters
            if active_filter.column != column
        ]
        self.filters.append(ActiveFilter(column=column, value=value))

    def clear(self) -> None:
        """PURPOSE remove all active filters
        DOMAIN  editor workflow
        """

        self.filters.clear()

    def is_empty(self) -> bool:
        """PURPOSE check whether no filters are active
        DOMAIN  editor workflow
        """

        return len(self.filters) == 0

    def display_lines(self) -> list[str]:
        """PURPOSE get display lines for active filters
        DOMAIN  editor workflow
        """

        if self.is_empty():
            return ["none"]
        return [active_filter.display() for active_filter in self.filters]


def parse_filter_input(raw_input: str) -> tuple[str, str] | str:
    """PURPOSE parse a filter input string
    DOMAIN  editor workflow
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
    """PURPOSE apply all active filters to a list of search records
    DOMAIN  editor workflow
    """

    result = records
    for active_filter in filter_state.filters:
        result = _apply_single_filter(result, active_filter)

    return result


def _apply_single_filter(
    records: list[SearchRecord],
    active_filter: ActiveFilter,
) -> list[SearchRecord]:
    """PURPOSE apply one filter to a list of records
    DOMAIN  editor workflow
    """

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
    """PURPOSE check if a record matches a filter value for the given column
    DOMAIN  editor workflow
    """

    column_value = _get_record_column_value(record, column)
    return value_lower in column_value.lower()


def _get_record_column_value(record: SearchRecord, column: str) -> str:
    """PURPOSE get the string value of a record for a filter column
    DOMAIN  editor workflow
    """

    column_map = {
        "status": record.status,
        "purpose": record.purpose,
        "domain": record.domain,
        "name": record.name,
        "path": record.path,
        "symbol": record.symbol,
        "id": record.responsibility_id,
    }
    return column_map.get(column, "")