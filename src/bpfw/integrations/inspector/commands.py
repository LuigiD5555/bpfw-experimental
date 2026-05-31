"""Command handling for the inspector integration."""

from collections.abc import Callable
from typing import Any, Dict, List

from bpfw.integrations.inspector.suggestions.purpose.models import PurposeSuggestion
from bpfw.integrations.inspector.base import InspectIssue
from bpfw.integrations.shared.cli_runtime import is_quit_command, normalize_command

InputFunc = Callable[[str], str]
ALLOW_DUPLICATE_PROFILE_KEY = "a"
PURPOSE_SUGGESTION_KEYS = ("p1", "p2", "p3", "p4", "p5")
CUSTOM_PURPOSE_KEY = "p"
LEGACY_CUSTOM_PURPOSE_KEY = "p6"
DOMAIN_SUGGESTION_KEYS = ("d1", "d2", "d3", "d4", "d5")
CUSTOM_DOMAIN_KEY = "d"
LEGACY_CUSTOM_DOMAIN_KEY = "d6"
LIFECYCLE_KEYS = {
    "s1": "active",
    "s2": "experimental",
    "s3": "legacy",
    "s4": "deprecated",
}


def _read_optional_value(input_func: InputFunc, prompt: str) -> str | None:
    """Read one optional value and cancel cleanly on keyboard interrupt."""

    try:
        return input_func(prompt).strip()
    except KeyboardInterrupt:
        return None


def _mark_duplicate_profile_allowed(
    block: Dict[str, Any],
    duplicate_profile: Any | None,
    reason: str,
) -> bool:
    """Record an explicit false-positive allowance for one duplicate profile."""
    if duplicate_profile is None:
        return False
    profile_keys = getattr(duplicate_profile, "keys", None)
    if profile_keys is None:
        return False
    duplicate_hash = getattr(profile_keys, "duplicate_hash", None)
    duplicate_key = getattr(profile_keys, "duplicate_key", None)
    if not duplicate_hash and not duplicate_key:
        return False

    duplicate_policy = block.get("duplicate_policy")
    if not isinstance(duplicate_policy, dict):
        duplicate_policy = {}
        block["duplicate_policy"] = duplicate_policy

    entries = duplicate_policy.get("allowed_active_duplicate_profiles")
    if not isinstance(entries, list):
        entries = []
        duplicate_policy["allowed_active_duplicate_profiles"] = entries

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        if duplicate_hash and entry.get("duplicate_hash") == duplicate_hash:
            entry["duplicate_key"] = duplicate_key
            entry["reason"] = reason
            return True
        if duplicate_key and entry.get("duplicate_key") == duplicate_key:
            entry["duplicate_hash"] = duplicate_hash
            entry["reason"] = reason
            return True

    entries.append(
        {
            "duplicate_hash": duplicate_hash,
            "duplicate_key": duplicate_key,
            "reason": reason,
        }
    )
    return True


class InspectorAction:
    """Define action names produced by inspector commands."""

    STAY = "stay"
    SAVE_NEXT = "save_next"
    SAVE_STAY = "save_stay"
    BACK = "back"
    QUIT = "quit"
    HELP = "help"
    INTERFACE_EDIT = "interface_edit"
    TOGGLE_FULL_VIEW = "toggle_full_view"
    UNKNOWN = "unknown"


