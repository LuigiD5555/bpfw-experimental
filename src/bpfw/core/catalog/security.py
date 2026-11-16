"""Security validation for BPFW blueprint files."""

import re
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from bpfw.reports.finding import FINDING_SEVERITY_BLOCK, Finding


SECRET_KEYWORDS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "credentials",
    "bearer",
    "jwt",
    "database_url",
    "connection_string",
    "access_key",
    "refresh_token",
    "client_secret",
)

_WORD_SECRET_KEYWORDS = {
    "password",
    "passwd",
    "secret",
    "token",
    "credential",
    "credentials",
    "bearer",
    "jwt",
}

_WORD_SECRET_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(keyword) for keyword in sorted(_WORD_SECRET_KEYWORDS)) + r")\b"
)
_SUBSTRING_SECRET_KEYWORDS = tuple(
    keyword for keyword in SECRET_KEYWORDS if keyword not in _WORD_SECRET_KEYWORDS
)

_DESCRIPTIVE_METADATA_PATH = re.compile(
    r"blueprint\.blocks\[\d+\]\."
    r"(?:id|name|domain|purpose|code\.(?:path|symbol|module)|detected\.(?:signature|docstring|qualified_name|unit_id|parent_unit_id)"
    r"|entrypoints\[\d+\]|interface\.inputs\[\d+\]\.(?:name|type)"
    r"|analysis\.contract\.inputs\[\d+\]|analysis\.test_references\[\d+\]\.target"
    r"|connections\[\d+\]\.target)"
)
_INTERFACE_DEFAULT_PATH = re.compile(
    r"blueprint\.blocks\[\d+\]\.interface\.inputs\[\d+\]\.default"
)
_LOCAL_FILESYSTEM_ROOTS = frozenset({
    "bin", "boot", "data", "dev", "etc", "home", "lib", "lib32", "lib64", "media",
    "mnt", "opt", "private", "proc", "root", "run", "sbin", "snap", "srv", "sys",
    "tmp", "usr", "var", "users", "volumes", "applications", "library", "system",
})
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(keyword) for keyword in SECRET_KEYWORDS) + r")\b"
    r"[\"']?\s*(?::\s*(?:str|bytes)(?:\s*\|\s*None)?\s*)?[:=]\s*"
    r"(?P<value>\"[^\"\r\n]*\"|'[^'\r\n]*'|[^\s,;)]+)",
    re.IGNORECASE,
)
_CREDENTIAL_MATERIAL_PATTERN = re.compile(
    r"-----BEGIN (?:[A-Z ]*PRIVATE KEY|OPENSSH PRIVATE KEY)-----"
    r"|\bBearer\s+[A-Za-z0-9._~+/-]{16,}"
    r"|\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"
    r"|sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16})\b"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
    r"|[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@",
    re.IGNORECASE,
)


def contains_credential_material(value: str) -> bool:
    """Detect embedded credential literals without flagging names and prose."""
    if _CREDENTIAL_MATERIAL_PATTERN.search(value):
        return True
    for match in _SECRET_ASSIGNMENT_PATTERN.finditer(value):
        assigned_value = match.group("value")
        unquoted = assigned_value[1:-1] if assigned_value[:1] in {"'", '"'} and assigned_value[-1:] == assigned_value[:1] else assigned_value
        if re.fullmatch(r"\{\{\s*[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*\s*\}\}", unquoted):
            continue
        if assigned_value not in {"None", "True", "False", "str", "bytes", "''", '\"\"'}:
            return True
    return False


def is_portable_url_default(value: str, path: str) -> bool:
    """Recognize root-relative URL defaults without allowing local filesystem locations."""
    if not _INTERFACE_DEFAULT_PATH.fullmatch(path):
        return False
    if not re.fullmatch(r"/(?!/)[A-Za-z0-9_~!$&'()*+,;=:@/?#.-]*", value):
        return False
    url_path = value.split("?", 1)[0].split("#", 1)[0]
    segments = url_path.lstrip("/").split("/")
    return (
        segments[0].lower() not in _LOCAL_FILESYSTEM_ROOTS
        and not any(segment in {".", ".."} for segment in segments)
    )


