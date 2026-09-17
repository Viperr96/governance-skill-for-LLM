# What each check measures

Source of the method: three articles by Gábor Mészáros (Reporails) on Opus 5 instruction behavior, plus the Claude Code memory and hooks docs. Each check is a property of the text with a definite answer; none needs a model run.

## bloat

Measures the share of words that sit inside a directive (a rule) versus everything else: headings, prose that describes, code fences, tables, tree diagrams, descriptive lists. Across ~30,000 public repositories only ~27% of an instruction file is instruction.

Flags:
- Always-on file over the line budget (default 200). Longer files cost context every turn and reduce adherence.
- Sections whose heading reads like documentation the agent can derive from the repository: project structure, tech stack, dependencies, architecture, overview. This is what `/doctor` trims.
- Directory tree diagrams.
- Files that are more than a third fenced code.
- Lists where most items describe rather than instruct.

Fix: cut derivable content. Keep pitfalls, rationale, and conventions that differ from the tool default. Move procedures to skills and path-specific rules to `.claude/rules/` with a `paths:` list.

## specificity

A rule binds when it names the construct it is about. `Format with ruff format before committing` is followed at roughly a 10.9x odds ratio over `keep the code clean`. On Opus 5 a vague rule fires on unrelated tasks, and the model fills the gap with its own judgment.

Flags:
- warn: a vague term (clean, proper, appropriate, best practices, careful, high quality, as needed, ...) with no concrete token (code span, path, file, identifier, tool, number with unit, constant, quoted literal, naming scheme, named technology).
- info: no vague term but also no concrete token or domain noun.

Fix: name the tool, path, pattern, or number. Or delete the rule.

## inverted

Rule classes that the Opus 5 generation over-obeys or that stopped helping.

| class | why | fix |
|---|---|---|
| verification | the model verifies its own work by default; these lines cause over-verification | delete; use a held-out test or hook instead |
| hedge (`be conservative`, `only report high-severity`) | followed literally; the model under-reports | ask for everything, filter in a second pass |
| thinking (`think step by step`, `do not think`) | written for older models; effort lives in settings | delete unless measured |
| effort / budgets in prose | belong in settings; a 4.8 value stays live on Opus 5 | re-run an effort sweep |
| brevity-no-shape (`be concise`) | names nothing to bind to | reply-shape rule, output style, or Stop hook |
| model-vintage | mentions an older model | re-test on the current model |
| emphasis (CAPS, bold, !!) | emphasis never resolves a conflict or a vague rule | remove; check conflicts on the same subject |

Emphasis means a shouted word (IMPORTANT, NEVER, ALWAYS, ...), a fully bold sentence, `!!`, or two or more unknown four-letter capitals in one rule. A bold header (`**Plan**`, `- **Pull**`, `2. **Report back:**`) is scaffold, with or without a list marker, and is never a rule. Domain acronyms (ARPU, ARPPU) look like shouting to a generic list; name them once with `--acronyms ARPU,ARPPU` or in `.instruction-audit.json` as `{"acronyms": ["ARPU", "ARPPU"]}` at the project root.

## placement

A rule loads where it applies. A rule about `src/payments/` on the always-on surface taxes every unrelated turn and, on Opus 5, fires there.

Flags:
- A rule on an always-on surface (root CLAUDE.md, unscoped `.claude/rules`, user CLAUDE.md, `.cursorrules`, copilot instructions) that names an existing directory or a glob.
- Skills and agents without a `description`, or with a description over 1536 characters (the listing truncates there).
- SKILL.md over 500 lines (move reference material into linked files).

Fix: `.claude/rules/<topic>.md` with `paths: ["<dir>/**"]`, or `<dir>/CLAUDE.md`, which loads only when the agent reads files there.

## conflicts

Two rules that cannot both hold do not average out. The model commits to one and drops the other, silently. Position decides: the rule read later governs (about a 90-point swing in a controlled experiment when one rule moved from top to bottom). Opus 5 commits harder than 4.x, so the run-to-run flakiness that used to expose a conflict is gone.

