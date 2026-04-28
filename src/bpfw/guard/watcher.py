from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bpfw.authority.lock_manager import AuthorityLockManager
from bpfw.authority.state import clear_unlock_window, load_authority_state
from bpfw.guard.restorer import AuthorityRestorer
from bpfw.guard.watch_reporter import WatchReporter
from bpfw.integrity.manifest import IntegrityManifestError, load_manifest


class AuthorityWatcher:
    """Foreground watcher-style scanner for authority drift."""

    def __init__(self) -> None:
        self._restorer = AuthorityRestorer()
        self._reporter = WatchReporter()

    def scan_once(self, project_root: Path):  # noqa: ANN001
        try:
            _ = load_manifest(project_root=project_root)
        except IntegrityManifestError as error:
            return self._reporter.render_block(file_path=str(error))

        state = load_authority_state(project_root=project_root)
        drifted_path = self._restorer.first_drifted_authority_path(project_root=project_root)
        if not drifted_path:
            return self._reporter.render_no_drift()

        # If there is a valid active unlock window for this exact resource and it is not expired,
        # watcher does not block during this scan.
        if state.active_unlock_window is not None and state.active_unlock_window.resource_path == drifted_path:
            expires_at = datetime.fromisoformat(state.active_unlock_window.expires_at.replace("Z", "+00:00"))
            if expires_at.astimezone(timezone.utc) > datetime.now(tz=timezone.utc):
                return self._reporter.render_no_drift()

        try:
            self._relock_all(project_root=project_root)
        except Exception:
            # Watcher still reports a blocking event even if relock fails.
            pass
        clear_unlock_window(project_root=project_root, mark_locked=True)
        self._restorer.restore(project_root=project_root, relative_path=drifted_path)
        return self._reporter.render_block(file_path=drifted_path)

    def _relock_all(self, project_root: Path) -> None:
        AuthorityLockManager().relock_all(project_root=project_root)
