# Instruction governance skills for LLM-driven projects

Four Claude Code skills, built from the approaches in `approaches.md`, that check and fix the files which steer a coding agent: `CLAUDE.md`, `AGENTS.md`, `.cursorrules`, Copilot instructions, `.claude/rules`, skills, agents, output styles, hooks and permission rules.

| skill | run it when | what it does |
|---|---|---|
| `/fix-verbose-output [path] [rule\|style\|hook\|plugin]` | Claude talks too much and `Be concise` in CLAUDE.md does nothing | Injects the verbose-output article's setup in one go: replaces vague brevity lines with a `Reply shape` rule, adds the output style and selects it, and on the first install asks whether to add the optional length-gating Stop hook. Can bundle it all as a plugin. Every changed line is listed. |
| `/instruction-audit [path] [fix]` | you want a health check of every instruction file, or after a model upgrade | Runs a deterministic checker (bloat, vague rules, Opus 5 inverted classes, misplaced rules, conflict candidates, ungated enforcement, broken hooks, rules that send the model to a skill `skillOverrides` switched off), then judges only what the text cannot settle. `fix` applies the edits and shows before/after. |
| `/instruction-conflicts [path] [fix]` | the agent ignores a rule that is in the file, or follows it inconsistently | Groups every rule by subject across all files, tests each same-subject pair for "can both hold at once", names the winner under recency, proposes one resolution per conflict. |
| `/instruction-enforce <behavior>` | a rule must hold no matter what (length floor, forbidden command, protected path, step before commit) | Picks the weakest lever that holds (rule, output style, deny rule, hook, plugin) and generates it from templates, merging into `settings.json` without clobbering existing hooks. |

## Install

This repository is a plugin marketplace. Add it once, install the plugin, and all four skills load in every project on this machine:

```
/plugin marketplace add Viperr96/governance-skill-for-LLM
/plugin install instruction-governance@opus5-governance
```

The same two steps from a terminal, outside a session:

```
claude plugin marketplace add Viperr96/governance-skill-for-LLM
claude plugin install instruction-governance@opus5-governance
```

`/plugin` on its own opens the browser, where the plugin can be enabled or disabled per project. Add `@v1.0` to the marketplace source to pin a tag or branch. `claude plugin details instruction-governance` prints the four skills and what they cost in tokens, `claude plugin update instruction-governance` pulls a newer version, and `claude plugin uninstall instruction-governance` removes it.

The skills are plain files and work without the marketplace too. Project-level: copy `.claude/skills/` into any repository. User-level:

```
# PowerShell
Copy-Item -Recurse .claude\skills\fix-verbose-output, .claude\skills\instruction-* $HOME\.claude\skills\

# bash
cp -r .claude/skills/fix-verbose-output .claude/skills/instruction-* ~/.claude/skills/
```

`fix-verbose-output` is self-contained and can be taken on its own. The three `instruction-*` skills ship as a set: `instruction-conflicts` and `instruction-enforce` call the checker script inside `instruction-audit/scripts/`.

## Examples

### Fix verbose output

```
/fix-verbose-output
```

Installs the levers from "Opus 5: How to Fix Verbose Output" into the current project. It deletes any `Be concise` / `No preamble` line from `CLAUDE.md`, writes the reply-shape rules once as `.claude/output-styles/reply-shape.md` with `outputStyle` set in `.claude/settings.json`, and leaves a one-line pointer in `CLAUDE.md` so a human can find them. `rule` alone puts the full section in `CLAUDE.md` instead. The rules never live in both places; two copies are the duplicated steering `/instruction-audit` flags, and they drift into a conflict as soon as one is edited. On the first install in a project it asks one question: add the Stop hook, or not. Saying yes installs `.claude/hooks/gate_length.py`, wires it into `hooks.Stop` next to whatever hooks are already there, and runs it once with a long, a short, and a second-pass payload before the skill reports. Saying no leaves the hook out; later runs do not ask again, and `/fix-verbose-output hook` adds it whenever you want the floor.

