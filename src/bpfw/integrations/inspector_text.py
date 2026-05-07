"""Compatibility facade for the text inspector integration.

This module is kept for backward compatibility. New code should use
bpfw.integrations.inspector.run_text_inspector directly.
"""

from bpfw.integrations.inspector.screen import render_inspector_screen
from bpfw.integrations.inspector.session import (
    run_text_inspector,
    run_text_inspector_session,
)

# Backward compatibility aliases
render_text_inspector_screen = render_inspector_screen

__all__ = [
    "run_text_inspector",
    "run_text_inspector_session",
    "render_text_inspector_screen",
]