"""Compatibility wrapper for catalog unlock command."""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from bpfw.cli import main as aioa_cli_main


def main() -> int:
    return aioa_cli_main(["unlock"])


if __name__ == "__main__":
    exit(main())
