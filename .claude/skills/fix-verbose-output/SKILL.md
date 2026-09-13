---
name: fix-verbose-output
description: Inject the fix for verbose, over-long agent replies from "Opus 5: How to Fix Verbose Output" into a project. Replaces vague "be concise" lines in CLAUDE.md with a Reply shape rule that names the shape, adds the same rules as an output style selected through the outputStyle setting, and on first install asks whether to add an optional Stop hook that sends an over-long reply back once; can also bundle the style and hook into a plugin. Levers are cumulative, weakest first; a deterministic script does the edits and lists every changed line. Use when Claude talks too much, ignores "be concise" or "no preamble", pads replies with recaps and summaries, or when asked to make replies shorter, answer-first, terser, or to add a reply length limit, an output style, or a Stop hook.
argument-hint: "[path] [rule|style|hook|plugin] [--limit N] [--dry-run] [--force]"
allowed-tools: Bash(python *) Bash(python3 *) Bash(py *) Read Glob Grep AskUserQuestion
---

# Fix verbose output

`Be concise. No preamble.` names nothing the model can act on, and on Opus 5 it is read straight past. The fix is four levers, weakest first: a rule that names the shape, an output style that rides in the system prompt, an optional Stop hook that can refuse an over-long reply, and a plugin that carries the others across repositories. Instruction can be set aside; a hook cannot. Reach for the least that holds.

Arguments received: `$ARGUMENTS`

- A token that is an existing directory is the project root. Default: the current working directory.
- A level token, `rule`, `style`, `hook`, or `plugin`, sets how far up the ladder to go. Levels are cumulative: `hook` installs the rule, the style, and the hook. Without a level token, follow Step 1.
- `--limit N`: word budget for the Stop hook. Default 180.
- `--dry-run`: report what would change without writing.
- `--force`: overwrite an existing style, hook, or plugin file, and replace an `outputStyle` already set to something else.
- `--hook-lang bash`: install the article's original bash hook (needs `jq`) instead of the Python one.
- `--plugin-dir DIR`: where to build the plugin. Default `<root>/reply-shape-plugin`.

If the user asks in plain words, map the request: "add the rule" is `rule`; "make it lean terser by default" is `style`; "a hard cap", "never over N words", "send it back" is `hook`; "in every repo", "portable" is `plugin`.

## Step 1: pick the level when none was given

Run the status check first:

```
python "${CLAUDE_SKILL_DIR}/scripts/inject_reply_shape.py" "<root>" --status --json
```

Use `py -3` on Windows if `python` is not on PATH, and `python3` on macOS or Linux. Then:

- **`first_install` is true** (no Reply shape section, no pointer line, and no style file yet): ask the user, with AskUserQuestion, whether to add the Stop hook. One question, three options: "No, rule and style only", "Yes, 180-word budget", "Yes, a different budget" (then take the number from their answer). Skip the question under `--dry-run` and use `style`. The hook is the only lever that can refuse a reply, and the only one that changes what happens after every turn, which is why it is the user's call.
- **`hook_present` is true**: use `hook`, so the gate is re-verified and reported as unchanged.
- **Otherwise** (rule or style present, no hook): use `style` and do not ask again. The user already went through the first install; the report's note says how to add the hook later.

A level token from the user always wins over this step. If the status shows `duplicate_copy` (a full section in CLAUDE.md and the style file both present), any run at `style` or above collapses the section to a pointer; say so in the report.

## Step 2: run the installer

```
python "${CLAUDE_SKILL_DIR}/scripts/inject_reply_shape.py" "<root>" --level <level> [--limit N] [--dry-run] [--force]
```

If the script is missing, stop and report the expected path. Do not reimplement the edits by hand; the script is what makes the result the same every run.

What it does, per level:

| level | files | detail |
|---|---|---|
| rule | `CLAUDE.md` | removes lines that are only vague brevity phrases and lists each with `file:line`; at `rule` level with no style installed, appends or replaces a `## Reply shape` section from `templates/reply-shape.rule.md` |
| style | `.claude/output-styles/reply-shape.md`, `.claude/settings.json`, `CLAUDE.md` | writes the style with `keep-coding-instructions: true`; sets `outputStyle` to `Reply shape` if nothing else is set; collapses any Reply shape section in CLAUDE.md to a one-line pointer so the rules have exactly one copy |
| hook | `.claude/hooks/gate_length.py`, `.claude/settings.json` | installs the Stop hook with the budget; appends to `hooks.Stop` without touching other hooks or permissions; runs it with a long, a short, and a second-pass payload |
| plugin | `<plugin-dir>/` | manifest, `hooks/hooks.json` using `${CLAUDE_PLUGIN_ROOT}`, the hook, the style, a README with the rule |

It never overwrites an existing file without `--force`, never edits a `settings.json` that is not strict JSON, and never removes a line that carries anything besides a brevity phrase; such lines are reported for a hand edit.

## Step 3: read the report

The script prints a verdict, an action table, the removed lines, errors, and next steps. Check three things:

- **Errors.** A failed hook self-test or a malformed `settings.json` is an error and the exit code is 1. Report it first and say what the user has to fix.
- **A local override.** If `.claude/settings.local.json` sets a different `outputStyle`, it wins over `settings.json`; the report says so. Tell the user to pick `Reply shape` under `/config`.
- **Lines left in place.** A line such as `Be brief and use British spelling.` is reported but not removed. Propose the split: keep the second half, drop the first.

Read [reference/levers.md](reference/levers.md) when the user asks why one lever and not another, or how to tune the hook.

## Step 4: report

Reply in the shape the skill installs. First sentence: which levers landed and where, and whether the hook was added, declined, or already there. Then the action table from the script, trimmed to rows that changed something. Then the removed lines, verbatim, so any can be restored. Then next steps, at most three bullets:

- Restart Claude Code so the new style file is read; it applies from the next message.
- With the hook: it reloads through the file watcher, `/hooks` shows it, and `LIMIT_WORDS` in `.claude/hooks/gate_length.py` moves the budget.
- Without the hook: `/fix-verbose-output hook` adds it later.

Do not paste the script output verbatim and do not restate what each lever is; the user asked for the fix, not the article.

## Boundaries

- Do not weaken or remove an existing hook, deny rule, or output style. The script appends; so do you.
- Do not install the Stop hook without the user choosing it, through the level token or the first-install question.
- Do not keep the same rules in CLAUDE.md and in the output style. One copy: the style when it is installed, CLAUDE.md otherwise. Two agreeing copies are what `/instruction-audit` reports as duplicated steering, and they turn into a conflict the moment one is edited.
- Do not add `double-check` or `verify your reply` lines anywhere; those are the class Opus 5 over-obeys.
- Do not resolve a `be concise` line by bolding it, repeating it, or moving it; delete it and let the shape rule stand.
- Do not edit `~/.claude/` unless the user asked for a user-level install; this skill works at project scope.
- Do not write a hook that calls a model to judge the reply; the gate is a word count and stays deterministic.
