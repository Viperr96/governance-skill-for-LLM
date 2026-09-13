#!/usr/bin/env python3
"""PreToolUse hook: refuse commands and edits that match the patterns below, whatever the model decided.

Wire it in .claude/settings.json:

  "hooks": { "PreToolUse": [ { "matcher": "Bash|PowerShell|Edit|Write|MultiEdit|NotebookEdit", "hooks": [
      { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/deny_patterns.py\"" }
  ] } ] }

Prints a permissionDecision of "deny" with a reason; the harness refuses the call and shows the reason to the model.
For fixed prefixes, permissions.deny in settings.json is simpler; use this hook when a pattern needs a regex.
"""
import fnmatch
import json
import re
import sys

DENY_COMMANDS = [
    (r"\brm\s+-[A-Za-z]*r[A-Za-z]*f|\brm\s+-[A-Za-z]*f[A-Za-z]*r", "recursive force delete"),
    (r"\bgit\s+push\b[^|;&]*\s(?:--force|-f|--force-with-lease)\b", "force-push"),
    (r"\bgit\s+push\b[^|;&]*\s(?:origin\s+)?(?:main|master)\b", "push to a protected branch"),
    (r"\bgit\s+reset\s+--hard\b", "hard reset"),
    (r"\bgit\s+checkout\s+--\s|\bgit\s+restore\s", "discarding working-tree changes"),
    (r"\bgit\s+clean\b", "deleting untracked files"),
    (r"\bdrop\s+(?:table|database|schema)\b", "destructive SQL"),
]
DENY_PATHS = [
    "**/migrations/**",
    "**/*.lock",
    "**/package-lock.json",
    "**/pnpm-lock.yaml",
    "**/yarn.lock",
    "**/generated/**",
    ".env",
    ".env.*",
]


def path_matches(path: str, pattern: str) -> bool:
    p = path.replace("\\", "/")
    base = p.rsplit("/", 1)[-1]
    return fnmatch.fnmatch(p, pattern) or fnmatch.fnmatch("/" + p, pattern) or fnmatch.fnmatch(base, pattern)


def decide(tool: str, tool_input: dict):
    if tool in ("Bash", "PowerShell"):
        cmd = tool_input.get("command", "") or ""
        for pattern, label in DENY_COMMANDS:
            if re.search(pattern, cmd, re.I):
                return "Blocked: %s (matched /%s/). This gate is set in .claude/hooks/deny_patterns.py." % (label, pattern)
    elif tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        for pattern in DENY_PATHS:
            if path_matches(path, pattern):
                return "Blocked: edits under %s are not allowed (%s). This gate is set in .claude/hooks/deny_patterns.py." % (pattern, path)
    return None


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    reason = decide(data.get("tool_name", ""), data.get("tool_input") or {})
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
