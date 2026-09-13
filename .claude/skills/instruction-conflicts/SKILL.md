---
name: instruction-conflicts
description: Find pairs of agent instructions that cannot both hold at once, across CLAUDE.md, nested CLAUDE.md, .claude/rules, skills, agents, @imports, and other agent instruction files, and name which rule wins under recency (the later-loaded rule governs, and Opus 5 commits to it silently). Use when an agent ignores a rule that is in the file, follows a rule inconsistently, thrashes, or when asked to find contradictions, conflicts, inconsistencies, or overlaps in CLAUDE.md, AGENTS.md, rules, skills, or prompts.
argument-hint: "[path] [fix]"
allowed-tools: Bash(python *) Bash(python3 *) Bash(py *) Read Glob Grep
---

# Instruction conflicts

Two rules that cannot both hold do not cancel. The model commits to one and the other reads as if it were never written. Position decides the winner: the rule read later governs. Nothing surfaces the collision, and Opus 5 picks the same side every run, so there is no flakiness to notice. This skill finds those pairs by reading the files as a set of constraints, not top to bottom.

Arguments received: `$ARGUMENTS`

- A token that is an existing directory is the project root. Default: the current working directory.
- `fix`: apply the resolutions after reporting.

## Step 1: get the rule inventory and candidate pairs

Run the shared checker, conflicts only, with the rule inventory:

```
python "${CLAUDE_SKILL_DIR}/../instruction-audit/scripts/audit_instructions.py" "<root>" --only conflicts --rules --json-out "<scratchpad>/instruction-conflicts.json"
```

Use `py -3` on Windows if `python` is not on PATH. If the script is missing, read every surface listed under "Surfaces to cover" below with Read and build the inventory by hand: one row per rule with file, line, heading, and subject.

The output gives you: every surface and how it loads, every extracted rule with its subjects and polarity, and candidate pairs with a recency winner. Candidates are a deterministic narrowing, not a verdict.

## Step 2: build the subject index

Group every rule by subject. The script tags subjects by keyword. Add the merges only a reader can make:

- Different vocabulary for one thing: `mock` and `fake` and `stub`; `throwaway script` and `scratchpad`; `external calls` and `network` and `third-party API`.
- Different headings for one subject: a testing rule under "Testing" and another under "Prototyping workflow" or "Definition of done".
- A general rule and a specific exception written as a new topic: "ask before installing a dependency" under Workflow and "run the setup script, it pulls what it needs" under Onboarding.

For each subject, list every rule with its `file:line`.

## Step 3: test each same-subject pair

For every pair of rules on one subject, answer one question: is there one concrete task on which following rule A forbids what rule B requires? Write that task in one line. A pair with such a task is a conflict. A pair without one is dismissed in one line.

Check the four places conflicts hide:

1. Different headings, same subject, in one file.
2. Different vocabulary for the same thing.
3. A general rule plus an exception that does not read as one.
4. Root `CLAUDE.md` versus a nested `CLAUDE.md`, a path-scoped rule, a skill, or an agent. That conflict exists only on the turns the on-demand surface is loaded, which is exactly when nobody is reading the root file.

Also compare user-level files (`~/.claude/CLAUDE.md`, `~/.claude/rules/`) against project files. They load first, so the project rule wins.

## Step 4: name the winner

For each confirmed conflict, state which rule wins and why, using the load order:

1. Output style (system prompt), then user `CLAUDE.md`, then user rules.
2. Project `CLAUDE.md` and `.claude/CLAUDE.md`, then `CLAUDE.local.md`. An `@import` is inlined at the line of the import.
3. Unscoped `.claude/rules/*.md`.
4. Nested `CLAUDE.md` files, deeper ones later, loaded when the agent reads files there.
5. Path-scoped rules, loaded when a matching file is read.
6. Skills, agents, commands, on invocation.

Inside one file, the later line wins. The script names the winner using this order; keep its answer unless a file it did not see changes the order.

## Step 5: resolve

Pick one resolution per conflict:

- Delete the losing rule when it no longer describes what the team wants.
- Rewrite both as one rule with an explicit exception, general rule first, exception after it, scope named: `Write a pytest test for every function under src/. Scripts under scratchpad/ ship without tests.`
- Move the exception into a path-scoped rule (`.claude/rules/<topic>.md` with `paths:`) so it loads only where it applies, and keep the general rule where it is.

Never resolve by bolding, capitalizing, repeating, or moving the losing rule lower. Emphasis does not enter into which rule the model follows, and reordering leaves the contradiction in the file.

## Step 6: report

Lead with the count of confirmed conflicts in the first sentence. Then one table:

| # | subject | rule A (file:line) | rule B (file:line) | task where they collide | winner today | resolution |

Then the dismissed candidates, one line each. Then the proposed edits as a list, one per conflict, with the exact replacement text.

## Fix mode

Only when the arguments contain `fix`:

1. Apply each resolution with Edit. Touch only the files listed in the Surfaces table.
2. Re-run the checker with `--only conflicts` and report the remaining candidates. Dismissed candidates that remain are expected; confirmed conflicts must be zero.
3. List every deleted or rewritten rule as `file:line` plus its previous text.

## Surfaces to cover

`CLAUDE.md`, `.claude/CLAUDE.md`, `CLAUDE.local.md`, nested `CLAUDE.md` in subdirectories, `@imports`, `.claude/rules/**/*.md`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`, `.claude/commands/**/*.md`, `.claude/output-styles/*.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules`, `.cursor/rules/**`, `.github/copilot-instructions.md`, `.github/instructions/**`, `.windsurfrules`, `.windsurf/rules/**`, `.clinerules`, `.devin/rules/**`, `.roo/rules/**`, `.junie/guidelines.md`, `prompts/**`, plus `~/.claude/CLAUDE.md` and `~/.claude/rules/**`.

## Boundaries

- A static read tells you which rules cannot both hold. It cannot tell you which rule fired on a given turn or whether a rule went stale against the code. Say so if the user asks for either.
- Do not delete a rule from a skill or agent body without saying which invocation loses it.
- Do not edit hooks or settings; a conflict between a prose rule and a hook is not a conflict, the hook wins.
