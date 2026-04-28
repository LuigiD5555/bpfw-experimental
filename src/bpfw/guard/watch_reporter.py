from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class WatchReport:
    status: str
    message: str


class WatchReporter:
    """Renders deterministic watcher output."""

    def render_no_drift(self) -> WatchReport:
        return WatchReport(status="OK", message="Watcher scan completed. No authority drift detected.")

    def render_block(self, file_path: str) -> WatchReport:
        return WatchReport(
            status="BLOCK",
            message=(
                "BLOCK\n\n"
                "Watcher detected authority drift outside authorized unlock window.\n\n"
                f"Resource:\n{file_path}\n\n"
                "Action:\nrestore + relock"
            ),
        )