```
/fix-verbose-output rule
/fix-verbose-output style
/fix-verbose-output hook --limit 120
/fix-verbose-output plugin
/fix-verbose-output C:\work\shop-api --dry-run
```

Levels are cumulative, weakest first, and a level token skips the question. `rule` only touches `CLAUDE.md`; `plugin` also builds `reply-shape-plugin/` for `claude --plugin-dir`. `--dry-run` reports without writing; `--force` overwrites a style or hook that already exists.

The report it comes back with after a yes to the hook:

```
**Verdict:** installed 3 lever(s) (rule, style, hook) in `C:\work\shop-api`; 2 vague brevity line(s) removed

| lever | target | action |
|---|---|---|
| rule | `CLAUDE.md:4` | removed vague brevity line: - Be concise. No preamble. |
| rule | `CLAUDE.md` | added a one-line pointer to the output style (no second copy of the rules) |
| style | `.claude/output-styles/reply-shape.md` | created |
| style | `.claude/settings.json outputStyle` | set to 'Reply shape' |
| hook | `.claude/hooks/gate_length.py` | created |
| hook | `.claude/settings.json hooks.Stop` | added the length gate (180-word budget); other hooks kept |
| self-test | `.claude/hooks/gate_length.py` | 372-word reply exit 2 ok; short reply exit 0 ok; second pass (stop_hook_active) exit 0 ok |
```

Running it again changes nothing; every row reads "already present; unchanged". The installer is a stdlib Python script and runs on its own too:

```
python .claude/skills/fix-verbose-output/scripts/inject_reply_shape.py . --status
python .claude/skills/fix-verbose-output/scripts/inject_reply_shape.py . --level hook --limit 180 --dry-run
python .claude/skills/fix-verbose-output/scripts/inject_reply_shape.py . --level plugin --json
```

`--status` prints what is already installed and whether this counts as a first install; the skill uses it to decide whether to ask about the hook.

### Health check of a project

```
/instruction-audit
```

Audits the current directory plus `~/.claude/CLAUDE.md` and `~/.claude/rules/`. The reply leads with a verdict and a counts table, then findings grouped by severity with `file:line`, then a fix list. Nothing is edited.

```
/instruction-audit C:\work\shop-api
/instruction-audit . --no-user
```

Point it at another repository, or leave the user-level files out of the run.

```
/instruction-audit fix
```

Same audit, then the edits are applied in order: confirmed conflicts, inverted-class deletions, vague-rule rewrites, moves into `.claude/rules/`, bloat cuts. The reply ends with a before/after table and a list of every deleted rule with its text, so any of them can be restored.

### What a report looks like

An excerpt from the checker's run on the fixture project used to test it:

```
**Verdict:** 8 error(s), 27 warning(s), 7 info across 5 surface(s), 28 rules; instruction share 68% of words

| check       | error | warn | info |
|-------------|------:|-----:|-----:|
| bloat       |     0 |    0 |    2 |
| specificity |     0 |    4 |    1 |
| inverted    |     0 |    3 |    2 |
| placement   |     0 |    3 |    0 |
| conflicts   |     7 |   14 |    0 |
| enforcement |     1 |    3 |    2 |

- **error** `CLAUDE.md:23` — "Always write a test for every function."
  - [tests] opposite polarity; one carries an exception; shared terms: test. Pair: CLAUDE.md:23 <-> CLAUDE.md:43.
    both always on. Recency winner: CLAUDE.md:43 (later in the same file).
  - other: `CLAUDE.md:43` — "Code under scratchpad/ ships without tests."

- **warn** `CLAUDE.md:21` — "Keep the code clean and follow best practices."
  - Vague term(s): best practices, clean; names no construct the model can bind to.

- **warn** `CLAUDE.md:27` — "Be conservative: only report high-severity issues in reviews."
  - Class 'hedge'. Opus 5 follows a limiter literally and under-reports. Ask for everything, then filter in a second pass.

- **warn** `CLAUDE.md:39` — "Never edit files under prisma/migrations/."
  - Enforcement-shaped (protected-path) but steering only: no hook or permission rule backs it.
  - fix: Add permissions.deny Edit(<glob>) and Write(<glob>); or a PreToolUse hook on Edit|Write.

- **error** `.claude/settings.json:1` — "${CLAUDE_PROJECT_DIR}/.claude/hooks/gate-length.sh"
  - Stop hook references a script that does not exist.
```

