from __future__ import annotations

from pathlib import Path

from bpfw.authority.lock_policy import OsLockPolicy
from bpfw.authority.os_lock import OsLockProvider
from bpfw.authority.resources import AuthorityResourceRegistry
from bpfw.authority.state import load_authority_state, save_authority_state


class AuthorityLockManager:
    """Applies OS lock operations over registered authority resources."""

    def __init__(self) -> None:
        self._registry = AuthorityResourceRegistry()
        self._provider: OsLockProvider | None = None

    @property
    def provider(self) -> OsLockProvider:
        return self._get_provider()

    def lock_all(self, project_root: Path) -> int:
        locked_count = 0
        for resource in self._registry.list_resources():
            resource_path = project_root / resource.path
            locked_count += self._lock_path(resource_path)
        state = load_authority_state(project_root=project_root)
        state.os_lock_enabled = True
        save_authority_state(project_root=project_root, state=state)
        return locked_count

    def relock_all(self, project_root: Path) -> int:
        return self.lock_all(project_root=project_root)

    def lock_resource(self, project_root: Path, resource_id: str) -> int:
        resource = self._registry.get(resource_id)
        if resource is None:
            raise RuntimeError(f"Unknown authority resource: {resource_id}")
        resource_path = project_root / resource.path
        locked_count = self._lock_path(resource_path)
        state = load_authority_state(project_root=project_root)
        state.os_lock_enabled = True
        save_authority_state(project_root=project_root, state=state)
        return locked_count

    def unlock_resource(self, project_root: Path, resource_id: str) -> int:
        resource = self._registry.get(resource_id)
        if resource is None:
            raise RuntimeError(f"Unknown authority resource: {resource_id}")
        resource_path = project_root / resource.path
        unlocked_count = self._unlock_path(resource_path)
        state = load_authority_state(project_root=project_root)
        state.os_lock_enabled = False
        save_authority_state(project_root=project_root, state=state)
        return unlocked_count

    def status(self, project_root: Path) -> list[tuple[str, str, str]]:
        output: list[tuple[str, str, str]] = []
        for resource in self._registry.list_resources():
            resource_path = project_root / resource.path
            if resource_path.is_file():
                output.append((resource.resource_id, resource.path, self._get_provider().status(resource_path)))
                continue
            if resource_path.is_dir():
                states: set[str] = set()
                has_files = False
                for nested_file in self._iter_resource_files(resource_path):
                    has_files = True
                    states.add(self._get_provider().status(nested_file))
                if not has_files:
                    output.append((resource.resource_id, resource.path, "unknown"))
                elif states == {"locked"}:
                    output.append((resource.resource_id, resource.path, "locked"))
                elif states == {"unlocked"}:
                    output.append((resource.resource_id, resource.path, "unlocked"))
                else:
                    output.append((resource.resource_id, resource.path, "mixed"))
                continue
            output.append((resource.resource_id, resource.path, "unknown"))
        return output

    def _lock_path(self, resource_path: Path) -> int:
        if resource_path.is_file():
            self._get_provider().lock(resource_path)
            return 1

        if resource_path.is_dir():
            count = 0
            for nested_file in self._iter_resource_files(resource_path):
                self._get_provider().lock(nested_file)
                count += 1
            return count

        return 0

    def _unlock_path(self, resource_path: Path) -> int:
        if resource_path.is_file():
            self._get_provider().unlock(resource_path)
            return 1

        if resource_path.is_dir():
            count = 0
            for nested_file in self._iter_resource_files(resource_path):
                self._get_provider().unlock(nested_file)
                count += 1
            return count

        return 0

    def _get_provider(self) -> OsLockProvider:
        if self._provider is None:
            self._provider = OsLockPolicy().resolve_provider()
        return self._provider

    def _iter_resource_files(self, directory_path: Path):  # noqa: ANN202
        for nested_file in sorted(directory_path.rglob("*")):
            if not nested_file.is_file():
                continue
            if "__pycache__" in nested_file.parts:
                continue
            if nested_file.suffix in {".pyc", ".pyo"}:
                continue
            yield nested_file
