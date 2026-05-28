"""PURPOSE lightweight runtime profiling for BPFW performance measurement
DOMAIN  framework core
"""

import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator


class RuntimeProfiler:
    """PURPOSE collect and print lightweight runtime profiling information
    DOMAIN  framework core
    """

    def __init__(self) -> None:
        """PURPOSE set up the profiler based on the BPFW_PROFILE environment variable
        DOMAIN  framework core
        """
        self.enabled = os.environ.get("BPFW_PROFILE") == "1"

    @contextmanager
    def measure(self, label: str) -> Iterator[None]:
        """PURPOSE measure a named runtime stage and print the duration when profiling is enabled
        DOMAIN  framework core
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