def apply_inspector_command(
    command: str,
    issue: InspectIssue,
    purpose_suggestions: List[PurposeSuggestion],
    domain_suggestions: List[str],
    input_func: InputFunc,
    duplicate_profile: Any | None = None,
) -> str:
    """Apply one inspector command and return the navigation action."""

    stripped_command = normalize_command(command)

    if stripped_command == "":
        return InspectorAction.SAVE_NEXT

    if stripped_command in PURPOSE_SUGGESTION_KEYS:
        suggestion_index = PURPOSE_SUGGESTION_KEYS.index(stripped_command)
        if suggestion_index < len(purpose_suggestions):
            suggestion_text = purpose_suggestions[suggestion_index].text.strip()
            normalized_text = " ".join(suggestion_text.strip().lower().split())
            if normalized_text not in {"", "-", "write custom purpose", "write custom purpose..."}:
                issue.block["purpose"] = normalized_text
        return InspectorAction.STAY

    if (
        stripped_command == CUSTOM_PURPOSE_KEY
        or stripped_command.startswith(CUSTOM_PURPOSE_KEY)
        or stripped_command == LEGACY_CUSTOM_PURPOSE_KEY
        or stripped_command.startswith(f"{LEGACY_CUSTOM_PURPOSE_KEY} ")
    ):
        if stripped_command.startswith(f"{LEGACY_CUSTOM_PURPOSE_KEY} "):
            value = stripped_command[len(LEGACY_CUSTOM_PURPOSE_KEY):].strip()
        elif stripped_command == LEGACY_CUSTOM_PURPOSE_KEY:
            value = ""
        elif stripped_command.startswith(CUSTOM_PURPOSE_KEY):
            value = stripped_command[len(CUSTOM_PURPOSE_KEY):].strip()
        else:
            value = ""
        if not value:
            prompt_value = _read_optional_value(input_func=input_func, prompt="purpose: ")
            if prompt_value is None:
                return InspectorAction.STAY
            value = prompt_value
        if value:
            issue.block["purpose"] = " ".join(value.strip().lower().split())
        return InspectorAction.STAY

    # Check domain keys before other single-key commands.
    if stripped_command in DOMAIN_SUGGESTION_KEYS:
        domain_index = DOMAIN_SUGGESTION_KEYS.index(stripped_command)
        if domain_index < len(domain_suggestions):
            domain_text = domain_suggestions[domain_index].strip()
            if domain_text not in {"", "-", "custom"}:
                issue.block["domain"] = " ".join(domain_text.strip().lower().split())
        return InspectorAction.STAY

    # Then check lifecycle keys (s1, s2, s3, s4).
    if stripped_command in LIFECYCLE_KEYS:
        issue.block["status"] = LIFECYCLE_KEYS[stripped_command]
        return InspectorAction.STAY

    # Custom domain input.
    if (
        stripped_command == CUSTOM_DOMAIN_KEY
        or stripped_command.startswith(CUSTOM_DOMAIN_KEY)
        or stripped_command == LEGACY_CUSTOM_DOMAIN_KEY
        or stripped_command.startswith(f"{LEGACY_CUSTOM_DOMAIN_KEY} ")
    ):
        if stripped_command.startswith(f"{LEGACY_CUSTOM_DOMAIN_KEY} "):
            value = stripped_command[len(LEGACY_CUSTOM_DOMAIN_KEY):].strip()
        elif stripped_command == LEGACY_CUSTOM_DOMAIN_KEY:
            value = ""
        elif stripped_command.startswith(CUSTOM_DOMAIN_KEY):
            value = stripped_command[len(CUSTOM_DOMAIN_KEY):].strip()
        else:
            value = ""
        if not value:
            prompt_value = _read_optional_value(input_func=input_func, prompt="domain: ")
            if prompt_value is None:
                return InspectorAction.STAY
            value = prompt_value
        if value:
            issue.block["domain"] = " ".join(value.strip().lower().split())
        return InspectorAction.STAY


    if stripped_command.startswith("o"):
        value = stripped_command[1:].strip()
        if not value:
            prompt_value = _read_optional_value(input_func=input_func, prompt="observations: ")
            if prompt_value is None:
                return InspectorAction.STAY
            value = prompt_value
        if value:
            issue.block["notes"] = value
        return InspectorAction.STAY

    if stripped_command == ALLOW_DUPLICATE_PROFILE_KEY or stripped_command.startswith(f"{ALLOW_DUPLICATE_PROFILE_KEY} "):
        value = stripped_command[len(ALLOW_DUPLICATE_PROFILE_KEY):].strip()
        if not value:
            prompt_value = _read_optional_value(
                input_func=input_func,
                prompt="false-positive reason: ",
            )
            if prompt_value is None:
                return InspectorAction.STAY
            value = prompt_value
        reason = " ".join(value.strip().split())
        if reason:
            _mark_duplicate_profile_allowed(
                block=issue.block,
                duplicate_profile=duplicate_profile,
                reason=reason,
            )
        return InspectorAction.SAVE_STAY

    # Interface editing (i prefix)
    if stripped_command.startswith("i"):
        return InspectorAction.INTERFACE_EDIT

    if stripped_command == "b":
        return InspectorAction.BACK

    if is_quit_command(stripped_command):
        return InspectorAction.QUIT

    if stripped_command == "h":
        return InspectorAction.HELP

    if stripped_command == "f":
        return InspectorAction.TOGGLE_FULL_VIEW

    return InspectorAction.UNKNOWN


