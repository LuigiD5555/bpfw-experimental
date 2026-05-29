"""Reusable metadata window used inside ``bpfw diff``."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from bpfw.integrations.inspector.suggestions.domain.engine import suggest_domains
from bpfw.integrations.inspector.suggestions.purpose.engine import suggest_purposes
from bpfw.integrations.shared.cli_runtime import is_back_command, is_quit_command, normalize_command

InputFunc = Callable[[str], str]
PrintFunc = Callable[[str], None]


@dataclass
class MetadataDraft:
    """Mutable metadata draft returned by the diff inspector window.

    Attributes:
        name: Authority display name.
        purpose: Authority purpose.
        domain: Authority domain.
        status: Authority status or lifecycle.
        observations: Human observations or notes.
    """

    name: str | None = None
    purpose: str | None = None
    domain: str | None = None
    status: str | None = None
    observations: str | None = None

    @classmethod
    def from_block(cls, block: dict[str, Any]) -> "MetadataDraft":
        """Create a metadata draft from a block dictionary.

        Args:
            block: Authority block dictionary.

        Returns:
            Metadata draft populated from the block.
        """
        return cls(
            name=_clean(block.get("name")),
            purpose=_clean(block.get("purpose")),
            domain=_clean(block.get("domain")),
            status=_clean(block.get("status")) or _clean(block.get("lifecycle")),
            observations=_clean(block.get("observations")) or _clean(block.get("notes")),
        )

    def apply_to_block(self, block: dict[str, Any]) -> dict[str, Any]:
        """Return a block copy with this metadata applied.

        Args:
            block: Original block dictionary.

        Returns:
            Updated block copy.
        """
        updated = dict(block)
        updated["name"] = self.name
        updated["purpose"] = self.purpose
        updated["domain"] = self.domain
        updated["status"] = self.status
        updated["observations"] = self.observations
        updated["notes"] = self.observations
        return updated

    def metadata_changes(self) -> dict[str, Any]:
        """Return metadata changes suitable for BlueprintEngine.

        Returns:
            Non-empty dictionary of metadata fields.
        """
        changes: dict[str, Any] = {}
        if self.name is not None:
            changes["name"] = self.name
        if self.purpose is not None:
            changes["purpose"] = self.purpose
        if self.domain is not None:
            changes["domain"] = self.domain
        if self.status is not None:
            changes["status"] = self.status
            changes["lifecycle"] = self.status
        if self.observations is not None:
            changes["observations"] = self.observations
            changes["notes"] = self.observations
        return changes


def run_metadata_window(
    block: dict[str, Any],
    title: str,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> MetadataDraft | None:
    """Run the metadata editor window used by diff.

    Args:
        block: Block dictionary used as the initial metadata source.
        title: Window title.
        input_func: Function used to read user input.
        print_func: Function used to print the window.

    Returns:
        Saved metadata draft, or None when the user exits without saving.
    """
    draft = MetadataDraft.from_block(block)
    while True:
        _render_metadata_window(title=title, block=block, draft=draft, print_func=print_func)
        command = normalize_command(input_func("Choice: "))
        if is_quit_command(command) or is_back_command(command):
            return None
        if command == "s":
            return draft
        if command == "n":
            draft.name = _read_optional_value("Name", draft.name, input_func, print_func)
            continue
        if command == "p":
            draft.purpose = _read_purpose(block, draft.purpose, input_func, print_func)
            continue
        if command == "d":
            draft.domain = _read_domain(block, draft.domain, input_func, print_func)
            continue
        if command == "l":
            draft.status = _read_status(draft.status, input_func, print_func)
            continue
        if command == "o":
            draft.observations = _read_optional_value(
                "Observations",
                draft.observations,
                input_func,
                print_func,
            )
            continue
        print_func("Unknown command.")


def _render_metadata_window(
    title: str,
    block: dict[str, Any],
    draft: MetadataDraft,
    print_func: PrintFunc,
) -> None:
    """Render the metadata editor window.

    Args:
        title: Window title.
        block: Block dictionary used for target display.
        draft: Current metadata draft.
        print_func: Print function.
    """
    code = block.get("code") if isinstance(block.get("code"), dict) else {}
    print_func("")
    print_func(title)
    print_func("")
    print_func("Target:")
    print_func(f"  {code.get('path', 'unknown')}::{code.get('symbol', 'unknown')}")
    print_func("")
    print_func("Fields:")
    print_func(f"  Name:         {_display(draft.name)}")
    print_func(f"  Purpose:      {_display(draft.purpose)}")
    print_func(f"  Domain:       {_display(draft.domain)}")
    print_func(f"  Lifecycle:    {_display(draft.status)}")
    print_func(f"  Observations: {_display(draft.observations)}")
    print_func("")
    print_func("Options:")
    print_func("  [n] Edit name")
    print_func("  [p] Edit purpose")
    print_func("  [d] Edit domain")
    print_func("  [l] Edit lifecycle")
    print_func("  [o] Edit observations")
    print_func("  [s] Save metadata to diff decision")
    print_func("  [b] Back without saving")
    print_func("")


def _read_purpose(
    block: dict[str, Any],
    current_value: str | None,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> str | None:
    """Prompt for purpose with stable suggestions."""
    suggestions = suggest_purposes(block, project_blocks=[], existing_purposes=())
    print_func("")
    print_func("EDIT PURPOSE")
    print_func("")
    print_func(f"Current: {_display(current_value)}")
    print_func("")
    print_func("Suggestions:")
    for index, suggestion in enumerate(suggestions[:3], start=1):
        print_func(f"  [{index}] {suggestion.text}")
    print_func("  [4] custom")
    print_func("  [b] back")
    value = normalize_command(input_func("Choice: "))
    if is_back_command(value):
        return current_value
    if value in {"1", "2", "3"}:
        selected_index = int(value) - 1
        if selected_index < len(suggestions):
            return suggestions[selected_index].text
    if value == "4":
        return _read_optional_value("Custom purpose", current_value, input_func, print_func)
    return current_value


def _read_domain(
    block: dict[str, Any],
    current_value: str | None,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> str | None:
    """Prompt for domain with stable suggestions."""
    suggestions = suggest_domains(block, project_blocks=[])
    print_func("")
    print_func("EDIT DOMAIN")
    print_func("")
    print_func(f"Current: {_display(current_value)}")
    print_func("")
    print_func("Suggestions:")
    for index, suggestion in enumerate(suggestions[:5], start=1):
        print_func(f"  [{index}] {suggestion}")
    print_func("  [c] custom")
    print_func("  [b] back")
    value = normalize_command(input_func("Choice: "))
    if is_back_command(value):
        return current_value
    if value.isdigit():
        selected_index = int(value) - 1
        if 0 <= selected_index < len(suggestions):
            return suggestions[selected_index]
    if value == "c":
        return _read_optional_value("Custom domain", current_value, input_func, print_func)
    return current_value


def _read_status(
    current_value: str | None,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> str | None:
    """Prompt for lifecycle/status value.

    Args:
        current_value: Current status.
        input_func: Input function.
        print_func: Print function.

    Returns:
        Selected status.
    """
    values = ["active", "experimental", "legacy", "deprecated"]
    print_func("")
    print_func("EDIT LIFECYCLE")
    print_func("")
    print_func(f"Current: {_display(current_value)}")
    for index, value in enumerate(values, start=1):
        print_func(f"  [{index}] {value}")
    print_func("  [b] back")
    command = normalize_command(input_func("Choice: "))
    if is_back_command(command):
        return current_value
    if command.isdigit():
        selected_index = int(command) - 1
        if 0 <= selected_index < len(values):
            return values[selected_index]
    return current_value


def _read_optional_value(
    field_label: str,
    current_value: str | None,
    input_func: InputFunc,
    print_func: PrintFunc,
) -> str | None:
    """Prompt for a free-text optional field.

    Args:
        field_label: Field label.
        current_value: Current value.
        input_func: Input function.
        print_func: Print function.

    Returns:
        Cleaned value or current value when blank.
    """
    print_func("")
    print_func(f"{field_label}:")
    value = input_func("> ").strip()
    if not value:
        return current_value
    return value


def _display(value: str | None) -> str:
    """Return a printable value.

    Args:
        value: Optional string.

    Returns:
        Value or dash marker.
    """
    return value if value else "<empty>"


def _clean(value: Any) -> str | None:
    """Return a stripped string or None.

    Args:
        value: Value to clean.

    Returns:
        Cleaned string or None.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None
