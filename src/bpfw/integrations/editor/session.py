"""Editor session — search-first block launcher for BPFW Editor.

The editor searches blueprint blocks and delegates editing to Inspector.
It does not edit fields directly — it locates a block and opens the
inspector in target mode.
"""

from pathlib import Path

from bpfw.catalog.loader import BlueprintLoader
from bpfw.integrations.editor.filters import FilterState, apply_filters, parse_filter_input
from bpfw.integrations.editor.screen import (
    read_input,
    render_editor_help_screen,
    render_filter_error,
    render_filter_screen,
    render_invalid_selection,
    render_results_table,
    render_search_screen,
)
from bpfw.integrations.editor.search import (
    SearchRecord,
    build_search_records,
    build_search_records_from_document,
    search_records,
)
from bpfw.integrations.shared.cli_runtime import is_quit_command, normalize_command
from bpfw.protection.authority import get_authority_protection_status


class EditorSession:
    """Search-first launcher that finds blocks and opens inspector."""

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root

    def run(self) -> int:
        """Run the editor session. Returns exit code."""

        # Check blueprint exists
        loader = BlueprintLoader(project_root=self.project_root)
        load_result = loader.load()

        if load_result.state == "missing":
            print("No blueprint found.\n\nCreate one first:\n\n  bpfw init")
            return 1

        if load_result.state == "invalid":
            print("Blueprint is invalid.\n\nFix bpfw/blueprint.yaml before using editor.")
            return 1

        # Check lock status
        lock_state = get_authority_protection_status(project_root=self.project_root).status
        if lock_state == "locked":
            print("Blueprint is locked.\n\nUnlock before using editor:\n\n  bpfw unlock")
            return 1

        # Check has blocks
        blueprint_data = load_result.data
        blocks = blueprint_data.get("blocks", [])
        if not isinstance(blocks, list) or len(blocks) == 0:
            print(
                "Blueprint has no blocks.\n\n"
                "Next:\n"
                "  bpfw inspector"
            )
            return 1

        # Build search records and start session
        if load_result.domain_document is not None:
            records = build_search_records_from_document(load_result.domain_document)
        else:
            records = build_search_records(blueprint_data)
        if not records:
            print(
                "Blueprint has no searchable blocks.\n\n"
                "Next:\n"
                "  bpfw inspector"
            )
            return 1

        return self._run_search_loop(records)


    def _run_search_loop(self, all_records: list[SearchRecord]) -> int:
        """Main search loop: search → results → inspect → search again."""

        current_records = all_records
        query = ""
        filter_state = FilterState()

        while True:
            # Show search screen and get query
            render_search_screen()
            raw_input = read_input("search: ")
            command = normalize_command(raw_input)

            if is_quit_command(command):
                print("Editor closed.")
                return 0
            if command == "h":
                self._show_help()
                continue

            # Empty input means show all
            if command == "" or command == "a":
                query = ""
                filter_state.clear()
                current_records = all_records
            else:
                query = raw_input
                current_records = search_records(all_records, query)
                # Re-apply any existing filters on the search results
                current_records = apply_filters(current_records, filter_state)

            # Results loop
            should_continue = True
            while should_continue:
                render_results_table(
                    results=current_records,
                    query=query,
                    filter_display_lines=filter_state.display_lines(),
                )

                raw_command = read_input("command: ")
                command = normalize_command(raw_command)

                if is_quit_command(command):
                    print("Editor closed.")
                    return 0

                if command == "h":
                    self._show_help()
                    continue

                if command == "/":
                    # Search again — keep filters
                    should_continue = False
                    continue

                if command == "a":
                    # Show all — clear query and filters
                    query = ""
                    filter_state.clear()
                    current_records = all_records
                    should_continue = False
                    continue

                if command == "c":
                    # Clear filters, keep query
                    filter_state.clear()
                    current_records = search_records(all_records, query)
                    continue

                if command == "f":
                    # Filter flow
                    result = self._handle_filter(filter_state)
                    if result == "quit":
                        print("Editor closed.")
                        return 0
                    # Recalculate results with current query + updated filters
                    current_records = search_records(all_records, query)
                    current_records = apply_filters(current_records, filter_state)
                    continue

                # Try to parse as IDX
                if command.isdigit():
                    selected_index = int(command) - 1
                    if 0 <= selected_index < len(current_records):
                        record = current_records[selected_index]
                        inspector_result = self._open_inspector(record)
                        if inspector_result == "quit":
                            print("Editor closed.")
                            return 0

                        # Reload blueprint after inspector may have modified it
                        reloaded_records = self._reload_records()
                        if reloaded_records is not None:
                            all_records = reloaded_records

                        # Return to search screen (clear query and filters)
                        query = ""
                        filter_state.clear()
                        current_records = all_records
                        should_continue = False
                        continue

                    render_invalid_selection()
                    continue

                # Unknown command
                if command:
                    render_invalid_selection()
                    continue

                # Empty input — do nothing, re-render
                continue

        return 0


    def _handle_filter(self, filter_state: FilterState) -> str:
        """Handle the filter input flow. Returns 'continue' or 'quit'."""

        render_filter_screen()
        raw_input = read_input("filter: ")
        command = normalize_command(raw_input)

        if is_quit_command(command):
            return "quit"

        if not raw_input:
            return "continue"

        result = parse_filter_input(raw_input)
        if isinstance(result, str):
            render_filter_error(result)
            return "continue"

        column, value = result
        filter_state.add(column, value)
        return "continue"


    def _open_inspector(self, record: SearchRecord) -> str:
        """Open the inspector in target mode for a given record."""

        from bpfw.integrations.inspector.target import run_inspector_target

        result = run_inspector_target(
            project_root=self.project_root,
            block_id=record.responsibility_id,
            header_title="Blueprint Framework Editor · Inspect",
        )

        if result == "saved":
            print("")
            print("Saved.")
            print("")
            print("Returning to Editor search...")

        return result


    def _reload_records(self) -> list[SearchRecord] | None:
        """Reload blueprint and rebuild search records. Returns None on failure."""

        loader = BlueprintLoader(project_root=self.project_root)
        load_result = loader.load()

        if load_result.state in {"missing", "invalid"}:
            return None

        if load_result.domain_document is not None:
            return build_search_records_from_document(load_result.domain_document)
        return build_search_records(load_result.data)


    def _show_help(self) -> None:
        """Render editor help and wait for user confirmation."""

        render_editor_help_screen()
        print("")
        print("Press any key then Enter to continue...")
        read_input("> ")
