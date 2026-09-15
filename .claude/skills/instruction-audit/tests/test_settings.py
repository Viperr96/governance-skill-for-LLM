"""Regression tests for what settings.json decides about which surfaces load (v1.4.0, defect L).
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


def run(fixture, *extra):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        try:
            audit.main([str(HERE / "fixtures" / fixture), "--json", "--no-user", *extra])
        except SystemExit:
            pass
    return json.loads(buf.getvalue())


def findings(report, check=None, severity=None, cls=None):
    out = report["findings"]
    if check:
        out = [f for f in out if f["check"] == check]
    if severity:
        out = [f for f in out if f["severity"] == severity]
    if cls:
        out = [f for f in out if f["meta"].get("cls") == cls]
    return out


class DisabledSkill(unittest.TestCase):
    """CLAUDE.md sends the model to the `polars` skill; .claude/settings.json sets skillOverrides.polars to "off".
    v1.3.0 read the file for hooks and permissions, stepped over the key, and reported the project clean."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("disabled-skill")

    def test_rule_naming_a_disabled_skill_is_an_error(self):
        errs = findings(self.report, "enforcement", "error", cls="dead-skill")
        self.assertEqual(len(errs), 1, errs)
        self.assertEqual(errs[0]["line"], 3)
        self.assertEqual(errs[0]["meta"]["skills"], ["polars"])

    def test_disabled_skill_surface_is_flagged(self):
        warns = findings(self.report, "enforcement", "warn", cls="disabled-skill")
        self.assertEqual(len(warns), 1, warns)
        self.assertEqual(warns[0]["file"], ".claude/skills/polars/SKILL.md")

    def test_surfaces_table_says_the_skill_never_loads(self):
        skill = [s for s in self.report["surfaces"] if s["kind"] == "skill"][0]
        self.assertEqual(skill["loads"], "never (skillOverrides off)")
        self.assertEqual(skill["disabled_by"], "settings.json")

    def test_bare_library_name_is_not_the_skill(self):
        # CLAUDE.md:4 "Use Polars when pandas becomes memory- or runtime-bound." names the library, not the skill
        self.assertEqual([f["line"] for f in findings(self.report, cls="dead-skill")], [3])

    def test_rules_inside_the_disabled_skill_are_not_double_flagged(self):
        inside = [f for f in findings(self.report, cls="dead-skill") if f["file"].endswith("SKILL.md")]
        self.assertEqual(inside, [])


class EnabledSkill(unittest.TestCase):
    """The same project with no skillOverrides: the negative control."""

    @classmethod
    def setUpClass(cls):
        cls.report = run("enabled-skill")

    def test_no_overrides_means_no_findings(self):
        self.assertEqual(findings(self.report, "enforcement"), [])
        self.assertEqual(findings(self.report, severity="error") + findings(self.report, severity="warn"), [])

    def test_skill_loads_on_invocation(self):
        skill = [s for s in self.report["surfaces"] if s["kind"] == "skill"][0]
        self.assertEqual(skill["loads"], "on invocation")
        self.assertIsNone(skill["disabled_by"])


class NamesSkill(unittest.TestCase):
    def test_code_span_and_slash_forms_name_the_skill(self):
        self.assertTrue(audit.names_skill("Use the `polars` skill for pulls over 5 GiB.", "polars"))
        self.assertTrue(audit.names_skill("Run /polars on the parquet drop.", "polars"))
        self.assertTrue(audit.names_skill("Local processing: `polars`, `xlsx`, and `docx`.", "xlsx"))

    def test_bare_word_needs_the_word_skill(self):
        self.assertTrue(audit.names_skill("Use the polars skill when pandas is slow.", "polars"))
        self.assertFalse(audit.names_skill("Use Polars when pandas becomes memory-bound.", "polars"))
        self.assertFalse(audit.names_skill("Export the table as docx.", "docx"))
        self.assertFalse(audit.names_skill("Use `polars-cli` for the pull.", "polars"))


class LoadSettings(unittest.TestCase):
    def test_skill_overrides_are_collected_with_their_file(self):
        settings = audit.load_settings(HERE / "fixtures" / "disabled-skill", include_user=False)
        self.assertEqual(set(settings["skill_overrides"]), {"polars"})
        val, f = settings["skill_overrides"]["polars"]
        self.assertEqual(val, "off")
        self.assertEqual(Path(f).name, "settings.json")
        self.assertEqual(set(audit.disabled_skills(settings)), {"polars"})

    def test_local_settings_win_over_project_settings(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".claude").mkdir()
            (Path(d) / ".claude" / "settings.json").write_text('{"skillOverrides": {"a": "off", "b": "off"}}')
            (Path(d) / ".claude" / "settings.local.json").write_text('{"skillOverrides": {"a": "on"}}')
            settings = audit.load_settings(d, include_user=False)
            self.assertEqual(set(audit.disabled_skills(settings)), {"b"})


if __name__ == "__main__":
    unittest.main()
