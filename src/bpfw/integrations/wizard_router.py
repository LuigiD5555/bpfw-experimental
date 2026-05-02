"""Route the wizard command to inspect or plan."""

from dataclasses import dataclass
from pathlib import Path

from bpfw.catalog.loader import BlueprintLoader
from bpfw.catalog.models import AUTHORITY_STATE_INVALID
from bpfw.catalog.scanner import scan_python_project
from bpfw.catalog.verify import _read_ignored_paths, _read_source_roots


@dataclass(frozen=True, slots=True)
class WizardRoute:
    """Selected wizard route and decision details."""

    route_name: str
    authority_state: str
    discovered_count: int
    message: str
    exit_code: int = 0

    @property
    def blocked(self) -> bool:
        """Return True when the wizard cannot route."""

        return self.exit_code != 0


def select_wizard_route(project_root: Path) -> WizardRoute:
    """Select the wizard route for the current project state."""

    resolved_root = project_root.resolve()
    load_result = BlueprintLoader(project_root=resolved_root).load()

    if load_result.state == AUTHORITY_STATE_INVALID:
        return WizardRoute(
            route_name="blocked",
            authority_state=load_result.state,
            discovered_count=0,
            message="Blueprint is invalid. Fix bpfw/blueprint.yaml before running wizard.",
            exit_code=1,
        )

    source_roots = _read_source_roots(load_result.data)
    ignored_paths = _read_ignored_paths(load_result.data)
    scan_result = scan_python_project(
        project_root=resolved_root,
        source_roots=source_roots,
        ignored_paths=ignored_paths,
    )
    discovered_count = len(scan_result.discovered_units)

    if discovered_count > 0:
        return WizardRoute(
            route_name="inspect",
            authority_state=load_result.state,
            discovered_count=discovered_count,
            message="Existing code detected. Routing to inspect.",
        )

    return WizardRoute(
        route_name="plan",
        authority_state=load_result.state,
        discovered_count=discovered_count,
        message="No existing code detected. Routing to plan.",
    )


def render_wizard_route_screen(
    route: WizardRoute,
    print_func=print,  # noqa: ANN001
) -> None:
    """Render the wizard routing decision."""

    print_func("BPFW Wizard")
    print_func("")
    print_func("Decision")
    print_func(f"  route: {route.route_name}")
    print_func(f"  authority: {route.authority_state}")
    print_func(f"  discovered code units: {route.discovered_count}")
    print_func("")
    print_func(route.message)
