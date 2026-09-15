---
name: instruction-audit
description: Audit the instruction files that steer an LLM-driven project (CLAUDE.md, AGENTS.md, .cursorrules, copilot-instructions, .claude/rules, skills, agents, output styles, hooks and permission rules) for bloat, vague rules, rule classes that Opus 5 inverts, misplaced rules, conflicting rules, and enforcement written as prose. Runs a deterministic checker first and applies judgment only where the text has no definite answer. Reports findings with file:line and a fix per finding. Edits files only when invoked with "fix". Use when asked to check, review, audit, lint, rightsize, clean up, or shrink CLAUDE.md, agent instructions, prompts, or agent documentation; after a model upgrade; or when the agent ignores rules, over-verifies, over-explains, or thrashes between rules.
argument-hint: "[path] [fix] [--no-user]"
allowed-tools: Bash(python *) Bash(python3 *) Bash(py *) Read Glob Grep
---

# Instruction audit

Audit every instruction surface an LLM agent loads for this project. Report what binds, what is dead weight, and what fights another rule. The script measures the deterministic properties; you judge only what the text cannot settle.

Arguments received: `$ARGUMENTS`

- A token that is an existing directory is the project root. Default: the current working directory.
- `fix`: apply fixes after reporting. Without it, report only.
- `--no-user`: skip `~/.claude/CLAUDE.md`, `~/.claude/rules/` and user settings.

## Step 1: run the deterministic checker

Run this once, with the root resolved to an absolute path:

```
python "${CLAUDE_SKILL_DIR}/scripts/audit_instructions.py" "<root>" --rules --json-out "<scratchpad>/instruction-audit.json"
```

- Use `py -3` on Windows if `python` is not on PATH, and `python3` on macOS or Linux.
- Pass `--no-user` through when the user gave it.
- Skills installed from a plugin or marketplace (`docx`, `pptx`, `xlsx`, and other bundles the user did not write; a `license:` key in the SKILL.md frontmatter or a LICENSE file beside it is the usual sign) are not the user's to edit. Pass `--exclude ".claude/skills/<name>/**"` once per such skill so their findings do not crowd the report.
- If the project's vocabulary has acronyms the `emphasis` class mistakes for shouting (two metric names in one sentence), pass `--acronyms A,B` once, or tell the user a `.instruction-audit.json` with `{"acronyms": [...]}` at the root makes it stick.
- If the script is missing, stop and report the expected path. Do not reimplement the checks by hand.
- Read the markdown it prints in full. The Surfaces table lists every file the audit covers; the findings carry `file:line`.

The script does not run any model and returns the same result for the same input. Treat its numbers (instruction share, counts, which rule wins under recency) as the numbers. Do not re-score them by judgment.

## Step 2: judge only what the script flagged

Work through the findings by check. For each one write a one-line decision. The checks and their meaning are in [reference/checks.md](reference/checks.md).

- **conflicts**: for each candidate pair, name one concrete task on which following rule A forbids what rule B requires. If no such task exists, dismiss the pair in one line. If it exists, the pair is confirmed: state the winner the script named and propose one rewrite (an explicit exception placed after the general rule and scoped to a path) or one deletion.
- **enforcement** with no gate: name the lever from [reference/checks.md](reference/checks.md) and point to `/instruction-enforce` for generation. Keep the prose rule as a one-line note for humans.
- **specificity**: rewrite each vague rule in the three-line shape from [reference/rule-writing.md](reference/rule-writing.md), naming the tool, path, pattern, or number. If the rule restates something a config file in the repo already enforces (`.prettierrc`, `ruff.toml`, `tsconfig.json`, `.editorconfig`), mark it derivable and propose deletion.
- **inverted**: recommend delete, keep, or rewrite per the class advice in the finding. Default to delete for verification and hedge classes.
- **placement**: name the target file: `.claude/rules/<topic>.md` with a `paths:` list, or `<dir>/CLAUDE.md`.
- **bloat**: list the sections to cut. Keep pitfalls and conventions that differ from tool defaults.

Add what the script cannot see, using Glob and Read on the repository:

- A rule that names a path, script, or command that no longer exists is stale. Verify each path-bearing rule with Glob before keeping it.
- A rule that describes the codebase (framework, layout, dependencies) rather than constraining behavior is documentation. Propose deletion.
- A skill or agent whose body repeats rules already in CLAUDE.md is duplicated steering. Propose keeping one copy.

## Step 3: report

Lead with the verdict in the first sentence, then the counts table from the script. Then list findings grouped by severity as bullets with `file:line`, the rule text, and the decision. End with a fix list ordered: conflicts, ungated enforcement, vague rules, inverted classes, placement, bloat.

Keep dismissed conflict candidates to one line each. Do not paste the script output verbatim; the user can open the JSON.

## Step 4: fix mode

Only when the arguments contain `fix`.

1. Apply in this order: confirmed conflicts, inverted-class deletions, vague-rule rewrites, placement moves, bloat cuts.
2. Edit only files listed in the Surfaces table. Do not edit hook scripts, `settings.json`, permission rules, CI config, or git hooks. Gates outlive model upgrades. A `dead-skill` finding is fixed on the rule side (drop the skill name) unless the user says to re-enable the skill; a `disabled-skill` finding is the user's call.
3. Before deleting a rule that names a path, command, or number, confirm with Glob or Read that it is derivable or stale. Otherwise keep it.
4. When moving a rule to `.claude/rules/<topic>.md`, write the `paths:` frontmatter and delete the original line.
5. Re-run the script and show a before/after table: files, lines, instruction share, findings per check.
6. List every deleted rule as `file:line` plus its text so the user can restore any of them.

## Boundaries

- Do not ask the model, yourself included, to grade specificity or instruction share. Those are the script's numbers.
- Do not delete hooks, deny rules, or CI checks, whatever the model can now do on its own.
- Do not add lines that tell the model to re-examine its own work; those are the inverted class this audit removes.
- Do not resolve a conflict by bolding, repeating, or reordering a rule.
- Do not touch files outside the Surfaces table.
