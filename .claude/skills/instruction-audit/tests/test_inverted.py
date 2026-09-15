"""Regression tests for the emphasis class of check_inverted (v1.4.0, defects M1 and M2).
Run: python -m unittest discover -s tests (from the skill directory)."""
import io
import json
import contextlib
import importlib.util
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "audit_instructions.py"
spec = importlib.util.spec_from_file_location("audit_instructions", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def audit_text(text, *extra, config=None):
    """Audit a one-file project whose CLAUDE.md is `text`. Returns the JSON report with the rule inventory."""
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "CLAUDE.md").write_text("# R\n\n" + text, encoding="utf-8")
        if config is not None:
            (Path(d) / ".instruction-audit.json").write_text(json.dumps(config), encoding="utf-8")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            try:
                audit.main([d, "--json", "--no-user", "--rules", "--only", "inverted", *extra])
            except SystemExit:
                pass
    return json.loads(buf.getvalue())


def classes(report):
    return [f["meta"].get("cls") for f in report["findings"] if f["check"] == "inverted"]


def rules(report):
    return [r["text"] for r in report["rules"]]


class BoldHeaders(unittest.TestCase):
    """v1.3.0 treated `**Plan**` as scaffold and `- **Plan**` as a rule, then flagged the rule as emphasis (M1)."""

    def test_bold_header_is_scaffold_with_or_without_a_list_marker(self):
        self.assertEqual(rules(audit_text("**Plan**\n")), rules(audit_text("- **Plan**\n")))
        self.assertEqual(rules(audit_text("- **Plan**\n")), [])

    def test_bold_list_header_is_not_emphasis(self):
        report = audit_text("1. **Frame**\n2. **Plan**\n- **Report back in this shape, and nothing more:**\n")
        self.assertNotIn("emphasis", classes(report))
        self.assertEqual(rules(report), [])

    def test_bold_header_is_not_a_list_item_for_bloat(self):
        # a header carries no instruction and does not count toward the doc-item ratio either
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "CLAUDE.md"
            p.write_text("# R\n\n- **Plan**\n- Run `pytest` first.\n", encoding="utf-8")
            s = audit.Surface(p, "claude-md", d)
            audit.load_surface(s)
            self.assertEqual(s.list_items, 1)
            self.assertEqual(s.line_kinds[3], "scaffold")
            self.assertEqual(s.line_kinds[4], "rule")

    def test_fully_bold_sentence_is_still_a_rule_and_still_emphasis(self):
        for text in ("- **Never commit to main.**\n", "**Never commit to main.**\n"):
            report = audit_text(text)
            self.assertEqual(rules(report), ["Never commit to main."], text)
            self.assertIn("emphasis", classes(report), text)

    def test_shouting_is_still_emphasis(self):
        self.assertIn("emphasis", classes(audit_text("- **NEVER** commit to main. ALWAYS ASK!!\n")))
        self.assertIn("emphasis", classes(audit_text("- Run the linter!! Then commit.\n")))


class DomainAcronyms(unittest.TestCase):
    """v1.3.0 read any two four-letter capitals outside its generic-tech list as shouting (M2)."""

    LINE = "- Report ARPPU/ARPU and revenue share.\n"

    def test_two_unknown_acronyms_still_read_as_shouting_by_default(self):
        self.assertIn("emphasis", classes(audit_text(self.LINE)))

    def test_two_domain_acronyms_are_not_shouting_with_the_flag(self):
        self.assertNotIn("emphasis", classes(audit_text(self.LINE, "--acronyms", "arppu, ARPU")))

    def test_acronyms_are_read_from_the_project_config(self):
        self.assertNotIn("emphasis", classes(audit_text(self.LINE, config={"acronyms": ["ARPPU", "ARPU"]})))

    def test_allowlist_does_not_silence_real_shouting(self):
        self.assertIn("emphasis", classes(audit_text("- ALWAYS report ARPPU and NEVER ARPU.\n",
                                                      "--acronyms", "ARPPU,ARPU")))

    def test_project_acronyms_helper(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(audit.project_acronyms(d, "a, b"), {"A", "B"})
            (Path(d) / ".instruction-audit.json").write_text('{"acronyms": ["c"]}', encoding="utf-8")
            self.assertEqual(audit.project_acronyms(d, "a"), {"A", "C"})
            (Path(d) / ".instruction-audit.json").write_text("not json", encoding="utf-8")
            self.assertEqual(audit.project_acronyms(d), set())


if __name__ == "__main__":
    unittest.main()