### Find why a rule is ignored

```
/instruction-conflicts
```

Groups every rule across every file by subject and tests each pair for "can both hold for one concrete task". The reply is one table:

| # | subject | rule A | rule B | task where they collide | winner today | resolution |
|---|---|---|---|---|---|---|
| 1 | tests | `CLAUDE.md:23` write a test for every function | `CLAUDE.md:43` scratchpad ships without tests | a throwaway script in `scratchpad/` | B (later in file) | keep both as one rule: general first, exception after, scoped to `scratchpad/**` |
| 2 | dependencies | `CLAUDE.md:31` use pnpm | `AGENTS.md:3` use yarn | any install | A (project file loads after import) | delete the yarn line |

```
/instruction-conflicts fix
```

Applies the resolutions and re-runs the pass to confirm zero confirmed conflicts remain.

Asking in plain words works too, because the skill's description names the symptoms:

```
Claude keeps writing tests for my scratchpad scripts even though CLAUDE.md says not to. Why?
```

### Make a rule hold no matter what

```
/instruction-enforce replies under 180 words
```

Installs the Stop hook from `templates/gate_length.py` into `.claude/hooks/`, merges it into `.claude/settings.json`, runs it once with a sample payload, and reports the constant to edit for a different budget.

```
/instruction-enforce never force-push and never push directly to main
/instruction-enforce no edits under prisma/migrations/ or any lock file
/instruction-enforce run pytest before every commit
/instruction-enforce ask before installing a dependency
/instruction-enforce answer first, tables instead of prose walls
```

Each picks the weakest lever that holds: a `permissions.deny` entry for the first two, a git pre-commit hook for the third, `permissions.ask` for the fourth, an output style plus a three-line rule for the last.

```
/instruction-enforce never force-push --lever hook
```

Forces a lever when the default is not what you want; here a PreToolUse hook (`templates/deny_patterns.py`) instead of a deny rule, useful when the pattern needs a regex.

### After a model upgrade

```
/instruction-audit
```

Read the `inverted` section first. It lists the classes the Opus 5 generation over-obeys: `double-check` lines, `be conservative` hedges, `think step by step`, effort values in prose, `be concise` with no shape. Delete or rewrite those before touching anything else. Then run `/instruction-conflicts`; a stronger model commits to one side of every conflict silently, so the run-to-run flakiness that used to expose them is gone.

## The checker on its own

`audit_instructions.py` is stdlib-only Python 3.8+ and runs the same way in CI:

```
python .claude/skills/instruction-audit/scripts/audit_instructions.py . --no-user --fail-on error
python .claude/skills/instruction-audit/scripts/audit_instructions.py . --json --rules > audit.json
python .claude/skills/instruction-audit/scripts/audit_instructions.py . --only conflicts,enforcement
python .claude/skills/instruction-audit/scripts/audit_instructions.py . --list
python .claude/skills/instruction-audit/scripts/audit_instructions.py . --acronyms ARPU,ARPPU   # or .instruction-audit.json
```

Its regression tests run with `python -m unittest discover -s tests` from `.claude/skills/instruction-audit/`. They pin six fixture projects: a prose-heavy `CLAUDE.md` that `@import`s a knowledge file and must produce no conflict findings (it carries the same positive instruction twice with a negation in its `when` clause, and two rules that share only the homograph `scope`), a pair of files with four real contradictions that must all stay errors, a single `CLAUDE.md` with four adjacent contradictions that must yield exactly two errors and score the same when split across an `@import`, a reply-shape rule against an output style that contradicts it (one warning), and a `CLAUDE.md` that names a skill `settings.json` switches off with `skillOverrides` (one error, one warning) next to the same project with the override removed (nothing). Bold list headers and domain acronyms have their own tests against the `emphasis` class.

