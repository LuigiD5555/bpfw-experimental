"""Native source identities and unevaluated template variables are descriptive metadata."""

import pytest
from pytest_readable import readable
from bpfw.core.catalog.security import validate_no_blueprint_secrets


@pytest.mark.parametrize("field", ["unit_id", "parent_unit_id"])
@readable(
    intention="Accept source identity names without exempting embedded credential material.",
    steps=["Inspect a native identity mentioning an authentication operation and one containing a literal assignment."],
    criteria=["The descriptive identity is accepted and the literal credential is still rejected."],
)
def test_native_identities_remain_subject_to_literal_secret_detection(field):
    assert validate_no_blueprint_secrets({"blocks": [{"detected": {field: "python:src/password.py::authenticate_api_key"}}]}) == []
    findings = validate_no_blueprint_secrets({"blocks": [{"detected": {field: "password='example-test-token-value'"}}]})
    assert any(finding.code == "BLUEPRINT_SECRET_LIKE_VALUE" for finding in findings)


@pytest.mark.parametrize("block", [
    {"code": {"module": "src.access.templates.password"}},
    {"domain": "source_catalog/html/src/access/templates/password"},
])
@readable(
    intention="Recognize authentication module and domain names as source identifiers.",
    steps=["Inspect the dotted name of a password template module."],
    criteria=["The source module name is accepted as descriptive metadata."],
)
def test_authentication_module_name_is_descriptive(block):
    assert validate_no_blueprint_secrets({"blocks": [block]}) == []


@readable(
    intention="Distinguish an unevaluated template variable from a hardcoded token.",
    steps=["Inspect a variable-based data-token attribute and a literal data-token attribute."],
    criteria=["The variable is accepted while the literal is rejected."],
)
def test_template_token_variable_is_not_a_literal_secret():
    assert validate_no_blueprint_secrets({"blocks": [{"detected": {"signature": '<form data-token="{{ token }}">'}}]}) == []
    findings = validate_no_blueprint_secrets({"blocks": [{"detected": {"signature": '<form data-token="example-test-token-value">'}}]})
    assert any(finding.code == "BLUEPRINT_SECRET_LIKE_VALUE" for finding in findings)