def run_interface_edit_submode(
    block: Dict[str, Any],
    input_func: InputFunc,
    print_func: Callable[[str], None],
) -> None:
    """Run interface editing sub-mode for adding/editing interface metadata.

    This is a simple interactive sub-mode that allows editing:
    - Add input (a)
    - Edit input by index (1, 2, 3...)
    - Remove input by index (d1, d2, d3...)
    - Edit output type/description (o)
    - Return to main inspector (Enter)

    Args:
        block: The block dict to modify.
        input_func: Function for reading user input.
        print_func: Function for printing output.
    """
    # Ensure interface dict exists
    if "interface" not in block:
        block["interface"] = {}

    interface = block["interface"]
    if not isinstance(interface, dict):
        block["interface"] = {}
        interface = block["interface"]

    try:
        while True:
            print_func("")
            print_func("─" * 50)
            print_func(" Interface Editor")
            print_func("─" * 50)

            # Show current interface
            inputs = interface.get("inputs", [])
            if not isinstance(inputs, list):
                inputs = []
                interface["inputs"] = inputs

            output = interface.get("output", {})
            if not isinstance(output, dict):
                output = {}
                interface["output"] = output

            print_func("")
            print_func("  inputs:")
            if not inputs:
                print_func("    (none defined)")
            else:
                for i, inp in enumerate(inputs, 1):
                    if not isinstance(inp, dict):
                        continue
                    name = inp.get("name", "?")
                    param_type = inp.get("type", "-")
                    default = inp.get("default", "-")
                    required = inp.get("required", True)
                    req_str = "required" if required else "optional"
                    print_func(f"    [{i}] {name} ({param_type}) {req_str} = {default}")

            print_func("")
            print_func("  output:")
            output_type = output.get("type", "-")
            print_func(f"    type: {output_type}")

            print_func("")
            print_func("  Commands:")
            print_func("    [a] add input              [o] edit output")
            print_func("    [1-N] edit input N          [dN] delete input N")
            print_func("    [Enter] return to inspector")
            print_func("")

            command = input_func("> ").strip()
            if command == "":
                break

            if command == "a":
                name = input_func("  parameter name: ").strip()
                if not name:
                    print_func("  Name is required")
                    continue

                param_type = input_func("  type (or Enter to skip): ").strip() or None
                default_str = input_func("  default value (or Enter for required): ").strip()

                if default_str == "":
                    required = True
                    default_val = None
                else:
                    required = False
                    try:
                        default_val = eval(default_str, {"__builtins__": {}}, {})
                    except Exception:
                        default_val = default_str

                new_input = {
                    "name": name,
                    "type": param_type,
                    "default": default_val,
                    "required": required,
                    "description": None,
                }
                inputs.append(new_input)
                interface["inputs"] = inputs
                print_func(f"  Added input: {name}")

            elif command == "o":
                current_type = output.get("type", "")
                current_desc = output.get("description", "")
                new_type = input_func(f"  output type [{current_type}]: ").strip() or current_type or None

                if not new_type:
                    if "output" in interface:
                        del interface["output"]
                    print_func("  Output removed")
                else:
                    interface["output"] = {"type": new_type, "description": current_desc}
                    print_func(f"  Output type set to: {new_type}")

            elif command.startswith("d") and len(command) > 1:
                try:
                    index = int(command[1:]) - 1
                    if 0 <= index < len(inputs):
                        removed = inputs.pop(index)
                        interface["inputs"] = inputs
                        print_func(f"  Removed input: {removed.get('name', '?')}")
                    else:
                        print_func(f"  Invalid input index: {index + 1}")
                except ValueError:
                    print_func(f"  Invalid command: {command}")

            else:
                try:
                    index = int(command) - 1
                    if 0 <= index < len(inputs):
                        inp = inputs[index]
                        if not isinstance(inp, dict):
                            continue

                        name = inp.get("name", "")
                        param_type = inp.get("type", "")
                        default_val = inp.get("default")
                        required = inp.get("required", True)

                        new_name = input_func(f"  name [{name}]: ").strip() or name
                        new_type = input_func(f"  type [{param_type}]: ").strip() or param_type or None

                        new_default = None
                        if not required:
                            default_str = str(default_val) if default_val is not None else ""
                            new_default_str = input_func(f"  default [{default_str}]: ").strip()
                            if new_default_str:
                                try:
                                    new_default = eval(new_default_str, {"__builtins__": {}}, {})
                                except Exception:
                                    new_default = new_default_str
                        else:
                            required_str = input_func("  required? [Y/n]: ").strip().lower()
                            if required_str and required_str.startswith("n"):
                                new_default_str = input_func("  default value: ").strip()
                                if new_default_str:
                                    try:
                                        new_default = eval(new_default_str, {"__builtins__": {}}, {})
                                    except Exception:
                                        new_default = new_default_str
                                required = False

                        inputs[index] = {
                            "name": new_name,
                            "type": new_type,
                            "default": new_default,
                            "required": required,
                            "description": None,
                        }
                        interface["inputs"] = inputs
                        print_func(f"  Updated input: {new_name}")
                    else:
                        print_func(f"  Invalid input index: {index + 1}")
                except ValueError:
                    print_func(f"  Unknown command: {command}")

            if not inputs and not output.get("type"):
                if "interface" in block:
                    del block["interface"]
    except KeyboardInterrupt:
        print_func("Interface editor cancelled.")