The script narrows candidates deterministically:
- both rules touch the same subject (tests, mocks, dependencies, git, formatting, types, comments, docs, errors, logging, verbosity, questions, scope, files, secrets, performance, naming, imports, async, database, api, ui, subagents, verification, planning, language, security, build, commands, editing, completion), and
- they have opposite polarity, or one carries an exception marker, or they name exclusive alternatives (npm vs pnpm, tabs vs spaces, jest vs vitest, ...).

Polarity is `pos` (an explicit modal such as must/always/every/required), `imperative` (a leading imperative verb with no modal), `neg` (never/do not/without, which wins over a positive modal in the same sentence), `mixed` (a positive modal and a negation together), or `neutral` (a plain declarative with neither). `pos` against `neg` counts as opposite. `Verify no circular references`, `Check that there are no orphan rows`, `Ensure no secrets reach the log` command a check: the `no` names what is checked for, and the sentence is a bare imperative, not a prohibition. `imperative` against `neg` counts only when both bind the same verb (`Ask for confirmation` against `Never ask for confirmation`); `Follow the spec` is not the opposite of `Never edit knowledge/` just because one has a `never` in it, and the `neg` side must actually prohibit that verb with a leading never/do not/avoid (`Push the tag, not the branch` commands push). Polarity is read on the main clause only: a negation or modal inside a trailing `when` / `if` / `only when` / `unless` / `before` clause states the condition, not the directive, so `Push back when the conclusion is not supported` and `Pull rows only when a distribution is required` are both bare imperatives. A question is never a party to a conflict; it states no obligation. `only` is not a modal at all: it restricts an obligation rather than stating one. An exception marker is a construction (except, unless, but not, optional, as needed), not a bare `can` or `may`.

A sentence that names both alternatives (`Do not format with black; use ruff format`) counts as choosing the one that is not under the negation. Two rules written next to each other under one heading are skipped only when one of them carries an exception marker (a rule and its scoped exception); adjacent flat contradictions are scored like any other pair.

Subjects are matched with domain context where the word is a homograph: `push back` is argument, not `git`; `merge the datasets` is data work, not a branch merge; `commit to a visual motif` is a decision, `commit to main` is `git`; bare `scope` (`scope context`, `scope it tightly`) is not the change-scope subject, `expand the scope` and `out of scope` are.

What is not a rule: anything under a heading named Overview, Resources, References, Key references, Further reading, See also, Related skills, Scripts, Files, Examples, or Changelog, whatever modal the prose uses; and a list item that opens with a backticked path followed by a dash or colon (`` `scripts/power.py` — unified interface ``), which names a file rather than instructing. Two items of one checklist inside a skill (same heading, both list items) are steps, never rivals, and are not paired.

Precedence pairs: two rules that each name a winner for one decision conflict whatever their polarity. `constants.yaml takes precedence over the table` and `the markdown table is the canonical source` are both positive and cannot both hold. The script pairs any two rules that carry precedence vocabulary (`canonical`, `source of truth`, `authoritative`, `takes precedence`, `governs`, `overrides`, `wins`, `defer to`, `ranks above`, `prefer X over Y`, `when sources disagree`, `in case of conflict`) and share a domain noun that is not that vocabulary. A precedence statement counts as a rule even without a modal. This is the only detector that ignores polarity.

Severity `error` needs semantic evidence: exclusive alternatives, or opposite polarity plus shared terms or a second shared subject, and both sides always on. Severity `warn` needs exclusive alternatives, or opposite polarity plus an exception marker plus two shared terms. Opposite polarity plus one shared word is `info`: on a real project every such pair was a keyword collision (`errors` in "standard error" and "Excel errors"; `tests` in "A/B tests" and "one-sided test"), so it is listed for the reader and not graded. Shared vocabulary and the fact that two always-on files exist never reach `error` on their own. A pair whose only signal is polarity, with no shared terms and a single shared subject, is not reported. When one file `@import`s the other, the pair is one authored unit split across files: it scores exactly as it would in a single file, and the note says so. Moving rules across an `@import` boundary never changes severity. In a `--only conflicts` run the header line says `Candidates:`, because the counts are pairs to test, not a verdict.

