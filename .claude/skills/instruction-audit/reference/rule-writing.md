# Writing a rule that binds

## The shape

One instruction per line. Imperative. Names its construct. When a rule needs a constraint, order it:

1. Lead with the directive and name the exact construct to use.
2. Add one line of reasoning. Do not re-name the thing being banned in it.
3. Put the prohibition last, phrased at the category level. Naming the forbidden API anchors the model on it, and the ban backfires.

Example:

```
- Lead every reply with the outcome: put the answer or the finding in the first sentence.
- A reader who gets the result first can act on it right away and reads the rest as support.
- Do not open with preamble, a recap of the request, or status narration.
```

## Four properties every kept rule has

- **Names a construct.** `Format with ruff format before committing`, not `keep the code clean`.
- **Does not contradict another rule.** Two rules that disagree do not average; the model follows one and drops the other, and position picks which.
- **Loads where it applies.** A rule about `src/payments/` lives in `.claude/rules/payments.md` with `paths: ["src/payments/**"]` or in `src/payments/CLAUDE.md`, not on the always-on surface.
- **Is behavior to enforce, not documentation.** Layout, dependency lists, and architecture are readable from the repository. A pitfall or a convention that differs from the tool default is not.

Rule count is not on this list. Forty rules that all name constructs and do not conflict beat eight vague ones.

## Rewrite patterns

| before | after |
|---|---|
| Keep the code clean | Run `ruff format` and `ruff check --fix` before every commit |
| Write good tests | Add a `pytest` test under `tests/` for every new public function; name it `test_<function>` |
| Be concise | Put the answer in the first sentence; carry multi-item results in a bullet list or table; cap prose at two paragraphs |
| Handle errors properly | Raise `AppError` subclasses from `src/errors.py`; never swallow an exception without logging it at `warning` |
| Follow best practices for React | Use function components with hooks; colocate a component's styles in `<Component>.module.css` |
| Always double-check your work | (delete; the model verifies by default) or: Run `npm test` before reporting a task done |
| Don't use `eval` | Parse untrusted input with `JSON.parse` inside a try block. Do not execute strings as code. |

## Exceptions

Write the general rule first and the exception after it, naming the scope:

```
- Write a `pytest` test for every function under `src/`.
- Scripts under `scratchpad/` are throwaway and ship without tests.
```

Put the exception in a path-scoped rule when the scope is a directory:

```
---
paths:
  - "scratchpad/**"
---
- Files here are throwaway: no tests, no type annotations, no review.
```

## Symptom to fix (Opus 5)

| symptom | fix |
|---|---|
| Long answers | brevity per surface, named shape; `effort` does not change length |
| Scope creep | one-line scope statement; a write-path allowlist is the only enforceable slice |
| Under-reporting after a limiter | ask for everything, filter in a second pass |
| Compulsive self-checking | delete `double-check` and `use a subagent to verify` lines |
| Old 4.x lines misfiring | target verification prompts, hedges, thinking directives, effort defaults; test each |
| Thrashing between rules | find the same-subject pair; remove one; reordering does not fix it |
| Vague rule firing everywhere | name its construct or scope it to a path |
| Over-eager subagents | cap them; delegate only large independent tracks |
| Confident wrong "done" | require stated assumptions; re-run the goal against a check the model cannot edit |
| Effort carried from 4.8 | re-run an effort sweep; low and medium hold for most work |
