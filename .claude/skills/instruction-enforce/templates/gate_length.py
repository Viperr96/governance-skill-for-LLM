#!/usr/bin/env python3
"""Stop hook: send an over-long reply back once to be tightened.

Wire it in .claude/settings.json:

  "hooks": { "Stop": [ { "hooks": [
      { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/gate_length.py\"" }
  ] } ] }

Exit 2 blocks the stop and hands the stderr text to the model as its next instruction.
The hook lets the turn end after one rewrite (stop_hook_active), so it cannot loop.
"""
import json
import re
import sys

LIMIT_WORDS = 180          # the budget for prose words; code blocks and tables are not counted
COUNT_TABLES = False       # set True to count table rows against the budget
SHORT_OK = re.compile(r"^\s*(?:done|yes|no|ok|okay|correct)[.!]?\s*$", re.I)


def prose_words(reply: str) -> int:
    text = re.sub(r"```.*?```", " ", reply, flags=re.S)
    if not COUNT_TABLES:
        text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("|"))
    return len(text.split())


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("stop_hook_active"):
        return 0
    reply = data.get("last_assistant_message") or ""
    if SHORT_OK.match(reply):
        return 0
    words = prose_words(reply)
    if words <= LIMIT_WORDS:
        return 0
    sys.stderr.write(
        "Your reply ran %d prose words; the budget is %d. Rewrite it under %d words: put the answer in the first "
        "sentence, then cut the preamble, the recap of the request, and the summary of what you did. Keep code "
        "blocks and tables as they are.\n" % (words, LIMIT_WORDS, LIMIT_WORDS)
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
