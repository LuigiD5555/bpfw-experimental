"""Compatibility wrapper for idle autolock daemon."""

import argparse
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from bpfw.cli import main as aioa_cli_main


def main() -> int:
    parser = argparse.ArgumentParser(description="Catalog idle autolock daemon.")
    parser.add_argument("--idle-seconds", type=int, default=30)
    arguments = parser.parse_args()
    return aioa_cli_main(["idle-autolock", "--idle-seconds", str(arguments.idle_seconds)])


if __name__ == "__main__":
    raise SystemExit(main())
