# Repro prompt for a surviving conflict false positive

Give this to whoever reports that the `conflicts` check still flags a pair that is not a contradiction.
They paste the fenced block below into their Claude Code session inside the audited repo. It produces one
file, `instruction-audit-defect-G-repro.md`, that shows which copy of the checker ran, the exact polarity,
regex hits and head verb for both sides of every error-level pair, and the copy's own test output. The
first thing to read in that file is the version table: a copy below 1.3.0 means a plugin update, not a fix.

---

````text
I need to produce a diagnostic file for the instruction-audit plugin maintainer. A conflict false positive
("defect G": a bare imperative like `Follow the spec.` scored as the opposite of a sentence containing
never/not/avoid) is still reported after the v1.3.0 fix. Do exactly the following, do not modify any
project file, and write everything into ONE file at the repo root: `instruction-audit-defect-G-repro.md`.

## Step 1: find every copy of the checker and the one the skill actually runs

1. Search for every `audit_instructions.py` on this machine that belongs to the plugin: under the repo,
   under `~/.claude/` (plugins cache, skills), and any `instruction-governance*` directory. For each,
   record the absolute path, the `VERSION = "..."` line, and the file's mtime.
2. Run `claude plugin list` (ignore failure if the CLI is not available) and record the output.
3. Open the SKILL.md for `instruction-audit` that the plugin resolves to and record how it invokes the
   script (the exact command line it tells the agent to run). That is the copy under test. If more than one
   copy exists and any is below 1.3.0, say so at the top of the report.

## Step 2: create the diagnostic script

Create `defect_g_repro.py` in a temp directory (not in the repo) with exactly this content:

```python
"""Collect everything needed to diagnose a surviving defect-G conflict error.
Usage: python defect_g_repro.py <audit_instructions.py> <repo root> [--exclude GLOB]... > report.md
"""
import contextlib, hashlib, importlib.util, io, json, re, sys
from pathlib import Path

SCRIPT = Path(sys.argv[1]).resolve()
ROOT = sys.argv[2]
EXTRA = sys.argv[3:]
spec = importlib.util.spec_from_file_location("audit_under_test", SCRIPT)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

args = [ROOT, "--json", "--rules", "--only", "conflicts"] + EXTRA
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    try:
        m.main(args)
    except SystemExit:
        pass
rep = json.loads(buf.getvalue())
by_text = {}
for r in rep.get("rules", []):
    by_text.setdefault((r["file"], r["text"]), r)

L = ["# instruction-audit: defect G repro", ""]
L += ["| item | value |", "|---|---|",
      "| script | `%s` |" % SCRIPT,
      "| VERSION | `%s` |" % getattr(m, "VERSION", "?"),
      "| sha256 | `%s` |" % hashlib.sha256(SCRIPT.read_bytes()).hexdigest()[:16],
      "| has head_verb (v1.2.0 marker) | %s |" % hasattr(m, "head_verb"),
      "| has main_clause + prohibited_verb (v1.3.0 marker) | %s |" % (hasattr(m, "main_clause") and hasattr(m, "prohibited_verb")),
      "| imperative polarity in classify_rule | %s |" % ('"imperative"' in SCRIPT.read_text(encoding="utf-8", errors="replace")),
      "| python | `%s` |" % sys.version.split()[0],
      "| invocation | `%s` |" % " ".join(args),
      "| summary | `%s` |" % json.dumps(rep.get("summary")), ""]
L += ["POS_RE: `%s`" % m.POS_RE.pattern, "", "NEG_RE: `%s`" % m.NEG_RE.pattern, ""]


def describe(tag, file, line, text):
    r = by_text.get((file, text))
    L.append("**%s** `%s:%s`" % (tag, file, line))
    L.append("")
    L.append("```")
    L.append(text)
    L.append("```")
    neg = [x.group(0) for x in m.NEG_RE.finditer(text)]
    pos = [x.group(0) for x in m.POS_RE.finditer(text)]
    row = ["polarity=%s" % (r["polarity"] if r else "?"),
           "subjects=%s" % (r["subjects"] if r else "?"),
           "exception=%s" % (r.get("exception") if r else "?"),
           "heading=%r" % (r.get("heading") if r else "?"),
           "NEG hits=%s" % neg, "POS hits=%s" % pos,
           "leading_imperative=%s" % m.leading_imperative(text)]
    if hasattr(m, "head_verb"):
        row.append("head_verb=%r" % m.head_verb(text))
    if hasattr(m, "main_clause"):
        row.append("main_clause=%r" % m.main_clause(text))
    if hasattr(m, "prohibited_verb"):
        row.append("prohibited_verb=%r" % m.prohibited_verb(text))
    if hasattr(m, "alt_hits"):
        row.append("alt_hits=%s" % m.alt_hits(text))
    L.append("- " + "; ".join(row))
    L.append("")


