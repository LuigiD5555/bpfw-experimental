"""Regression checks for URL defaults and editor correction access."""

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bpfw.core.catalog.models import VerificationReport
from bpfw.core.catalog.security import validate_no_blueprint_secrets
from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.core.result import ResultStatus, StepResult
from bpfw.reports.finding import Finding


class EditorWorkflowTests(unittest.TestCase):
    def findings_for_default(self, value):
        return validate_no_blueprint_secrets({
            "blocks": [{"interface": {"inputs": [{"name": "path", "default": value}]}}]
        })

    def test_root_relative_http_defaults_are_accepted(self):
        for value in ("/healthy", "/", "/api/health", "/status?format=json"):
            with self.subTest(value=value):
                self.assertEqual(self.findings_for_default(value), [])

    def test_host_locations_still_block_in_defaults(self):
        for value in (
            "/home/example/project", "/Users/example/project", "/etc/config",
            "/tmp/output", "/data/files", "/opt/project", "C:\\Users\\example",
            "\\\\server\\share", "//server/share", "/../private", "/custom/../private",
        ):
            with self.subTest(value=value):
                self.assertIn("BLUEPRINT_ABSOLUTE_PATH", [finding.code for finding in self.findings_for_default(value)])

    def test_filesystem_metadata_has_no_url_exemption(self):
        for blueprint in (
            {"project": {"root": "/healthy"}},
            {"blocks": [{"code": {"path": "/healthy"}}]},
            {"custom": {"interface": {"inputs": [{"default": "/healthy"}]}}},
        ):
            with self.subTest(blueprint=blueprint):
                findings = validate_no_blueprint_secrets(blueprint)
                self.assertIn("BLUEPRINT_ABSOLUTE_PATH", [finding.code for finding in findings])

    def test_url_defaults_are_still_scanned_for_credentials(self):
        findings = self.findings_for_default("/login?password=sample-value")
        self.assertIn("BLUEPRINT_SECRET_LIKE_VALUE", [finding.code for finding in findings])

    def run_engine(self, command_name, codes, status=ResultStatus.BLOCK, authority_state="defined"):
        report = VerificationReport(
            authority_state=authority_state,
            allowed=False,
            findings=[Finding(source="bpfw", code=code, severity="block", message=code) for code in codes],
        )

        def fake_verify(context):
            context.runtime_cache["verify_report"] = report
            return StepResult(status=status, message="Verification blocked", source="catalog.verify")

        with (
            patch("bpfw.core.engine.core_registry.get_authority_protection_status", return_value=SimpleNamespace(status="locked")),
            patch("bpfw.core.engine.VerifyBlueprintStep.run", side_effect=fake_verify) as verify,
            patch("bpfw.core.engine.execute_pipeline", return_value=[StepResult(status=ResultStatus.OK, message="Editor reached", source="test")]) as dispatch,
        ):
            result = BlueprintEngine().run(build_command(command_name, Path.cwd(), {}))
            return result, dispatch.called, verify.called

    def test_editor_opens_for_declaration_drift_with_warning(self):
        result, dispatched, verified = self.run_engine("editor", ["UNDECLARED_CODE", "MISSING_DECLARED_CODE", "DUPLICATE_ACTIVE_PROFILE"])
        self.assertTrue(verified)
        self.assertTrue(dispatched)
        self.assertEqual(result.status, ResultStatus.WARNING)

    def test_editor_keeps_security_and_unknown_findings_blocked(self):
        for code in ("BLUEPRINT_ABSOLUTE_PATH", "BLUEPRINT_SECRET_LIKE_VALUE", "BLUEPRINT_SECRET_LIKE_FIELD", "SOURCE_PARSE_ERROR", "AUTHORITY_REPOSITORY_ERROR", "UNKNOWN_BLOCK"):
            with self.subTest(code=code):
                result, dispatched, _ = self.run_engine("editor", ["UNDECLARED_CODE", code])
                self.assertFalse(dispatched)
                self.assertEqual(result.status, ResultStatus.BLOCK)

    def test_inspector_and_planner_keep_existing_gates(self):
        for command in ("inspector", "planner"):
            with self.subTest(command=command):
                result, dispatched, _ = self.run_engine(command, ["UNDECLARED_CODE"])
                self.assertFalse(dispatched)
                self.assertEqual(result.status, ResultStatus.BLOCK)

    def test_critical_and_invalid_authority_do_not_open_editor(self):
        for status, state in ((ResultStatus.CRITICAL, "defined"), (ResultStatus.BLOCK, "invalid")):
            with self.subTest(status=status, state=state):
                _, dispatched, _ = self.run_engine("editor", ["UNDECLARED_CODE"], status, state)
                self.assertFalse(dispatched)

    def test_previous_security_suite(self):
        from test_security_metadata import SecurityMetadataTests

        result = unittest.TestResult()
        unittest.defaultTestLoader.loadTestsFromTestCase(SecurityMetadataTests).run(result)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.failures, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
