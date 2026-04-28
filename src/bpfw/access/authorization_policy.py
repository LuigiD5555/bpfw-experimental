from __future__ import annotations

import os


class AccessAuthorizationError(ValueError):
    """Raised when the selected authorization backend is not allowed."""


class AccessAuthorizationPolicy:
    """Decides whether an authorization backend is allowed in the current environment."""

    def validate_backend(self, backend_name: str) -> None:
        """Raise a specific error when the selected backend is not allowed."""

        environment_name = os.getenv("BPFW_ENV", "protected").strip().lower() or "protected"
        normalized_backend_name = backend_name.strip().lower()
        if environment_name != "dev" and normalized_backend_name == "dummy":
            raise AccessAuthorizationError(
                "BLOCK\n\n"
                "No secure authorization backend configured.\n\n"
                "Dummy access grants are only allowed in development mode.\n\n"
                "Set:\n"
                "BPFW_ENV=dev\n\n"
                "Or configure:\n"
                "BPFW_AUTH_BACKEND=sudo"
            )
