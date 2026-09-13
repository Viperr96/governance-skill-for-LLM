# Levers, weakest first

| lever | where it lands | can it refuse | when to use |
|---|---|---|---|
| `CLAUDE.md` rule | user message after the system prompt, every session | no | the part a human reads too; judgment calls |
| output style | appended to the system prompt, re-surfaced during the session | no | communication defaults (shape, tone, length preference) |
| `permissions.deny` / `permissions.ask` | harness permission check before a tool runs | yes | fixed command or path patterns |
| hook | shell command at a lifecycle event | yes | anything that needs logic or reads the reply |
| plugin | bundles the above | no (carries them) | reuse across repositories |

## Hook contracts (Claude Code)

Configuration lives under `hooks` in `.claude/settings.json` (project), `.claude/settings.local.json` (personal, gitignored), or `~/.claude/settings.json` (user). Each event holds an array of groups; a group has an optional `matcher` (tool name, `Bash|Edit` alternation, or regex) and a `hooks` array of commands.

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/gate_length.py\"" } ] }
    ],
    "PreToolUse": [
      { "matcher": "Bash|Edit|Write|MultiEdit",
        "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/deny_patterns.py\"" } ] }
    ],
    "PostToolUse": [
      { "matcher": "Edit|Write",
        "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/format_after_edit.py\"" } ] }
    ]
  }
}
```

`Stop` takes no matcher. `${CLAUDE_PROJECT_DIR}` expands to the project root. Settings changes need a new session or `/hooks` to reload.

### Input (stdin JSON)

Common fields: `session_id`, `transcript_path`, `cwd`, `hook_event_name`, `permission_mode`.

- `Stop`: adds `last_assistant_message` (the finished reply) and `stop_hook_active` (true when the turn is already continuing because a Stop hook blocked once). Use `stop_hook_active` to send a reply back at most once.
- `PreToolUse` / `PostToolUse`: add `tool_name` and `tool_input` (`command` for Bash; `file_path` for Edit and Write; `content` for Write).

### Output

- Exit 0: allow. Stdout is ignored unless it is the JSON below.
- Exit 2: block. Stderr is shown to the model as the reason. On `Stop` this prevents the turn from ending and the model answers again with your message in context.
- JSON on stdout (exit 0) for a permission decision on PreToolUse:

```json
{ "hookSpecificOutput": { "hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": "Force-push is blocked in this repo." } }
```

`permissionDecision` accepts `allow`, `deny`, or `ask`.

## Permission rule syntax

```json
{
  "permissions": {
    "deny": [
      "Bash(git push --force*)",
      "Bash(git push -f*)",
      "Bash(rm -rf*)",
      "Edit(migrations/**)",
      "Write(migrations/**)",
      "Read(./.env)",
      "Read(./.env.*)"
    ],
    "ask": [
      "Bash(npm install *)",
      "Bash(pip install *)"
    ]
  }
}
```

`Bash(prefix*)` matches by prefix. `Edit`, `Write`, and `Read` take gitignore-style path patterns relative to the project.

## Output style file

```markdown
---
name: Reply shape
description: "Answer-first, scannable replies; tables and bullets over prose walls"
keep-coding-instructions: true
---

(rules)
```

Save under `.claude/output-styles/<name>.md`, pick it under `/config`, restart the session or run `/clear`.

## Plugin layout

```
my-plugin/
  .claude-plugin/plugin.json
  hooks/hooks.json          # same shape as the "hooks" object in settings.json
  hooks/gate_length.py
  skills/<name>/SKILL.md
```

Reference hook scripts with `${CLAUDE_PLUGIN_ROOT}` inside `hooks.json`. Test with `claude --plugin-dir ./my-plugin`. The Claude Code plugins docs carry the manifest fields and marketplace steps.
