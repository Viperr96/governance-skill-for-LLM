"""Regression tests for check_conflicts. Run: python -m unittest discover -s tests (from the skill directory)."""
import io
import json
import contextlib
import importlib.util
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "scripts" / "audit_instructions.py"
spec = importlib.util.spec_from_file_location("audit_instructions", SCRIPT)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def run(fixture):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            audit.main([str(HERE / "fixtures" / fixture), "--json", "--no-user", "--rules"])
        except SystemExit:
            pass
    return json.loads(buf.getvalue())


def conflicts(report, severity):
    return [f for f in report["findings"] if f["check"] == "conflicts" and f["severity"] == severity]


class ProsePair(unittest.TestCase):
    """A prose-heavy CLAUDE.md that @imports KNOWLEDGE.md. Nothing here contradicts anything."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("prose-pair")
        cls.rules = {r["text"]: r for r in cls.report["rules"]}

    def test_no_errors(self):
        self.assertEqual(conflicts(self.report, "error"), [])

    def test_no_warnings(self):
        self.assertEqual(conflicts(self.report, "warn"), [])

    def test_hyphenated_only_is_not_a_directive(self):
        for text in self.rules:
            self.assertNotIn("append-only", text)
            self.assertNotIn("read-only", text)

    def test_question_is_not_a_positive_obligation(self):
        self.assertEqual(self.rules["Is the sample large enough for the claim?"]["polarity"], "neutral")

    def test_scientific_claim_is_not_the_completion_subject(self):
        self.assertNotIn("completion", self.rules["Do not claim causality from correlation."]["subjects"])


class TrueConflicts(unittest.TestCase):
    """Four genuine contradictions across CLAUDE.md and an imported STYLE.md must all stay errors."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("true-conflicts")

    def test_four_errors(self):
        errors = conflicts(self.report, "error")
        self.assertEqual(len(errors), 4, [e["detail"] for e in errors])

    def test_each_expected_pair_is_an_error(self):
        details = " || ".join(e["detail"] for e in conflicts(self.report, "error"))
        for marker in ("shared terms: run, suite, test", "shared terms: ask, confirmation, edit",
                       "exclusive alternatives: spaces vs tabs", "shared terms: npm"):
            self.assertIn(marker, details)

    def test_import_chain_is_labelled(self):
        details = [e["detail"] for e in conflicts(self.report, "error")]
        self.assertTrue(all("one authored unit split by @import" in d for d in details), details)


class Polarity(unittest.TestCase):
    def classify(self, text):
        s = audit.Surface(SCRIPT, "claude-md", SCRIPT.parent)
        r = audit.Rule(s, 1, text, text, "", "sentence")
        audit.classify_rule(r)
        return r

    def test_bare_imperative_is_positive(self):
        self.assertEqual(self.classify("Ask for confirmation before editing any file under src/.").polarity, "pos")

    def test_negated_imperative_is_negative(self):
        self.assertEqual(self.classify("Do not run the test suite before committing.").polarity, "neg")

    def test_declarative_without_modal_is_neutral(self):
        self.assertEqual(self.classify("The warehouse holds one row per battle.").polarity, "neutral")

    def test_bare_modal_is_not_an_exception(self):
        self.assertFalse(self.classify("A claim can accumulate confirmations.").exc)
        self.assertTrue(self.classify("Run the linter, except on generated files.").exc)


if __name__ == "__main__":
    unittest.main()
