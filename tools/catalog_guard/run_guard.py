"""Compatibility wrapper for guard runner."""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from bpfw.cli import main as aioa_cli_main


def main() -> int:
    return aioa_cli_main(["run-guard"])


if __name__ == "__main__":
    raise SystemExit(main())
