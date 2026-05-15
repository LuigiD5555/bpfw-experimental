"""Tests for blueprint security validation."""

from bpfw.catalog.security import validate_no_blueprint_secrets


def test_validate_no_blueprint_secrets_allows_clean_blueprint() -> None:
    """Validate that clean structural metadata is allowed."""

    blueprint_data = {
        "version": 1,
        "project": {
            "root": ".",
        },
        "policy": {
            "security": {
                "no_secrets_in_blueprint": True,
                "public_safe_mode": True,
                "detected_detail_level": "minimal",
            }
        },
        "blocks": [
            {
                "id": "user_service",
                "purpose": "manage_users",
                "name": "User Service",
                "domain": "users",
                "status": "active",
                "code": {
                    "path": "src/users.py",
                    "symbol": "UserService",
                    "kind": "class",
                },
                "detected": {
                    "qualified_name": "users.UserService",
                    "kind": "class",
                },
            }
        ],
    }

    findings = validate_no_blueprint_secrets(blueprint_data)

    assert findings == []


def test_validate_no_blueprint_secrets_blocks_secret_like_field() -> None:
    """Validate that secret-like field names are blocked."""

    blueprint_data = {
        "version": 1,
        "blocks": [
            {
                "id": "auth_service",
                "purpose": "authenticate_users",
                "api_key": "abc123",
            }
        ],
    }

    findings = validate_no_blueprint_secrets(blueprint_data)

    assert len(findings) == 1
    assert findings[0].code == "BLUEPRINT_SECRET_LIKE_FIELD"


def test_validate_no_blueprint_secrets_blocks_secret_like_value() -> None:
    """Validate that secret-like text values are blocked."""

    blueprint_data = {
        "version": 1,
        "blocks": [
            {
                "id": "auth_service",
                "purpose": "authenticate_users",
                "notes": "Reads bearer token from request headers.",
            }
        ],
    }

    findings = validate_no_blueprint_secrets(blueprint_data)

    assert len(findings) == 1
    assert findings[0].code == "BLUEPRINT_SECRET_LIKE_VALUE"


def test_validate_no_blueprint_secrets_allows_security_policy_keys() -> None:
    """Validate that security policy metadata is not flagged."""

    blueprint_data = {
        "policy": {
            "security": {
                "no_secrets_in_blueprint": True,
                "public_safe_mode": True,
                "detected_detail_level": "minimal",
            }
        }
    }

    findings = validate_no_blueprint_secrets(blueprint_data)

    assert findings == []


def test_validate_no_blueprint_secrets_blocks_absolute_path_posix() -> None:
    """Validate that absolute POSIX paths are blocked."""

    blueprint_data = {
        "version": 1,
        "project": {
            "root": "/home/user/private/client_project/backend",
        },
    }

    findings = validate_no_blueprint_secrets(blueprint_data)

    absolute_findings = [finding for finding in findings if finding.code == "BLUEPRINT_ABSOLUTE_PATH"]
    assert len(absolute_findings) == 1


def test_validate_no_blueprint_secrets_blocks_absolute_path_windows() -> None:
    """Validate that absolute Windows paths are blocked."""

    blueprint_data = {
        "version": 1,
        "project": {
            "root": "C:\\Users\\admin\\secrets\\project",
        },
    }

    findings = validate_no_blueprint_secrets(blueprint_data)

    absolute_findings = [finding for finding in findings if finding.code == "BLUEPRINT_ABSOLUTE_PATH"]
    assert len(absolute_findings) == 1