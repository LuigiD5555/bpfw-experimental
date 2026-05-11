"""Terminal UI renderer for the Planner workspace."""

from typing import List, Optional

from bpfw.integrations.editor.screen import clear_screen, get_terminal_width
from bpfw.integrations.planner_impl.models import PlannerBox, PlannerConnection, PlannerState
from bpfw.integrations.shared.visual_theme import (
    DEFAULT_THEME,
    compute_panel_width,
    render_commands_box,
    render_header,
    render_panel,
    render_stacked_sections,
)
from bpfw.integrations.shared.visual_width import fit_text


class WorkspaceRenderer:
    """Render the hybrid workspace interface."""

    def __init__(self) -> None:
        """Initialize the workspace renderer."""
        self.terminal_width = get_terminal_width()

    def render(self, state: PlannerState) -> str:
        """Render complete workspace with stacked sections."""
        clear_screen()
        panel_width = compute_panel_width(
            content_lines=self._collect_content_preview(state),
            title="Blueprint Planner",
            terminal_width=self.terminal_width,
            theme=DEFAULT_THEME,
        )
        header_lines = self._render_banner(panel_width=panel_width)
        structure_lines = self._render_structure_panel(state.boxes, state.selected_box_id, panel_width)
        flow_lines = self._render_flow_panel(
            state.connections,
            state.boxes,
            state.selected_box_id,
            state.flow_source_filter,
            state.flow_confidence_filter,
            panel_width,
        )
        details_lines = self._render_config_panel(state, panel_width)
        command_lines = self._render_commands(panel_width)

        lines = render_stacked_sections(
            [header_lines, structure_lines, flow_lines, details_lines, command_lines],
            spacing=1,
        )
        return "\n".join(lines)

    def _render_banner(self, panel_width: int) -> List[str]:
        """Render planner header."""
        return render_header(
            title="Blueprint Planner",
            width=panel_width,
            theme=DEFAULT_THEME,
            centered=True,
        )

    def _render_structure_panel(
        self,
        boxes: List[PlannerBox],
        selected_box_id: Optional[str],
        panel_width: int,
    ) -> List[str]:
        """Render structure grouped by domain."""
        if not boxes:
            return self._render_panel(
                title="Structure",
                content_lines=[
                    "No boxes yet.",
                    "Press [a] to add your first box.",
                ],
                panel_width=panel_width,
            )

        domains: dict[str, List[PlannerBox]] = {}
        for box in boxes:
            domains.setdefault(box.domain, []).append(box)

        for domain in domains:
            domains[domain].sort(key=lambda item: item.name)

        content_lines: List[str] = []
        for domain in sorted(domains):
            content_lines.append(domain)
            for box in domains[domain]:
                prefix = "└─ " if box == domains[domain][-1] else "├─ "
                marker = "→ " if box.id == selected_box_id else "  "
                content_lines.append(f"{marker}{prefix}{box.name}")

        return self._render_panel(title="Structure", content_lines=content_lines, panel_width=panel_width)

    def _render_flow_panel(
        self,
        connections: List[PlannerConnection],
        boxes: List[PlannerBox],
        selected_box_id: Optional[str],
        source_filter: str,
        confidence_filter: str,
        panel_width: int,
    ) -> List[str]:
        """Render flow with filter metadata."""
        content_lines: List[str] = []
        box_names = {box.id: box.name for box in boxes}
        filtered_connections = self._filter_connections(connections, source_filter, confidence_filter)

        declared_count = sum(1 for conn in connections if conn.source_kind == "blueprint")
        inferred_count = sum(1 for conn in connections if conn.source_kind == "inferred")
        suggested_count = sum(1 for conn in connections if conn.status == "suggested")
        content_lines.append(f"declared:{declared_count} inferred:{inferred_count} suggested:{suggested_count}")
        content_lines.append(f"filters source:{source_filter} confidence:{confidence_filter}")
        content_lines.append("")

        if not filtered_connections:
            content_lines.append("No connections yet.")
            content_lines.append("Use [f] source and [g] confidence filters.")
        else:
            for connection in filtered_connections:
                source_name = box_names.get(connection.source_box_id, connection.source_box_id)
                target_name = box_names.get(connection.target_box_id, connection.target_box_id)
                marker = "→ " if (
                    connection.source_box_id == selected_box_id
                    or connection.target_box_id == selected_box_id
                ) else "  "
                source_marker = "B" if connection.source_kind == "blueprint" else "I"
                confidence_marker = connection.confidence[:1].upper()
                status_marker = "A" if connection.status == "accepted" else "S"
                content_lines.append(
                    f"{marker}[{source_marker}{confidence_marker}{status_marker}] "
                    f"{source_name} -> {target_name} ({connection.relationship})"
                )

        return self._render_panel(title="Flow", content_lines=content_lines, panel_width=panel_width)

    def _render_config_panel(self, state: PlannerState, panel_width: int) -> List[str]:
        """Render selected box details or selected connection details."""
        selected_box = None
        if state.selected_box_id:
            for box in state.boxes:
                if box.id == state.selected_box_id:
                    selected_box = box
                    break

        if not selected_box:
            selected_connection = None
            if state.selected_connection_id is not None and 0 <= state.selected_connection_id < len(state.connections):
                selected_connection = state.connections[state.selected_connection_id]
            if selected_connection:
                evidence_text = "; ".join(selected_connection.evidence[:2]) or "no evidence"
                return self._render_panel(
                    title="Details",
                    content_lines=[
                        f"connection: {selected_connection.source_box_id} -> {selected_connection.target_box_id}",
                        f"relationship: {selected_connection.relationship}",
                        f"origin: {selected_connection.source_kind}",
                        f"confidence: {selected_connection.confidence}",
                        f"status: {selected_connection.status}",
                        f"evidence: {evidence_text}",
                    ],
                    panel_width=panel_width,
                )
            return self._render_panel(
                title="Details",
                content_lines=["No box selected. Select a box to see details."],
                panel_width=panel_width,
            )

        content_lines = [
            f"id: {selected_box.id}",
            f"intent: {selected_box.intent}",
            f"domain: {selected_box.domain}",
            f"lifecycle: {selected_box.lifecycle}",
            "",
            f"path: {selected_box.path or '(not set)'}",
            f"symbol: {selected_box.symbol or '(not set)'}",
            f"symbol_type: {selected_box.symbol_type}",
        ]
        if selected_box.interface:
            content_lines.append("")
            if selected_box.interface.inputs:
                content_lines.append("inputs:")
                for item in selected_box.interface.inputs:
                    item_line = f"   - {item.name}"
                    if item.type:
                        item_line += f": {item.type}"
                    content_lines.append(item_line)
            if selected_box.interface.output:
                content_lines.append("output:")
                content_lines.append(
                    f"   - type: {selected_box.interface.output.type or 'not set'}"
                )

        return self._render_panel(
            title=f"Config: {selected_box.name}",
            content_lines=content_lines,
            panel_width=panel_width,
        )

    def _render_commands(self, panel_width: int) -> List[str]:
        """Render commands in inspector-style box."""
        command_lines = [
            "[a] Add Box             [c] Connect               [tab] Configure",
            "[f] Source Filter       [g] Confidence Filter     [x] Accept Suggestion",
            "[z] Reject Suggestion   [p] Project               [r] Review",
            "[s] Save                [q] Quit",
        ]
        return render_commands_box(
            lines=command_lines,
            width=panel_width,
            theme=DEFAULT_THEME,
            wrap_mode="safe_wrap",
        )

    def _filter_connections(
        self,
        connections: List[PlannerConnection],
        source_filter: str,
        confidence_filter: str,
    ) -> List[PlannerConnection]:
        """Filter connections by source and confidence."""
        filtered: List[PlannerConnection] = []
        for connection in connections:
            source_ok = source_filter == "all" or connection.source_kind == source_filter
            confidence_ok = confidence_filter == "all" or connection.confidence == confidence_filter
            if source_ok and confidence_ok:
                filtered.append(connection)
        return filtered

    def _render_panel(self, title: str, content_lines: List[str], panel_width: int) -> List[str]:
        """Render one panel."""
        normalized = [fit_text(line, panel_width) for line in content_lines]
        return render_panel(
            title=title,
            lines=normalized,
            width=panel_width,
            theme=DEFAULT_THEME,
            centered_title=True,
        )

    def _collect_content_preview(self, state: PlannerState) -> List[str]:
        """Build content sample for width calculation."""
        preview: List[str] = [
            "Blueprint Planner",
            "[a] Add Box             [c] Connect               [tab] Configure",
        ]
        for box in state.boxes[:12]:
            preview.append(f"{box.domain} {box.name} {box.path or ''}")
        for connection in state.connections[:12]:
            preview.append(
                f"{connection.source_box_id} -> {connection.target_box_id} ({connection.relationship})"
            )
        return preview
