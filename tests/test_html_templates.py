"""Regression checks for the installed BPFW Django HTML parsing fix."""

from pathlib import Path
import tempfile
import unittest

from bpfw.core.catalog.multilang_scanner import scan_non_python_project
from bpfw.core.source.tree_sitter_adapter import _mask_html_template_tokens, extract_units


class HtmlTemplateParsingTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def extract(self, source, language="html", filename="sample.html"):
        source_path = self.root / filename
        source_path.write_text(source, encoding="utf-8")
        return extract_units(language, source_path, Path(filename))

    def test_translation_quotes_and_comparison_are_template_syntax(self):
        units, has_error = self.extract(
            '<p title="{% translate "People & Access" %}">'
            '{% if count > 1 %}Many{% endif %}</p>'
        )
        self.assertFalse(has_error)
        self.assertEqual(len(units), 1)

    def test_conditional_attributes_and_unquoted_variables(self):
        _, has_error = self.extract(
            '<option {% if selected == "yes" %}selected{% endif %} '
            'value={{ value }}>Choice</option>'
        )
        self.assertFalse(has_error)

    def test_comment_blocks_do_not_create_html_elements(self):
        units, has_error = self.extract(
            '{% comment "notes" %}<details><div>{% endcomment %}'
            '<p>Visible</p>{# <article> #}'
        )
        self.assertFalse(has_error)
        self.assertEqual([unit.symbol for unit in units], ["p[1]"])

    def test_multibyte_offsets_and_line_endings_are_preserved(self):
        source = '{% translate "México" %}\r\n{{ value }}\n<p>Text</p>'.encode()
        masked = _mask_html_template_tokens(source)
        self.assertEqual(len(source), len(masked))
        self.assertEqual(
            [position for position, byte in enumerate(source) if byte in (10, 13)],
            [position for position, byte in enumerate(masked) if byte in (10, 13)],
        )

    def test_original_signatures_ids_and_ownership_are_preserved(self):
        units, has_error = self.extract(
            '{% translate "México" %}\n'
            '<section id="outer">\n'
            '<a id="link" href="{% url \'home\' %}">{{ title }}</a>\n'
            '</section>'
        )
        self.assertFalse(has_error)
        self.assertEqual([unit.start_line for unit in units], [2, 3])
        self.assertEqual(units[1].symbol, "section#outer/a#link")
        self.assertEqual(units[1].parent_unit_id, units[0].unit_id)
        self.assertIn("{% url 'home' %}", units[1].signature)

    def test_real_html_errors_remain_errors(self):
        for source in ('<div></span>', '{% if show %}<div></span>{% endif %}'):
            with self.subTest(source=source):
                self.assertTrue(self.extract(source)[1])

    def test_template_expression_changes_remain_visible_in_hashes(self):
        first_units, _ = self.extract('<p>{{ first_value }}</p>')
        second_units, _ = self.extract('<p>{{ other_value }}</p>')
        self.assertNotEqual(
            first_units[0].normalized_body_hash,
            second_units[0].normalized_body_hash,
        )

    def test_plain_html_and_other_languages_still_extract(self):
        examples = [
            ("html", "plain.html", '<main id="main"><p>Text</p></main>'),
            ("css", "plain.css", ".card { color: red; }"),
            ("go", "plain.go", 'package sample\nfunc Name() string { return "ok" }\n'),
            ("rust", "plain.rs", "pub fn name() -> bool { true }"),
        ]
        for language, filename, source in examples:
            with self.subTest(language=language):
                units, has_error = self.extract(source, language, filename)
                self.assertFalse(has_error)
                self.assertTrue(units)
                self.assertTrue(all(unit.language == language for unit in units))

    def test_scanner_accepts_templates_and_reports_real_html_errors(self):
        self.extract('<p title="{% translate "Help & support" %}">Text</p>')
        self.extract('<div></span>', filename="invalid.html")
        report = scan_non_python_project(self.root, ["."], [])
        errors = [finding.path for finding in report.findings if finding.code == "SOURCE_PARSE_ERROR"]
        self.assertEqual(errors, ["invalid.html"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
