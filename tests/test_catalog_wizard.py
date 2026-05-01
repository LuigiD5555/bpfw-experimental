from pathlib import Path

from bpfw.integrations.wizard import (
    apply_automatic_authority_fields,
    complete_human_fields,
    get_incomplete_responsibilities,
    suggest_owner_layer,
)


def _responsibility(
    responsibility_id: str,
    intent: str,
    lifecycle: str,
    path: str = "src/bpfw/catalog/example.py",
    symbol: str = "ExampleService",
) -> dict:
    return {
        "id": responsibility_id,
        "intent": intent,
        "canonical_name": symbol,
        "owner_layer": None,
        "lifecycle": lifecycle,
        "location": {
            "path": path,
            "symbol": symbol,
            "symbol_type": "class",
            "start_line": 2,
            "end_line": 4,
        },
        "duplicate_policy": {
            "group": None,
            "allow_multiple_non_active": True,
            "forbidden_active_duplicates": True,
            "suspected_duplicates": [],
        },
        "related_code": [],
        "replacement": {
            "replaces": None,
            "replaced_by": None,
            "reason": None,
        },
    }


def test_suggest_owner_layer_from_source_package_path() -> None:
    responsibility = _responsibility(
        responsibility_id="example",
        intent="maintain example",
        lifecycle="active",
        path="src/bpfw/protection/authority.py",
    )

    assert suggest_owner_layer(responsibility) == "protection"


def test_get_incomplete_responsibilities_detects_missing_fields() -> None:
    complete = _responsibility("example", "maintain example", "active")
    incomplete = _responsibility("missing", "maintain example", "active")
    incomplete["owner_layer"] = ""
    blueprint_data = {"responsibilities": [complete, incomplete]}

    assert get_incomplete_responsibilities(blueprint_data) == [incomplete]


def test_apply_automatic_authority_fields_derives_groups() -> None:
    active_one = _responsibility("user_creation", "create user", "active")
    active_two = _responsibility(
        "account_registration",
        "create user",
        "active",
        path="src/bpfw/catalog/accounts.py",
        symbol="AccountRegistration",
    )
    blueprint_data = {"responsibilities": [active_one, active_two]}

    apply_automatic_authority_fields(blueprint_data)

    assert active_one["duplicate_policy"]["group"] == "create_user"
    assert active_two["duplicate_policy"]["group"] == "create_user"
    assert active_one["duplicate_policy"]["suspected_duplicates"] == [
        "account_registration"
    ]


def test_complete_human_fields_fills_missing_entries(tmp_path: Path) -> None:
    project_root = tmp_path
    blueprint_path = project_root / "bpfw" / "blueprint.yaml"
    blueprint_path.parent.mkdir(parents=True)
    blueprint_path.write_text(
        "version: 1\n"
        "responsibilities:\n"
        "  - id: example\n"
        "    canonical_name: ExampleService\n"
        "    lifecycle: ''\n"
        "    intent: ''\n",
        encoding="utf-8",
    )

    resolved_path, updated_entries = complete_human_fields(project_root=project_root)

    assert resolved_path == blueprint_path
    assert updated_entries >= 2
