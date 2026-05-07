"""Command handling for the inspector integration."""

from collections.abc import Callable
from typing import Any, Dict, List

from bpfw.catalog.intent_suggestions import IntentSuggestion
from bpfw.integrations.inspector_base import InspectIssue

InputFunc = Callable[[str], str]


class InspectorAction:
    """Define action names produced by inspector commands."""

    STAY = "stay"
    SAVE_NEXT = "save_next"
    BACK = "back"
    QUIT = "quit"
    HELP = "help"
    UNKNOWN = "unknown"


def apply_inspector_command(
    command: str,
    issue: InspectIssue,
    intent_suggestions: List[IntentSuggestion],
    domain_suggestions: List[str],
    input_func: InputFunc,
) -> str:
    """Apply one inspector command and return the navigation action."""

    stripped_command = command.strip()

    if stripped_command == "":
        return InspectorAction.SAVE_NEXT

    if stripped_command in {"1", "2", "3", "4", "5"}:
        suggestion_index = int(stripped_command) - 1
        if suggestion_index < len(intent_suggestions):
            issue.responsibility["intent"] = intent_suggestions[suggestion_index].text
        return InspectorAction.STAY

    if stripped_command.startswith("6"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("intent: ").strip()
        if value:
            issue.responsibility["intent"] = value
        return InspectorAction.STAY

    # Check domain keys first (a, s, d, f)
    if stripped_command in {"a", "s", "d", "f"}:
        domain_index = {"a": 0, "s": 1, "d": 2, "f": 3}[stripped_command]
        if domain_index < len(domain_suggestions):
            issue.responsibility["domain"] = domain_suggestions[domain_index]
        return InspectorAction.STAY

    # Then check lifecycle keys (z, x, c, v)
    if stripped_command in {"z", "x", "c", "v"}:
        issue.responsibility["lifecycle"] = {
            "z": "active",
            "x": "experimental",
            "c": "legacy",
            "v": "deprecated",
        }[stripped_command]
        return InspectorAction.STAY

    # Custom domain input (g prefix)
    if stripped_command.startswith("g"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("domain: ").strip()
        if value:
            issue.responsibility["domain"] = value
        return InspectorAction.STAY

    if stripped_command.startswith("n"):
        value = stripped_command[1:].strip()
        if not value:
            current_name = issue.responsibility.get("name", "")
            value = input_func(f"name [{current_name}]: ").strip()
        if value:
            issue.responsibility["name"] = value
        return InspectorAction.STAY

    if stripped_command.startswith("o"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("observations: ").strip()
        if value:
            issue.responsibility["notes"] = value
        return InspectorAction.STAY

    if stripped_command == "b":
        return InspectorAction.BACK

    if stripped_command == "q":
        return InspectorAction.QUIT

    if stripped_command == "h":
        return InspectorAction.HELP

    return InspectorAction.UNKNOWN