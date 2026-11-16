"""Reusable terminal prompts and dimensions for all BPFW integrations.

Terminal input is independent of the Editor; Planner and Inspector may use
these routines without importing any catalogue or authority functionality.
"""
from __future__ import annotations

import shutil

from bpfw.integrations.shared.cli_runtime import QUIT_COMMAND
from bpfw.integrations.shared.input_adapter import read_editable_input


def get_terminal_width() -> int:
    try:
        return shutil.get_terminal_size((80,24)).columns
    except (ValueError,OSError):
        return 80


def get_terminal_height() -> int:
    try:
        return shutil.get_terminal_size((80,24)).lines
    except (ValueError,OSError):
        return 24


def read_input(prompt: str = '> ') -> str:
    try:
        return read_editable_input(prompt or '> ').strip()
    except (EOFError,KeyboardInterrupt):
        return QUIT_COMMAND


def read_line(prompt: str = '> ') -> str:
    try:
        return read_editable_input(prompt or '> ').rstrip('\n')
    except (EOFError,KeyboardInterrupt):
        return ''
