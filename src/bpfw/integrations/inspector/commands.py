"""Command handling for the inspector integration."""

from collections.abc import Callable
from typing import Any, Dict, List

from bpfw.catalog.purpose_suggestions import PurposeSuggestion
from bpfw.catalog.schema import set_purpose, set_status
from bpfw.integrations.inspector.base import InspectIssue
from bpfw.integrations.shared.cli_runtime import is_quit_command, normalize_command

InputFunc = Callable[[str], str]
DOMAIN_SUGGESTION_KEYS = ("q", "w", "e", "r", "t")
CUSTOM_DOMAIN_KEY = "y"


class InspectorAction:
    """Define action names produced by inspector commands."""

    STAY = "stay"
    SAVE_NEXT = "save_next"
    BACK = "back"
    QUIT = "quit"
    HELP = "help"
    INTERFACE_EDIT = "interface_edit"
    UNKNOWN = "unknown"


def apply_inspector_command(
    command: str,
    issue: InspectIssue,
    purpose_suggestions: List[PurposeSuggestion],
    domain_suggestions: List[str],
    input_func: InputFunc,
) -> str:
    """Apply one inspector command and return the navigation action."""

    stripped_command = normalize_command(command)

    if stripped_command == "":
        return InspectorAction.SAVE_NEXT

    if stripped_command in {"1", "2", "3", "4", "5"}:
        suggestion_index = int(stripped_command) - 1
        if suggestion_index < len(purpose_suggestions):
            suggestion_text = purpose_suggestions[suggestion_index].text.strip()
            if suggestion_text not in {"", "-", "Write custom purpose..."}:
                set_purpose(issue.block, suggestion_text)
        return InspectorAction.STAY

    if stripped_command.startswith("6"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("purpose: ").strip()
        if value:
            set_purpose(issue.block, value)
        return InspectorAction.STAY

    # Check domain keys before other single-key commands.
    if stripped_command in DOMAIN_SUGGESTION_KEYS:
        domain_index = DOMAIN_SUGGESTION_KEYS.index(stripped_command)
        if domain_index < len(domain_suggestions):
            domain_text = domain_suggestions[domain_index].strip()
            if domain_text not in {"", "-", "custom"}:
                issue.block["domain"] = domain_text
        return InspectorAction.STAY

    # Then check status keys (z, x, c, v)
    if stripped_command in {"z", "x", "c", "v"}:
        set_status(issue.block, {
            "z": "active",
            "x": "experimental",
            "c": "legacy",
            "v": "deprecated",
        }[stripped_command])
        return InspectorAction.STAY

    # Custom domain input.
    if stripped_command.startswith(CUSTOM_DOMAIN_KEY):
        value = stripped_command[len(CUSTOM_DOMAIN_KEY):].strip()
        if not value:
            value = input_func("domain: ").strip()
        if value:
            issue.block["domain"] = value
        return InspectorAction.STAY

    if stripped_command.startswith("n"):
        value = stripped_command[1:].strip()
        if not value:
            current_name = issue.block.get("name", "")
            value = input_func(f"name [{current_name}]: ").strip()
        if value:
            issue.block["name"] = value
        return InspectorAction.STAY

    if stripped_command.startswith("o"):
        value = stripped_command[1:].strip()
        if not value:
            value = input_func("observations: ").strip()
        if value:
            issue.block["notes"] = value
        return InspectorAction.STAY

    # Interface editing (i prefix)
    if stripped_command.startswith("i"):
        return InspectorAction.INTERFACE_EDIT

    if stripped_command == "b":
        return InspectorAction.BACK

    if is_quit_command(stripped_command):
        return InspectorAction.QUIT

    if stripped_command == "h":
        return InspectorAction.HELP

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