errs = [f for f in rep["findings"] if f["check"] == "conflicts" and f["severity"] == "error"]
L.append("## Error-level conflict findings: %d" % len(errs))
L.append("")
for f in errs:
    meta = f.get("meta", {})
    L.append("### %s:%s <-> %s:%s" % (f["file"], f["line"], meta.get("other_file"), meta.get("other_line")))
    L.append("")
    L.append("- detail: %s" % f["detail"])
    L.append("- score=%s semantic=%s co_load=%s same_unit=%s winner=%s" % (
        meta.get("score"), meta.get("semantic"), meta.get("co_load"), meta.get("same_unit"), meta.get("winner")))
    L.append("")
    describe("A", f["file"], f["line"], f["text"])
    describe("B", meta.get("other_file"), meta.get("other_line"), meta.get("other_text", ""))

warns = [f for f in rep["findings"] if f["check"] == "conflicts" and f["severity"] == "warn"]
L.append("## Warn-level conflict findings: %d (detail only)" % len(warns))
L.append("")
for f in warns:
    L.append("- %s" % f["detail"])
L.append("")
L.append("## Polarity census of all extracted rules")
L.append("")
census = {}
for r in rep.get("rules", []):
    census[r["polarity"]] = census.get(r["polarity"], 0) + 1
L.append("`%s`" % json.dumps(census, sort_keys=True))
L.append("")
sys.stdout.write("\n".join(L) + "\n")
```

## Step 3: run it

Run the script against the copy under test from Step 1, with the repo root and the SAME `--exclude`
arguments used in the last `/instruction-audit` run (look them up in the previous audit's invocation or
JSON output). Add `--no-user` so the user-level CLAUDE.md is left out. Example shape:

```
python <tmp>/defect_g_repro.py <path to copy under test> <repo root> --no-user --exclude "<glob1>" --exclude "<glob2>" ...
```

If the copy under test reports VERSION below 1.3.0, run `claude plugin update instruction-governance`,
locate the updated copy, and run the script a second time against it. Keep both outputs.

## Step 4: run the copy's own tests

From the directory containing the copy under test's `scripts/` and `tests/` folders, run
`python -m unittest discover -s tests -v` and capture the full output (it is fine if the tests
directory does not exist in an older copy; say so).

## Step 5: write the file

Write `instruction-audit-defect-G-repro.md` at the repo root with these sections, in order:

1. **Copies found**: table of path, VERSION, mtime; the `claude plugin list` output; the SKILL.md
   invocation line; one sentence naming which copy the skill runs.
2. **Diagnostic output**: the script's full output, unedited (both runs if Step 3 ran twice).
3. **Test output**: from Step 4.
4. **Rules in context**: for every error-level pair in the diagnostic output, paste the 3 source lines
   before and after each of the two rules from the original markdown files, with line numbers, so the
   maintainer can see the paragraph the sentence was extracted from.

Do not summarize, interpret, or shorten the script output. Do not fix anything. When the file is written,
tell me its path and the VERSION of the copy under test in one line.
````