It does not run a model. The same input gives the same output every time, which is the point: whether a rule names a construct, contradicts another, or loads where it applies are properties of the text, and asking the model to grade them is asking a stochastic judge a question with a definite answer.

Flags:

| flag | effect |
|---|---|
| `--only bloat,conflicts` | run a subset of the six checks |
| `--rules` | append the extracted rule inventory (subjects, polarity, concrete tokens) |
| `--json` / `--json-out FILE` | machine-readable output, or write it alongside the markdown |
| `--out FILE` | write the report to a file |
| `--no-user` | skip `~/.claude/CLAUDE.md`, `~/.claude/rules/`, and user settings |
| `--include "docs/prompts/*.md"` | audit extra files (system prompts kept elsewhere) |
| `--exclude "**/vendor-rules/**"` | skip files matching a glob; use it for skills installed from a plugin or marketplace that you do not maintain |
| `--max-lines 150` | change the line budget for always-on files (default 200) |
| `--fail-on warn` | exit 1 on warnings or errors (default `none`) |
| `--acronyms ARPU,ARPPU` | domain acronyms the `emphasis` class must not read as shouting; `.instruction-audit.json` with `{"acronyms": [...]}` at the root makes it stick |

GitHub Actions, failing the build on a hard conflict or a broken hook:

```yaml
name: instruction-audit
on: [pull_request]
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: python .claude/skills/instruction-audit/scripts/audit_instructions.py . --no-user --fail-on error --out audit.md
      - uses: actions/upload-artifact@v4
        if: always()
        with: { name: instruction-audit, path: audit.md }
```

As a pre-commit hook, so a conflicting rule never lands in `CLAUDE.md`:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: instruction-audit
        name: instruction audit
        entry: python .claude/skills/instruction-audit/scripts/audit_instructions.py . --no-user --only conflicts,enforcement --fail-on error
        language: system
        files: '(CLAUDE\.md|AGENTS\.md|\.cursorrules|\.claude/.*\.md|\.claude/settings.*\.json)$'
        pass_filenames: false
```

## Layout

```
.claude-plugin/
  marketplace.json                  # the marketplace entry: /plugin marketplace add
  plugin.json                       # the plugin manifest; its skills path points at .claude/skills/
.claude/skills/
  fix-verbose-output/
    SKILL.md
    scripts/inject_reply_shape.py     # the installer: rule, style, hook, plugin, self-test
    reference/levers.md               # the article's four levers with the Claude Code details
    templates/reply-shape.rule.md     # the CLAUDE.md section
    templates/reply-shape.style.md    # the output style
    templates/gate_length.py          # Stop hook, Python (default)
    templates/gate-length.sh          # Stop hook, the article's bash original (needs jq)
    templates/settings.hooks.json     # settings.json fragment
    templates/plugin.json, hooks.json # plugin manifest and hook wiring
  instruction-audit/
    SKILL.md
    scripts/audit_instructions.py     # the deterministic checker
    reference/checks.md               # what each check measures and why
    reference/rule-writing.md         # the three-line rule shape, rewrite patterns, symptom table
    tests/test_conflicts.py           # regression tests for the conflicts check
    tests/test_inverted.py            # bold headers and domain acronyms against the emphasis class
    tests/test_settings.py            # skillOverrides: disabled skills and the rules that name them
  instruction-conflicts/
    SKILL.md
  instruction-enforce/
    SKILL.md
    reference/levers.md               # hook contracts, permission syntax, plugin layout
    templates/gate_length.py          # Stop hook: sends an over-long reply back once
    templates/deny_patterns.py        # PreToolUse hook: refuses matching commands and edits
    templates/reply-shape.md          # output style
    templates/settings.hooks.json     # settings.json fragment to merge
    templates/plugin.json             # plugin manifest
approaches.md                         # the extracted approaches from the three source articles
```

## Sources

Three DEV Community articles by Gábor Mészáros (Reporails), saved as `.mhtml` in this folder: "Opus 5: Delete your CLAUDE.md?", "Opus 5: How to Fix Verbose Output", and "Opus 5: The Cost of Instruction Conflicts". Format details come from the Claude Code docs on memory, skills, and hooks.
