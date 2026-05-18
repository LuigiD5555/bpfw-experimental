"""Lightweight real-time drift feedback for BPFW."""

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, Sequence

from bpfw.catalog.verify import run_verify
from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding
from bpfw.reports.verify_report import render_verify_report


class WatchDependencyError(RuntimeError):
    """Raised when the optional watch dependency is not installed."""


@dataclass(frozen=True)
class WatchSettings:
    """Configuration for the BPFW watch service.

    Attributes:
        project_root: Root directory of the project being observed.
        debounce_ms: Number of milliseconds used to batch rapid filesystem events.
        once: Whether to run a single verification and exit.
    """

    project_root: Path
    debounce_ms: int = 800
    once: bool = False


@dataclass(frozen=True)
class VerificationSnapshot:
    """Compact immutable summary of a verification run.

    Attributes:
        allowed: Whether the verified project state is executable according to BPFW.
        exit_code: Exit code returned by the verification pipeline.
        fingerprint: Stable fingerprint for the current finding set.
        finding_count: Number of findings returned by verification.
        block_count: Number of blocking findings returned by verification.
        report_text: Human-readable verification report.
    """

    allowed: bool
    exit_code: int
    fingerprint: str
    finding_count: int
    block_count: int
    report_text: str


class BpfwWatchFilter:
    """Filter filesystem events to files relevant for BPFW drift feedback."""

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
        """Initialize the event filter.

        Args:
            project_root: Root directory used to compute relative paths.
        """

        self.project_root = project_root.resolve()

    def __call__(self, _change: object, path: str) -> bool:
        """Return whether the event path should trigger BPFW feedback.

        Args:
            _change: Filesystem change enum supplied by watchfiles.
            path: Changed filesystem path supplied by watchfiles.

        Returns:
            True when the event is relevant to BPFW, otherwise False.
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
    """Observe project changes and provide lightweight drift feedback."""

    def __init__(self, settings: WatchSettings) -> None:
        """Initialize the watch service.

        Args:
            settings: Watch configuration for this service instance.
        """

        self.settings = WatchSettings(
            project_root=settings.project_root.resolve(),
            debounce_ms=settings.debounce_ms,
            once=settings.once,
        )

    def run(self) -> int:
        """Run real-time feedback or a single verification pass.

        Returns:
            Process exit code. One-shot mode mirrors verify's exit code. Continuous mode
            returns 0 when stopped normally with Ctrl+C.
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
        """Analyze one debounced filesystem event batch.

        Args:
            changes: Debounced filesystem changes emitted by watchfiles.
            previous_snapshot: Previous verification summary used to avoid repeated noise.

        Returns:
            The latest verification snapshot.
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
    """Run BPFW verification and summarize the resulting drift state.

    Args:
        project_root: Root directory of the project being verified.

    Returns:
        Compact immutable summary of the verification result.
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
    """Run the BPFW watch command.

    Args:
        project_root: Root directory of the project being observed.
        debounce_ms: Number of milliseconds used to batch rapid filesystem events.
        once: Whether to run a single verification and exit.

    Returns:
        Process exit code for the watch command.
    """

    settings = WatchSettings(project_root=project_root, debounce_ms=debounce_ms, once=once)
    return WatchService(settings=settings).run()


def _fingerprint_findings(findings: Sequence[Finding]) -> str:
    """Build a stable fingerprint for a finding sequence.

    Args:
        findings: Findings returned by BPFW verification.

    Returns:
        SHA-256 fingerprint of the normalized finding data.
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
    """Format changed paths relative to the project root.

    Args:
        project_root: Root directory used to compute relative paths.
        changes: Filesystem changes emitted by watchfiles.

    Returns:
        Sorted relative changed paths.
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
    """Render the first watch verification summary.

    Args:
        snapshot: Initial verification snapshot.

    Returns:
        Human-readable summary for the initial watch state.
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
    """Render drift feedback after a watched change.

    Args:
        snapshot: Latest verification snapshot after a filesystem event.

    Returns:
        Human-readable feedback for the changed drift state.
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