Co-load classes:
- always: both always on for the same tool. The output style that `outputStyle` selects in `settings.json` or `settings.local.json` is always on (`always (outputStyle in settings.json)` in the Surfaces table); a style file nobody selected is `when selected (/output-style)` and on-demand.
- on-demand: one lives in a nested CLAUDE.md, a path-scoped rule, a skill, an agent, or an unselected output style. The conflict exists only on those turns.
- separate-invocations: two skills, agents, or commands. They have no fixed relative order, so the winner is `depends on invocation order`. Always `info`.
- same-procedure: two rules in one skill or agent body. Usually sequencing. Always `info`.
- cross-tool: different tools (`.cursorrules` vs `CLAUDE.md`). Drift rather than a co-load conflict, unless `CLAUDE.md` imports the other file. Winner `none`. Always `info`.
- disabled: one side is a skill `skillOverrides` sets to `"off"`. Such rules are not paired at all unless `--include-disabled` is given; then the pair is `info` with winner `none`.

Recency winner: the rule with the higher load rank, then the later position. Load order used: the selected output style, user CLAUDE.md, user rules, project CLAUDE.md and other root files, CLAUDE.local.md, unscoped project rules, nested CLAUDE.md (deeper later), path-scoped rules, skills and agents. Inside a file, a later line wins. An `@import` is inlined at the import line.

The rank is position, not authority. An output style is the earliest text in the context (it replaces the default system-prompt section), so under recency a CLAUDE.md rule on the same subject is read after it and wins the tie. `/fix-verbose-output` calls the style the stronger lever for a different reason: it displaces the default instructions the reply-shape rule would otherwise compete with, rather than out-ranking CLAUDE.md. Both hold; keep the two copies of a reply-shape rule identical, and this check reports them when they drift.

The judgment the script cannot make: whether the two rules can both hold for one concrete task. Answer that per pair. Where they cannot, fix by deleting one, or by writing one rule with an explicit exception placed after the general rule and scoped to a path. Never by bolding, repeating, or reordering.

## enforcement

Prompts steer; hooks enforce. A rule shaped like a gate (never force-push, do not edit `migrations/`, run tests before commit, reply under 180 words, ask before installing) is still only steering unless a hook or permission rule backs it. A model upgrade never retires a gate.

Flags:
- warn: enforcement-shaped rule with no matching hook or permission rule in `.claude/settings.json`, `.claude/settings.local.json`, or `~/.claude/settings.json`, and no git pre-commit hook for step-before-commit rules.
- info: enforcement-shaped rule that a hook or deny rule possibly covers. Confirm the gate covers the exact case.
- error: a hook whose command points at a script that does not exist, or a settings file that does not parse.
- error (warn on an on-demand surface): a rule that names a skill (`` `polars` ``, `/polars`, `the polars skill`) which `skillOverrides` sets to `"off"` in a settings file. The rule cannot be followed.
- warn: a skill under `.claude/skills/` that `skillOverrides` sets to `"off"`. The Surfaces table lists it as `never (skillOverrides off)`. Anything in settings that decides whether a surface loads belongs to an audit of what loads.

| rule class | lever |
|---|---|
| destructive command | `permissions.deny` `Bash(<pattern>)`, or a PreToolUse hook on Bash |
| protected path | `permissions.deny` `Edit(<glob>)` and `Write(<glob>)`, or a PreToolUse hook on Edit and Write |
| protected branch | deny `Bash(git push*main*)` plus remote branch protection |
| step before commit | a git pre-commit hook (pre-commit, husky, lefthook), or a PreToolUse hook matching `git commit` |
| step after edit | a PostToolUse hook on Edit and Write |
| secrets | deny `Read(./.env)` and friends, plus a pre-commit secret scanner |
| length cap | a Stop hook counting words in `last_assistant_message`, exit 2 to send the reply back |
| approval gate | `permissions.ask`, or a PreToolUse hook returning `permissionDecision: ask` |

`/instruction-enforce` generates these from templates.
