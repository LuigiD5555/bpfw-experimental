"""Lightweight runtime profiling for BPFW performance measurement."""

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator


class RuntimeProfiler:
    """Collect and print lightweight runtime profiling information."""

    def __init__(self) -> None:
        """Initialize the profiler based on the BPFW_PROFILE environment variable."""
        self.enabled = os.environ.get("BPFW_PROFILE") == "1"

    @contextmanager
    def measure(self, label: str) -> Iterator[None]:
        """Measure a named runtime stage and print the duration when profiling is enabled.

        Args:
            label: Descriptive name for the measured operation.

        Yields:
            None
        """
        if not self.enabled:
            yield
            return

        start_time = time.perf_counter()
        try:
            yield
        finally:
            elapsed_seconds = time.perf_counter() - start_time
            print(
                f"[BPFW PROFILE] {label}: {elapsed_seconds:.3f}s",
                file=sys.stderr,
            )