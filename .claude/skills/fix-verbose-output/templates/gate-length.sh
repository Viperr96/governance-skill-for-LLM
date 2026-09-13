#!/usr/bin/env bash
# Stop hook: if the reply ran long, send it back once to tighten up.
# This is the article's original; it needs bash and jq. The Python
# version (gate_length.py) does the same job without jq and runs on Windows.

# The Stop event hands us the finished reply on stdin.
input="$(cat)"
reply="$(printf '%s' "$input" | jq -r '.last_assistant_message // ""')"

# Send a reply back at most once per turn.
if [ "$(printf '%s' "$input" | jq -r '.stop_hook_active // false')" = "true" ]; then
  exit 0
fi

# Your bar. Word count here; a line count or a preamble check works the same way.
limit=180
words="$(printf '%s' "$reply" | wc -w | tr -d ' ')"

if [ "$words" -gt "$limit" ]; then
  # Exit 2 blocks the stop; this line goes back to the model as its instruction.
  echo "Your reply ran ${words} words; the budget is ${limit}. Rewrite it under ${limit} words: put the answer in the first sentence, then cut the preamble, the recap, and the summary of what you did." >&2
  exit 2
fi

exit 0
