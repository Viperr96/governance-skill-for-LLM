# The four levers for verbose output

From "Opus 5: How to Fix Verbose Output" (Gábor Mészáros, Reporails), with the Claude Code details checked against the docs.

## The problem

`Be concise. No preamble.` sat near the top of CLAUDE.md for a year. On 4.x it mostly held. On Opus 5 the model reaches for more rules at once and checks its own work by default, so a line that names nothing gets crowded out. The fix is not emphasis; it is naming the shape and, when that is not enough, putting something after the reply that can refuse it.

## Weakest first

| lever | where it lands | can it refuse | reach for it when |
|---|---|---|---|
| CLAUDE.md rule | a user message after the system prompt, every session | no | a human should read the rule too |
| output style | appended to the system prompt; Claude Code re-reminds the model of it during the session | no | you want the model leaning terser by default |
| Stop hook (optional) | a script the harness runs when the turn ends; exit 2 sends the reply back | yes | you want a floor on length the model cannot talk past |
| plugin | bundles style and hook | no (it carries them) | you are tired of setting the others up in every repo |

The three real levers are one move underneath: they decide what the model is holding when it answers, and whether anything checks the answer after it lands.

## 1. The rule

`Be concise` fails because it names nothing. A rule that names the shape does better. The paste-ready section:

```markdown
## Reply shape
- Lead with the answer in the first sentence, before any table, list, or caveat.
- Carry status, comparisons, and any multi-item result in a `table` or `bullet` list, never a prose paragraph.
- Cap unbroken prose at two paragraphs; if a third starts, convert the run to a `bullet` list or `table`.
- Give each item its own `bullet` row, not a clause buried across sentences.
- Compose in this shape from the start; do not draft prose and reshape it afterward.
```

One caveat: a short confirmation is already the answer. `Done.` or `Yes, that works.` should not be tabulated. The rule is about shape when there is something to shape; the template carries that as a sixth line.

Even this tight, a CLAUDE.md line is advice competing with everything else the model holds. Write it, but do not expect it to hold on its own. The installer appends it at the end of the file, because the later rule wins under recency, and deletes the vague lines it replaces so there is no competing instruction on the same subject.

## 2. The output style

An output style modifies the system prompt itself; Claude Code adds the style's instructions to the end of that prompt and reminds the model of the active style during the conversation, so the rule is re-surfaced rather than decaying after one appearance.

File: `.claude/output-styles/reply-shape.md` (project) or `~/.claude/output-styles/` (user).

```markdown
---
name: Reply shape
description: "Answer-first, scannable replies; tables and bullets over prose walls"
keep-coding-instructions: true
---

(the same lines as the rule)
```

- `keep-coding-instructions: true` keeps Claude Code's built-in engineering behavior and changes only how it communicates. Without it the style replaces the coding instructions.
- `name` is the value the `outputStyle` setting uses; the file name is the fallback.
- Selection: `/config` then **Output style**. The menu writes `outputStyle` to `.claude/settings.local.json`. The installer writes it to `.claude/settings.json` instead so it travels with the repository; a value in `settings.local.json` overrides it.
- The standalone `/output-style` command was removed; it lives under `/config`.
- Style files are read at startup. A file created during a session needs a restart. Once loaded, switching styles applies from the next message (before v2.1.251 it needed `/clear`).
- Claude Code also ships a built-in `Concise` style. It is a reasonable alternative when you do not need the exact shape.

Still instruction, so the model can still drift, but it drifts less than from a line buried in a file.

## 3. The Stop hook

The rule and the style are both instruction, and the model can weigh instruction and set it aside. A hook is a script the harness runs at a fixed moment, and it can refuse.

Claude Code fires `Stop` when the model finishes a turn and hands the finished reply on stdin as `last_assistant_message`. Exit 2 blocks the stop; the stderr line goes back to the model as its instruction, and it answers again.

Stdin fields that matter:

```json
{
  "hook_event_name": "Stop",
  "stop_reason": "end_turn",
  "last_assistant_message": "…the finished reply…",
  "stop_hook_active": true
}
```

- `stop_hook_active` is true when the turn is already continuing because a Stop hook blocked once. Return 0 on it to send a reply back at most once per turn.
- Claude Code caps any Stop hook at five consecutive blocks, then lets the turn end. It cannot loop forever.
- `Stop` takes no matcher.

Wiring in `.claude/settings.json`:

```json
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/gate_length.py\"" } ] }
    ]
  }
}
```

`${CLAUDE_PROJECT_DIR}` is the project root where the session started. Edits to hooks in settings files are picked up by the file watcher; `/hooks` lists what is active.

The article's original is a bash script with `jq` (`templates/gate-length.sh`). The installer defaults to the Python version (`templates/gate_length.py`) because it needs no `jq` and runs on Windows; the logic is the same.

Tuning the bar, all in the hook file:

- `LIMIT_WORDS`: the budget. 180 is the article's number.
- `COUNT_CODE`, `COUNT_TABLES`: whether fenced code and table rows count. Off by default, since the shape rule pushes content into those.
- `SHORT_OK`: replies that are already the answer (`Done.`, `Yes.`).
- Swap the word count for a line count, or a regex for opening filler (`Great question`, `Sure, I can`), if that is what you want to refuse.

## 4. The plugin

A plugin adds no strength. It bundles the style and the hook so the setup travels instead of being re-pasted into each repo.

```
reply-shape-plugin/
  .claude-plugin/plugin.json
  hooks/hooks.json            # same shape as the "hooks" object in settings.json
  hooks/gate_length.py
  output-styles/reply-shape.md
  README.md                   # carries the CLAUDE.md rule for pasting
```

- Inside `hooks.json` reference scripts with `${CLAUDE_PLUGIN_ROOT}`, the plugin's install directory.
- `output-styles/` is a supported plugin folder. Add `force-for-plugin: true` to the style's frontmatter to apply it whenever the plugin is enabled, overriding the user's `outputStyle` setting. The installer leaves that off so the user keeps the choice.
- Test with `claude --plugin-dir ./reply-shape-plugin`. Install from a marketplace with `/plugin install` once published.

## Which one to reach for

A CLAUDE.md rule for the parts a human reads too. An output style when you want the model leaning terser by default. The hook when you want a floor on length the model cannot talk its way past. A plugin once you are tired of setting those up again in every repo. The installer's default, `style`, installs the rule and the style. The hook is opt-in: the skill asks once, on the first install in a project, and `--level hook` adds it any time later. It is the only lever that runs after every turn and can send a reply back, so it stays the user's call.

The harder version of this problem is which of your rules the model follows once you have a hundred that quietly disagree; that is `/instruction-conflicts`.
