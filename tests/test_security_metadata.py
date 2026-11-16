"""Regression tests for blueprint metadata and embedded credential detection."""

import unittest

from bpfw.core.catalog.security import validate_no_blueprint_secrets


class SecurityMetadataTests(unittest.TestCase):
    def findings(self, block):
        return validate_no_blueprint_secrets({"blocks": [block]})

    def test_authentication_metadata_is_not_a_credential(self):
        self.assertEqual(self.findings({
            "id": "authenticate_api_key",
            "name": "Password service",
            "purpose": "Validate the password and issue a token.",
            "code": {"symbol": "authenticate_api_key", "path": "src/private_keys.py"},
            "detected": {
                "signature": "authenticate(request, token, password=None)",
                "docstring": "Never expose credentials or private_key material.",
                "qualified_name": "auth.authenticate_api_key",
            },
            "interface": {"inputs": [{"name": "password"}, {"name": "token"}]},
            "entrypoints": ["Django route: activate/<str:token>/"],
            "analysis": {
                "contract": {"inputs": ["password", "token"]},
                "test_references": [{"target": "tests/auth.py::test_private_keys"}],
            },
            "connections": [{"target": "authenticate_api_key"}],
        }), [])

    def test_credential_type_annotation_is_not_a_secret_value(self):
        self.assertEqual(self.findings({
            "id": "authorize_call",
            "interface": {"inputs": [
                {"name": "node", "type": "Node"},
                {"name": "credential", "type": "Credential | None"},
            ]},
        }), [])

    def test_real_credentials_remain_blocked_in_metadata(self):
        examples = [
            "password=hunter2",
            'password: "hunter2"',
            'password: str = "hunter2"',
            "token='opaque-sample-value'",
            'Uses {"api_key": "sample-value"}',
            "Bearer abcdef0123456789abcdef0123456789",
            "-----BEGIN PRIVATE KEY-----",
            "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
            "sk-abcdefghijklmnopqrstuvwxyz0123456789",
            "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJkZW1vIn0.signature",
            "postgresql://demo:sample-password@localhost/example",
        ]
        for example in examples:
            with self.subTest(example=example):
                findings = self.findings({"purpose": example})
                self.assertIn("BLUEPRINT_SECRET_LIKE_VALUE", [finding.code for finding in findings])
                self.assertNotIn(example, repr(findings))

    def test_explicit_secret_fields_remain_blocked(self):
        for field_name in ("password", "token", "api_key", "client_secret"):
            with self.subTest(field_name=field_name):
                findings = self.findings({field_name: "sample-value"})
                self.assertIn("BLUEPRINT_SECRET_LIKE_FIELD", [finding.code for finding in findings])

    def test_unknown_notes_keep_the_conservative_keyword_check(self):
        findings = self.findings({"notes": "Reads bearer token from headers."})
        self.assertEqual([finding.code for finding in findings], ["BLUEPRINT_SECRET_LIKE_VALUE"])

    def test_metadata_allowance_requires_an_exact_schema_path(self):
        findings = self.findings({"custom": {"purpose": "password"}})
        self.assertEqual([finding.code for finding in findings], ["BLUEPRINT_SECRET_LIKE_VALUE"])

    def test_absolute_paths_remain_blocked(self):
        findings = self.findings({"code": {"path": "/private/auth.py"}})
        self.assertEqual([finding.code for finding in findings], ["BLUEPRINT_ABSOLUTE_PATH"])



if __name__ == "__main__":
    unittest.main(verbosity=2)
