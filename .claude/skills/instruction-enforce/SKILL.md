---
name: instruction-enforce
description: Turn a behavior you need from an LLM coding agent into the weakest lever that actually holds, a CLAUDE.md rule in the imperative/context/prohibition shape, an output style, a permissions deny or ask rule, a Stop or PreToolUse or PostToolUse hook, or a plugin that bundles them, and generate the files plus the settings.json wiring without clobbering existing hooks. Use when the agent is too verbose, ignores a rule, needs a hard floor or gate (never force-push, no edits under a path, tests before commit, replies under N words, ask before installing), or when an instruction audit flagged enforcement written as prose. Prompts steer; hooks enforce.
argument-hint: "<behavior to enforce> [--lever rule|style|deny|hook|plugin]"
allowed-tools: Read Glob Grep Bash(python *) Bash(python3 *) Bash(py *)
---

# Instruction enforce

A rule in `CLAUDE.md` is advice that competes with everything else the model holds. An output style rides in the system prompt and decays less. A permission rule or a hook is a gate: the harness runs it at a fixed moment and it can refuse. Reach for the least that holds, and never delete a gate because the model got smarter.

Behavior to enforce: `$ARGUMENTS`

If the arguments are empty, ask for the behavior in one line and stop.

## Step 1: classify the behavior and pick the lever

| behavior class | example | default lever |
|---|---|---|
| communication shape | answer first, no preamble, tables for lists | output style (`.claude/output-styles/`) plus a three-line rule for humans |
| length floor the model must not talk past | replies under 180 words | Stop hook (`templates/gate_length.py`) |
| forbidden command shape | never force-push, never `rm -rf`, never `DROP TABLE` | `permissions.deny` `Bash(<pattern>)`; PreToolUse hook (`templates/deny_patterns.py`) when the pattern needs logic |
| protected paths | no edits under `migrations/`, never touch lock files | `permissions.deny` `Edit(<glob>)` and `Write(<glob>)`; PreToolUse hook for anything conditional |
| secrets | never read or print `.env` | `permissions.deny` `Read(./.env)` and `Read(./.env.*)`; a pre-commit secret scanner |
| step at a fixed moment | format after every edit, tests before commit | PostToolUse hook on `Edit|Write`; git pre-commit hook for commits |
| approval before an action | ask before installing a dependency | `permissions.ask` `Bash(npm install *)` or a PreToolUse hook returning `ask` |
| judgment call (scope, style of reasoning, when to delegate) | stay within the files the task named | a rule only; the one enforceable slice is a write-path allowlist via deny rules |
| the same setup in every repo | all of the above, portable | plugin (`templates/plugin.json`) |

Honor `--lever` when the user passes it. Otherwise pick from the table and say why in one line.

## Step 2: generate

Templates live in `${CLAUDE_SKILL_DIR}/templates/`. Read the one you need, adapt it, and write it into the project. Hook input and output contracts are in [reference/levers.md](reference/levers.md).

**Rule.** Write it in the three-line shape: directive naming the construct, one line of reasoning that does not re-name the banned thing, prohibition last at category level. Put it under the heading in `CLAUDE.md` that already covers the subject, after any general rule it refines. Delete a vague duplicate such as `be concise` in the same file.

**Output style.** Copy `templates/reply-shape.md` to `.claude/output-styles/<name>.md`. Keep `keep-coding-instructions: true` unless the user wants to replace the engineering behavior too. Tell the user to select it under `/config` and that it takes effect after `/clear` or a new session.

**Deny or ask rule.** Read `.claude/settings.json`. Merge the new entries into `permissions.deny` or `permissions.ask` without removing existing entries. Write the file back with two-space indentation.

**Hook.** Copy `templates/gate_length.py` or `templates/deny_patterns.py` to `.claude/hooks/`, edit the constants at the top (word limit, denied patterns, denied paths), then merge the entry from `templates/settings.hooks.json` into `.claude/settings.json`. Append to an existing event array; never replace it. Use the `python` command form from the template so the hook runs on Windows, macOS, and Linux.

**Plugin.** Create `<plugin-dir>/.claude-plugin/plugin.json` from `templates/plugin.json`, move the hooks into `<plugin-dir>/hooks/` with a `hooks.json`, and the output style and rules alongside. Tell the user to test with `claude --plugin-dir <plugin-dir>`.

## Step 3: verify the gate runs

Run each new hook once with a sample payload and confirm the exit code and output:

```
echo {"hook_event_name":"Stop","last_assistant_message":"<400 words of filler>"} | python .claude/hooks/gate_length.py ; echo exit=$?
echo {"tool_name":"Bash","tool_input":{"command":"git push --force origin main"}} | python .claude/hooks/deny_patterns.py
```

Expect exit 2 with a stderr message from the length gate, and a JSON `permissionDecision: deny` from the pattern hook. On Windows PowerShell, pipe a here-string instead of `echo`.

Then run the audit script to confirm the enforcement finding is now covered:

```
python "${CLAUDE_SKILL_DIR}/../instruction-audit/scripts/audit_instructions.py" "<root>" --only enforcement
```

## Step 4: report

First sentence: which lever, and the file it lives in. Then a short list: files created or changed with paths, how the user activates it (`/config` for a style, restart for settings hooks), and how to tune it (the constant to edit). Keep the prose rule you wrote to a one-line mention.

## Boundaries

- Do not remove or weaken an existing hook, deny rule, or CI check. Add alongside.
- Do not write a hook that calls a model to judge the output; gates are deterministic.
- Do not put the enforcement only in prose when the user asked for a floor or a gate.
- Do not edit `~/.claude/settings.json` unless the user asked for a user-level gate.
