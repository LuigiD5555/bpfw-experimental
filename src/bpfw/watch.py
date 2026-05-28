"""PURPOSE lightweight real-time drift feedback for BPFW
DOMAIN  file watching
"""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence

from bpfw.core.catalog.verify import run_verify
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding
from bpfw.reports.verify_report import render_verify_report


class WatchDependencyError(RuntimeError):
    """PURPOSE raised when the watch dependency is not installed
    DOMAIN  file watching
    """


@dataclass(frozen=True)
class WatchSettings:
    """PURPOSE configuration for the BPFW watch service
    DOMAIN  file watching
    """

    project_root: Path
    debounce_ms: int = 800
    once: bool = False


@dataclass(frozen=True)
class VerificationSnapshot:
    """PURPOSE compact immutable summary of a verification run
    DOMAIN  file watching
    """

    allowed: bool
    exit_code: int
    fingerprint: str
    finding_count: int
    block_count: int
    report_text: str


class BpfwWatchFilter:
    """PURPOSE filter filesystem events to files relevant for BPFW drift feedback
    DOMAIN  file watching
    """

    _IGNORED_PARTS = frozenset(
        {
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "node_modules",
            "venv",
        }
    )
    _RELEVANT_SUFFIXES = frozenset({".py", ".yaml", ".yml", ".toml"})

    def __init__(self, project_root: Path) -> None:
        """PURPOSE set up the event filter
        DOMAIN  file watching
        """

        self.project_root = project_root.resolve()

    def __call__(self, _change: object, path: str) -> bool:
        """PURPOSE check whether the event path should trigger BPFW feedback
        DOMAIN  file watching
        """

        changed_path = Path(path).resolve()
        try:
            relative_path = changed_path.relative_to(self.project_root)
        except ValueError:
            return False

        if any(part in self._IGNORED_PARTS for part in relative_path.parts):
            return False

        if relative_path.parts[:2] == (".bpfw", "cache"):
            return False

        return changed_path.suffix in self._RELEVANT_SUFFIXES


class WatchService:
    """PURPOSE observe project changes and provide lightweight drift feedback
    DOMAIN  file watching
    """

    def __init__(self, settings: WatchSettings) -> None:
        """PURPOSE set up the watch service
        DOMAIN  file watching
        """

        self.settings = WatchSettings(
            project_root=settings.project_root.resolve(),
            debounce_ms=settings.debounce_ms,
            once=settings.once,
        )

    def run(self) -> int:
        """PURPOSE run real-time feedback or a single verification pass
        DOMAIN  file watching
        """

        initial_snapshot = build_verification_snapshot(self.settings.project_root)
        print(_render_initial_snapshot(initial_snapshot))

        if self.settings.once:
            return initial_snapshot.exit_code

        try:
            from watchfiles import watch
        except ModuleNotFoundError as error:
            raise WatchDependencyError(
                "bpfw watch requires the optional dependency 'watchfiles'. "
                "Install the project dependencies again or run: pip install watchfiles"
            ) from error

        last_snapshot = initial_snapshot
        event_filter = BpfwWatchFilter(self.settings.project_root)
        print("BPFW WATCH ACTIVE")
        print(f"  project: {self.settings.project_root}")
        print(f"  debounce: {self.settings.debounce_ms}ms")
        print("  press Ctrl+C to stop")
        print("")

        try:
            for changes in watch(
                self.settings.project_root,
                debounce=self.settings.debounce_ms,
                watch_filter=event_filter,
            ):
                last_snapshot = self._handle_changes(
                    changes=changes,
                    previous_snapshot=last_snapshot,
                )
        except KeyboardInterrupt:
            print("BPFW WATCH STOPPED")
            return 0

        return 0

    def _handle_changes(
        self,
        changes: Iterable[tuple[object, str]],
        previous_snapshot: VerificationSnapshot,
    ) -> VerificationSnapshot:
        """PURPOSE analyze one debounced filesystem event batch
        DOMAIN  file watching
        """

        changed_paths = _format_changed_paths(
            project_root=self.settings.project_root,
            changes=changes,
        )
        current_snapshot = build_verification_snapshot(self.settings.project_root)

        print("BPFW WATCH EVENT")
        if changed_paths:
            print("  changed:")
            for changed_path in changed_paths:
                print(f"    - {changed_path}")

        if current_snapshot.fingerprint == previous_snapshot.fingerprint:
            print("  drift: unchanged")
            print("")
            return current_snapshot

        print(_render_delta_snapshot(current_snapshot))
        return current_snapshot


def build_verification_snapshot(project_root: Path) -> VerificationSnapshot:
    """PURPOSE run BPFW verification and summarize the resulting drift state
    DOMAIN  file watching
    """

    report, exit_code = run_verify(project_root=project_root.resolve())
    report_text = render_verify_report(report)
    return VerificationSnapshot(
        allowed=report.allowed,
        exit_code=exit_code,
        fingerprint=_fingerprint_findings(report.findings),
        finding_count=len(report.findings),
        block_count=sum(1 for finding in report.findings if finding.severity == FINDING_SEVERITY_BLOCK),
        report_text=report_text,
    )


def run_watch(project_root: Path, debounce_ms: int = 800, once: bool = False) -> int:
    """PURPOSE run the BPFW watch command
    DOMAIN  file watching
    """

    settings = WatchSettings(project_root=project_root, debounce_ms=debounce_ms, once=once)
    return WatchService(settings=settings).run()


def _fingerprint_findings(findings: Sequence[Finding]) -> str:
    """PURPOSE build a stable fingerprint for a finding sequence
    DOMAIN  file watching
    """

    normalized_items = []
    for finding in findings:
        normalized_items.append(
            "|".join(
                [
                    finding.severity,
                    finding.code,
                    finding.path or "",
                    finding.symbol or "",
                    finding.message,
                    repr(sorted(finding.evidence.items())),
                ]
            )
        )
    payload = "\n".join(sorted(normalized_items)).encode("utf-8")
    return sha256(payload).hexdigest()


def _format_changed_paths(project_root: Path, changes: Iterable[tuple[object, str]]) -> list[str]:
    """PURPOSE format changed paths relative to the project root
    DOMAIN  file watching
    """

    formatted_paths: set[str] = set()
    resolved_root = project_root.resolve()
    for _change, path in changes:
        changed_path = Path(path).resolve()
        try:
            relative_path = changed_path.relative_to(resolved_root)
        except ValueError:
            formatted_paths.add(str(changed_path))
            continue
        formatted_paths.add(str(relative_path))
    return sorted(formatted_paths)


def _render_initial_snapshot(snapshot: VerificationSnapshot) -> str:
    """PURPOSE show the first watch verification summary
    DOMAIN  file watching
    """

    state = "ALIGNED" if snapshot.allowed else "DRIFT DETECTED"
    return "\n".join(
        [
            "BPFW WATCH BASELINE",
            f"  state: {state}",
            f"  findings: {snapshot.finding_count}",
            f"  blocking findings: {snapshot.block_count}",
            "",
        ]
    )


def _render_delta_snapshot(snapshot: VerificationSnapshot) -> str:
    """PURPOSE show drift feedback after a watched change
    DOMAIN  file watching
    """

    if snapshot.allowed:
        return "\n".join(
            [
                "  drift: resolved",
                "  execution: ALLOWED",
                "",
            ]
        )

    return "\n".join(
        [
            "  drift: changed",
            "  execution: BLOCKED",
            "",
            snapshot.report_text,
            "",
        ]
    )
