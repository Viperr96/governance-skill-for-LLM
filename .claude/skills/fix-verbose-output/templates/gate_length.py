#!/usr/bin/env python3
"""Stop hook: if the reply ran long, send it back once to tighten up.

Claude Code fires Stop when the model finishes a turn and hands the finished
reply on stdin as `last_assistant_message`. Exit 2 blocks the stop and the
stderr line goes back to the model as its next instruction.

Wired in .claude/settings.json (Stop takes no matcher):

  "hooks": { "Stop": [ { "hooks": [
      { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/gate_length.py\"" }
  ] } ] }

Tuning: edit LIMIT_WORDS. Swap prose_words() for a line count or a grep for
opening filler if that is your bar. The hook returns 0 when `stop_hook_active`
is set, so a reply is sent back at most once per turn; Claude Code also caps
any Stop hook at five consecutive blocks.
"""
import json
import re
import sys

LIMIT_WORDS = 180          # the budget for prose words
COUNT_CODE = False         # set True to count fenced code blocks against the budget
COUNT_TABLES = False       # set True to count table rows against the budget
SHORT_OK = re.compile(r"^\s*(?:done|yes|no|ok|okay|correct)[.!]?\s*$", re.I)


def prose_words(reply: str) -> int:
    text = reply
    if not COUNT_CODE:
        text = re.sub(r"```.*?```", " ", text, flags=re.S)
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
        "Your reply ran %d words; the budget is %d. Rewrite it under %d words: put the answer in the first "
        "sentence, then cut the preamble, the recap, and the summary of what you did. Keep code blocks and "
        "tables as they are.\n" % (words, LIMIT_WORDS, LIMIT_WORDS)
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
