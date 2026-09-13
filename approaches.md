# Main approaches extracted from the three articles

Source: three DEV Community articles by Gábor Mészáros (Reporails), saved as `.mhtml` in this folder.

---

## 1. "Opus 5: Delete your CLAUDE.md?"

**What changed.** Boris Cherny (Claude Code) recommends deleting CLAUDE.md, skills and hooks every six months and seeing what the model does. Anthropic cut over 80% of Claude Code's own system prompt for Opus 5 by ablation: delete everything, add lines back one at a time, measure each.

**Why old instruction files regress on Opus 5** (three compounding mechanisms):

1. **Wider instruction retrieval.** Vague rules that used to sit dormant now fire on tasks they were never written for. With nothing concrete to bind to, the model fills the gap with its own judgment.
2. **Built-in self-verification (LLM-as-a-judge).** Old `double-check` / `verify` lines stack on top and cause over-verification.
3. **Long-horizon (auto mode) tasks.** The longer the trace, the more the model's own steps crowd out your instructions. The weakest rules go first.

**The numbers.** Only ~27% of a typical instruction file is instruction; ~73% is scaffolding (headings, restated context, examples, prose). 89.9% of configs carry at least one rule that names nothing concrete. A rule that names its exact construct is followed with a ~10.9x odds ratio over the same rule stated as a category.

**Why blind deletion is a blunt tool.** Ablation only catches defects that fail loudly. Two of the three defects fail silently and get rebuilt unchanged:

- **Low specificity** underperforms silently (followed sometimes, not others).
- **Conflicts** resolve silently (the model follows one rule, drops the other).
- Only **bloat** is what deletion actually fixes.

Also a category error: **hooks and deny rules are deterministic gates, not steering.** A model upgrade never retires them. "Prompts steer, hooks enforce."

**Symptom → fix table (Opus 5):**

| Symptom | Fix |
|---|---|
| Long answers | Instruct brevity per surface and name the shape; `effort` does not change output length |
| Scope creep | State scope in one line; the only enforceable slice is a write-path allowlist |
| Over-obeying a limiter (`be conservative`, `only report high-severity`) | Ask for everything, filter in a second pass |
| Compulsive self-checking | Delete `double-check` / `use a subagent to verify` lines |
| Old 4.x instructions misfiring | Do not wipe by vintage; target the inverted classes: verification prompts, hedges, `do not think` rules, effort defaults |
| Thrashing on conflicting rules | Find same-subject pairs that cannot both hold; remove one; reordering does not fix it |
| Vague rule firing on unrelated tasks | Name its construct or scope it to a path |
| Over-eager subagents | Cap; delegate only large independent tracks; never a subagent to verify own work |
| Confident wrong "done" | Have it state assumptions; re-run the goal against a held-out check it cannot edit |
| Effort carried over from 4.8 | Re-run an effort sweep; Opus 5 defaults `high`, adds `xhigh` |

**How to write a rule that binds** (one instruction per line, imperative, names the construct):

1. Lead with the directive and name the exact construct to use.
2. Add one line of reasoning that does not re-name the thing being banned.
3. Put any prohibition last, phrased at the category level (naming the forbidden API anchors the model on it).

**Four properties of rules worth keeping** (all checkable without running a model):

- Names a construct (`Format with ruff format before committing`, not `keep the code clean`).
- Does not contradict another rule.
- Loads where it applies (a `src/payments/` rule lives in a file scoped to `src/payments/`).
- Is behavior you want enforced, not documentation the model can read off the codebase.

Rule count is irrelevant; quality is not.

**Process.** Run `/doctor` (trims derivable content: directory layouts, dependency lists, architecture overviews; keeps pitfalls and conventions that differ from defaults). Then run a **deterministic checker** over what is left and fix the vague and conflicting rules. Do not ask the model to grade its own rules; those properties have definite answers.

---

## 2. "Opus 5: How to Fix Verbose Output"

**Four levers, weakest first.** Reach for the least that holds.

