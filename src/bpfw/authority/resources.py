from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthorityResource:
    """Represents a protected authority resource inside a governed project."""

    resource_id: str
    path: str
    resource_type: str
    default_policy: str
    allowed_operations: list[str]


DEFAULT_AUTHORITY_RESOURCES = [
    AuthorityResource(
        resource_id="project_blueprint",
        path="blueprint.yaml",
        resource_type="blueprint",
        default_policy="deny_direct_edit",
        allowed_operations=[
            "add_allowed_file",
            "add_allowed_symbol",
            "add_experimental_implementation",
            "create_responsibility",
            "set_lifecycle",
            "promote_implementation",
        ],
    ),
    AuthorityResource(
        resource_id="bpfw_core",
        path="src/bpfw/",
        resource_type="framework_core",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_framework_core"],
    ),
    AuthorityResource(
        resource_id="project_config",
        path="pyproject.toml",
        resource_type="project_config",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_project_config"],
    ),
    AuthorityResource(
        resource_id="bootstrap_wiring",
        path="src/bootstrap/wiring.py",
        resource_type="bootstrap_wiring",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_bootstrap_wiring"],
    ),
    AuthorityResource(
        resource_id="bootstrap_container",
        path="src/bootstrap/container.py",
        resource_type="bootstrap_container",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_bootstrap_container"],
    ),
    AuthorityResource(
        resource_id="python_lock_uv",
        path="uv.lock",
        resource_type="lockfile",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_lock_file"],
    ),
    AuthorityResource(
        resource_id="python_lock_poetry",
        path="poetry.lock",
        resource_type="lockfile",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_lock_file"],
    ),
    AuthorityResource(
        resource_id="python_requirements",
        path="requirements.txt",
        resource_type="lockfile",
        default_policy="deny_direct_edit",
        allowed_operations=["modify_lock_file"],
    ),
    AuthorityResource(
        resource_id="architecture_profile",
        path="architecture.yaml",
        resource_type="architecture",
        default_policy="deny_direct_edit",
        allowed_operations=["add_layer", "add_composition_root", "change_import_rule"],
    ),
    AuthorityResource(
        resource_id="integrity_manifest",
        path=".bpfw/manifest.json",
        resource_type="manifest",
        default_policy="deny_direct_edit",
        allowed_operations=["seal_baseline"],
    ),
]

_AUTHORITY_FILE_PATHS = {
    ".bpfw/state.json": "authority_state",
    "pyproject.toml": "python_project_config",
    "uv.lock": "python_lock_uv",
    "poetry.lock": "python_lock_poetry",
    "requirements.txt": "python_requirements",
    "src/bootstrap/wiring.py": "bootstrap_wiring",
    "src/bootstrap/container.py": "bootstrap_container",
}

_AUTHORITY_DIRECTORY_PREFIXES = {
    ".bpfw/access_requests/": "authority_access_requests",
    ".bpfw/access_grants/": "authority_access_grants",
    ".bpfw/approvals/": "authority_approvals",
    "src/bpfw/": "framework_runtime",
}


class AuthorityResourceRegistry:
    """Provides the official list of authority resources protected by BPFW."""

    def list_resources(self) -> list[AuthorityResource]:
        return list(DEFAULT_AUTHORITY_RESOURCES)

    def get(self, resource_id: str) -> AuthorityResource | None:
        for resource in DEFAULT_AUTHORITY_RESOURCES:
            if resource.resource_id == resource_id:
                return resource
        return None

    def is_authority_path(self, relative_path: str) -> bool:
        return self.resolve_by_path(relative_path) is not None

    def resolve_by_path(self, relative_path: str) -> AuthorityResource | None:
        normalized_path = relative_path.strip().replace("\\", "/")
        if not normalized_path:
            return None

        for resource in DEFAULT_AUTHORITY_RESOURCES:
            if resource.path.endswith("/") and normalized_path.startswith(resource.path):
                return resource
            if resource.path == normalized_path:
                return resource

        if normalized_path in _AUTHORITY_FILE_PATHS:
            resource_id = _AUTHORITY_FILE_PATHS[normalized_path]
            return AuthorityResource(resource_id, normalized_path, "authority_config", "deny_direct_edit", [])

        for prefix, resource_id in _AUTHORITY_DIRECTORY_PREFIXES.items():
            if normalized_path.startswith(prefix):
                return AuthorityResource(resource_id, prefix, "authority_directory", "deny_direct_edit", [])

        return None
