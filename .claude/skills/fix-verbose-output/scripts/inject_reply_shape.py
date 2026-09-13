#!/usr/bin/env python3
"""Inject the reply-shape fix for verbose output into a project.

Installs the levers from "Opus 5: How to Fix Verbose Output", weakest first,
up to the level asked for:

  rule    a "Reply shape" section in CLAUDE.md that names the shape, replacing
          vague brevity lines ("Be concise. No preamble.") that name nothing
  style   the rules as an output style in .claude/output-styles/, selected
          through the outputStyle setting so it rides in the system prompt;
          CLAUDE.md then carries a one-line pointer, not a second copy
  hook    (optional) a Stop hook in .claude/hooks/ that sends an over-long reply
          back once, wired into .claude/settings.json without touching other hooks
  plugin  a plugin directory that bundles the style and the hook for reuse

Levels are cumulative. Default is style; the hook is opt-in. Stdlib only, Python 3.8+.

  python inject_reply_shape.py <root> [--level rule|style|hook|plugin]
                               [--limit 180] [--hook-lang python|bash]
                               [--plugin-dir DIR] [--force] [--dry-run] [--json]
  python inject_reply_shape.py <root> --status [--json]

--status reports what is already installed (rule section, style, hook, plugin)
and whether this is a first install, without changing anything.

Existing files are never overwritten unless --force is given. Existing hooks,
permissions, and other settings keys are preserved. Every removed line is
reported with file:line and its text so it can be restored.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

LEVELS = ["rule", "style", "hook", "plugin"]
STYLE_NAME = "Reply shape"
HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = os.path.join(os.path.dirname(HERE), "templates")

# Phrases that ask for brevity without naming a shape. A line is removed only
# when every sentence on it is one of these; a line that also carries something
# else is reported and left in place.
VAGUE_PHRASE = re.compile(
    r"""^\s*(?:please\s+)?(?:
        be\s+(?:very\s+|extremely\s+|as\s+)?(?:concise|brief|terse|succinct|short)(?:\s+as\s+possible)?
      | (?:no|avoid|skip|without|omit|cut)\s+(?:the\s+)?(?:preamble|fluff|filler|verbosity|chatter|padding|small\s+talk)
      | (?:no|avoid)\s+verbose\s+(?:output|answers?|replies|responses?)
      | keep\s+(?:it|(?:your\s+)?(?:answers?|replies|responses?|output|messages?|explanations?))\s+(?:very\s+)?(?:short|brief|concise|terse|minimal|to\s+the\s+point)
      | (?:don'?t|do\s+not|never)\s+be\s+(?:verbose|wordy|chatty|long-winded)
      | (?:don'?t|do\s+not|never)\s+(?:over-?explain|ramble|pad(?:\s+(?:the\s+)?(?:answer|reply|response))?)
      | (?:short|brief|concise|terse|minimal)\s+(?:answers?|replies|responses?|output)(?:\s+only)?
      | answer\s+(?:concisely|briefly|tersely)
      | (?:concise|brief|terse|succinct)
      | less\s+(?:talking|talk|prose|text)
      | get\s+to\s+the\s+point
    )\s*$""",
    re.I | re.X,
)
VAGUE_ANY = re.compile(
    r"\b(?:be\s+(?:concise|brief|terse|succinct)|no\s+preamble|keep\s+(?:it|answers?|replies|responses?)\s+(?:short|brief|concise)"
    r"|(?:don'?t|do\s+not|never)\s+be\s+(?:verbose|wordy|chatty)|answer\s+(?:concisely|briefly))\b",
    re.I,
)
# A line that names any of these already carries a shape; never treat it as vague.
SHAPE_TOKENS = re.compile(
    r"first sentence|answer first|lead with|table|bullet|paragraph|\bwords?\b|\blines?\b|heading|list", re.I
)
BULLET = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
EMPH = re.compile(r"(\*\*|__|`|\*|_)")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
SECTION_TITLE = re.compile(r"^reply\s+shape$", re.I)
# One copy of the rules. At style level and above they live in the output style and
# CLAUDE.md carries this pointer for humans instead of a second copy.
POINTER = "Reply shape is set by the `Reply shape` output style (`.claude/output-styles/reply-shape.md`); edit the rules there."
POINTER_RE = re.compile(r"reply\s+shape.*output\s+style", re.I)


def read(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def write(path: str, text: str, dry: bool) -> None:
    if dry:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def rel(root: str, path: str) -> str:
    try:
        return os.path.relpath(path, root).replace(os.sep, "/")
    except ValueError:
        return path


class Report:
    def __init__(self, root: str, level: str, dry: bool) -> None:
        self.root = root
        self.level = level
        self.dry = dry
        self.actions: List[Dict[str, str]] = []
        self.removed: List[Dict[str, object]] = []
        self.notes: List[str] = []
        self.errors: List[str] = []

    def act(self, lever: str, target: str, action: str) -> None:
        self.actions.append({"lever": lever, "target": target, "action": action})

    def markdown(self) -> str:
        done = sorted({a["lever"] for a in self.actions if a["lever"] != "self-test"}, key=LEVELS.index)
        verb = "would install" if self.dry else "installed"
        out = [
            "**Verdict:** %s %d lever(s) (%s) in `%s`; %d vague brevity line(s) removed%s"
            % (
                verb,
                len(done),
                ", ".join(done) or "none",
                self.root,
                len(self.removed),
                "; %d error(s)" % len(self.errors) if self.errors else "",
            ),
            "",
            "| lever | target | action |",
            "|---|---|---|",
        ]
        for a in self.actions:
            out.append("| %s | `%s` | %s |" % (a["lever"], a["target"], a["action"]))
        if self.removed:
            out += ["", "Removed lines (restore any of them by hand):", ""]
            for r in self.removed:
                out.append("- `%s:%s` %s" % (r["file"], r["line"], r["text"]))
        if self.errors:
            out += ["", "Errors:", ""] + ["- " + e for e in self.errors]
        if self.notes:
            out += ["", "Next:", ""] + ["- " + n for n in self.notes]
        return "\n".join(out) + "\n"

    def json(self) -> str:
        return json.dumps(
            {
                "root": self.root,
                "level": self.level,
                "dry_run": self.dry,
                "actions": self.actions,
                "removed": self.removed,
                "notes": self.notes,
                "errors": self.errors,
            },
            indent=2,
        )


# ---------------------------------------------------------------- rule ------


def is_vague_line(line: str) -> Tuple[bool, bool]:
    """Return (fully_vague, partly_vague) for one CLAUDE.md line."""
    body = BULLET.sub("", line, count=1)
    body = EMPH.sub("", body).strip()
    if not body or body.startswith("#") or len(body) > 160:
        return False, False
    if SHAPE_TOKENS.search(body):
        return False, False
    parts = [p.strip() for p in re.split(r"[.;!:]+(?:\s+|$)", body) if p.strip()]
    if not parts:
        return False, False
    hits = [bool(VAGUE_PHRASE.match(p)) for p in parts]
    return all(hits), any(hits) or bool(VAGUE_ANY.search(body))


def find_section(lines: List[str]) -> Optional[Tuple[int, int, int]]:
    """Return (start, end, level) of an existing Reply shape section, end exclusive."""
    for i, line in enumerate(lines):
        m = HEADING.match(line)
        if m and SECTION_TITLE.match(m.group(2)):
            level = len(m.group(1))
            end = len(lines)
            for j in range(i + 1, len(lines)):
                m2 = HEADING.match(lines[j])
                if m2 and len(m2.group(1)) <= level:
                    end = j
                    break
            return i, end, level
    return None


def install_rule(root: str, rep: Report, pointer: bool) -> None:
    """Full section at rule level; a one-line pointer once the output style is the copy."""
    template = read(os.path.join(TEMPLATES, "reply-shape.rule.md")).rstrip("\n").split("\n")
    candidates = [os.path.join(root, "CLAUDE.md"), os.path.join(root, ".claude", "CLAUDE.md")]
    existing = [p for p in candidates if os.path.isfile(p)]
    path = existing[0] if existing else candidates[0]
    target = rel(root, path)

    if not existing:
        if pointer:
            rep.act("rule", target, "absent; nothing to point from (the rules live in the output style)")
            return
        write(path, "\n".join(template) + "\n", rep.dry)
        rep.act("rule", target, "created with the Reply shape section")
        return

    original = read(path)
    lines = original.split("\n")
    kept: List[str] = []
    changed = False
    for idx, line in enumerate(lines, start=1):
        fully, partly = is_vague_line(line)
        if fully:
            rep.removed.append({"file": target, "line": idx, "text": line.strip()})
            rep.act("rule", "%s:%d" % (target, idx), "removed vague brevity line: %s" % line.strip())
            changed = True
            continue
        if partly:
            rep.act("rule", "%s:%d" % (target, idx), "left in place; carries a vague brevity phrase next to something else. Edit by hand.")
        kept.append(line)
    lines = kept

    sec = find_section(lines)
    pointer_at = next((i for i, l in enumerate(lines) if POINTER_RE.search(l) and not HEADING.match(l)), None)

    if pointer:
        if sec:
            start, end, _ = sec
            tail = lines[end:]
            lines = lines[:start] + [POINTER] + ([""] if tail and tail[0].strip() else []) + tail
            rep.act("rule", "%s:%d" % (target, start + 1), "collapsed the Reply shape section to a pointer; the rules now live only in the output style")
            changed = True
        elif pointer_at is not None:
            rep.act("rule", target, "pointer to the output style already present; unchanged")
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines = lines + ["", POINTER] if lines else [POINTER]
            rep.act("rule", target, "added a one-line pointer to the output style (no second copy of the rules)")
            changed = True
    else:
        block = list(template)
        if pointer_at is not None and not sec:
            del lines[pointer_at]
            rep.act("rule", "%s:%d" % (target, pointer_at + 1), "removed the pointer line; the full section replaces it")
            changed = True
        if sec:
            start, end, level = sec
            block[0] = "#" * level + " " + STYLE_NAME
            current = [l for l in lines[start:end] if l.strip()]
            wanted = [l for l in block if l.strip()]
            if current == wanted:
                rep.act("rule", target, "Reply shape section already present; unchanged")
            else:
                tail = lines[end:]
                lines = lines[:start] + block + ([""] if tail and tail[0].strip() else []) + tail
                rep.act("rule", "%s:%d" % (target, start + 1), "replaced the existing Reply shape section")
                changed = True
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines = lines + ["", ""] + block if lines else block
            rep.act("rule", target, "appended the Reply shape section at the end (the later rule wins under recency)")
            changed = True

    if changed:
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).rstrip("\n") + "\n"
        write(path, text, rep.dry)


# --------------------------------------------------------------- style ------


def load_settings(path: str, rep: Report) -> Optional[dict]:
    if not os.path.isfile(path):
        return {}
    try:
        data = json.loads(read(path))
    except Exception as e:  # malformed or commented JSON: do not clobber it
        rep.errors.append("%s is not strict JSON (%s); settings were left untouched." % (path, e))
        return None
    if not isinstance(data, dict):
        rep.errors.append("%s does not hold a JSON object; settings were left untouched." % path)
        return None
    return data


def save_settings(path: str, data: dict, dry: bool) -> None:
    write(path, json.dumps(data, indent=2) + "\n", dry)


def place_file(src_text: str, dest: str, root: str, lever: str, rep: Report, force: bool, executable: bool = False) -> bool:
    target = rel(root, dest)
    if os.path.isfile(dest):
        if read(dest) == src_text:
            rep.act(lever, target, "already present; unchanged")
            return False
        if not force:
            rep.act(lever, target, "exists with different content; left as is (pass --force to overwrite)")
            return False
        write(dest, src_text, rep.dry)
        rep.act(lever, target, "overwritten (--force)")
    else:
        write(dest, src_text, rep.dry)
        rep.act(lever, target, "created")
    if executable and not rep.dry and os.name != "nt":
        os.chmod(dest, os.stat(dest).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return True


def install_style(root: str, rep: Report, force: bool) -> None:
    style = read(os.path.join(TEMPLATES, "reply-shape.style.md"))
    dest = os.path.join(root, ".claude", "output-styles", "reply-shape.md")
    wrote_style = place_file(style, dest, root, "style", rep, force)

    settings_path = os.path.join(root, ".claude", "settings.json")
    data = load_settings(settings_path, rep)
    target = rel(root, settings_path) + " outputStyle"
    if data is not None:
        current = data.get("outputStyle")
        if current == STYLE_NAME:
            rep.act("style", target, "already %r; unchanged" % STYLE_NAME)
        elif current is None or force:
            data["outputStyle"] = STYLE_NAME
            save_settings(settings_path, data, rep.dry)
            rep.act("style", target, "set to %r" % STYLE_NAME if current is None else "changed from %r to %r (--force)" % (current, STYLE_NAME))
        else:
            rep.act("style", target, "is %r; left as is. Pick %r under /config or pass --force." % (current, STYLE_NAME))

    local_path = os.path.join(root, ".claude", "settings.local.json")
    if os.path.isfile(local_path):
        try:
            local = json.loads(read(local_path))
        except Exception:
            local = {}
        if isinstance(local, dict) and local.get("outputStyle") not in (None, STYLE_NAME):
            rep.act(
                "style",
                rel(root, local_path) + " outputStyle",
                "is %r and overrides settings.json; switch it under /config" % local["outputStyle"],
            )
    if wrote_style:
        rep.notes.append("Restart Claude Code so it reads the new output style file; the style then applies from the next message.")


# ---------------------------------------------------------------- hook ------


def hook_source(lang: str, limit: int) -> Tuple[str, str]:
    if lang == "bash":
        text = read(os.path.join(TEMPLATES, "gate-length.sh"))
        text = re.sub(r"^limit=\d+", "limit=%d" % limit, text, count=1, flags=re.M)
        return "gate-length.sh", text
    text = read(os.path.join(TEMPLATES, "gate_length.py"))
    text = re.sub(r"^LIMIT_WORDS = \d+", "LIMIT_WORDS = %d" % limit, text, count=1, flags=re.M)
    return "gate_length.py", text


def hook_command(name: str, var: str) -> str:
    if name.endswith(".py"):
        return 'python "${%s}/%s"' % (var, name)
    return '"${%s}/%s"' % (var, name)


def stop_hook_present(hooks: dict) -> bool:
    for group in hooks.get("Stop", []) or []:
        for h in (group or {}).get("hooks", []) or []:
            cmd = str((h or {}).get("command", ""))
            if "gate_length" in cmd or "gate-length" in cmd:
                return True
    return False


def install_hook(root: str, rep: Report, limit: int, lang: str, force: bool) -> Optional[str]:
    name, text = hook_source(lang, limit)
    dest = os.path.join(root, ".claude", "hooks", name)
    place_file(text, dest, root, "hook", rep, force, executable=name.endswith(".sh"))

    settings_path = os.path.join(root, ".claude", "settings.json")
    data = load_settings(settings_path, rep)
    target = rel(root, settings_path) + " hooks.Stop"
    if data is None:
        return dest
    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
        data["hooks"] = hooks
    if stop_hook_present(hooks):
        rep.act("hook", target, "already references the length gate; unchanged")
    else:
        stop = hooks.get("Stop")
        if not isinstance(stop, list):
            stop = []
            hooks["Stop"] = stop
        stop.append({"hooks": [{"type": "command", "command": hook_command(".claude/hooks/" + name, "CLAUDE_PROJECT_DIR")}]})
        save_settings(settings_path, data, rep.dry)
        rep.act("hook", target, "added the length gate (%d-word budget); other hooks kept" % limit)
    rep.notes.append("Hooks in settings.json are picked up by the file watcher; run /hooks if the gate does not show. Edit LIMIT_WORDS in the hook to change the budget.")
    return dest


def self_test(hook_path: str, limit: int, rep: Report) -> None:
    if not os.path.isfile(hook_path):
        return
    if hook_path.endswith(".py"):
        cmd = [sys.executable, hook_path]
    else:
        cmd = ["bash", hook_path]
    long_reply = " ".join(["word"] * (limit * 2 + 12))
    cases = [
        ("%d-word reply" % (limit * 2 + 12), {"hook_event_name": "Stop", "last_assistant_message": long_reply}, 2),
        ("short reply", {"hook_event_name": "Stop", "last_assistant_message": "Done. The test passes now."}, 0),
        ("second pass (stop_hook_active)", {"hook_event_name": "Stop", "stop_hook_active": True, "last_assistant_message": long_reply}, 0),
    ]
    results = []
    for label, payload, expected in cases:
        try:
            proc = subprocess.run(cmd, input=json.dumps(payload), capture_output=True, text=True, timeout=30)
            code = proc.returncode
        except Exception as e:
            rep.errors.append("self-test could not run the hook: %s" % e)
            return
        ok = code == expected
        results.append("%s exit %d %s" % (label, code, "ok" if ok else "expected %d" % expected))
        if not ok:
            rep.errors.append("hook self-test failed: %s returned %d, expected %d. stderr: %s" % (label, code, expected, proc.stderr.strip()[:200]))
    rep.act("self-test", rel(rep.root, hook_path), "; ".join(results))


# -------------------------------------------------------------- plugin ------


def install_plugin(root: str, rep: Report, plugin_dir: str, limit: int, lang: str, force: bool) -> None:
    name, text = hook_source(lang, limit)
    manifest = read(os.path.join(TEMPLATES, "plugin.json"))
    hooks_json = json.dumps(
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": hook_command("hooks/" + name, "CLAUDE_PLUGIN_ROOT")}]}]}},
        indent=2,
    ) + "\n"
    style = read(os.path.join(TEMPLATES, "reply-shape.style.md"))
    rule = read(os.path.join(TEMPLATES, "reply-shape.rule.md"))
    readme = (
        "# Reply shape plugin\n\n"
        "Bundles the output style and the Stop hook from \"Opus 5: How to Fix Verbose Output\" so the setup travels across projects.\n\n"
        "Test: `claude --plugin-dir %s`\n\n"
        "Then pick `Reply shape` under /config, or add `force-for-plugin: true` to `output-styles/reply-shape.md` to apply it whenever the plugin is enabled.\n\n"
        "Keep one copy of the rules. With the plugin's style selected, CLAUDE.md should carry only a pointer line, not these rules again. "
        "In a project that does not use the plugin, `/fix-verbose-output rule` writes them into CLAUDE.md instead.\n\n"
        "For reference, the rules the style carries:\n\n%s"
    ) % (rel(root, plugin_dir) or ".", rule)
    files = [
        (os.path.join(plugin_dir, ".claude-plugin", "plugin.json"), manifest, False),
        (os.path.join(plugin_dir, "hooks", "hooks.json"), hooks_json, False),
        (os.path.join(plugin_dir, "hooks", name), text, name.endswith(".sh")),
        (os.path.join(plugin_dir, "output-styles", "reply-shape.md"), style, False),
        (os.path.join(plugin_dir, "README.md"), readme, False),
    ]
    for dest, content, execu in files:
        place_file(content, dest, root, "plugin", rep, force, executable=execu)
    rep.notes.append("Test the plugin with `claude --plugin-dir %s`; install it from a marketplace with /plugin install once it is published." % (rel(root, plugin_dir) or "."))


# -------------------------------------------------------------- status ------


def status(root: str) -> dict:
    """What this skill has already put in the project. Changes nothing."""
    candidates = [os.path.join(root, "CLAUDE.md"), os.path.join(root, ".claude", "CLAUDE.md")]
    claude_md = next((p for p in candidates if os.path.isfile(p)), None)
    rule_present = False
    pointer_present = False
    vague: List[Dict[str, object]] = []
    if claude_md:
        lines = read(claude_md).split("\n")
        rule_present = find_section(lines) is not None
        pointer_present = any(POINTER_RE.search(l) and not HEADING.match(l) for l in lines)
        for idx, line in enumerate(lines, start=1):
            fully, partly = is_vague_line(line)
            if fully or partly:
                vague.append({"file": rel(root, claude_md), "line": idx, "text": line.strip(), "removable": fully})

    style_present = os.path.isfile(os.path.join(root, ".claude", "output-styles", "reply-shape.md"))

    def read_json(path: str) -> dict:
        if not os.path.isfile(path):
            return {}
        try:
            data = json.loads(read(path))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    settings = read_json(os.path.join(root, ".claude", "settings.json"))
    local = read_json(os.path.join(root, ".claude", "settings.local.json"))
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    hook_dir = os.path.join(root, ".claude", "hooks")
    hook_file = any(os.path.isfile(os.path.join(hook_dir, n)) for n in ("gate_length.py", "gate-length.sh"))
    hook_wired = stop_hook_present(hooks)
    plugin_present = os.path.isfile(os.path.join(root, "reply-shape-plugin", ".claude-plugin", "plugin.json"))

    return {
        "root": root,
        "claude_md": rel(root, claude_md) if claude_md else None,
        "rule_present": rule_present,
        "pointer_present": pointer_present,
        "vague_lines": vague,
        "style_present": style_present,
        "output_style": settings.get("outputStyle"),
        "output_style_local": local.get("outputStyle"),
        "hook_file": hook_file,
        "hook_wired": hook_wired,
        "hook_present": hook_file and hook_wired,
        "plugin_present": plugin_present,
        "duplicate_copy": rule_present and style_present,
        "first_install": not rule_present and not pointer_present and not style_present,
    }


def status_markdown(st: dict) -> str:
    yes = lambda b: "yes" if b else "no"  # noqa: E731
    out = [
        "**Status:** %s in `%s`"
        % ("first install; nothing from this skill is present" if st["first_install"] else "already installed in part or in full", st["root"]),
        "",
        "| component | present |",
        "|---|---|",
        "| Reply shape in %s | %s |"
        % (
            st["claude_md"] or "CLAUDE.md (missing)",
            "full section AND output style (duplicate; run --level style to collapse)" if st["duplicate_copy"]
            else "full section" if st["rule_present"]
            else "pointer to the output style" if st["pointer_present"]
            else "no",
        ),
        "| vague brevity lines | %d (%d removable) |" % (len(st["vague_lines"]), sum(1 for v in st["vague_lines"] if v["removable"])),
        "| output style file | %s |" % yes(st["style_present"]),
        "| outputStyle in settings.json | %s |" % (st["output_style"] or "unset"),
        "| outputStyle in settings.local.json | %s |" % (st["output_style_local"] or "unset"),
        "| Stop hook (file + wiring) | %s |" % yes(st["hook_present"]),
        "| plugin directory | %s |" % yes(st["plugin_present"]),
    ]
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main ------


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("root", nargs="?", default=".", help="project root (default: current directory)")
    ap.add_argument("--level", choices=LEVELS, default="style", help="how far up the ladder to go (cumulative; default style, the Stop hook is opt-in)")
    ap.add_argument("--status", action="store_true", help="report what is already installed and stop; changes nothing")
    ap.add_argument("--limit", type=int, default=180, help="word budget for the Stop hook (default 180)")
    ap.add_argument("--hook-lang", choices=["python", "bash"], default="python", help="hook implementation (default python; bash needs jq)")
    ap.add_argument("--plugin-dir", default=None, help="where to build the plugin (default <root>/reply-shape-plugin)")
    ap.add_argument("--force", action="store_true", help="overwrite existing files and an existing outputStyle value")
    ap.add_argument("--dry-run", action="store_true", help="report what would change without writing")
    ap.add_argument("--no-self-test", action="store_true", help="skip running the installed hook with sample payloads")
    ap.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.stderr.write("not a directory: %s\n" % root)
        return 2
    if not os.path.isdir(TEMPLATES):
        sys.stderr.write("templates directory missing: %s\n" % TEMPLATES)
        return 2

    if args.status:
        st = status(root)
        sys.stdout.write(json.dumps(st, indent=2) + "\n" if args.json else status_markdown(st))
        return 0

    rep = Report(root, args.level, args.dry_run)
    depth = LEVELS.index(args.level)

    style_exists = os.path.isfile(os.path.join(root, ".claude", "output-styles", "reply-shape.md"))
    if depth == 0 and style_exists:
        rep.notes.append("The output style already carries the rules, so CLAUDE.md keeps a pointer instead of a second copy. Delete the style first if you want the rules in CLAUDE.md only.")
    install_rule(root, rep, pointer=depth >= 1 or style_exists)
    if depth >= 1:
        install_style(root, rep, args.force)
    hook_path = None
    if depth >= 2:
        hook_path = install_hook(root, rep, args.limit, args.hook_lang, args.force)
    if depth >= 3:
        plugin_dir = os.path.abspath(args.plugin_dir) if args.plugin_dir else os.path.join(root, "reply-shape-plugin")
        install_plugin(root, rep, plugin_dir, args.limit, args.hook_lang, args.force)
    if hook_path and not args.dry_run and not args.no_self_test:
        self_test(hook_path, args.limit, rep)

    if depth == 0:
        rep.notes.append("A CLAUDE.md rule is advice and competes with everything else in context; add --level style if it does not hold.")
    if depth < 2 and not status(root)["hook_present"]:
        rep.notes.append("The Stop hook is optional and not installed. Add it with --level hook when you want a length floor the model cannot talk past.")

    sys.stdout.write(rep.json() if args.json else rep.markdown())
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