1. **CLAUDE.md rule.** Weakest: it is advice competing with everything else in context. `Be concise` names nothing; name the **shape** instead:
   - Lead with the answer in the first sentence.
   - Carry multi-item results in a table or bullet list, never a prose paragraph.
   - Cap unbroken prose at two paragraphs.
   - One item per bullet row.
   - Compose in this shape from the start.
   (A short confirmation like `Done.` is already the answer; do not tabulate it.)
2. **Output style** (`.claude/output-styles/<name>.md` with `name`, `description`, `keep-coding-instructions: true` frontmatter). Lands in the system prompt and is re-surfaced during the session, so it decays less. Select under `/config`; takes effect after `/clear`.
3. **Stop hook** (`.claude/hooks/gate-length.sh` plus `hooks.Stop` in `.claude/settings.json`). Reads `last_assistant_message` from stdin; on overflow, `exit 2` with a stderr message blocks the stop and sends the reply back to be rewritten. The only lever that can **refuse**.
4. **Plugin** (`.claude-plugin/plugin.json`). Adds no strength; bundles rule, style and hook so the setup travels across projects.

**Principle.** The levers decide what the model holds when it answers and whether anything checks the answer after it lands. Instruction can be set aside; a hook cannot.

---

## 3. "Opus 5: The Cost of Instruction Conflicts"

**Conflicts resolve silently.** Two rules that cannot both hold do not cancel; the model commits to one and the other reads as if it were never written. No warning is ever surfaced.

**Position decides.** In a controlled experiment, moving one rule from the top of the file to the bottom swung compliance by ~90 points. The most recently read instruction governs (recency). Naming the exact target (a path, a function) adds weight, but position still wins.

**Opus 5 commits harder.** 4.x flip-flopped between the two rules run to run, which was the only visible symptom. Opus 5 picks the same rule every run, so the symptom disappears and the losing rule goes permanently silent.

**Where conflicts hide** (almost never `do X` next to `do not X`):

- Different headings, same subject ("Testing" vs "Prototyping workflow").
- Different vocabulary for the same thing ("never use mocks" vs "wrap external calls in a fake").
- A general rule plus a specific exception written as if it were a new topic.
- Root `CLAUDE.md` vs nested `src/CLAUDE.md` (the conflict only exists when the agent is in `src/`).
- `@path` imports are inlined at the import position; skills, rules, agents and memory follow the same recency logic.

**Emphasis does not help.** Bolding, caps, or repeating the losing rule does nothing, because the problem is a competing rule, not emphasis.

**What a static read can and cannot do.** It can find same-subject pairs that cannot both hold (a satisfiability check over the text, no model needed). It cannot tell you which rule fired on a given turn, or whether a rule went stale against the code.

**Method.** Do not read top to bottom (that is how the conflict got in). Group every rule by subject (tests, dependencies, what ships without review, ...) and hold each same-subject pair against the others: can both be true at once? Formalizing rules (subject, predicate, scope) and progressive disclosure make this check easy.

---

## What the skills in `.claude/skills/` do with this

| Skill | Built from | Job |
|---|---|---|
| `instruction-audit` | Article 1 (plus 2 and 3) | Discover every instruction surface, run the deterministic checker (bloat, specificity, inverted classes, placement, conflict candidates, ungated enforcement), report, and optionally fix |
| `instruction-conflicts` | Article 3 | Deep same-subject satisfiability pass across files, with the recency winner named |
| `instruction-enforce` | Article 2 (plus "prompts steer, hooks enforce") | Pick the weakest lever that holds for a behavior and generate the rule, output style, deny rule, hook, or plugin |
| `fix-verbose-output` | Article 2, end to end | Inject the article's exact setup into a project in one run: delete vague brevity lines; write the Reply shape rules once, as the output style (selected via `outputStyle`) with a pointer line in CLAUDE.md, or as a CLAUDE.md section at `rule` level; ask once, on first install, whether to add the length-gating Stop hook; optionally build the plugin bundle. Cumulative levels, idempotent, every removed line listed |
