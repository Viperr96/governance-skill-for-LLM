#!/usr/bin/env python3
"""
audit_instructions.py - deterministic checker for the instruction surfaces of an LLM-driven project.

Reads the files that steer coding agents and reports, without running any model:

  bloat        instruction-vs-scaffolding share, derivable documentation, oversize files
  specificity  rules that name no construct (vague terms, no concrete token)
  inverted     rule classes that Opus 5-generation models over-obey or invert
  placement    path-specific rules on an always-on surface; skills/agents without a description
  conflicts    same-subject rule pairs with opposing polarity or exclusive alternatives, with the recency winner
  enforcement  enforcement-shaped rules with no hook or permission rule behind them; broken hook commands

Surfaces discovered (project root and every subdirectory, minus build/vendor dirs):
  CLAUDE.md, .claude/CLAUDE.md, CLAUDE.local.md, @imports (4 hops), .claude/rules/**/*.md,
  .claude/skills/*/SKILL.md, .claude/agents/*.md, .claude/output-styles/*.md, .claude/commands/**/*.md,
  AGENTS.md, GEMINI.md, .cursorrules, .cursor/rules/**, .github/copilot-instructions.md,
  .github/instructions/**, .windsurfrules, .windsurf/rules/**, .clinerules(/**), .devin/rules/**,
  .roo/rules/**, .junie/guidelines.md, prompts/**/*.md|txt
  plus ~/.claude/CLAUDE.md and ~/.claude/rules/** unless --no-user
  hooks and permissions from .claude/settings.json, .claude/settings.local.json, ~/.claude/settings.json

Usage:
  python audit_instructions.py [ROOT] [--json] [--json-out FILE] [--out FILE] [--only a,b,c]
                               [--rules] [--list] [--no-user] [--include GLOB]... [--exclude GLOB]...
                               [--max-lines 200] [--max-pairs 60] [--fail-on none|warn|error]

Stdlib only. Python 3.8+. Same input, same output, every time.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

VERSION = "1.2.0"
CHECKS = ["bloat", "specificity", "inverted", "placement", "conflicts", "enforcement"]

SKIP_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "target", ".next",
    ".nuxt", "vendor", ".tox", ".mypy_cache", ".pytest_cache", ".ruff_cache", "coverage", ".idea", ".vs",
    "bin", "obj", ".cache", ".turbo", ".output", "out", "Intermediate", "Saved", "DerivedDataCache",
    "Binaries", ".gradle", ".dart_tool", "Pods", ".terraform", "site-packages",
}

# (relative file, kind) found in root and in every subdirectory; always_on decided by depth.
FILE_PATTERNS = [
    ("CLAUDE.md", "claude-md"),
    (".claude/CLAUDE.md", "claude-md"),
    ("CLAUDE.local.md", "claude-local"),
    ("AGENTS.md", "agents-md"),
    ("GEMINI.md", "gemini-md"),
    (".cursorrules", "cursor"),
    (".windsurfrules", "windsurf"),
    (".clinerules", "cline"),
    (".github/copilot-instructions.md", "copilot"),
    (".junie/guidelines.md", "junie"),
]
# (relative dir, glob, kind)
DIR_PATTERNS = [
    (".claude/rules", "*.md", "rule"),
    (".claude/skills", "SKILL.md", "skill"),
    (".claude/agents", "*.md", "agent"),
    (".claude/output-styles", "*.md", "output-style"),
    (".claude/commands", "*.md", "command"),
    (".cursor/rules", "*.mdc", "cursor-rule"),
    (".cursor/rules", "*.md", "cursor-rule"),
    (".github/instructions", "*.md", "copilot-rule"),
    (".windsurf/rules", "*.md", "windsurf-rule"),
    (".clinerules", "*.md", "cline-rule"),
    (".devin/rules", "*.md", "devin-rule"),
    (".roo/rules", "*.md", "roo-rule"),
    ("prompts", "*.md", "prompt"),
    ("prompts", "*.txt", "prompt"),
]
FAMILY = {
    "claude-md": "claude", "claude-md-nested": "claude", "claude-local": "claude", "rule": "claude",
    "skill": "claude", "agent": "claude", "output-style": "claude", "command": "claude",
    "user-claude-md": "claude", "user-rule": "claude", "import": "claude",
    "agents-md": "agents-md", "gemini-md": "gemini", "cursor": "cursor", "cursor-rule": "cursor",
    "copilot": "copilot", "copilot-rule": "copilot", "windsurf": "windsurf", "windsurf-rule": "windsurf",
    "cline": "cline", "cline-rule": "cline", "devin-rule": "devin", "roo-rule": "roo", "junie": "junie",
    "prompt": "prompt", "extra": "extra",
}
# Approximate load order for the Claude family (higher = read later = wins under recency).
LOAD_RANK = {
    "output-style": 5, "user-claude-md": 10, "user-rule": 20, "claude-md": 30, "agents-md": 30,
    "gemini-md": 30, "cursor": 30, "copilot": 30, "windsurf": 30, "cline": 30, "junie": 30, "prompt": 30,
    "extra": 30, "import": 30, "claude-local": 32, "rule": 40, "cursor-rule": 40, "copilot-rule": 40,
    "windsurf-rule": 40, "cline-rule": 40, "devin-rule": 40, "roo-rule": 40, "claude-md-nested": 50,
    "skill": 70, "agent": 70, "command": 70,
}
ALWAYS_ON_KINDS = {
    "claude-md", "claude-local", "user-claude-md", "user-rule", "rule", "agents-md", "gemini-md", "cursor",
    "copilot", "windsurf", "cline", "junie", "import",
}

# ---------------------------------------------------------------- markdown parsing
FENCE_RE = re.compile(r"^\s*(```|~~~)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+(?:\[[ xX]\]\s+)?(.*)$")
TREE_RE = re.compile(r"[├└│┌┐┘┬┴┼]|^\s*[|`]--\s")
TABLE_RE = re.compile(r"^\s*\|")
BOLD_LINE_RE = re.compile(r"^\s*(?:\*\*|__)[^*_]+(?:\*\*|__):?\s*$")
LINK_ONLY_RE = re.compile(r"^\s*(?:!?\[[^\]]*\]\([^)]*\)\s*)+$|^\s*<?https?://\S+>?\s*$")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'`(\[*_])")
IMPORT_RE = re.compile(r"(?<![\w`@/])@((?:~|\.{1,2})?/?[\w][\w./~-]*)")
CODE_SPAN_RE = re.compile(r"`[^`]*`")

MODAL_RE = re.compile(
    r"\b(?:must|should|shall|never|always|do not|don'?t|dont|avoid|prefer|required|prohibited|forbidden|"
    r"need to|needs to|has to|have to|make sure|ensure|be sure|not allowed|not permitted|instead of|rather than|"
    r"unless|except)\b|(?<![-\w])only\b", re.I)
LEAD_CLAUSE_RE = re.compile(
    r"^(?:when|if|before|after|for|unless|while|once|whenever|in|on|during|until|to)\b[^,]{0,90},\s*(.*)$", re.I)
IMPERATIVE_VERBS = set("""
use run keep write put add remove delete ensure check test follow include return call wrap name place lead cap ask
confirm commit push format lint import export log handle throw raise treat stop verify validate document update
create generate read open edit modify change move refactor split group sort order set configure install upgrade
pin limit report state explain describe list summarize summarise reply respond answer be do start end finish leave
skip ignore mark flag note remember consider try assume expect require apply respect maintain preserve store save
load fetch send emit print show display hide escape sanitize encode decode parse mock stub assert type annotate
declare define implement extend register bind map filter iterate break exit abort retry default route render
dispatch subscribe publish listen watch schedule batch stream cache memoize debounce throttle favor favour stick
pass provide give make let allow deny block reject accept close clone copy search look find locate grep scan review
inspect compare diff merge rebase squash branch tag release deploy build compile bundle serve launch spawn kill
wait poll pause resume restart reload refresh reset clear flush trim strip pad align indent quote lowercase
uppercase rename replace substitute swap toggle enable disable turn switch unset get post patch receive tell say
narrate announce mention cite reference link point refer see consult choose pick select decide determine judge
evaluate assess measure count estimate guess plan design sketch draft outline structure organize organise arrange
compose author revise rewrite polish tighten shorten expand elaborate clarify simplify minimize minimise maximize
optimize optimise tune adjust tweak fix repair debug trace profile benchmark certify approve sign stage stash pull
fork mirror sync backup restore archive destroy drop truncate wipe erase never always avoid prefer only no
prioritize prioritise delegate spin spawn cap treat keep
""".split())
NO_PREFIX_RE = re.compile(r"^no\s+\w+", re.I)

# ---------------------------------------------------------------- specificity
STRONG_CONCRETE = [
    ("code span", re.compile(r"`[^`]+`")),
    ("path", re.compile(r"(?<![\w@:])(?:\.{1,2}/)?[\w.-]+/[\w./*{}-]+")),
    ("file/ext", re.compile(
        r"\b[\w.-]+\.(?:py|ts|tsx|js|jsx|mjs|cjs|json|ya?ml|toml|md|mdc|sh|ps1|go|rs|java|kt|rb|php|cs|cpp|cc|c|h|hpp|"
        r"sql|env|lock|txt|css|scss|html|vue|svelte|proto|graphql|tf|ini|cfg|xml|csv)\b")),
    ("identifier", re.compile(r"\b[a-z]+_[a-z_]+\b|\b[a-z]+[A-Z][A-Za-z]+\b|\b[A-Z][a-z]+[A-Z][A-Za-z]+\b")),
    ("tool", re.compile(
        r"\b(?:npm|npx|pnpm|yarn|bun|pip|pipx|uv|poetry|cargo|make|pytest|jest|vitest|mocha|ruff|black|isort|mypy|"
        r"pyright|eslint|prettier|biome|tsc|dotnet|gradle|mvn|docker|kubectl|terraform|gh|prisma|alembic|django|"
        r"rails|rake|bundle|composer|deno|flake8|pylint|clippy|rustfmt|gofmt|golangci-lint|swiftlint|ktlint|"
        r"checkstyle|rubocop|stylelint|husky|lint-staged|commitlint|playwright|cypress|storybook|vite|webpack|esbuild|"
        r"turbo|nx|lerna|changesets|git commit|git push|git rebase|git merge|plan mode|auto mode)\b", re.I)),
    ("number+unit", re.compile(
        r"\b\d+(?:[-\s]?(?:space|spaces|chars?|characters|lines?|words?|sentences?|paragraphs?|ms|seconds?|minutes?|"
        r"items?|levels?|args?|arguments|parameters?|files?|px|%|kb|mb|tokens?|columns?|bullets?|hops?|retries|"
        r"attempts?|hours?|days?))\b", re.I)),
    ("constant", re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")),
    ("quoted literal", re.compile(r"\"[^\"]{2,}\"|(?<!\w)'[^']{2,}'(?!\w)")),
    ("http verb", re.compile(r"\b(?:GET|POST|PUT|PATCH|DELETE)\b")),
    ("naming scheme", re.compile(r"\b(?:camelCase|snake_case|PascalCase|kebab-case|SCREAMING_SNAKE_CASE)\b")),
    ("named technology", re.compile(
        r"\b(?:TypeScript|JavaScript|Python|Rust|Golang|Java|Kotlin|Swift|C#|C\+\+|Ruby|PHP|SQL|React|Vue|Svelte|"
        r"Angular|Next\.js|Nuxt|Django|Flask|FastAPI|Express|NestJS|Spring|Rails|Laravel|Tailwind|Redux|Zustand|"
        r"Prisma|Drizzle|SQLAlchemy|Pydantic|Zod|GraphQL|REST|gRPC|Docker|Kubernetes|Postgres|PostgreSQL|MySQL|"
        r"SQLite|Redis|MongoDB|Kafka|RabbitMQ|Unreal|Unity|Godot|Blueprint|UObject|AActor)\b")),
    ("branch name", re.compile(r"\b(?:main|master|develop|trunk)\b\s+branch|\bbranch\s+\b(?:main|master|develop)\b")),
]
DOMAIN_NOUN_RE = re.compile(
    r"\b(?:dependenc(?:y|ies)|packages?|commit(?:s|ting)?|push(?:ing)?|branch(?:es)?|pull requests?|PRs?|tests?|"
    r"migrations?|schema|env(?:ironment)? (?:variables?|vars?)|secrets?|credentials?|API keys?|tokens?|passwords?|"
    r"logs?|logging|comments?|docstrings?|types?|imports?|exports?|functions?|classes?|methods?|modules?|components?|"
    r"hooks?|endpoints?|routes?|handlers?|middleware|queries|transactions?|mocks?|stubs?|fixtures?|snapshots?|"
    r"assertions?|exceptions?|errors?|warnings?|lint(?:ing|er)?|format(?:ting|ter)?|indent(?:ation)?|semicolons?|"
    r"quotes?|tabs?|spaces?|line length|README|CHANGELOG|LICENSE|Dockerfile|Makefile|CI|pipeline|workflow|"
    r"subagents?|sub-agents?|agents?|tools?|MCP|plan mode|scratchpad|worktrees?|first sentence|bullets?|tables?|"
    r"paragraphs?|headers?|headings?|files?|directories|directory|folders?|paths?|shell|terminal|commands?|scripts?|"
    r"issues?|tickets?|screenshots?|assumptions?|question|questions|approval|permission|confirmation)\b", re.I)
VAGUE_RE = re.compile(
    r"\b(?:clean(?:ly)?|clear(?:ly)?|good|great|nice(?:ly)?|proper(?:ly)?|appropriate(?:ly)?|best practices?|"
    r"careful(?:ly)?|high[- ]quality|quality|readable|readability|maintainable|maintainability|"
    r"well[- ](?:structured|organized|organised|written|documented|tested|named|formatted|designed|defined)|"
    r"efficient(?:ly)?|robust(?:ly)?|sensible|sensibly|reasonable|reasonably|as needed|when needed|when necessary|"
    r"if necessary|where appropriate|as appropriate|when appropriate|if appropriate|where possible|when possible|"
    r"if possible|whenever possible|etc\.?|and so on|correct(?:ly)?|idiomatic|meaningful|descriptive|"
    r"thoughtful(?:ly)?|professional(?:ly)?|modern|elegant|simple|simply|optimal|smart(?:ly)?|intelligent(?:ly)?|"
    r"helpful|useful|relevant|important|critical|essential|thorough(?:ly)?|comprehensive(?:ly)?|concise(?:ly)?|"
    r"brief(?:ly)?|minimal(?:ly)?|standard|conventional|consistent(?:ly)?|accurate(?:ly)?|precise(?:ly)?|"
    r"diligent(?:ly)?|rigorous(?:ly)?|graceful(?:ly)?|clean code|solid|sane|safe(?:ly)?|the right (?:way|thing)|"
    r"as expected|as usual|like a (?:senior|pro|professional|expert)|expert|senior|common sense|"
    r"use (?:your )?(?:best )?judg?ment|as much as possible|as little as possible|reasonable defaults|"
    r"performant|scalable|secure(?:ly)?|world[- ]class|production[- ](?:ready|grade|quality)|enterprise[- ]grade|"
    r"bulletproof|state[- ]of[- ]the[- ]art)\b", re.I)

# ---------------------------------------------------------------- inverted classes (Opus 5 generation)
SHAPE_RE = re.compile(r"\b(?:first sentence|bullet|bullets|table|tables|paragraphs?|words|lines|sentences)\b", re.I)
INVERTED = [
    ("verification", re.compile(
        r"\b(?:double[- ]check|triple[- ]check|re-?check your|verify (?:your|that your|the (?:work|output|answer|"
        r"results?|changes|code|response|fix|solution))|review your (?:own )?(?:work|output|answer|changes|code)|"
        r"self[- ](?:review|verify|check)|validate your (?:work|output|answer|changes|code|solution)|"
        r"check your (?:work|answer|output|changes)|use a sub-?agent to (?:verify|review|check|validate)|"
        r"spawn (?:a|an) (?:sub-?agent|agent|reviewer) to (?:verify|review|check)|before (?:you )?(?:finish|reply|"
        r"respond|answer),? (?:verify|check|re-?read))\b", re.I), "warn",
     "Opus 5 verifies its own output by default; this line stacks on that and causes over-verification. "
     "Delete it, or replace it with a held-out check the model cannot edit (a test, a hook)."),
    ("hedge", re.compile(
        r"\b(?:be conservative|err on the side of|only (?:report|flag|mention|include|raise|surface) "
        r"(?:high|critical|severe|serious|major|important|significant|real|genuine|confirmed|obvious)|"
        r"only (?:if|when) (?:you are|you're) (?:sure|certain|confident)|avoid false positives|"
        r"when in doubt,? (?:do nothing|skip|leave it|don'?t)|don'?t be too (?:strict|aggressive|picky|thorough|"
        r"pedantic)|minimi[sz]e (?:findings|reports|noise)|keep (?:findings|feedback|comments) to a minimum)\b",
        re.I), "warn",
     "Opus 5 follows a limiter literally and under-reports. Ask for everything, then filter in a second pass."),
    ("thinking", re.compile(
        r"\b(?:think (?:step[- ]by[- ]step|hard(?:er)?|carefully|deeply|thoroughly|long|first)|do not think|"
        r"don'?t think|no thinking|ultrathink|chain[- ]of[- ]thought|reason (?:step[- ]by[- ]step|carefully|"
        r"out loud)|take your time to think|before answering,? think|let'?s think)\b", re.I), "info",
     "Thinking directives were written for older models; Opus 5 reasons by default and effort lives in settings. "
     "Delete unless you measured a difference on the current model."),
    ("effort", re.compile(r"\b(?:effort(?: level)?|thinking budget|reasoning budget|max_tokens|temperature)\b", re.I),
     "info",
     "Effort and budgets belong in settings, not prose. A value tuned for 4.8 stays live on Opus 5 until changed "
     "(Opus 5 defaults to high and adds xhigh); re-run an effort sweep."),
    ("brevity-no-shape", re.compile(
        r"\b(?:be (?:concise|brief|terse|succinct|short)|keep (?:it|responses|replies|answers|output|messages|"
        r"explanations) (?:short|brief|concise|minimal|to a minimum)|no preamble|don'?t be verbose|"
        r"avoid (?:verbosity|being verbose|long (?:answers|responses|replies|explanations))|less verbose|"
        r"shorter (?:answers|responses|replies)|(?:concise|brief|short|terse) (?:answers|responses|replies|"
        r"explanations)|don'?t (?:over-?explain|ramble)|no (?:fluff|filler))\b", re.I), "warn",
     "Names no shape. Replace with a reply-shape rule (answer in the first sentence; multi-item results as bullets "
     "or a table; cap prose at two paragraphs) or a Stop hook with a word budget. See /instruction-enforce."),
    ("model-vintage", re.compile(
        r"\b(?:claude[- ]?(?:3|4)(?:\.\d)?|opus[- ]?4(?:\.\d)?|sonnet[- ]?(?:3|4)(?:\.\d)?|haiku[- ]?3|"
        r"gpt-?[34](?:o|\.\d)?|o[13]-?(?:mini|preview)?)\b", re.I), "info",
     "Mentions an older model generation. Re-test the rule on the current model before keeping it."),
]
SHOUT_WORDS = {"IMPORTANT", "ALWAYS", "NEVER", "MUST", "CRITICAL", "WARNING", "MANDATORY", "REQUIRED", "STRICTLY",
               "ATTENTION", "FORBIDDEN", "PROHIBITED", "ABSOLUTELY", "REMEMBER", "NOTE", "CAUTION", "STOP"}
ACRONYMS = {"API", "APIS", "JSON", "HTML", "CSS", "SQL", "HTTP", "HTTPS", "URL", "URLS", "README", "CLAUDE", "MCP",
            "CLI", "UI", "UX", "PR", "PRS", "TODO", "FIXME", "YAML", "TOML", "XML", "CSV", "REST", "GRPC", "JWT",
            "AWS", "GCP", "CI", "CD", "IDE", "SDK", "ORM", "DTO", "CRUD", "TDD", "BDD", "DRY", "KISS", "YAGNI",
            "ADR", "RFC", "ID", "IDS", "UUID", "ENV", "OS", "GPU", "CPU", "RAM", "LLM", "LLMS", "AI", "ML", "NLP",
            "MIT", "GPL", "BSD", "ASCII", "UTF", "TS", "JS", "PHP", "GET", "POST", "PUT", "PATCH", "DELETE", "HEAD",
            "CORS", "CSRF", "XSS", "SSR", "SSG", "SPA", "PWA", "DOM", "SVG", "PNG", "JPG", "GIF", "PDF", "UE", "UE5",
            "MD", "MDX", "NPM", "PNPM", "SEO", "OK", "N/A"}

# ---------------------------------------------------------------- derivable documentation
DERIVABLE_HEADING_RE = re.compile(
    r"(?:project|directory|folder|repo(?:sitory)?|codebase|code|source|file)\s+(?:structure|layout|tree|overview|"
    r"organi[sz]ation|map)|tech(?:nology)?\s*stack|technologies|dependencies|packages used|libraries used|"
    r"architecture|^overview$|^about\b|^introduction|^background|what (?:is|this)|key (?:files|components|modules|"
    r"directories|concepts)|main (?:files|components|modules)|^stack$|^modules$|^components$|^services$",
    re.I)

# ---------------------------------------------------------------- placement
PATH_TOKEN_RE = re.compile(r"(?<![\w@:/.])((?:\.{1,2}/)?[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.*{},-]+)+/?|\*\*/\*\.\w+)")
WORD_SLASH_RE = re.compile(r"^[A-Za-z]+/[A-Za-z]+$")  # and/or, input/output

# ---------------------------------------------------------------- conflicts
SUBJECTS = {
    "tests": r"\b(?:tests?|testing|specs?|coverage|tdd|e2e|jest|vitest|pytest|mocha|unittest|untested)\b",
    "mocks": r"\b(?:mocks?|mocking|stubs?|fakes?|spies|spy|fixtures?|monkeypatch)\b",
    "dependencies": r"\b(?:dependenc(?:y|ies)|packages?|libraries|library|install(?:s|ing|ation|ed)?|npm i(?:nstall)?|"
                    r"pip install|node_modules|requirements\.txt|package\.json|pyproject)\b",
    "git": r"\b(?:commits?|committing|push(?:es|ing)?|branch(?:es)?|rebase|merge|squash|pull requests?|PRs?|git|"
           r"force[- ]push|main branch|master branch)\b",
    "formatting": r"\b(?:format(?:ting|ter)?|prettier|ruff|black|eslint|lint(?:ing|er)?|biome|indent(?:ation)?|"
                  r"tabs?|spaces|semicolons?|quotes|line length|code style|style guide|gofmt|rustfmt)\b",
    "types": r"\b(?:types?|typing|typed|typescript|strict mode|mypy|pyright|type annotations?|type hints?|generics?|"
             r"\bany\b type|: any\b)\b",
    "comments": r"\b(?:comments?|docstrings?|jsdoc|inline documentation|commented)\b",
    "docs": r"\b(?:documentation|docs|readme|changelog|adr)\b",
    "errors": r"\b(?:errors?|exceptions?|throw|raise|try/catch|try/except|error handling|failures?|panics?|"
              r"swallow(?:ing)?)\b",
    "logging": r"\b(?:logs?|logging|logger|console\.log|print statements?|print\(|debug output|stdout)\b",
    "verbosity": r"\b(?:concise|brief|verbose|verbosity|terse|short|long|preamble|summar(?:y|ies|ize|ise)|"
                 r"explanations?|explain|repl(?:y|ies)|responses?|answers?|output length|wordy|word count|words|"
                 r"chatty|narrat(?:e|ion))\b",
    "questions": r"\b(?:ask(?:ing)?|confirm(?:ation)?|clarif(?:y|ication|ying)|permission|approval|check in|"
                 r"before proceeding|without asking|assume|assumptions?)\b",
    "scope": r"\b(?:scope|refactor(?:ing|s)?|unrelated|extra|beyond|only (?:change|modify|touch|edit)|"
             r"minimal(?:ly)? (?:change|diff)|drive-by|out of scope|creep|additional (?:changes|features)|"
             r"while you'?re (?:there|at it))\b",
    "files": r"\b(?:new files?|create files?|creating files?|delete files?|remove files?|rename|file names?|"
             r"filenames?|file (?:size|length)|one file|per file|single file)\b",
    "secrets": r"\b(?:secrets?|credentials?|tokens?|api keys?|passwords?|\.env|env vars?|environment variables?|"
               r"private keys?)\b",
    "performance": r"\b(?:performance|optimi[sz]e|optimi[sz]ation|cache|caching|fast|slow|latency|memory|"
                   r"premature)\b",
    "naming": r"\b(?:naming|names?|camelCase|snake_case|PascalCase|kebab-case|prefix(?:es)?|suffix(?:es)?|"
              r"abbreviations?)\b",
    "imports": r"\b(?:imports?|require\(|barrel|index files?|circular|absolute paths?|relative paths?)\b",
    "async": r"\b(?:async|await|promises?|callbacks?|threads?|concurrency|parallel|synchronous|blocking)\b",
    "database": r"\b(?:database|db|migrations?|sql|quer(?:y|ies)|schema|orm|prisma|sqlalchemy|transactions?|"
                r"raw sql)\b",
    "api": r"\b(?:endpoints?|api|routes?|handlers?|rest|graphql|controllers?|middleware|status codes?)\b",
    "ui": r"\b(?:components?|css|tailwind|styling|styles|ui|layout|accessibility|a11y|inline styles?)\b",
    "subagents": r"\b(?:sub-?agents?|agents?|delegate|delegation|parallel agents|tools?|mcp|spawn)\b",
    "verification": r"\b(?:verify|verification|double[- ]check|re-?check|validate|self[- ]review|review your)\b",
    "planning": r"\b(?:plan|planning|plan mode|design first|think(?:ing)?|reason(?:ing)?|proposal|before coding|"
                r"before implementing)\b",
    "language": r"\b(?:english|russian|german|french|spanish|chinese|japanese|in (?:the )?language|"
                r"respond in|answer in|reply in|write in)\b",
    "security": r"\b(?:security|secure|sanitize|xss|injection|csrf|auth(?:entication|orization)?|permissions?|"
                r"validate input|input validation)\b",
    "build": r"\b(?:build|compile|bundle|ci|pipeline|deploy(?:ment)?|release|production|prod)\b",
    "commands": r"\b(?:run|execute|commands?|scripts?|shell|bash|terminal|powershell)\b",
    "editing": r"\b(?:edit(?:s|ing)?|modify|modification|overwrite|rewrite|touch|generated files?|hand-edit)\b",
    "completion": r"\b(?:done|finished|complete|completion|stop when|report (?:back|completion)|declare|"
                  r"claim(?:s|ed|ing)? (?:that )?(?:it'?s |it is |this is |the \w+ is )?(?:done|complete|finished|"
                  r"fixed|working|resolved))\b",
}
SUBJECT_RES = {k: re.compile(v, re.I) for k, v in SUBJECTS.items()}
BROAD_SUBJECTS = {"commands", "editing", "files", "verbosity", "build", "questions"}
STOP_WORDS = set("""
the a an and or of to in on for with without by at from as is are be it its this that these those all every each
any no not never always must should shall do does don dont use using used file files code when if before after
only into onto than then them they their there here your you our we will would could can may might also just
under over about between within without which what who how why one two first last same other another each
""".split())


def stem(word):
    for suf in ("ing", "es", "ed", "s"):
        if len(word) > 4 and word.endswith(suf):
            return word[: -len(suf)]
    return word


def content_overlap(a, b):
    def toks(t):
        out = set()
        for w in re.findall(r"[a-z][a-z0-9_.-]{2,}", t.lower()):
            w = w.strip("._-")
            if len(w) >= 3 and w not in STOP_WORDS:
                out.add(stem(w))
        return out
    return toks(a) & toks(b)
NEG_RE = re.compile(
    r"\b(?:never|don'?t|do not|avoid|no\b|not\b|without|skip|except|unless|exempt|instead of|prohibited|forbidden|"
    r"must not|should not|shouldn'?t|mustn'?t|can'?t|cannot|isn'?t (?:needed|required)|not (?:needed|required|"
    r"necessary)|ships without|does not need|doesn'?t need|no need|stop\b)\b", re.I)
# 'only' is guarded so it does not fire inside read-only, append-only, write-only.
POS_RE = re.compile(
    r"\b(?:always|must|should|every|all|each|required|ensure|make sure|be sure|need to|needs to|have to|has to)\b"
    , re.I)
# Exception *constructions* only. Bare modals (may, can) and adverbs (only, automatically) are how ordinary prose
# is written and carried no signal: they fired on nearly every pair in prose-heavy files.
EXC_RE = re.compile(
    r"\b(?:except|unless|exempt|but not|ships without|does not need|doesn'?t need|no need|allowed to|"
    r"is fine|are fine|ok to|okay to|optional|without asking|as needed|when needed)\b", re.I)
ALT_GROUPS = [
    ["npm", "pnpm", "yarn", "bun"],
    ["tabs", "spaces"],
    ["2 spaces", "4 spaces", "2-space", "4-space", "two spaces", "four spaces"],
    ["single quotes", "double quotes"],
    ["camelCase", "snake_case", "PascalCase", "kebab-case"],
    ["jest", "vitest", "mocha"],
    ["pytest", "unittest"],
    ["black", "ruff format", "autopep8", "yapf"],
    ["eslint", "biome"],
    ["prettier", "biome"],
    ["rebase", "merge commit", "squash"],
    ["main", "master"],
    ["poetry", "pipenv", "uv", "pip-tools", "conda"],
    ["requirements.txt", "pyproject.toml"],
    ["typescript", "javascript"],
    ["default export", "named export"],
    ["fetch", "axios"],
    ["redux", "zustand", "mobx"],
    ["react query", "swr"],
    ["css modules", "styled-components", "tailwind", "emotion"],
    ["async/await", "callbacks", ".then("],
    ["print(", "logging"],
    ["feature branches", "trunk-based"],
    ["conventional commits", "gitmoji"],
    ["english", "russian", "german", "french", "spanish", "chinese", "japanese"],
    ["interfaces", "type aliases"],
    ["classes", "functional"],
    ["docker", "podman"],
    ["mocks", "no mocks"],
]

# ---------------------------------------------------------------- enforcement
ENFORCEMENT = [
    ("destructive-command", re.compile(
        r"\brm\s+-[a-z]*r|\bgit\s+push\s+(?:--force|-f)\b|force[- ]push|\bgit\s+reset\s+--hard|\bgit\s+clean\b|"
        r"\bdrop\s+(?:table|database)|\btruncate\b|\b(?:never|do not|don'?t|must not)\s+(?:\w+\s+){0,2}(?:run|"
        r"execute|delete|drop|wipe|erase|destroy)\s+(?:\w+\s+){0,3}(?:files?|folders?|director(?:y|ies)|"
        r"branch(?:es)?|databases?|db|tables?|data|records?|repos?|repository|history|commits?|migrations?|"
        r"node_modules|scripts?|commands?|anything|\S*/\S*)\b", re.I),
     ("PreToolUse:Bash", "deny:Bash"),
     "permissions.deny Bash(<pattern>) for a fixed command shape; a PreToolUse hook on Bash for anything that "
     "needs logic (see /instruction-enforce, templates/deny_patterns.py)."),
    ("protected-path", re.compile(
        r"\b(?:never|do not|don'?t|must not)\s+(?:\w+\s+){0,2}(?:edit|modify|touch|change|write to|overwrite|"
        r"rewrite|delete|remove)\b.*?(?:/|\.\w{1,5}\b|generated|migrations?|lock ?files?|vendor|build output|"
        r"\bdist\b)|\b(?:read[- ]only|do not hand-edit|never hand-edit|generated files?, do not)\b", re.I),
     ("PreToolUse:Edit", "PreToolUse:Write", "deny:Edit", "deny:Write"),
     "permissions.deny Edit(<glob>) and Write(<glob>); or a PreToolUse hook on Edit|Write."),
    ("protected-branch", re.compile(
        r"\b(?:never|do not|don'?t|must not)\s+(?:\w+\s+){0,2}(?:commit|push|merge)\s+(?:directly\s+)?"
        r"(?:to|on|into|onto)\s+(?:main|master|production|prod|release|develop)\b|\b(?:main|master)\s+is\s+"
        r"protected\b", re.I),
     ("PreToolUse:Bash", "deny:Bash"),
     "permissions.deny Bash(git push*main*) or a PreToolUse hook that inspects the git command; remote branch "
     "protection is the real gate."),
    ("step-before-commit", re.compile(
        r"\b(?:run|execute|make sure|ensure|always run)\b.*\b(?:before|prior to)\s+(?:you\s+)?(?:commit(?:ting)?|"
        r"push(?:ing)?|every commit|each commit|opening a pr|creating a pr|submitting)\b|\bbefore\s+(?:commit"
        r"(?:ting)?|push(?:ing)?|every commit)[,:]?\s+(?:always\s+)?(?:run|execute)\b", re.I),
     ("PreToolUse:Bash", "precommit"),
     "a git pre-commit hook (.pre-commit-config.yaml, husky, lefthook, or .git/hooks/pre-commit), which runs "
     "regardless of the agent; or a PreToolUse hook matching git commit."),
    ("step-after-edit", re.compile(
        r"\b(?:after|following)\s+(?:every|each|any)\s+(?:edit|change|file change|modification|write|save)\b.*\b"
        r"(?:run|execute|format|lint|test)\b|\b(?:run|execute|format|lint|test)\b.*\bafter\s+(?:every|each|any)\s+"
        r"(?:edit|change|modification|write|save)\b", re.I),
     ("PostToolUse:Edit", "PostToolUse:Write"),
     "a PostToolUse hook on Edit|Write that runs the formatter or linter."),
    ("secrets", re.compile(
        r"\b(?:never|do not|don'?t|must not)\s+(?:\w+\s+){0,3}(?:commit|log|print|expose|leak|hardcode|hard-code|"
        r"read|cat|echo|paste|share)\b.*\b(?:secrets?|credentials?|tokens?|api keys?|passwords?|\.env\b|private "
        r"keys?)|\b(?:secrets?|credentials?|\.env)\b.*\b(?:never|must not|do not|don'?t)\b", re.I),
     ("deny:Read", "deny:Edit", "PreToolUse:Read", "PreToolUse:Bash"),
     "permissions.deny Read(./.env) Read(./.env.*) Read(**/secrets/**); a PreToolUse hook on Bash for cat/echo of "
     "those paths; a pre-commit secret scanner."),
    ("length-cap", re.compile(
        r"\b(?:under|max(?:imum)?|at most|no more than|cap(?:ped)? at|limit(?:ed)? to|within)\s+\d+\s+(?:words|"
        r"lines|sentences|paragraphs|bullets|characters|tokens)\b|\b\d+\s+(?:words|lines|sentences)\s+(?:max|"
        r"maximum|or fewer|or less|tops)\b", re.I),
     ("Stop",),
     "a Stop hook that counts words in last_assistant_message and exits 2 with a rewrite instruction "
     "(templates/gate_length.py in /instruction-enforce)."),
    ("approval-gate", re.compile(
        r"\b(?:always\s+)?(?:ask|check with|confirm with|get (?:my |user |explicit )?(?:approval|permission|"
        r"confirmation))\s+(?:me\s+|the user\s+|first\s+)?(?:before|prior to)\b|\bnever\b.*\bwithout\s+(?:asking|"
        r"confirmation|approval|permission)\b|\b(?:requires?|needs?)\s+(?:my |user |explicit )?(?:approval|"
        r"confirmation|permission)\b", re.I),
     ("ask:", "PreToolUse:"),
     "permissions.ask Bash(<pattern>) or a PreToolUse hook returning permissionDecision ask."),
]
HOOK_SCRIPT_RE = re.compile(r"(?:\.sh|\.py|\.ps1|\.js|\.mjs|\.cjs|\.rb|\.bat|\.cmd)$", re.I)


# ================================================================ data
class Surface:
    def __init__(self, path, kind, root, scope="project", depth=0, importer=None, import_line=0, hop=0):
        self.path = Path(path)
        self.kind = kind
        self.root = root
        self.scope = scope
        self.depth = depth
        self.importer = importer
        self.import_line = import_line
        self.hop = hop
        self.family = FAMILY.get(kind, "extra")
        self.families = {self.family}
        self.text = ""
        self.lines = []
        self.frontmatter = {}
        self.fm_lines = 0
        self.paths_scoped = False
        self.rules = []
        self.line_kinds = {}
        self.headings = []  # (line, level, text)
        self.words = 0
        self.instr_words = 0
        self.code_lines = 0
        self.tree_lines = 0
        self.doc_items = 0
        self.list_items = 0
        self.error = None
        self.base_tuple = importer.base_tuple + (import_line,) if importer else ()
        self.rank = LOAD_RANK.get(kind, 30)
        if kind == "claude-md-nested":
            self.rank += min(depth, 9)

    @property
    def rel(self):
        try:
            return self.path.resolve().relative_to(Path(self.root).resolve()).as_posix()
        except Exception:
            p = self.path.as_posix()
            home = Path.home().as_posix()
            return "~" + p[len(home):] if p.startswith(home) else p

    @property
    def always_on(self):
        if self.kind == "rule" or self.kind == "user-rule":
            return not self.paths_scoped
        if self.kind == "import":
            return self.importer.always_on if self.importer else True
        return self.kind in ALWAYS_ON_KINDS

    def loads(self):
        if self.kind in ("skill", "agent", "command", "output-style"):
            return "on invocation"
        if self.kind == "claude-md-nested":
            return "on demand (subtree)"
        if self.kind in ("rule", "user-rule") and self.paths_scoped:
            return "on demand (paths)"
        if self.kind == "prompt" or self.kind == "extra":
            return "unknown"
        return "always"


class Rule:
    __slots__ = ("surface", "line", "text", "raw", "heading", "form", "pos", "subjects", "polarity", "exc",
                 "interrogative", "strong", "domain", "vague", "index")

    def __init__(self, surface, line, text, raw, heading, form):
        self.surface = surface
        self.line = line
        self.text = text
        self.raw = raw
        self.heading = heading
        self.form = form
        self.pos = surface.base_tuple + (line,)
        self.subjects = set()
        self.polarity = "neutral"
        self.exc = False
        self.interrogative = False
        self.strong = []
        self.domain = False
        self.vague = []
        self.index = 0

    @property
    def loc(self):
        return "%s:%d" % (self.surface.rel, self.line)


def read_text(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


# ================================================================ discovery
def discover(root, include_user=True, includes=(), excludes=()):
    root = Path(root)
    surfaces = []
    seen = set()

    def add(path, kind, depth=0, scope="project"):
        p = Path(path)
        key = str(p.resolve()).lower()
        if key in seen or not p.is_file():
            return None
        rel = None
        try:
            rel = p.resolve().relative_to(root.resolve()).as_posix()
        except Exception:
            rel = p.as_posix()
        for ex in excludes:
            if fnmatch.fnmatch(rel, ex) or fnmatch.fnmatch(p.name, ex):
                return None
        seen.add(key)
        s = Surface(p, kind, root, scope=scope, depth=depth)
        surfaces.append(s)
        return s

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".git"))
        d = Path(dirpath)
        try:
            depth = len(d.resolve().relative_to(root.resolve()).parts)
        except Exception:
            depth = 0
        for rel, kind in FILE_PATTERNS:
            p = d / rel
            if p.is_file():
                k = kind
                if depth > 0 and kind in ("claude-md", "claude-local"):
                    k = "claude-md-nested"
                add(p, k, depth)
        for sub, glob, kind in DIR_PATTERNS:
            sd = d / sub
            if sd.is_dir():
                for p in sorted(sd.rglob(glob)):
                    if any(part in SKIP_DIRS for part in p.parts):
                        continue
                    add(p, kind, depth)
    for inc in includes:
        for p in sorted(root.glob(inc)):
            if p.is_file():
                add(p, "extra", 0)
    if include_user:
        home = Path.home() / ".claude"
        if (home / "CLAUDE.md").is_file():
            add(home / "CLAUDE.md", "user-claude-md", 0, scope="user")
        rules_dir = home / "rules"
        if rules_dir.is_dir():
            for p in sorted(rules_dir.rglob("*.md")):
                add(p, "user-rule", 0, scope="user")
    return surfaces


def resolve_imports(surfaces, root):
    """Expand @path imports found in Claude-family memory files, up to 4 hops."""
    out = list(surfaces)
    seen = {str(s.path.resolve()).lower() for s in surfaces}
    queue = [s for s in surfaces if s.kind in ("claude-md", "claude-md-nested", "claude-local", "user-claude-md")]
    while queue:
        s = queue.pop(0)
        if s.hop >= 4 or not s.text:
            continue
        in_fence = False
        for i, line in enumerate(s.lines, start=1):
            if FENCE_RE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            stripped = CODE_SPAN_RE.sub("", line)
            for m in IMPORT_RE.finditer(stripped):
                token = m.group(1)
                if "://" in token or token.endswith((".", ",")):
                    continue
                if token.startswith("~/"):
                    target = Path.home() / token[2:]
                else:
                    target = (s.path.parent / token)
                try:
                    target = target.resolve()
                except Exception:
                    continue
                if not target.is_file():
                    continue
                key = str(target).lower()
                if key in seen:
                    # AGENTS.md imported by CLAUDE.md: it now also loads for the Claude family.
                    for t in out:
                        if str(t.path.resolve()).lower() == key:
                            t.families.add("claude")
                    continue
                seen.add(key)
                imp = Surface(target, "import", root, scope=s.scope, depth=s.depth, importer=s, import_line=i,
                              hop=s.hop + 1)
                load_surface(imp)
                out.append(imp)
                queue.append(imp)
    return out


# ================================================================ parsing
def parse_frontmatter(text):
    if not text.startswith("---"):
        return {}, text, 0
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?", text, re.S)
    if not m:
        return {}, text, 0
    body = m.group(1)
    fm = {}
    key = None
    for line in body.splitlines():
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if km:
            key = km.group(1)
            val = km.group(2).strip()
            if val.startswith("[") and val.endswith("]"):
                fm[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
            elif val in ("", "|", ">", "|-", ">-"):
                fm[key] = [] if val == "" else ""
            else:
                fm[key] = val.strip("\"'")
        elif key is not None:
            lm = re.match(r"^\s*-\s*(.+)$", line)
            if lm and isinstance(fm.get(key), list):
                fm[key].append(lm.group(1).strip().strip("\"'"))
            elif isinstance(fm.get(key), str):
                fm[key] = (fm[key] + " " + line.strip()).strip()
    rest = text[m.end():]
    fm_lines = body.count("\n") + 3
    return fm, rest, fm_lines


def strip_md(s):
    s = re.sub(r"(\*\*|__)(.*?)\1", r"\2", s)
    s = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", s)
    s = re.sub(r"^\s*>\s?", "", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def leading_imperative(t):
    """True when the sentence (after an optional lead-in clause) opens with an imperative verb or 'No <thing>'."""
    m = LEAD_CLAUSE_RE.match(t)
    t2 = m.group(1) if m else t
    first = re.split(r"[\s,:;(]", t2, maxsplit=1)[0].lower().strip("*_`\"'()[]")
    return first in IMPERATIVE_VERBS or bool(NO_PREFIX_RE.match(t2))


HEAD_NEG_RE = re.compile(r"^(?:never|do not|don'?t|dont|avoid|always|also|please)\s+", re.I)


def head_verb(t):
    """The imperative verb a sentence commands or prohibits: 'Never run X' -> 'run', 'Run X' -> 'run'."""
    m = LEAD_CLAUSE_RE.match(t)
    t2 = m.group(1) if m else t
    t2 = HEAD_NEG_RE.sub("", t2.lstrip("*_`\"'()[] "))
    first = re.split(r"[\s,:;(]", t2, maxsplit=1)[0].lower().strip("*_`\"'()[]")
    return first if first in IMPERATIVE_VERBS else ""


def is_directive(sentence):
    t = strip_md(sentence)
    if not t:
        return False
    if MODAL_RE.search(t):
        return True
    return leading_imperative(t)


def is_doc_item(text):
    """List items that describe rather than instruct: '- src/: source', '- react 18', '- **Name**: thing'."""
    t = strip_md(text)
    if not t:
        return True
    if t.endswith(":") and len(t.split()) <= 6:
        return True  # a lead-in line such as "Deploy the application:"
    if is_directive(t):
        return False
    if re.match(r"^[`\w./*@-]+\s*[-:—–]\s*.*$", t) and len(t.split()) <= 14:
        return True
    if len(t.split()) <= 4:
        return True
    return False


def load_surface(s):
    try:
        s.text = read_text(s.path)
    except Exception as e:
        s.error = str(e)
        return
    fm, body, fm_lines = parse_frontmatter(s.text)
    s.frontmatter = fm
    s.fm_lines = fm_lines
    paths = fm.get("paths")
    s.paths_scoped = bool(paths) if isinstance(paths, list) else bool(paths)
    body = HTML_COMMENT_RE.sub(lambda m: "\n" * m.group(0).count("\n"), body)
    s.lines = s.text.splitlines()
    body_lines = body.splitlines()
    s.words = len(body.split())
    heading_stack = []
    in_fence = False
    para = []  # (line_no, text)
    rules = []

    def flush_para():
        if not para:
            return
        start = para[0][0]
        joined = " ".join(t.strip() for _, t in para)
        for sent in SENT_SPLIT_RE.split(joined):
            sent = sent.strip()
            if not sent:
                continue
            if sent.endswith(":") and len(sent.split()) <= 6:
                continue
            if is_directive(sent):
                rules.append(Rule(s, start, strip_md(sent), sent, " > ".join(h for _, h in heading_stack), "sentence"))
                s.instr_words += len(sent.split())
        para.clear()

    last_item = None
    for idx, line in enumerate(body_lines, start=1):
        ln = idx + fm_lines
        stripped = line.strip()
        if FENCE_RE.match(line):
            flush_para()
            last_item = None
            in_fence = not in_fence
            s.line_kinds[ln] = "code"
            s.code_lines += 1
            continue
        if in_fence:
            s.line_kinds[ln] = "code"
            s.code_lines += 1
            continue
        if not stripped:
            flush_para()
            last_item = None
            s.line_kinds[ln] = "blank"
            continue
        hm = HEADING_RE.match(line)
        if hm:
            flush_para()
            last_item = None
            level = len(hm.group(1))
            text = strip_md(hm.group(2))
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            heading_stack.append((level, text))
            s.headings.append((ln, level, text))
            s.line_kinds[ln] = "heading"
            continue
        if TREE_RE.search(line):
            flush_para()
            s.line_kinds[ln] = "tree"
            s.tree_lines += 1
            continue
        if TABLE_RE.match(line):
            flush_para()
            s.line_kinds[ln] = "table"
            continue
        if BOLD_LINE_RE.match(line) or LINK_ONLY_RE.match(line) or re.fullmatch(r"@[\w./~-]+", stripped):
            flush_para()
            s.line_kinds[ln] = "scaffold"
            continue
        lm = LIST_RE.match(line)
        if lm:
            flush_para()
            s.list_items += 1
            text = lm.group(2)
            if is_doc_item(text):
                s.doc_items += 1
                s.line_kinds[ln] = "doc-item"
                last_item = None
                continue
            r = Rule(s, ln, strip_md(text), text, " > ".join(h for _, h in heading_stack), "list")
            rules.append(r)
            s.instr_words += len(text.split())
            s.line_kinds[ln] = "rule"
            last_item = r
            continue
        if last_item is not None and line.startswith((" ", "\t")):
            # continuation of a list item
            last_item.text = strip_md(last_item.raw + " " + stripped)
            last_item.raw += " " + stripped
            s.instr_words += len(stripped.split())
            s.line_kinds[ln] = "rule"
            continue
        last_item = None
        para.append((ln, line))
        s.line_kinds[ln] = "prose"
    flush_para()
    for r in rules:
        classify_rule(r)
    s.rules = rules
    for ln, k in s.line_kinds.items():
        if k == "prose":
            pass


def classify_rule(r):
    t = r.text
    for name, rx in STRONG_CONCRETE:
        if rx.search(t):
            r.strong.append(name)
    r.domain = bool(DOMAIN_NOUN_RE.search(t))
    r.vague = sorted({m.group(0).lower() for m in VAGUE_RE.finditer(t)})
    low = t.lower()
    for name, rx in SUBJECT_RES.items():
        if rx.search(low):
            r.subjects.add(name)
    neg = bool(NEG_RE.search(t))
    pos = bool(POS_RE.search(t))
    if neg and pos:
        r.polarity = "mixed"
    elif neg:
        r.polarity = "neg"
    elif pos:
        r.polarity = "pos"
    elif leading_imperative(t):
        r.polarity = "imperative"
    else:
        r.polarity = "neutral"  # a declarative with no modal and no imperative: not an obligation
    r.exc = bool(EXC_RE.search(t))
    r.interrogative = t.rstrip().endswith("?")


# ================================================================ settings / hooks
def load_settings(root, include_user=True):
    files = [Path(root) / ".claude" / "settings.json", Path(root) / ".claude" / "settings.local.json"]
    if include_user:
        files.append(Path.home() / ".claude" / "settings.json")
    hooks = []  # dict(event, matcher, if, command, file)
    deny, allow, ask = [], [], []
    errors = []
    for f in files:
        if not f.is_file():
            continue
        try:
            data = json.loads(read_text(f))
        except Exception as e:
            errors.append((f, str(e)))
            continue
        perms = data.get("permissions") or {}
        deny += [(x, f) for x in perms.get("deny", []) or []]
        allow += [(x, f) for x in perms.get("allow", []) or []]
        ask += [(x, f) for x in perms.get("ask", []) or []]
        for event, groups in (data.get("hooks") or {}).items():
            if not isinstance(groups, list):
                continue
            for g in groups:
                if not isinstance(g, dict):
                    continue
                matcher = g.get("matcher", "") or ""
                for h in g.get("hooks", []) or []:
                    if not isinstance(h, dict):
                        continue
                    hooks.append({"event": event, "matcher": matcher, "if": h.get("if", ""),
                                  "command": h.get("command", ""), "args": h.get("args", []) or [],
                                  "type": h.get("type", "command"), "file": f})
    return {"hooks": hooks, "deny": deny, "allow": allow, "ask": ask, "errors": errors, "files": files}


def matcher_hits(matcher, tool):
    if not matcher or matcher in ("*", ".*"):
        return True
    parts = [p.strip() for p in matcher.split("|")]
    if tool in parts:
        return True
    try:
        return re.fullmatch(matcher, tool) is not None
    except re.error:
        return False


def coverage(spec, settings, root):
    """Return a short description of what covers `spec`, or None."""
    hooks, deny, ask = settings["hooks"], settings["deny"], settings["ask"]
    if spec == "precommit":
        for name in (".pre-commit-config.yaml", ".husky", "lefthook.yml", ".lefthook.yml", ".git/hooks/pre-commit"):
            if (Path(root) / name).exists():
                return "git pre-commit hook (%s)" % name
        return None
    if spec.startswith("deny:"):
        tool = spec[5:]
        for rule, f in deny:
            if rule.startswith(tool + "(") or rule == tool:
                return "permissions.deny %s (%s)" % (rule, Path(f).name)
        return None
    if spec.startswith("ask:"):
        if ask:
            return "permissions.ask %s" % ask[0][0]
        return None
    event, _, tool = spec.partition(":")
    for h in hooks:
        if h["event"] != event:
            continue
        if tool and not matcher_hits(h["matcher"], tool):
            continue
        return "%s hook (%s)" % (event, (h["command"] or h["type"])[:60])
    return None


# ================================================================ checks
class Findings:
    def __init__(self):
        self.items = []

    def add(self, check, severity, surface, line, text, detail, fix, **meta):
        self.items.append({"check": check, "severity": severity, "file": surface.rel if surface else "",
                           "line": line, "text": text, "detail": detail, "fix": fix, "meta": meta})


def check_bloat(surfaces, F, max_lines):
    for s in surfaces:
        if s.error or not s.text:
            continue
        n = len(s.lines)
        if n > max_lines and s.kind not in ("skill", "agent", "command", "output-style", "prompt"):
            F.add("bloat", "warn", s, 1, "", "%d lines (target under %d). Longer always-on files cost context on "
                  "every turn and reduce adherence." % (n, max_lines),
                  "Move path-specific rules to .claude/rules/<topic>.md with a paths: list, procedures to skills, "
                  "and cut derivable documentation.")
        # derivable sections
        for i, (ln, level, text) in enumerate(s.headings):
            if not DERIVABLE_HEADING_RE.search(text):
                continue
            end = len(s.lines) + 1
            for ln2, level2, _ in s.headings[i + 1:]:
                if level2 <= level:
                    end = ln2
                    break
            span = end - ln - 1
            if span < 3:
                continue
            nrules = sum(1 for r in s.rules if ln < r.line < end)
            F.add("bloat", "info", s, ln, text,
                  "Section '%s' (%d lines, %d rules) looks like documentation the model can derive from the "
                  "codebase." % (text, span, nrules),
                  "Cut it (or run /doctor). Keep only pitfalls and conventions that differ from tool defaults; keep "
                  "the %d rule(s) if they name a construct." % nrules if nrules else
                  "Cut it (or run /doctor). Keep only pitfalls and conventions that differ from tool defaults.",
                  span=span)
        if s.tree_lines >= 3:
            F.add("bloat", "info", s, 1, "", "Directory tree diagram (%d lines): derivable from the file system." %
                  s.tree_lines, "Delete it; the agent lists directories itself.")
        if n and s.code_lines / n > 0.35 and s.kind not in ("skill", "command", "output-style", "prompt"):
            F.add("bloat", "info", s, 1, "", "Fenced code makes up %d%% of the file. Examples are scaffolding unless "
                  "they show a convention that differs from the tool default." % round(100 * s.code_lines / n),
                  "Keep one example per convention that differs from defaults; delete the rest.")
        if s.list_items >= 4 and s.doc_items / s.list_items >= 0.7:
            F.add("bloat", "info", s, 1, "", "%d of %d list items describe rather than instruct (dependency lists, "
                  "layouts, glossaries)." % (s.doc_items, s.list_items),
                  "Descriptive lists do not change behavior; delete or move to README.")


def check_specificity(surfaces, F):
    for s in surfaces:
        for r in s.rules:
            if r.vague and not r.strong:
                F.add("specificity", "warn", s, r.line, r.text,
                      "Vague term(s): %s; names no construct the model can bind to." % ", ".join(r.vague),
                      "Name the tool, path, pattern, or number the rule is about (`Format with ruff format before "
                      "committing`, not `keep the code clean`), or delete it.", vague=r.vague)
            elif not r.strong and not r.domain and s.kind not in ("skill", "agent", "command", "output-style"):
                F.add("specificity", "info", s, r.line, r.text,
                      "Names no concrete construct (no path, tool, identifier, number, or domain noun).",
                      "Add the construct or scope it; a rule that binds nothing fires everywhere on Opus 5.")


def check_inverted(surfaces, F):
    for s in surfaces:
        for r in s.rules:
            plain = CODE_SPAN_RE.sub(" ", r.raw)  # a phrase quoted in backticks is mentioned, not instructed
            plain = strip_md(plain)
            for name, rx, sev, advice in INVERTED:
                if rx.search(plain):
                    if name == "brevity-no-shape" and (SHAPE_RE.search(r.text) or "number+unit" in r.strong):
                        continue
                    if name == "effort" and s.kind in ("skill", "agent", "command"):
                        continue
                    F.add("inverted", sev, s, r.line, r.text, "Class '%s'. %s" % (name, advice),
                          "Test on the current model; delete if it no longer binds.", cls=name)
            caps = [w for w in re.findall(r"\b[A-Z]{4,}\b", r.raw) if w not in ACRONYMS]
            bold_all = bool(re.match(r"^\s*(?:\*\*|__).+(?:\*\*|__)\s*[.!]?\s*$", r.raw.strip()))
            if any(w in SHOUT_WORDS for w in caps) or len(caps) >= 2 or bold_all or "!!" in r.raw:
                F.add("inverted", "info", s, r.line, r.text,
                      "Class 'emphasis'. Emphasis does not make a rule bind; a rule that gets ignored usually loses "
                      "to a competing rule on the same subject or names no construct.",
                      "Remove the emphasis; check the conflicts section for this subject.", cls="emphasis")


def check_placement(surfaces, F, root):
    root = Path(root)
    for s in surfaces:
        if s.kind in ("skill", "agent", "command", "output-style"):
            fm = s.frontmatter
            desc = fm.get("description", "")
            if s.kind in ("skill", "agent") and not desc:
                F.add("placement", "warn", s, 1, "", "No `description` in frontmatter; the model cannot decide "
                      "when this %s applies." % s.kind, "Add a one-sentence description naming the triggers.")
            elif desc:
                combined = len(str(desc)) + len(str(fm.get("when_to_use", "")))
                if combined > 1536:
                    F.add("placement", "warn", s, 1, "", "description + when_to_use is %d chars; the listing "
                          "truncates at 1536." % combined, "Shorten the description.")
            if len(s.lines) > 500 and s.kind == "skill":
                F.add("placement", "info", s, 1, "", "%d-line SKILL.md loads whole on invocation." % len(s.lines),
                      "Move reference material into files the skill links to (progressive disclosure).")
            continue
        if not s.always_on:
            continue
        for r in s.rules:
            for m in PATH_TOKEN_RE.finditer(r.text):
                tok = m.group(1).rstrip(".,;:)'\"")
                if not tok or "://" in tok or WORD_SLASH_RE.match(tok):
                    continue
                cand = tok.rstrip("/")
                has_glob = any(ch in tok for ch in "*{}")
                exists_dir = False
                if not has_glob:
                    for base in (s.path.parent, root):
                        try:
                            p = (base / cand)
                            if p.is_dir():
                                exists_dir = True
                                break
                        except Exception:
                            pass
                    if not exists_dir:
                        continue
                    # a command path like scripts/build.sh is "what to run", not "where the rule applies"
                    if re.search(r"\b(?:run|execute|call|invoke|use)\b\s+`?\.{0,2}/?" + re.escape(tok), r.text, re.I):
                        continue
                target = tok if has_glob else cand.strip("./") + "/**"
                F.add("placement", "warn", s, r.line, r.text,
                      "Names `%s` but lives on an always-on surface, so it loads on every unrelated turn." % tok,
                      "Move to .claude/rules/<topic>.md with `paths: [\"%s\"]`, or to %s/CLAUDE.md." %
                      (target, cand.strip("./") if not has_glob else "<dir>"), token=tok)
                break


def alt_hits(text):
    low = text.lower()
    hits = {}
    for gi, group in enumerate(ALT_GROUPS):
        found = [a for a in group
                 if re.search(r"(?<![A-Za-z0-9_])" + re.escape(a.lower()) + r"(?![A-Za-z0-9_])", low)]
        if len(found) == 1:
            hits[gi] = found[0]
        elif len(found) == 2:
            # "not A; use B" / "B, not A" names both: keep the one that is not under a negation
            kept, neg = [], False
            for seg in re.split(r"(;|:|\binstead of\b|\brather than\b|\bnot\b|\bnever\b|\bdon'?t\b|\bdo not\b|\bavoid\b)", low):
                if seg in (";", ":"):
                    neg = False
                    continue
                if re.fullmatch(r"instead of|rather than|not|never|don'?t|do not|avoid", seg):
                    neg = True
                    continue
                for a in found:
                    if not neg and re.search(r"(?<![A-Za-z0-9_])" + re.escape(a.lower()) + r"(?![A-Za-z0-9_])", seg):
                        kept.append(a)
            if len(kept) == 1:
                hits[gi] = kept[0]
    return hits


def authored_unit(s):
    """The root of an @import chain: CLAUDE.md and the files it imports are one deliberately split contract."""
    while s.importer is not None:
        s = s.importer
    return s


def check_conflicts(surfaces, F, max_pairs):
    # A question states no obligation and cannot contradict one; checklist items stay in the specificity check.
    rules = [r for s in surfaces for r in s.rules if r.subjects and not r.interrogative]
    for i, r in enumerate(rules):
        r.index = i
    by_subject = defaultdict(list)
    for r in rules:
        for sub in r.subjects:
            by_subject[sub].append(r)
    pairs = {}
    for sub, rs in by_subject.items():
        if len(rs) < 2 or len(rs) > 400:
            continue
        for a_i in range(len(rs)):
            for b_i in range(a_i + 1, len(rs)):
                a, b = rs[a_i], rs[b_i]
                if (a.surface is b.surface and abs(a.line - b.line) < 3 and a.heading == b.heading
                        and (a.exc or b.exc)):
                    continue  # a rule and its scoped exception, written together
                if not (a.surface.families & b.surface.families):
                    co = "cross-tool"
                elif a.surface is b.surface and a.surface.kind in ("skill", "agent", "command"):
                    co = "same-procedure"
                elif (a.surface is not b.surface and a.surface.kind in ("skill", "agent", "command")
                      and b.surface.kind in ("skill", "agent", "command")):
                    co = "separate-invocations"
                elif a.surface.always_on and b.surface.always_on:
                    co = "always"
                else:
                    co = "on-demand"
                shared = a.subjects & b.subjects
                same_unit = authored_unit(a.surface) is authored_unit(b.surface)
                score = 0
                reasons = []
                pol = {a.polarity, b.polarity}
                if pol == {"pos", "neg"}:
                    score += 2
                    reasons.append("opposite polarity")
                elif pol == {"imperative", "neg"}:
                    # a bare imperative contradicts a prohibition only when both bind the same verb
                    hv = head_verb(a.text)
                    if hv and hv == head_verb(b.text):
                        score += 2
                        reasons.append("'%s' is both commanded and prohibited" % hv)
                if a.exc != b.exc:
                    score += 1
                    reasons.append("one carries an exception")
                ah, bh = alt_hits(a.text), alt_hits(b.text)
                alts = [(ah[g], bh[g]) for g in ah if g in bh and ah[g] != bh[g]]
                if alts:
                    score += 3
                    reasons.append("exclusive alternatives: %s vs %s" % alts[0])
                if score == 0:
                    continue
                semantic = score  # polarity + exception + alternatives, before the lexical and structural points
                if sub in BROAD_SUBJECTS and score < 3 and len(shared) < 2:
                    continue
                overlap = content_overlap(a.text, b.text)
                if score <= 2 and not overlap and len(shared) < 2:
                    continue
                if overlap:
                    score += 1
                    reasons.append("shared terms: %s" % ", ".join(sorted(overlap)[:3]))
                if len(shared) >= 2:
                    score += 1
                if co == "always":
                    score += 1
                if a.surface is not b.surface and not same_unit:
                    score += 1
                key = (min(a.index, b.index), max(a.index, b.index))
                if key in pairs and pairs[key]["score"] >= score:
                    continue
                winner = a if (a.surface.rank, a.pos) > (b.surface.rank, b.pos) else b
                pairs[key] = {"a": a, "b": b, "score": score, "semantic": semantic, "reasons": reasons,
                              "subjects": sorted(shared), "co": co, "winner": winner, "alts": bool(alts),
                              "same_unit": same_unit}
    ranked = []
    seen_per_rule = defaultdict(int)
    for p in sorted(pairs.values(), key=lambda p: (-p["score"], p["a"].surface.rel, p["a"].line)):
        if seen_per_rule[p["a"].index] >= 5 or seen_per_rule[p["b"].index] >= 5:
            continue
        seen_per_rule[p["a"].index] += 1
        seen_per_rule[p["b"].index] += 1
        ranked.append(p)
        if len(ranked) >= max_pairs:
            break
    for p in ranked:
        a, b, w = p["a"], p["b"], p["winner"]
        if p["co"] in ("cross-tool", "separate-invocations", "same-procedure"):
            sev = "info"
        elif p["co"] == "always" and (p["alts"] or (p["semantic"] >= 2 and p["score"] >= 4)):
            # error needs semantic evidence (opposite polarity or exclusive alternatives); the lexical and
            # structural points alone can reach 5 on any two prose files and are not a contradiction
            sev = "error"
        else:
            sev = "warn"
        why = "; ".join(p["reasons"])
        if w.surface is a.surface and w.surface is b.surface:
            why_win = "later in the same file"
        elif w.surface.rank != (a.surface.rank if w is b else b.surface.rank):
            why_win = "loads later (%s after %s)" % (w.surface.kind, (a if w is b else b).surface.kind)
        else:
            why_win = "later in load order"
        always_note = "both always on"
        if p["same_unit"] and a.surface is not b.surface:
            always_note += "; one authored unit split by @import"
        co_note = {"always": always_note, "on-demand": "co-load only when the on-demand surface is active",
                   "cross-tool": "different tools; drift, not a co-load conflict",
                   "separate-invocations": "two on-invocation surfaces; a conflict only when both are invoked in "
                                           "one session",
                   "same-procedure": "steps of one on-invocation procedure; usually sequencing, not a conflict"
                   }[p["co"]]
        F.add("conflicts", sev, a.surface, a.line, a.text,
              "[%s] %s. Pair: %s <-> %s. %s. Recency winner: %s (%s)." %
              (", ".join(p["subjects"]), why, a.loc, b.loc, co_note, w.loc, why_win),
              "Decide whether both can hold for one concrete task. If not: delete one, or rewrite as one rule with "
              "an explicit exception placed after the general rule and scoped to a path. Do not fix by bolding or "
              "reordering.", other_file=b.surface.rel, other_line=b.line, other_text=b.text, winner=w.loc,
              subjects=p["subjects"], co_load=p["co"], score=p["score"], semantic=p["semantic"],
              same_unit=p["same_unit"])


def check_enforcement(surfaces, F, settings, root):
    for f, err in settings["errors"]:
        F.add("enforcement", "error", Surface(f, "extra", root), 1, "", "settings file does not parse: %s" % err,
              "Fix the JSON; hooks and permission rules in this file are not active until it parses.")
    # broken hook commands
    for h in settings["hooks"]:
        cmd = (h["command"] or "") + " " + " ".join(str(a) for a in h["args"])
        cmd = cmd.replace("${CLAUDE_PROJECT_DIR}", str(root)).replace("$CLAUDE_PROJECT_DIR", str(root))
        if "${CLAUDE_PLUGIN_ROOT}" in cmd or "$CLAUDE_PLUGIN_ROOT" in cmd:
            continue
        for tok in re.split(r"\s+", cmd.strip()):
            tok = tok.strip("\"'")
            if not tok or not (HOOK_SCRIPT_RE.search(tok) or "/hooks/" in tok.replace("\\", "/")):
                continue
            p = Path(os.path.expanduser(tok))
            if not p.is_absolute():
                p = Path(root) / p
            if not p.exists():
                F.add("enforcement", "error", Surface(h["file"], "extra", root), 1, h["command"],
                      "%s hook references a script that does not exist: %s" % (h["event"], tok),
                      "Restore the script or remove the hook; a gate that is not there enforces nothing.")
    for s in surfaces:
        procedural = s.kind in ("skill", "agent", "command", "output-style")
        for r in s.rules:
            plain = re.sub(r"\"[^\"]*\"|“[^”]*”", " ", r.text)  # quoted examples are mentioned, not instructed
            for name, rx, specs, lever in ENFORCEMENT:
                if not rx.search(plain):
                    continue
                cov = None
                for spec in specs:
                    cov = coverage(spec, settings, root)
                    if cov:
                        break
                if cov:
                    F.add("enforcement", "info", s, r.line, r.text,
                          "Enforcement-shaped (%s); possibly gated by %s. Confirm the gate covers this exact case."
                          % (name, cov), "Keep the prose short (one line for humans); the gate does the work.",
                          cls=name, gate=cov)
                elif procedural:
                    F.add("enforcement", "info", s, r.line, r.text,
                          "Enforcement-shaped (%s) inside an on-invocation procedure; steering only." % name,
                          "If it must hold, register a hook in this file's frontmatter or add %s" % lever, cls=name)
                else:
                    F.add("enforcement", "warn", s, r.line, r.text,
                          "Enforcement-shaped (%s) but steering only: no hook or permission rule backs it, so the "
                          "model can weigh it and set it aside." % name,
                          "Add %s" % lever, cls=name)
                break


# ================================================================ output
def summarize(surfaces, F):
    counts = {c: {"error": 0, "warn": 0, "info": 0} for c in CHECKS}
    for f in F.items:
        counts[f["check"]][f["severity"]] += 1
    total_words = sum(s.words for s in surfaces if not s.error)
    instr_words = sum(s.instr_words for s in surfaces if not s.error)
    return {
        "surfaces": len(surfaces),
        "rules": sum(len(s.rules) for s in surfaces),
        "words": total_words,
        "instruction_words": instr_words,
        "instruction_share": round(instr_words / total_words, 3) if total_words else 0.0,
        "by_check": counts,
        "errors": sum(c["error"] for c in counts.values()),
        "warnings": sum(c["warn"] for c in counts.values()),
        "infos": sum(c["info"] for c in counts.values()),
    }


def trunc(t, n=150):
    t = t.replace("\n", " ")
    return t if len(t) <= n else t[:n - 1] + "…"


def render_md(root, surfaces, F, summary, only, show_rules):
    L = []
    L.append("# Instruction audit: %s" % root)
    L.append("")
    L.append("Deterministic read of the instruction surfaces (audit_instructions.py v%s, no model involved)." % VERSION)
    L.append("")
    L.append("**Verdict:** %d error(s), %d warning(s), %d info across %d surface(s), %d rules; instruction share "
             "%d%% of words (rest is scaffolding)." % (summary["errors"], summary["warnings"], summary["infos"],
                                                      summary["surfaces"], summary["rules"],
                                                      round(100 * summary["instruction_share"])))
    L.append("")
    L.append("## Surfaces")
    L.append("")
    L.append("| file | kind | loads | lines | words | instruction share | rules |")
    L.append("|---|---|---|---:|---:|---:|---:|")
    for s in surfaces:
        if s.error:
            L.append("| `%s` | %s | unreadable: %s | | | | |" % (s.rel, s.kind, s.error))
            continue
        share = round(100 * s.instr_words / s.words) if s.words else 0
        via = " (via @import from %s:%d)" % (s.importer.rel, s.import_line) if s.importer else ""
        scope = " [user]" if s.scope == "user" else ""
        L.append("| `%s`%s%s | %s | %s | %d | %d | %d%% | %d |" %
                 (s.rel, scope, via, s.kind, s.loads(), len(s.lines), s.words, share, len(s.rules)))
    L.append("")
    L.append("## Summary by check")
    L.append("")
    L.append("| check | error | warn | info |")
    L.append("|---|---:|---:|---:|")
    for c in CHECKS:
        if c not in only:
            continue
        cc = summary["by_check"][c]
        L.append("| %s | %d | %d | %d |" % (c, cc["error"], cc["warn"], cc["info"]))
    L.append("")
    order = {"error": 0, "warn": 1, "info": 2}
    for c in CHECKS:
        if c not in only:
            continue
        items = sorted((f for f in F.items if f["check"] == c), key=lambda f: (order[f["severity"]], f["file"], f["line"]))
        L.append("## %s (%d)" % (c, len(items)))
        L.append("")
        if not items:
            L.append("No findings.")
            L.append("")
            continue
        for f in items:
            loc = "`%s:%d`" % (f["file"], f["line"]) if f["file"] else ""
            head = "- **%s** %s" % (f["severity"], loc)
            if f["text"]:
                head += " — \"%s\"" % trunc(f["text"])
            L.append(head)
            L.append("  - %s" % f["detail"])
            if c == "conflicts":
                L.append("  - other: `%s:%d` — \"%s\"" % (f["meta"]["other_file"], f["meta"]["other_line"],
                                                          trunc(f["meta"]["other_text"])))
            L.append("  - fix: %s" % f["fix"])
        L.append("")
    if show_rules:
        L.append("## Extracted rules")
        L.append("")
        L.append("| loc | polarity | subjects | concrete | rule |")
        L.append("|---|---|---|---|---|")
        for s in surfaces:
            for r in s.rules:
                L.append("| `%s` | %s%s | %s | %s | %s |" % (
                    r.loc, r.polarity, " (exc)" if r.exc else "", ", ".join(sorted(r.subjects)) or "-",
                    ", ".join(r.strong) or ("domain noun" if r.domain else "-"), trunc(r.text, 120).replace("|", "\\|")))
        L.append("")
    return "\n".join(L)


def to_json(root, surfaces, F, summary, only, show_rules):
    out = {
        "version": VERSION, "root": str(root), "checks": only, "summary": summary,
        "surfaces": [{
            "file": s.rel, "kind": s.kind, "scope": s.scope, "loads": s.loads(), "always_on": s.always_on,
            "lines": len(s.lines), "words": s.words, "instruction_words": s.instr_words, "rules": len(s.rules),
            "paths": s.frontmatter.get("paths") if s.paths_scoped else None,
            "via_import": ("%s:%d" % (s.importer.rel, s.import_line)) if s.importer else None,
            "error": s.error,
        } for s in surfaces],
        "findings": [{k: v for k, v in f.items()} for f in F.items],
    }
    if show_rules:
        out["rules"] = [{
            "file": r.surface.rel, "line": r.line, "heading": r.heading, "text": r.text, "polarity": r.polarity,
            "exception": r.exc, "subjects": sorted(r.subjects), "concrete": r.strong, "domain_noun": r.domain,
            "vague": r.vague, "load_rank": r.surface.rank,
        } for s in surfaces for r in s.rules]
    return out


# ================================================================ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="project root (default: current directory)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    ap.add_argument("--json-out", metavar="FILE", help="also write JSON to FILE")
    ap.add_argument("--out", metavar="FILE", help="write the main output to FILE instead of stdout")
    ap.add_argument("--only", default=",".join(CHECKS), help="comma list of checks: " + ",".join(CHECKS))
    ap.add_argument("--rules", action="store_true", help="include the extracted rule inventory")
    ap.add_argument("--list", action="store_true", help="only list discovered surfaces")
    ap.add_argument("--no-user", action="store_true", help="skip ~/.claude/CLAUDE.md, ~/.claude/rules and user settings")
    ap.add_argument("--include", action="append", default=[], metavar="GLOB", help="extra files to audit (relative glob)")
    ap.add_argument("--exclude", action="append", default=[], metavar="GLOB", help="skip files matching GLOB")
    ap.add_argument("--max-lines", type=int, default=200, help="line budget for always-on files (default 200)")
    ap.add_argument("--max-pairs", type=int, default=60, help="cap on reported conflict pairs (default 60)")
    ap.add_argument("--fail-on", choices=["none", "warn", "error"], default="none",
                    help="exit 1 when findings of this severity or worse exist")
    args = ap.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    root = Path(args.root).resolve()
    if not root.is_dir():
        print("not a directory: %s" % root, file=sys.stderr)
        return 2
    only = [c.strip() for c in args.only.split(",") if c.strip() in CHECKS]
    surfaces = discover(root, include_user=not args.no_user, includes=args.include, excludes=args.exclude)
    for s in surfaces:
        load_surface(s)
    surfaces = resolve_imports(surfaces, root)
    surfaces.sort(key=lambda s: (s.scope != "user", s.rank, s.rel))

    if args.list:
        for s in surfaces:
            print("%-14s %-22s %s%s" % (s.kind, s.loads(), s.rel, " [user]" if s.scope == "user" else ""))
        return 0

    settings = load_settings(root, include_user=not args.no_user)
    F = Findings()
    if "bloat" in only:
        check_bloat(surfaces, F, args.max_lines)
    if "specificity" in only:
        check_specificity(surfaces, F)
    if "inverted" in only:
        check_inverted(surfaces, F)
    if "placement" in only:
        check_placement(surfaces, F, root)
    if "conflicts" in only:
        check_conflicts(surfaces, F, args.max_pairs)
    if "enforcement" in only:
        check_enforcement(surfaces, F, settings, root)
    summary = summarize(surfaces, F)

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(to_json(root, surfaces, F, summary, only, args.rules), fh, indent=2, ensure_ascii=False)
    if args.json:
        text = json.dumps(to_json(root, surfaces, F, summary, only, args.rules), indent=2, ensure_ascii=False)
    else:
        text = render_md(root, surfaces, F, summary, only, args.rules)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print("wrote %s (%d errors, %d warnings, %d info)" % (args.out, summary["errors"], summary["warnings"],
                                                              summary["infos"]))
    else:
        print(text)

    if args.fail_on == "error" and summary["errors"]:
        return 1
    if args.fail_on == "warn" and (summary["errors"] or summary["warnings"]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
