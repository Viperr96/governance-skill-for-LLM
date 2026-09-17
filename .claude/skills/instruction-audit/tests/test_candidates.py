"""Regression tests for the candidate stage (v1.5.0, from INSTRUCTION_CONFLICTS_REVIEW.md).
Run: python -m unittest discover -s tests (from the skill directory)."""
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


def run(fixture, *extra, json_out=True):
    buf = io.StringIO()
    argv = [str(HERE / "fixtures" / fixture), "--no-user", "--rules", *extra]
    if json_out:
        argv.insert(1, "--json")
    with contextlib.redirect_stdout(buf):
        try:
            audit.main(argv)
        except SystemExit:
            pass
    return json.loads(buf.getvalue()) if json_out else buf.getvalue()


def conflicts(report, severity=None):
    out = [f for f in report["findings"] if f["check"] == "conflicts"]
    return [f for f in out if f["severity"] == severity] if severity else out


def surface(report, kind):
    return [s for s in report["surfaces"] if s["kind"] == kind][0]


class SelectedOutputStyle(unittest.TestCase):
    """Review 1.1: settings.json selects the style, so it is in the system prompt on every turn. The same pair
    that is info while the style is unselected becomes an always-on error once it is selected."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("reply-shape-selected")

    def test_surface_is_always_on(self):
        st = surface(self.report, "output-style")
        self.assertTrue(st["always_on"])
        self.assertEqual(st["loads"], "always (outputStyle in settings.json)")
        self.assertEqual(st["selected_by"], "settings.json")

    def test_pair_is_an_error_with_the_claude_md_rule_winning(self):
        errs = conflicts(self.report, "error")
        self.assertEqual(len(errs), 1, errs)
        self.assertEqual(errs[0]["meta"]["co_load"], "always")
        self.assertEqual(errs[0]["meta"]["winner"], "CLAUDE.md:3")

    def test_unselected_style_stays_on_demand(self):
        report = run("reply-shape-pair")
        st = surface(report, "output-style")
        self.assertFalse(st["always_on"])
        self.assertEqual(st["loads"], "when selected (/output-style)")
        self.assertIsNone(st["selected_by"])

    def test_style_is_matched_by_name_not_case(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".claude" / "output-styles").mkdir(parents=True)
            (Path(d) / ".claude" / "output-styles" / "reply-shape.md").write_text(
                "---\nname: Reply shape\n---\n\n- Lead with the answer.\n", encoding="utf-8")
            (Path(d) / ".claude" / "settings.json").write_text('{"outputStyle": "reply shape"}', encoding="utf-8")
            (Path(d) / "CLAUDE.md").write_text("# P\n\n- Ask before editing.\n", encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    audit.main([d, "--json", "--no-user"])
                except SystemExit:
                    pass
            st = surface(json.loads(buf.getvalue()), "output-style")
            self.assertTrue(st["always_on"])


class DisabledSurfaces(unittest.TestCase):
    """Review 1.2: a surface the table lists as `never (skillOverrides off)` is not paired. `--include-disabled`
    pairs it as info with no winner."""

    def test_disabled_skill_is_not_paired_by_default(self):
        report = run("disabled-pair")
        self.assertEqual(conflicts(report), [])
        self.assertEqual(surface(report, "skill")["loads"], "never (skillOverrides off)")

    def test_include_disabled_pairs_it_as_info(self):
        report = run("disabled-pair", "--include-disabled")
        found = conflicts(report)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["severity"], "info")
        self.assertEqual(found[0]["meta"]["co_load"], "disabled")
        self.assertEqual(found[0]["meta"]["winner"], "none")
        self.assertIn("never loads", found[0]["detail"])


class SeverityNeedsSemanticEvidence(unittest.TestCase):
    """Review 1.3: opposite polarity plus a shared word on an on-demand pair is a keyword collision most of the
    time; it is info, not warn. Always-on pairs with the same evidence stay errors."""

    def test_on_demand_polarity_clash_is_info(self):
        report = run("reply-shape-pair")
        self.assertEqual(conflicts(report, "warn"), [])
        self.assertEqual(conflicts(report, "error"), [])
        infos = conflicts(report, "info")
        self.assertEqual(len(infos), 1, infos)
        self.assertEqual(infos[0]["meta"]["semantic"], 2)

    def test_always_on_pairs_still_reach_error(self):
        self.assertEqual(len(conflicts(run("true-conflicts"), "error")), 4)
        self.assertEqual(len(conflicts(run("single-file"), "error")), 2)


class CandidatesHeader(unittest.TestCase):
    """Review 1.4: a conflicts-only run prints `Candidates:`, not `Verdict:`."""

    def test_conflicts_only_header(self):
        text = run("true-conflicts", "--only", "conflicts", json_out=False)
        self.assertIn("**Candidates:**", text)
        self.assertNotIn("**Verdict:**", text)

    def test_full_run_keeps_verdict(self):
        text = run("true-conflicts", json_out=False)
        self.assertIn("**Verdict:**", text)


class SkillScaffold(unittest.TestCase):
    """Review 1.5, 1.6, 1.7: overview and resource sections are not rules, checklist steps are not rivals, and two
    skills have no fixed order."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("skill-scaffold")
        cls.texts = [r["text"] for r in cls.report["rules"]]

    def test_overview_paragraph_is_not_a_rule(self):
        self.assertFalse(any("Power analysis answers" in t for t in self.texts), self.texts)
        self.assertFalse(any("Every study should settle" in t for t in self.texts), self.texts)

    def test_resource_listing_is_not_a_rule(self):
        self.assertFalse(any("scripts/power.py" in t for t in self.texts), self.texts)
        self.assertFalse(any("reference/tables.md" in t for t in self.texts), self.texts)
        self.assertFalse(any("for the write-up" in t for t in self.texts), self.texts)

    def test_workflow_items_are_rules(self):
        self.assertTrue(any(t.startswith("Always check the assumptions") for t in self.texts), self.texts)

    def test_commit_to_a_motif_is_not_git(self):
        rule = [r for r in self.report["rules"] if r["text"].startswith("Commit to a visual motif")][0]
        self.assertNotIn("git", rule["subjects"])
        main = [r for r in self.report["rules"] if r["text"].startswith("Never commit to main")][0]
        self.assertIn("git", main["subjects"])

    def test_verify_no_is_a_positive_check(self):
        rule = [r for r in self.report["rules"] if r["text"].startswith("Verify no unintended")][0]
        self.assertEqual(rule["polarity"], "imperative")

    def test_steps_of_one_checklist_are_not_paired(self):
        same = [f for f in conflicts(self.report) if f["meta"]["co_load"] == "same-procedure"]
        self.assertEqual(same, [])

    def test_two_skills_have_no_recency_winner(self):
        sep = [f for f in conflicts(self.report) if f["meta"]["co_load"] == "separate-invocations"]
        self.assertEqual(len(sep), 1, conflicts(self.report))
        self.assertEqual(sep[0]["severity"], "info")
        self.assertEqual(sep[0]["meta"]["winner"], "depends on invocation order")
        self.assertIn("depends on invocation order", sep[0]["detail"])


