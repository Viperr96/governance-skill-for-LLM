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


class SingleFile(unittest.TestCase):
    """Four literal contradictions written into one CLAUDE.md. v1.1.0 reported nothing: adjacent rules under
    one heading were skipped before scoring, so severity depended on how the author split the files."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("single-file")

    def test_two_errors(self):
        errors = conflicts(self.report, "error")
        self.assertEqual(len(errors), 2, [e["detail"] for e in errors])

    def test_no_warnings(self):
        self.assertEqual(conflicts(self.report, "warn"), [])

    def test_both_alternatives_in_one_sentence_are_read(self):
        details = " || ".join(e["detail"] for e in conflicts(self.report, "error"))
        self.assertIn("exclusive alternatives: black vs ruff format", details)

    def test_import_line_is_not_glued_to_a_rule(self):
        for r in run("true-conflicts")["rules"]:
            self.assertNotIn("@STYLE.md", r["text"])


class LayoutIndependence(unittest.TestCase):
    """The same rules split across an @import must score exactly as they do in one file."""

    def test_split_matches_single_file(self):
        import tempfile
        one = run("single-file")
        src = (HERE / "fixtures" / "single-file" / "CLAUDE.md").read_text(encoding="utf-8").splitlines()
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "CLAUDE.md").write_text("\n".join(src[:3] + [src[4], "", "@RULES.md"]) + "\n", encoding="utf-8")
            (Path(d) / "RULES.md").write_text("\n".join([src[3], src[5]]) + "\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    audit.main([d, "--json", "--no-user", "--rules"])
                except SystemExit:
                    pass
            two = json.loads(buf.getvalue())
        key = lambda f: (f["severity"], f["meta"]["score"], f["meta"]["semantic"], sorted(f["meta"]["subjects"]))
        self.assertEqual(sorted(key(f) for f in conflicts(one, "error") + conflicts(one, "warn")),
                         sorted(key(f) for f in conflicts(two, "error") + conflicts(two, "warn")))


class Polarity(unittest.TestCase):
    def classify(self, text):
        s = audit.Surface(SCRIPT, "claude-md", SCRIPT.parent)
        r = audit.Rule(s, 1, text, text, "", "sentence")
        audit.classify_rule(r)
        return r

    def test_bare_imperative_has_its_own_polarity(self):
        self.assertEqual(self.classify("Ask for confirmation before editing any file under src/.").polarity, "imperative")

    def test_explicit_modal_is_positive(self):
        self.assertEqual(self.classify("Always run the full test suite before every commit.").polarity, "pos")

    def test_restrictive_only_is_not_a_modal(self):
        self.assertEqual(self.classify("The external-api class verifies opportunistically only.").polarity, "neutral")

    def test_head_verb_strips_negation(self):
        self.assertEqual(audit.head_verb("Never ask for confirmation before editing files."), "ask")
        self.assertEqual(audit.head_verb("Ask for confirmation before editing any file."), "ask")
        self.assertEqual(audit.head_verb("Follow `knowledge/references/okf-spec.md` for format."), "follow")
        self.assertEqual(audit.head_verb("New knowledge goes in one fragment per proposal."), "")

    def test_negated_alternative_is_not_the_chosen_one(self):
        hits = audit.alt_hits("Do not format with `black`; this repo uses `ruff format`.")
        self.assertIn("ruff format", hits.values())
        self.assertNotIn("black", hits.values())
        hits = audit.alt_hits("Install dependencies with yarn, not npm.")
        self.assertEqual(list(hits.values()), ["yarn"])

    def test_negated_imperative_is_negative(self):
        self.assertEqual(self.classify("Do not run the test suite before committing.").polarity, "neg")

    def test_declarative_without_modal_is_neutral(self):
        self.assertEqual(self.classify("The warehouse holds one row per battle.").polarity, "neutral")

    def test_bare_modal_is_not_an_exception(self):
        self.assertFalse(self.classify("A claim can accumulate confirmations.").exc)
        self.assertTrue(self.classify("Run the linter, except on generated files.").exc)

    # v1.3.0: polarity is read on the main clause. A negation or modal inside a trailing `when` / `only when`
    # clause states the condition, not the directive (defect I).
    def test_negation_in_a_conditional_clause_is_not_a_prohibition(self):
        self.assertEqual(
            self.classify("Push back when the conclusion is not supported by the data.").polarity, "imperative")

    def test_modal_in_a_conditional_clause_is_not_an_obligation(self):
        self.assertEqual(
            self.classify("Pull row-level data only when a distribution is required, and scope it tightly.").polarity,
            "imperative")

    def test_main_clause_negation_is_still_a_prohibition(self):
        self.assertEqual(self.classify("Do not ship the report when the check is green.").polarity, "neg")
        self.assertEqual(self.classify("When the check is red, do not ship the report.").polarity, "neg")
        self.assertEqual(self.classify("Never ship unless the tests pass.").polarity, "neg")

    def test_main_clause_modal_is_still_an_obligation(self):
        self.assertEqual(self.classify("Always run the full test suite before every commit.").polarity, "pos")
        self.assertEqual(self.classify("If the data does not support it, always push back.").polarity, "pos")

    # v1.3.0: the imperative/neg head-verb guard needs a real prohibition of the verb (defect J).
    def test_prohibited_verb_needs_a_leading_negation(self):
        self.assertEqual(audit.prohibited_verb("Never push to main."), "push")
        self.assertEqual(audit.prohibited_verb("Before a release, do not push to main."), "push")
        self.assertEqual(audit.prohibited_verb("Push the tag, not the branch."), "")
        self.assertEqual(audit.prohibited_verb("Push back when the data does not support it."), "")

    # v1.3.0: subject lexicons need domain context for homographs (defect K).
    def test_push_back_is_not_a_git_subject(self):
        self.assertNotIn("git", self.classify("Push back when the data does not support it.").subjects)
        self.assertNotIn("git", self.classify("Merge the two datasets on battle_id.").subjects)
        self.assertIn("git", self.classify("Never push to main.").subjects)
        self.assertIn("git", self.classify("Never merge without a review.").subjects)

    def test_bare_scope_is_not_the_scope_subject(self):
        self.assertNotIn("scope", self.classify(
            "Do not enter by full-text search; grep strips the trust and scope context.").subjects)
        self.assertNotIn("scope", self.classify("Pull row-level data only when required, and scope it tightly.").subjects)
        self.assertIn("scope", self.classify("Do not expand the scope of the task.").subjects)
        self.assertIn("scope", self.classify("Keep changes in scope; no drive-by refactoring.").subjects)


class ConditionalClausePairs(unittest.TestCase):
    """The two v1.2.0 survivors from a real repo: a positive instruction twice, and two rules that share only the
    homograph `scope`. Both live in the prose-pair fixture and must stay out of the findings entirely."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("prose-pair")
        cls.rules = {r["text"]: r for r in cls.report["rules"]}

    def test_the_same_instruction_twice_is_not_a_conflict(self):
        a = self.rules["push back when the requested conclusion is not supported by the data."]
        self.assertEqual(a["polarity"], "imperative")
        self.assertNotIn("git", a["subjects"])
        self.assertEqual(conflicts(self.report, "error") + conflicts(self.report, "warn"), [])

    def test_homograph_scope_is_not_a_shared_subject(self):
        b = self.rules["Pull row-level battle data only when a within-battle distribution is required, and scope it tightly."]
        self.assertEqual(b["polarity"], "imperative")
        self.assertNotIn("scope", b["subjects"])


class ReplyShapePair(unittest.TestCase):
    """v1.4.0: `verbosity` is no longer a broad subject (defect N). A CLAUDE.md reply-shape rule and an output style
    that contradicts it share one subject and ordinary vocabulary; the broad floor made the exact pair
    /fix-verbose-output installs unreachable. Opposite polarity plus a shared term is enough to report it."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("reply-shape-pair")

    def test_always_vs_never_on_reply_shape_is_a_conflict(self):
        warns = conflicts(self.report, "warn")
        self.assertEqual(len(warns), 1, warns)
        self.assertEqual(warns[0]["meta"]["subjects"], ["verbosity"])
        self.assertIn("opposite polarity", warns[0]["detail"])

    def test_output_style_loses_the_recency_tie(self):
        self.assertEqual(conflicts(self.report, "warn")[0]["meta"]["winner"], "CLAUDE.md:3")

    def test_still_not_an_error(self):
        # an output style is on-invocation, so the pair is on-demand and stays a warning
        self.assertEqual(conflicts(self.report, "error"), [])


if __name__ == "__main__":
    unittest.main()