def validate_no_blueprint_secrets(blueprint_data: dict[str, Any]) -> list[Finding]:
    """Validate that blueprint data does not contain obvious secrets.

    Args:
        blueprint_data: Parsed blueprint data.

    Returns:
        Blocking findings for suspicious secret-like fields or values.
    """

    findings: list[Finding] = []
    scan_blueprint_value(
        value=blueprint_data,
        path="blueprint",
        findings=findings,
    )
    return findings


def scan_blueprint_value(value: Any, path: str, findings: list[Finding]) -> None:
    """Recursively scan blueprint values for secret-like content.

    Args:
        value: Current value.
        path: Logical YAML path.
        findings: Mutable findings list.
    """

    if isinstance(value, dict):
        for key, child_value in value.items():
            key_text = str(key).lower()
            child_path = f"{path}.{key}"

            if is_allowed_security_policy_path(child_path):
                continue

            if contains_secret_keyword(key_text):
                findings.append(
                    Finding(
                        source="bpfw",
                        code="BLUEPRINT_SECRET_LIKE_FIELD",
                        severity=FINDING_SEVERITY_BLOCK,
                        message="The blueprint contains a secret-like field name.",
                        evidence={"path": child_path},
                    )
                )

            scan_blueprint_value(
                value=child_value,
                path=child_path,
                findings=findings,
            )
        return

    if isinstance(value, list):
        for index, child_value in enumerate(value):
            scan_blueprint_value(
                value=child_value,
                path=f"{path}[{index}]",
                findings=findings,
            )
        return

    if isinstance(value, str):
        value_text = value.lower()

        if looks_like_absolute_path(value) and not is_portable_url_default(value, path):
            findings.append(
                Finding(
                    source="bpfw",
                    code="BLUEPRINT_ABSOLUTE_PATH",
                    severity=FINDING_SEVERITY_BLOCK,
                    message="The blueprint contains an absolute path.",
                    evidence={"path": path},
                )
            )

        descriptive_metadata = _DESCRIPTIVE_METADATA_PATH.fullmatch(path) is not None
        if contains_credential_material(value) or (
            contains_secret_keyword(value_text) and not descriptive_metadata
        ):
            findings.append(
                Finding(
                    source="bpfw",
                    code="BLUEPRINT_SECRET_LIKE_VALUE",
                    severity=FINDING_SEVERITY_BLOCK,
                    message="The blueprint contains secret-like text.",
                    evidence={"path": path},
                )
            )


def contains_secret_keyword(value: str) -> bool:
    """Return whether a string contains a secret-like keyword.

    Args:
        value: String to inspect.

    Returns:
        True when the value contains a suspicious keyword. False otherwise.
    """

    if _WORD_SECRET_PATTERN.search(value):
        return True
    return any(keyword in value for keyword in _SUBSTRING_SECRET_KEYWORDS)


def looks_like_absolute_path(value: str) -> bool:
    """Return whether a value looks like an absolute filesystem path.

    Args:
        value: String value to inspect.

    Returns:
        True when the value looks like a POSIX or Windows absolute path.
    """

    stripped_value = value.strip()
    if not _may_be_absolute_path(stripped_value):
        return False
    return (
        PurePosixPath(stripped_value).is_absolute()
        or PureWindowsPath(stripped_value).is_absolute()
    )


def _may_be_absolute_path(value: str) -> bool:
    """Return whether a value has a prefix worth testing as an absolute path.

    Args:
        value: String value to inspect.

    Returns:
        True when the value has a POSIX or Windows absolute-path prefix.
    """
    if not value:
        return False
    if value.startswith(("/", "\\")):
        return True
    return len(value) >= 3 and value[1] == ":" and value[2] in {"\\", "/"}


def is_allowed_security_policy_path(path: str) -> bool:
    """Return whether a path belongs to allowed security policy metadata.

    Args:
        path: Logical YAML path.

    Returns:
        True when the path is allowed to mention security keywords.
    """

    allowed_prefixes = (
        "blueprint.policy.security.no_secrets_in_blueprint",
        "blueprint.policy.security.public_safe_mode",
        "blueprint.policy.security.detected_detail_level",
    )
    return path in allowed_prefixes