class PolarityOfChecks(unittest.TestCase):
    def classify(self, text):
        s = audit.Surface(SCRIPT, "claude-md", SCRIPT.parent)
        r = audit.Rule(s, 1, text, text, "", "sentence")
        audit.classify_rule(r)
        return r

    def test_verify_no_forms(self):
        for t in ("Verify no unintended circular references remain.",
                  "Check that there are no orphan rows after the join.",
                  "Ensure no secrets are written to the log.",
                  "Make sure nothing under `dist/` is committed."):
            self.assertEqual(self.classify(t).polarity, "imperative", t)

    def test_real_prohibitions_keep_their_polarity(self):
        self.assertEqual(self.classify("Do not verify the output twice.").polarity, "neg")
        self.assertEqual(self.classify("Never check assumptions after the test.").polarity, "neg")
        self.assertEqual(self.classify("Always verify the join keys.").polarity, "pos")


class PrecedencePairs(unittest.TestCase):
    """Review 1.8: two positive rules that name different winners for one decision. Polarity does not separate
    them; the precedence vocabulary plus a shared domain noun does."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("precedence-pair")

    def test_same_polarity_precedence_conflict_is_an_error(self):
        errs = conflicts(self.report, "error")
        self.assertEqual(len(errs), 1, conflicts(self.report))
        self.assertIn("both name a precedence winner", errs[0]["detail"])
        self.assertIn("shared terms:", errs[0]["detail"])
        self.assertEqual({errs[0]["line"], errs[0]["meta"]["other_line"]}, {5, 10})

    def test_precedence_rules_on_different_subjects_are_not_paired(self):
        lines = {(f["line"], f["meta"]["other_line"]) for f in conflicts(self.report)}
        self.assertEqual(lines, {(5, 10)})

    def test_precedence_vocabulary(self):
        self.assertEqual(audit.precedence_terms("The table is the canonical source."), ["canonical"])
        self.assertEqual(audit.precedence_terms("Constants take precedence over the table."), ["take precedence"])
        self.assertEqual(audit.precedence_terms("Prefer polars over pandas for big pulls."),
                         ["prefer polars over"])
        self.assertEqual(audit.precedence_terms("Pull no more than 5 GiB over the network."), [])


class OutputFlags(unittest.TestCase):
    """Review 2.1 and 2.2: the rule inventory stays out of stdout unless asked for; the JSON layout is printable."""

    def test_rules_flag_keeps_the_table_out_of_markdown(self):
        text = run("single-file", json_out=False)
        self.assertNotIn("## Extracted rules", text)
        self.assertIn("`--print-rules`", text)

    def test_print_rules_prints_the_table(self):
        text = run("single-file", "--print-rules", json_out=False)
        self.assertIn("## Extracted rules", text)

    def test_rules_flag_still_fills_the_json(self):
        self.assertTrue(run("single-file")["rules"])

    def test_schema_flag(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            audit.main(["--schema"])
        out = buf.getvalue()
        for key in ("surfaces[]", "findings[]", "rules[]", "co_load", "selected_by", "semantic"):
            self.assertIn(key, out)


if __name__ == "__main__":
    unittest.main()
