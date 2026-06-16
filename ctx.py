#!/usr/bin/env python3
"""ctx.py - Token-Value Ledger (TVL): context-budget toolkit for coding agents.

Cross-harness prototype (Claude Code / Codex). Stdlib only; the `anthropic`
package is used opportunistically for exact token counts when available.

Subcommands:
  map [path]          repo map with per-file token estimates (what is expensive to read)
  digest <file>       structural digest of a file instead of a full read
  run -- <command>    run a noisy command, print only the salient extract; full log saved
  count <file|->      token count of a file or stdin (exact via API if key present)
  rawcount <path|->   token count of unsqueezed text with no compression or ledger savings
"""

from __future__ import annotations

__version__ = "0.0.3"

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

# Rough chars-per-token for code/mixed text. Real tokenizers vary (Fable 5
# tokenizes ~30% denser input into ~30% MORE tokens than Opus-tier), so this
# is a planning estimate, not a billing number.
CHARS_PER_TOKEN = 3.5

SKIP_DIRS = {
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".ctx", "dist", "build", ".idea", ".vscode", ".pytest_cache", ".mypy_cache",
    "target", "vendor", ".next", "coverage", "release", ".codegraph", ".obsidian",
    ".claude",
}
SKIP_FILES = {"package-lock.json", "src/assets/manifest.json"}
BINARY_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz",
    ".tar", ".7z", ".exe", ".dll", ".so", ".dylib", ".woff", ".woff2", ".ttf",
    ".mp3", ".mp4", ".sqlite", ".db", ".pyc", ".class", ".jar", ".lock",
}

ERROR_RE = re.compile(
    r"(error|exception|traceback|failed|failure|fatal|panic|assert"
    r"|FAIL|ERROR|E\d{3,4}\b|warning C\d+|\bnpm ERR!)",
    re.IGNORECASE,
)

MEMORY_REQUIRED = (
    "MEMORY.md",
    "project-rules.md",
    "architecture.md",
    "decisions.md",
    "bugs.md",
    "investigations.md",
    "operations.md",
    "changelog.md",
    "archive/tasks",
    "archive/bugs",
    "archive/decisions",
    "archive/investigations",
    "templates/task.md",
    "templates/bug.md",
    "templates/decision.md",
    "templates/investigation.md",
    ".obsidian/app.json",
    ".obsidian/templates.json",
    ".gitignore",
    ".rules.sha256",
)
MEMORY_DIRECTORIES = {
    "archive/tasks",
    "archive/bugs",
    "archive/decisions",
    "archive/investigations",
}
MEMORY_LINE_LIMIT = 120
JOURNAL_MAX_TOKENS = 8000
JOURNAL_TARGET_TOKENS = 5000
MEMORY_JOURNALS = {
    "bugs.md": "bugs",
    "decisions.md": "decisions",
    "investigations.md": "investigations",
}
WIKI_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
ENTRY_RE = re.compile(r"(?m)^##\s+((?:BUG|DEC|INV)-[^\n]+)\n")

MEMORY_TEMPLATES = {
    "MEMORY.md": """# Project Memory

> Read this index at session start. Open linked notes only when needed.

## Project

- Goal:
- Current state:
- Primary stack:
- User overview:

## Start Here

- Active tasks: [[../handoff]]
- Permanent rules: [[project-rules]]
- Architecture: [[architecture]]
- Operations: [[operations]]

## Logs

- Decisions: [[decisions]]
- Bugs: [[bugs]]
- Investigations: [[investigations]]
- Changes: [[changelog]]

## Retrieval

- Code relationships: `codegraph context "<task>"`
- Broad memory question: `python ctx.py memory query "<question>"`
- Broad project question: `python ctx.py memory query "<question>" --scope project`
- First bootstrap: `python ctx.py memory open --install-obsidian`
""",
    "project-rules.md": """# Permanent Project Rules

> Agents must not edit or delete these rules without explicit user instruction
> or confirmation. After an approved change, run
> `python ctx.py memory rules-approve --user-approved`.

## RULE-001

- Status: active
- Rule: Preserve existing behavior unless the task explicitly requires a change.

## RULE-002

- Status: active
- Rule: After memory initialization, run
  `python ctx.py memory open --install-obsidian` once for project bootstrap.
""",
    "architecture.md": "# Architecture\n\nProject architecture and stable component boundaries.\n",
    "decisions.md": "# Decision Log\n\n## DEC-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Decision:\n- Reason:\n- Consequences:\n- Links:\n",
    "bugs.md": "# Bug Log\n\n## BUG-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Symptom:\n- Cause:\n- Resolution:\n- Regression test:\n- Links:\n",
    "investigations.md": "# Investigation Log\n\n## INV-000 Template\n\n- Status: example\n- Date: YYYY-MM-DD\n- Question:\n- Findings:\n- Conclusion:\n- Links:\n",
    "operations.md": "# Operations\n\nCommands, verification steps, and operational constraints.\n",
    "changelog.md": "# Memory Changelog\n\nRecord meaningful changes to the memory system.\n",
    "templates/task.md": """## TASK-YYYYMMDD-NNN

- Status: next
- Goal:
- Acceptance:
- Links:
""",
    "templates/bug.md": """## BUG-YYYYMMDD-NNN

- Status: open
- Date: YYYY-MM-DD
- Symptom:
- Cause:
- Resolution:
- Regression test:
- Links:
""",
    "templates/decision.md": """## DEC-YYYYMMDD-NNN

- Status: active
- Date: YYYY-MM-DD
- Decision:
- Reason:
- Consequences:
- Links:
""",
    "templates/investigation.md": """## INV-YYYYMMDD-NNN

- Status: open
- Date: YYYY-MM-DD
- Question:
- Findings:
- Conclusion:
- Links:
""",
    ".obsidian/app.json": json.dumps({
        "newFileLocation": "folder",
        "newFileFolderPath": "memory",
        "useMarkdownLinks": False,
        "alwaysUpdateLinks": True,
    }, indent=2) + "\n",
    ".obsidian/templates.json": json.dumps({
        "folder": "templates",
        "dateFormat": "YYYY-MM-DD",
        "timeFormat": "HH:mm",
    }, indent=2) + "\n",
    ".gitignore": "workspace.json\nworkspace-mobile.json\ncache\n",
}
ROOT_GITIGNORE_TEMPLATE = """.ctx/
.codegraph/
__pycache__/
node_modules/
dist/
build/
coverage/
.env
.env.*
"""


def est_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN))


def exact_tokens(text: str) -> tuple[int, str]:
    """Return (tokens, method). Uses the Anthropic count_tokens endpoint when
    the SDK and ANTHROPIC_API_KEY are available; falls back to the heuristic."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            import anthropic  # type: ignore

            client = anthropic.Anthropic()
            resp = client.messages.count_tokens(
                model="claude-opus-4-8",
                messages=[{"role": "user", "content": text or " "}],
            )
            return resp.input_tokens, "api:claude-opus-4-8"
        except Exception as exc:  # network/SDK issues must never break the tool
            sys.stderr.write(f"[ctx] count_tokens unavailable ({exc}); using heuristic\n")
    return est_tokens(text), "heuristic(chars/3.5)"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


LEDGER_PATH = Path(".ctx") / "ledger.jsonl"


# Ops that pull full, uncompressed content into the agent's context. They are
# the denominator for the honest savings percentage: every token a `read`
# admits is context that ctx did NOT compress, so it dilutes the headline ratio
# instead of being silently excluded like a direct Read would be.
RAW_OPS = frozenset({"read", "direct"})

# Orientation ops whose "raw" side is a hypothetical read-everything cost rather
# than a real 1:1 content substitution. They stay in the per-op table for
# visibility but are kept out of the headline savings % so it cannot be inflated
# by a denominator the agent would never actually have paid.
RECON_OPS = frozenset({"map"})


def ledger_log(op: str, raw_tok: int, kept_tok: int, detail: str,
               **extra: object) -> None:
    """Append a savings record to the ledger.

    Written exclusively by this tool (deterministic code) — the model never
    computes or edits these numbers, so `ctx.py report` measures the effect
    independently of the agent's own claims. `extra` carries optional, schema-v2
    fields (provider/model/calls/path/exit_code); None values are dropped so old
    readers and aggregates keep working."""
    try:
        LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        rec: dict[str, object] = {
            "v": 2,
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "op": op,
            "raw_tokens": raw_tok,
            "kept_tokens": kept_tok,
            "saved_tokens": max(0, raw_tok - kept_tok),
            "detail": detail,
        }
        rec.update({k: v for k, v in extra.items() if v is not None})
        with LEDGER_PATH.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        sys.stderr.write(f"[ctx] ledger write failed: {exc}\n")


# ----------------------------------------------------------------- map ----

def cmd_map(args: argparse.Namespace) -> int:
    root = Path(args.path).resolve()
    rows: list[tuple[int, int, str]] = []  # (tokens, lines, relpath)
    total_tokens = 0
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            relpath = p.relative_to(root).as_posix()
            if name in SKIP_FILES or relpath in SKIP_FILES:
                skipped += 1
                continue
            if p.suffix.lower() in BINARY_EXT:
                skipped += 1
                continue
            try:
                text = read_text(p)
            except OSError:
                skipped += 1
                continue
            tok = est_tokens(text)
            total_tokens += tok
            rows.append((tok, text.count("\n") + 1, str(p.relative_to(root))))

    rows.sort(reverse=True)
    out: list[str] = []
    out.append(f"# repo map: {root}")
    out.append(f"# files: {len(rows)} (skipped {skipped} binary/unreadable), "
               f"~{total_tokens:,} tokens total to read everything")
    out.append(f"{'~tokens':>9}  {'lines':>6}  path")
    shown = rows if args.all else rows[: args.top]
    for tok, lines, rel in shown:
        flag = "  <- EXPENSIVE, prefer `ctx.py digest`" if tok >= args.warn else ""
        out.append(f"{tok:>9,}  {lines:>6}  {rel}{flag}")
    if not args.all and len(rows) > args.top:
        rest = sum(t for t, _, _ in rows[args.top:])
        out.append(f"      ...   {len(rows) - args.top} more files, ~{rest:,} tokens (use --all)")
    rendered = "\n".join(out)
    # Orienting via the map costs the printed listing instead of reading every
    # file; log that gap so recon shows up in the savings report too.
    ledger_log("map", total_tokens, est_tokens(rendered), str(root),
               files=len(rows))
    print(rendered)
    return 0


# -------------------------------------------------------------- digest ----

PY_KEEP = re.compile(r"^\s*(def |class |async def |import |from |@)")
GENERIC_KEEP = re.compile(
    r"^\s*(def |class |function |func |fn |interface |struct |enum |type "
    r"|import |from |export |const [A-Z_]+|public |private |protected "
    r"|#{1,3} |// ---|/\*\*|describe\(|it\(|test\()"
)


def digest_python(text: str) -> list[str]:
    """AST-based digest: imports, class/def signatures, first docstring lines."""
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return [ln for ln in text.splitlines() if PY_KEEP.match(ln)]

    lines = text.splitlines()
    out: list[str] = []
    doc = ast.get_docstring(tree)
    if doc:
        out.append('"""' + doc.splitlines()[0] + '"""')
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            ln = lines[node.lineno - 1].rstrip()
            indent = len(ln) - len(ln.lstrip())
            out.append((indent, node.lineno, ln))  # type: ignore[arg-type]
    # keep source order for tuple entries, strings (docstring) stay first
    sigs = sorted((e for e in out if isinstance(e, tuple)), key=lambda t: t[1])
    head = [e for e in out if isinstance(e, str)]
    return head + [t[2] for t in sigs]


def cmd_digest(args: argparse.Namespace) -> int:
    p = Path(args.file)
    if not p.is_file():
        sys.stderr.write(f"[ctx] not a file: {p}\n")
        return 2
    text = read_text(p)
    full_tok = est_tokens(text)
    if p.suffix == ".py":
        kept = digest_python(text)
    else:
        kept = [ln.rstrip() for ln in text.splitlines() if GENERIC_KEEP.match(ln)]
        if not kept:  # unknown structure: head + tail beats nothing
            ls = text.splitlines()
            kept = ls[:15] + (["..."] + ls[-5:] if len(ls) > 20 else [])
    digest = "\n".join(kept)
    dig_tok = est_tokens(digest)
    ledger_log("digest", full_tok, dig_tok, str(p))
    print(f"# digest of {p} -- ~{dig_tok:,} tokens instead of ~{full_tok:,} "
          f"({full_tok / max(dig_tok, 1):.1f}x saving); read the full file only if needed")
    print(digest)
    return 0


# ----------------------------------------------------------------- run ----

def cmd_run(args: argparse.Namespace) -> int:
    if not args.command:
        sys.stderr.write("[ctx] usage: ctx.py run -- <command...>\n")
        return 2
    cmdline = subprocess.list2cmdline(args.command) if os.name == "nt" else " ".join(args.command)
    proc = subprocess.run(cmdline, shell=True, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    raw = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr else "")
    raw_lines = raw.splitlines()

    log_dir = Path(".ctx") / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = log_dir / f"{stamp}.log"
    log_path.write_text(f"$ {cmdline}\nexit={proc.returncode}\n\n{raw}",
                        encoding="utf-8")

    # extract: every error-ish line (capped) + the tail
    err_idx = [i for i, ln in enumerate(raw_lines) if ERROR_RE.search(ln)]
    keep: dict[int, str] = {}
    for i in err_idx[: args.max_errors]:
        for j in range(max(0, i - args.ctx_lines), min(len(raw_lines), i + args.ctx_lines + 1)):
            keep[j] = raw_lines[j]
    for j in range(max(0, len(raw_lines) - args.tail), len(raw_lines)):
        keep[j] = raw_lines[j]

    shown_lines: list[str] = []
    prev = None
    for j in sorted(keep):
        if prev is not None and j > prev + 1:
            shown_lines.append(f"  ... [{j - prev - 1} lines omitted, see {log_path}]")
        shown_lines.append(keep[j])
        prev = j
    shown = "\n".join(shown_lines)

    raw_tok, shown_tok = est_tokens(raw), est_tokens(shown) if shown else 0
    ledger_log("run", raw_tok, shown_tok, cmdline)
    print(shown)
    print(f"\n# exit={proc.returncode} | {len(raw_lines)} lines -> {len(keep)} shown "
          f"| ~{raw_tok:,} -> ~{shown_tok:,} tokens "
          f"({raw_tok / max(shown_tok, 1):.1f}x saving) | full log: {log_path}")
    return proc.returncode


# --------------------------------------------------------------- count ----

def cmd_count(args: argparse.Namespace) -> int:
    if args.file == "-":
        text = sys.stdin.read()
        label = "<stdin>"
    else:
        p = Path(args.file)
        if not p.is_file():
            sys.stderr.write(f"[ctx] not a file: {p}\n")
            return 2
        text = read_text(p)
        label = str(p)
    tok, method = exact_tokens(text)
    print(f"{label}: {tok:,} tokens ({method}), {len(text):,} chars")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    """Print a file verbatim and record it as uncompressed context pulled in.

    Use this instead of a plain editor read when you genuinely need the whole
    file: it gives the agent the same bytes, but logs the pull so `ctx report`
    can show what fraction of context actually went through a compressor versus
    being admitted raw. Raw reads have no saving — they are the honest
    denominator of the savings percentage."""
    p = Path(args.file)
    if not p.is_file():
        sys.stderr.write(f"[ctx] not a file: {p}\n")
        return 2
    text = read_text(p)
    tok = est_tokens(text)
    ledger_log("read", tok, tok, str(p))
    sys.stdout.write(text)
    if text and not text.endswith("\n"):
        sys.stdout.write("\n")
    print(f"# read {p} verbatim -- ~{tok:,} tokens admitted uncompressed "
          f"(prefer `ctx.py digest` for structure or `rlm` for an answer)")
    return 0


def _hook_tokens_and_label(event: dict) -> tuple[int, str]:
    """Estimate the context tokens an agent tool call admitted, plus a label.

    Reads the Claude Code PostToolUse payload. We count the tool RESPONSE (what
    actually entered the agent's context), falling back to the read target's
    size. Returns (0, ...) when there is nothing to charge."""
    tool = str(event.get("tool_name", "") or "")
    resp = event.get("tool_response")
    text = ""
    if isinstance(resp, str):
        text = resp
    elif isinstance(resp, dict):
        # Read returns {"file": {"content": ...}}; Bash returns stdout/stderr.
        for key in ("content", "stdout", "output", "stderr"):
            val = resp.get(key)
            if isinstance(val, str):
                text += val
        if not text:
            inner = resp.get("file")
            if isinstance(inner, dict) and isinstance(inner.get("content"), str):
                text = inner["content"]
    if not text:
        # Pre-run or content-less event: fall back to the file being read.
        fp = (event.get("tool_input") or {}).get("file_path")
        if isinstance(fp, str) and Path(fp).is_file():
            try:
                text = read_text(Path(fp))
            except OSError:
                text = ""
    return est_tokens(text), tool or "tool"


def cmd_hook(args: argparse.Namespace) -> int:
    """Passively record context pulled by a direct agent tool call (Read/Bash).

    Wire this as a Claude Code PostToolUse hook so reads that bypass ctx still
    land in the savings denominator -- otherwise `ctx report` coverage only
    reflects pulls the agent voluntarily routed through `ctx read`. Always exits
    0 and prints nothing: a hook must never break or slow the agent loop."""
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict):
            return 0
        tok, label = _hook_tokens_and_label(event)
        if tok >= args.min_tokens:
            ledger_log("direct", tok, tok, f"{label} (bypassed ctx)",
                       session=event.get("session_id"))
    except Exception:  # a hook must be silent and harmless on any malformed input
        pass
    return 0


def cmd_rawcount(args: argparse.Namespace) -> int:
    """Report the full unsqueezed context size for a file, directory, or stdin.

    Unlike digest/run/rlm this does not compress, summarize, send content to an
    LLM, or write savings records. It is a baseline meter for A/B comparisons.
    """
    skipped_secrets: list[str] = []
    if args.path == "-":
        text = sys.stdin.read()
        label = "<stdin>"
        files = 1
    else:
        p = Path(args.path)
        label = str(p)
        if p.is_dir():
            text, files, skipped_secrets = collect_context(
                p, include_secrets=args.include_secrets)
        elif p.is_file():
            text = read_text(p)
            files = 1
        else:
            sys.stderr.write(f"[ctx] not a file or directory: {p}\n")
            return 2

    tokens = est_tokens(text)
    result = {
        "path": label,
        "files": files,
        "chars": len(text),
        "tokens": tokens,
        "method": "heuristic(chars/3.5)",
        "compression": "none",
        "ledger": "not written",
        "skipped_secret_files": skipped_secrets,
    }
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"# raw context: {label}")
    print("# compression: none; ledger: not written")
    print(f"files: {files:,}")
    print(f"chars: {len(text):,}")
    print(f"tokens: ~{tokens:,} ({result['method']})")
    if skipped_secrets:
        print(f"secret-looking files skipped: {len(skipped_secrets):,} "
              f"(e.g. {', '.join(skipped_secrets[:3])}); "
              "use --include-secrets to count them")
    return 0


# -------------------------------------------------------------- memory ----

def _project_root(path: str | os.PathLike[str]) -> Path:
    return Path(path).resolve()


def _memory_root(path: str | os.PathLike[str]) -> Path:
    return _project_root(path) / "memory"


def _rules_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rules_digest(memory: Path) -> None:
    rules = memory / "project-rules.md"
    (memory / ".rules.sha256").write_text(_rules_digest(rules) + "\n", encoding="utf-8")


def _run_codegraph(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str] | None:
    exe = shutil.which("codegraph")
    if not exe:
        sys.stderr.write("[ctx] codegraph not found; continuing without code graph\n")
        return None
    try:
        return subprocess.run(
            [exe, *command],
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        sys.stderr.write(f"[ctx] codegraph unavailable ({exc}); continuing\n")
        return None


def cmd_memory_init(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    memory = root / "memory"
    created: list[str] = []
    memory.mkdir(parents=True, exist_ok=True)
    for rel in MEMORY_REQUIRED:
        target = memory / rel
        if rel in MEMORY_DIRECTORIES:
            if not target.exists():
                target.mkdir(parents=True)
                created.append(f"memory/{rel}/")
            continue
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if rel == ".rules.sha256":
            continue
        target.write_text(MEMORY_TEMPLATES[rel], encoding="utf-8")
        created.append(f"memory/{rel}")

    handoff = root / "handoff.md"
    if not handoff.exists():
        handoff.write_text(
            "# Handoff\n\n## Now\n\n## Next\n\n## Blocked\n\n## Done this session\n",
            encoding="utf-8",
        )
        created.append("handoff.md")

    root_gitignore = root / ".gitignore"
    if not root_gitignore.exists():
        root_gitignore.write_text(ROOT_GITIGNORE_TEMPLATE, encoding="utf-8")
        created.append(".gitignore")

    checksum = memory / ".rules.sha256"
    if not checksum.exists():
        _write_rules_digest(memory)
        created.append("memory/.rules.sha256")

    if args.with_codegraph and not (root / ".codegraph").exists():
        proc = _run_codegraph(["init", "-i", str(root)], root)
        if proc and proc.returncode != 0:
            sys.stderr.write(f"[ctx] codegraph init failed: {proc.stderr.strip()[:300]}\n")

    print(f"# memory initialized at {memory}")
    print("# created: " + (", ".join(created) if created else "nothing (already initialized)"))
    return 0


def _resolve_wiki_link(source: Path, memory: Path, raw: str) -> Path | None:
    target = raw.split("|", 1)[0].split("#", 1)[0].strip()
    if not target or "://" in target:
        return None
    candidate = (source.parent / target)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".md")
    if candidate.exists():
        return candidate
    # Obsidian also resolves note names anywhere in the vault.
    matches = list(memory.rglob(candidate.name))
    return matches[0] if len(matches) == 1 else candidate


def memory_check(root: Path) -> list[dict[str, str]]:
    memory = root / "memory"
    issues: list[dict[str, str]] = []
    for rel in MEMORY_REQUIRED:
        target = memory / rel
        if not target.exists():
            issues.append({"code": "missing", "path": f"memory/{rel}",
                           "message": "required path is missing"})

    index = memory / "MEMORY.md"
    if index.is_file():
        lines = read_text(index).count("\n") + 1
        if lines > MEMORY_LINE_LIMIT:
            issues.append({"code": "index-too-long", "path": "memory/MEMORY.md",
                           "message": f"{lines} lines; limit is {MEMORY_LINE_LIMIT}"})

    for name in MEMORY_JOURNALS:
        journal = memory / name
        if journal.is_file() and est_tokens(read_text(journal)) > JOURNAL_MAX_TOKENS:
            issues.append({"code": "journal-too-large", "path": f"memory/{name}",
                           "message": f"over {JOURNAL_MAX_TOKENS} estimated tokens; rotate it"})

    for note in memory.rglob("*.md"):
        if "archive" in note.relative_to(memory).parts:
            continue
        for raw in WIKI_LINK_RE.findall(read_text(note)):
            resolved = _resolve_wiki_link(note, memory, raw)
            if resolved is not None and not resolved.exists():
                issues.append({"code": "broken-link",
                               "path": note.relative_to(root).as_posix(),
                               "message": f"[[{raw}]] does not resolve"})

    rules = memory / "project-rules.md"
    checksum = memory / ".rules.sha256"
    if rules.is_file() and checksum.is_file():
        expected = read_text(checksum).strip()
        actual = _rules_digest(rules)
        if expected != actual:
            issues.append({"code": "rules-changed", "path": "memory/project-rules.md",
                           "message": "rules changed without approved checksum update"})
    return issues


def cmd_memory_check(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    issues = memory_check(root)
    if args.json:
        print(json.dumps({"ok": not issues, "issues": issues}, ensure_ascii=False, indent=2))
    elif issues:
        print("# memory check failed")
        for issue in issues:
            print(f"- [{issue['code']}] {issue['path']}: {issue['message']}")
    else:
        print("# memory check: OK")
    return 1 if issues else 0


def _memory_context(root: Path, task: str, max_nodes: int, max_code: int) -> str:
    memory = root / "memory"
    parts = [f"# Task\n\n{task}"]
    for path in (memory / "MEMORY.md", root / "handoff.md", memory / "project-rules.md"):
        if path.is_file():
            parts.append(f"# {path.relative_to(root).as_posix()}\n\n{read_text(path)}")

    if (root / ".codegraph").exists():
        sync = _run_codegraph(["sync", str(root)], root)
        if sync and sync.returncode != 0:
            sys.stderr.write(f"[ctx] codegraph sync failed: {sync.stderr.strip()[:300]}\n")
        graph = _run_codegraph([
            "context", task, "--path", str(root),
            "--max-nodes", str(max_nodes), "--max-code", str(max_code),
        ], root)
        if graph and graph.returncode == 0 and graph.stdout.strip():
            parts.append("# CodeGraph context\n\n" + graph.stdout.strip())
        elif graph and graph.returncode != 0:
            sys.stderr.write(f"[ctx] codegraph context failed: {graph.stderr.strip()[:300]}\n")
    return "\n\n".join(parts).strip() + "\n"


def _memory_vault_tokens(root: Path) -> int:
    """Token cost of reading the whole memory vault + handoff at session start —
    the corpus a focused `memory context` is meant to stand in for."""
    total = 0
    memory = root / "memory"
    if memory.is_dir():
        for note in memory.rglob("*.md"):
            try:
                total += est_tokens(read_text(note))
            except OSError:
                continue
    handoff = root / "handoff.md"
    if handoff.is_file():
        total += est_tokens(read_text(handoff))
    return total


def cmd_memory_context(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    text = _memory_context(root, args.task, args.max_nodes, args.max_code)
    kept = est_tokens(text)
    # Conservative denominator: the memory vault, not the whole repo — distilling
    # a task context beats re-reading every note at session start.
    ledger_log("mem-context", max(_memory_vault_tokens(root), kept), kept,
               args.task[:60])
    print(text, end="")
    print(f"\n# memory context: ~{kept:,} estimated tokens")
    return 0


def cmd_memory_query(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    target = root / "memory" if args.scope == "memory" else root
    rlm_args = argparse.Namespace(
        file=str(target),
        query=args.question,
        mode=args.mode,
        engine="ours",
        provider=args.provider,
        model=args.model,
        sub_model=args.sub_model,
        chunk_tokens=args.chunk_tokens,
        max_depth=args.max_depth,
        no_prefilter=False,
        graph=None,
        include_secrets=False,
        json=args.json,
    )
    return cmd_rlm(rlm_args)


def _entry_is_closed(entry: str) -> bool:
    match = re.search(r"(?mi)^-\s*Status:\s*([^\n]+)", entry)
    if not match:
        return False
    status = match.group(1).strip().lower()
    return status in {"closed", "done", "resolved", "superseded", "archived", "example"}


def _rotate_journal(memory: Path, name: str, category: str) -> int:
    path = memory / name
    if not path.is_file():
        return 0
    text = read_text(path)
    if est_tokens(text) <= JOURNAL_MAX_TOKENS:
        return 0
    matches = list(ENTRY_RE.finditer(text))
    if not matches:
        return 0
    header = text[:matches[0].start()]
    entries = [
        text[m.start():(matches[i + 1].start() if i + 1 < len(matches) else len(text))]
        for i, m in enumerate(matches)
    ]
    moved: list[str] = []
    kept: list[str] = []
    current = est_tokens(text)
    for entry in entries:
        if current > JOURNAL_TARGET_TOKENS and _entry_is_closed(entry):
            moved.append(entry.strip())
            current -= est_tokens(entry)
        else:
            kept.append(entry.strip())
    if not moved:
        return 0
    path.write_text(header.rstrip() + "\n\n" + "\n\n".join(kept).rstrip() + "\n",
                    encoding="utf-8")
    month = datetime.date.today().strftime("%Y-%m")
    archive = memory / "archive" / category / f"{month}.md"
    archive.parent.mkdir(parents=True, exist_ok=True)
    existing = read_text(archive).rstrip() if archive.exists() else f"# {category.title()} Archive {month}"
    archive.write_text(existing + "\n\n" + "\n\n".join(moved) + "\n", encoding="utf-8")
    return len(moved)


def cmd_memory_rotate(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    total = sum(_rotate_journal(memory, name, category)
                for name, category in MEMORY_JOURNALS.items())
    print(f"# memory rotation: moved {total} closed entr{'y' if total == 1 else 'ies'}")
    return 0


def cmd_memory_rules_approve(args: argparse.Namespace) -> int:
    if not args.user_approved:
        sys.stderr.write("[ctx] refusing to approve rules without --user-approved\n")
        return 2
    memory = _memory_root(args.path)
    rules = memory / "project-rules.md"
    if not rules.is_file():
        sys.stderr.write(f"[ctx] missing rules file: {rules}\n")
        return 2
    _write_rules_digest(memory)
    print("# permanent rules checksum updated after explicit user approval")
    return 0


def _find_obsidian() -> str | None:
    found = shutil.which("obsidian")
    if found:
        return found
    if os.name != "nt":
        return None
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = (
        local / "Obsidian" / "Obsidian.exe",
        local / "Programs" / "Obsidian" / "Obsidian.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Obsidian" / "Obsidian.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Obsidian" / "Obsidian.exe",
    )
    return str(next((path for path in candidates if path.is_file()), "")) or None


def _install_obsidian_from_official_release() -> int:
    if os.name != "nt":
        sys.stderr.write("[ctx] automatic fallback install is currently supported on Windows only\n")
        return 1
    api = "https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest"
    try:
        request = urllib.request.Request(
            api,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "ctx-memory"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            release = json.load(response)
        assets = release.get("assets", [])
        asset = next(
            item for item in assets
            if re.fullmatch(r"Obsidian-\d+(?:\.\d+)+\.exe", item.get("name", ""))
        )
        url = asset["browser_download_url"]
        if not url.startswith(
            "https://github.com/obsidianmd/obsidian-releases/releases/download/"
        ):
            raise RuntimeError("release asset is not hosted by the official Obsidian repository")
        with tempfile.TemporaryDirectory(prefix="ctx-obsidian-") as temp:
            installer = Path(temp) / asset["name"]
            urllib.request.urlretrieve(url, installer)
            proc = subprocess.run([str(installer), "/S"])
            return proc.returncode
    except (OSError, KeyError, StopIteration, ValueError, RuntimeError) as exc:
        sys.stderr.write(f"[ctx] official Obsidian install failed: {exc}\n")
        return 1


def _register_obsidian_vault(memory: Path) -> tuple[str | None, bool]:
    if os.name != "nt":
        return None, False
    appdata = Path(os.environ.get("APPDATA", ""))
    if not appdata:
        return None, False
    config = appdata / "obsidian" / "obsidian.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {"vaults": {}}
    if config.is_file():
        try:
            loaded = json.loads(read_text(config))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            backup = config.with_suffix(".json.invalid")
            shutil.copy2(config, backup)
    vaults = data.setdefault("vaults", {})
    if not isinstance(vaults, dict):
        vaults = {}
        data["vaults"] = vaults
    normalized = str(memory.resolve())
    existing = next(
        (key for key, value in vaults.items()
         if isinstance(value, dict)
         and os.path.normcase(value.get("path", "")) == os.path.normcase(normalized)),
        None,
    )
    key = existing or hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    created = existing is None
    vaults[key] = {
        **(vaults.get(key, {}) if isinstance(vaults.get(key), dict) else {}),
        "path": normalized,
        "ts": round(datetime.datetime.now().timestamp() * 1000),
        "open": True,
    }
    config.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return key, created


def _restart_obsidian_if_running() -> None:
    if os.name != "nt":
        return
    check = subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq Obsidian.exe", "/NH"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if "Obsidian.exe" not in check.stdout:
        return
    subprocess.run(
        ["taskkill", "/IM", "Obsidian.exe", "/T"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    import time
    time.sleep(2)


def cmd_memory_open(args: argparse.Namespace) -> int:
    memory = _memory_root(args.path)
    if not memory.is_dir():
        sys.stderr.write(f"[ctx] memory vault not found: {memory}\n")
        return 2
    obsidian = _find_obsidian()
    if not obsidian and args.install_obsidian:
        winget = shutil.which("winget")
        if winget:
            proc = subprocess.run([
                winget, "install", "--id", "Obsidian.Obsidian", "-e",
                "--accept-package-agreements", "--accept-source-agreements",
            ], text=True)
            if proc.returncode != 0:
                return proc.returncode
        else:
            result = _install_obsidian_from_official_release()
            if result != 0:
                return result
        obsidian = _find_obsidian()
    if not obsidian:
        sys.stderr.write("[ctx] Obsidian not found. Re-run with --install-obsidian or open "
                         f"this folder manually: {memory}\n")
        return 1
    _, created = _register_obsidian_vault(memory)
    if created:
        _restart_obsidian_if_running()
    # Obsidian assigns the real vault ID internally. The stable public reference
    # after registering the path is the folder/vault name, not our config key.
    vault_uri = "obsidian://open?vault=" + urllib.parse.quote(memory.name, safe="")
    subprocess.Popen([obsidian, vault_uri])
    print(f"# opened Obsidian vault: {memory}")
    return 0


# ------------------------------------------------------------------ rlm ----

# Files that usually hold secrets - never sent to an LLM unless --include-secrets.
SECRET_RE = re.compile(
    r"(^\.env($|\.)|(^|\.)(pem|key|p12|pfx)$|id_rsa|id_ed25519|^\.npmrc$|"
    r"credentials.*\.json$|oauth_creds\.json$|secret|\.pem$)",
    re.IGNORECASE)


def _looks_secret(name: str) -> bool:
    return bool(SECRET_RE.search(name))


def collect_context(root: Path, include_secrets: bool = False) -> tuple[int, int, list[str]]:
    """Concatenate every text file under a directory (same skip rules as `map`)
    into one big context string with per-file headers. Returns (context_text,
    nfiles, skipped_secret_names). Secret-looking files are excluded by default so
    the project's .env/keys are never shipped to an LLM."""
    parts: list[str] = []
    nfiles = 0
    skipped_secrets: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for name in sorted(filenames):
            p = Path(dirpath) / name
            rel = p.relative_to(root).as_posix()
            if not include_secrets and _looks_secret(name):
                skipped_secrets.append(rel)
                continue
            if name.startswith("."):
                continue
            if name in SKIP_FILES or rel in SKIP_FILES:
                continue
            if p.suffix.lower() in BINARY_EXT:
                continue
            try:
                text = read_text(p)
            except OSError:
                continue
            parts.append(f"\n===== FILE: {rel} =====\n{text}")
            nfiles += 1
    return "".join(parts), nfiles, skipped_secrets


def cmd_rlm(args: argparse.Namespace) -> int:
    """Answer a query over a huge file or whole directory via a Recursive Language
    Model: the content never enters the agent's context, only the short answer does."""
    import rlm  # local module; imported lazily so `map`/`digest`/`run` stay light

    if args.file == "-":
        context = sys.stdin.read()
    else:
        p = Path(args.file)
        if p.is_dir():
            context, nfiles, secrets = collect_context(p, include_secrets=args.include_secrets)
            sys.stderr.write(f"[ctx] collected {nfiles} files (~{est_tokens(context):,} tokens) "
                             f"from {p}\n")
            if secrets:
                sys.stderr.write(f"[ctx] excluded {len(secrets)} secret-looking file(s) "
                                 f"(e.g. {', '.join(secrets[:3])}); use --include-secrets to override\n")
        elif p.is_file():
            context = read_text(p)
        else:
            sys.stderr.write(f"[ctx] not a file or directory: {p}\n")
            return 2

    cfg = rlm.RLMConfig(mode=args.mode, chunk_tokens=args.chunk_tokens,
                        max_depth=args.max_depth, prefilter=not args.no_prefilter)
    try:
        resolved = args.provider if args.provider == "fake" else rlm.pick_provider(args.provider)
        if args.provider == "auto":
            sys.stderr.write(f"[ctx] auto-selected provider: {resolved}\n")
        # one-command UX: if Gemini subscription is requested but not logged in yet,
        # bootstrap the OAuth browser flow automatically, then continue.
        if resolved == "gemini-oauth" and not rlm.gemini_creds_path().is_file():
            sys.stderr.write("[ctx] no Gemini login yet - opening browser to authorize...\n")
            rlm.gemini_login()
        if args.engine == "official":
            result = rlm.run_official(context, args.query, args.provider, args.model, cfg)
        else:
            fake_fn = rlm.demo_llm if args.provider == "fake" else None
            provider = rlm.resolve_provider(args.provider, args.model, args.sub_model,
                                            fake=fake_fn)
            graph = rlm.Graph.load(args.graph) if args.graph else None
            result = rlm.rlm_query(context, args.query, provider, cfg, graph,
                                   provider_name=resolved, model=args.model)
    except Exception as exc:  # backend/SDK/CLI problems must report cleanly
        sys.stderr.write(f"[ctx] rlm failed: {exc}\n")
        return 1

    if args.json:
        print(json.dumps({
            "answer": result.answer, "calls": result.calls,
            "context_tokens": result.context_tokens,
            "answer_tokens": result.answer_tokens,
            "trajectory": result.trajectory,
        }, ensure_ascii=False, indent=2))
        return 0

    print(result.answer)
    ratio = result.context_tokens / max(result.answer_tokens, 1)
    prov = resolved if resolved == args.provider else f"{args.provider}->{resolved}"
    print(f"\n# rlm {args.engine}/{cfg.mode} | {result.calls} sub-LM calls | "
          f"~{result.context_tokens:,} -> ~{result.answer_tokens:,} tokens to the agent "
          f"({ratio:.1f}x) | provider={prov}")
    return 0


# ------------------------------------------------------------ gemini-login ----

def cmd_gemini_login(args: argparse.Namespace) -> int:
    import rlm
    try:
        path = rlm.gemini_login()
    except Exception as exc:
        sys.stderr.write(f"[ctx] gemini-login failed: {exc}\n")
        return 1
    print(f"# Gemini subscription creds saved to {path}")
    print("# now run, e.g.:  python ctx.py rlm <file> --query \"...\" --provider gemini-oauth")
    return 0


# -------------------------------------------------------------- report ----

def cmd_report(args: argparse.Namespace) -> int:
    if args.reset:
        if LEDGER_PATH.is_file():
            LEDGER_PATH.unlink()
        print("# ledger reset")
        return 0
    if not LEDGER_PATH.is_file():
        print("# ledger is empty: no ctx.py digest/run operations recorded yet")
        return 0

    by_op: dict[str, dict[str, int]] = {}
    by_provider: dict[str, dict[str, int]] = {}
    bad = 0
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
            raw, kept = int(rec["raw_tokens"]), int(rec["kept_tokens"])
            agg = by_op.setdefault(rec["op"], {"n": 0, "raw": 0, "kept": 0})
            agg["n"] += 1
            agg["raw"] += raw
            agg["kept"] += kept
            prov = rec.get("provider")
            if prov:
                pa = by_provider.setdefault(str(prov),
                                            {"n": 0, "raw": 0, "kept": 0, "calls": 0})
                pa["n"] += 1
                pa["raw"] += raw
                pa["kept"] += kept
                pa["calls"] += int(rec.get("calls", 0) or 0)
        except (json.JSONDecodeError, KeyError, ValueError):
            bad += 1

    print("# savings report -- computed by ctx.py from .ctx/ledger.jsonl,")
    print("# NOT model-estimated. Heuristic token counts (chars/3.5).")
    print(f"{'op':<10} {'calls':>6} {'raw tokens':>12} {'admitted':>12} "
          f"{'saved':>12} {'ratio':>7}")
    tot_raw = tot_kept = 0
    for op in sorted(by_op):
        a = by_op[op]
        tot_raw += a["raw"]
        tot_kept += a["kept"]
        print(f"{op:<10} {a['n']:>6} {a['raw']:>12,} {a['kept']:>12,} "
              f"{a['raw'] - a['kept']:>12,} {a['raw'] / max(a['kept'], 1):>6.1f}x")
    saved = tot_raw - tot_kept
    print(f"{'TOTAL':<10} {sum(a['n'] for a in by_op.values()):>6} {tot_raw:>12,} "
          f"{tot_kept:>12,} {saved:>12,} {tot_raw / max(tot_kept, 1):>6.1f}x")

    # Honest savings %: over real content pulls only (recon excluded), of all the
    # bulk content the agent engaged with, how much ctx kept out of context.
    # `read` ops (raw == kept) are the denominator of integrity -- they pull
    # content in full and pull the percentage down, instead of vanishing the way
    # a direct editor read would.
    content = {op: a for op, a in by_op.items() if op not in RECON_OPS}
    c_raw = sum(a["raw"] for a in content.values())
    c_kept = sum(a["kept"] for a in content.values())
    c_saved = c_raw - c_kept
    pct = 100.0 * c_saved / max(c_raw, 1)
    raw_via_compressor = sum(a["raw"] for op, a in content.items() if op not in RAW_OPS)
    raw_via_read = sum(a["raw"] for op, a in content.items() if op in RAW_OPS)
    engaged = raw_via_compressor + raw_via_read
    coverage = 100.0 * raw_via_compressor / max(engaged, 1)
    recon_note = " (recon ops excluded)" if len(content) != len(by_op) else ""
    print(f"\n# saved {c_saved:,} of {c_raw:,} would-be content tokens = {pct:.0f}% "
          f"kept out of context{recon_note}, single pass.")
    if raw_via_read:
        print(f"# coverage: {coverage:.0f}% of engaged content ({raw_via_compressor:,} of "
              f"{engaged:,} tok) went through a ctx compressor; the rest was read raw.")
    else:
        print("# coverage: no `ctx read` pulls logged yet -- route full-file reads")
        print("#           through `ctx read` so the % reflects ALL content, not just wins.")
    usd = c_saved / 1e6 * args.price
    print(f"# dollar value: ~${usd:.2f} at ${args.price}/MTok. In an agent loop the real")
    print("# effect is larger: every admitted token is re-sent on each later turn.")

    if by_provider:
        print(f"\n{'rlm provider':<16} {'calls':>6} {'sub-LM':>7} {'context tok':>12} "
              f"{'answer tok':>11}")
        for prov in sorted(by_provider):
            p = by_provider[prov]
            print(f"{prov:<16} {p['n']:>6} {p['calls']:>7} {p['raw']:>12,} {p['kept']:>11,}")
    if bad:
        print(f"# warning: {bad} malformed ledger line(s) skipped")
    return 0


# ---------------------------------------------------------------- main ----

def main(argv: list[str] | None = None) -> int:
    # Legacy Windows consoles default to cp1251/cp866, which cannot encode
    # characters that routinely appear in answers (arrows, em dashes, etc.).
    # Force UTF-8 so output never crashes with UnicodeEncodeError.
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    ap = argparse.ArgumentParser(prog="ctx.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    m = sub.add_parser("map", help="repo map with token estimates")
    m.add_argument("path", nargs="?", default=".")
    m.add_argument("--top", type=int, default=40, help="show N most expensive files")
    m.add_argument("--all", action="store_true", help="show every file")
    m.add_argument("--warn", type=int, default=4000, help="flag files above N tokens")
    m.set_defaults(fn=cmd_map)

    d = sub.add_parser("digest", help="structural digest of a file")
    d.add_argument("file")
    d.set_defaults(fn=cmd_digest)

    r = sub.add_parser("run", help="run a command, show only the salient extract")
    r.add_argument("--tail", type=int, default=20, help="always keep last N lines")
    r.add_argument("--max-errors", type=int, default=30, help="cap on error sites kept")
    r.add_argument("--ctx-lines", type=int, default=2, help="context lines around an error")
    r.add_argument("command", nargs=argparse.REMAINDER,
                   help="command after `--`, e.g. ctx.py run -- pytest -q")
    r.set_defaults(fn=cmd_run)

    c = sub.add_parser("count", help="token count of a file or stdin (-)")
    c.add_argument("file")
    c.set_defaults(fn=cmd_count)

    rd = sub.add_parser(
        "read",
        help="print a file verbatim and log it as uncompressed context (savings denominator)")
    rd.add_argument("file")
    rd.set_defaults(fn=cmd_read)

    hk = sub.add_parser(
        "hook",
        help="PostToolUse hook: log context pulled by direct Read/Bash (reads JSON on stdin)")
    hk.add_argument("--min-tokens", type=int, default=200,
                    help="ignore tool calls smaller than this (default 200)")
    hk.set_defaults(fn=cmd_hook)

    rc = sub.add_parser(
        "rawcount",
        help="token count of unsqueezed text with no compression or ledger savings")
    rc.add_argument("path", help="file, directory, or - for stdin")
    rc.add_argument("--include-secrets", action="store_true",
                    help="when scanning a directory, include .env/keys/secrets")
    rc.add_argument("--json", action="store_true", help="emit machine-readable metrics")
    rc.set_defaults(fn=cmd_rawcount)

    mem = sub.add_parser("memory", help="manage the project memory vault")
    mem_sub = mem.add_subparsers(dest="memory_cmd", required=True)

    mem_init = mem_sub.add_parser("init", help="create missing memory vault files")
    mem_init.add_argument("path", nargs="?", default=".")
    mem_init.add_argument("--with-codegraph", action="store_true")
    mem_init.set_defaults(fn=cmd_memory_init)

    mem_check = mem_sub.add_parser("check", help="validate memory structure and rules")
    mem_check.add_argument("path", nargs="?", default=".")
    mem_check.add_argument("--json", action="store_true")
    mem_check.set_defaults(fn=cmd_memory_check)

    mem_context = mem_sub.add_parser("context", help="build a small task context")
    mem_context.add_argument("task")
    mem_context.add_argument("--path", default=".")
    mem_context.add_argument("--max-nodes", type=int, default=30)
    mem_context.add_argument("--max-code", type=int, default=6)
    mem_context.set_defaults(fn=cmd_memory_context)

    mem_query = mem_sub.add_parser("query", help="ask RLM about memory or the project")
    mem_query.add_argument("question")
    mem_query.add_argument("--path", default=".")
    mem_query.add_argument("--scope", choices=["memory", "project"], default="memory")
    mem_query.add_argument("--provider",
                           choices=["auto", "api", "cli", "gemini", "gemini-oauth",
                                    "gemini-cli", "openai", "openrouter",
                                    "codex", "openai-oauth", "fake"],
                           default="auto")
    mem_query.add_argument("--model", default=None,
                           help="root model; required for --provider openrouter")
    mem_query.add_argument("--sub-model", default=None,
                           help="sub-LM model; defaults to --model for openrouter")
    mem_query.add_argument("--mode", choices=["mapreduce", "repl"], default="mapreduce")
    mem_query.add_argument("--chunk-tokens", type=int, default=4000)
    mem_query.add_argument("--max-depth", type=int, default=1)
    mem_query.add_argument("--json", action="store_true")
    mem_query.set_defaults(fn=cmd_memory_query)

    mem_rotate = mem_sub.add_parser("rotate", help="archive closed journal entries")
    mem_rotate.add_argument("path", nargs="?", default=".")
    mem_rotate.set_defaults(fn=cmd_memory_rotate)

    mem_rules = mem_sub.add_parser("rules-approve",
                                   help="approve the current permanent-rules checksum")
    mem_rules.add_argument("path", nargs="?", default=".")
    mem_rules.add_argument("--user-approved", action="store_true", required=True)
    mem_rules.set_defaults(fn=cmd_memory_rules_approve)

    mem_open = mem_sub.add_parser("open", help="open the memory folder in Obsidian")
    mem_open.add_argument("path", nargs="?", default=".")
    mem_open.add_argument("--install-obsidian", action="store_true")
    mem_open.set_defaults(fn=cmd_memory_open)

    rl = sub.add_parser(
        "rlm", help="answer a query over a huge file via a Recursive Language Model")
    rl.add_argument("file", nargs="?", default=".",
                    help="file or directory with the context, or - for stdin "
                         "(default: the current folder)")
    rl.add_argument("--query", required=True, help="the question to answer")
    rl.add_argument("--mode", choices=["mapreduce", "repl"], default="mapreduce")
    rl.add_argument("--engine", choices=["ours", "official"], default="ours",
                    help="ours=built-in engine; official=delegate to `pip install rlms`")
    rl.add_argument("--provider",
                    choices=["auto", "api", "cli", "gemini", "gemini-oauth",
                             "gemini-cli", "openai", "openrouter",
                             "codex", "openai-oauth", "fake"],
                    default="auto",
                    help="auto-detects from API keys / .env / subscription logins "
                         "(gemini-oauth, gemini-cli, claude cli)")
    rl.add_argument("--model", default=None,
                    help="root model (required for --provider openrouter; otherwise default per-provider)")
    rl.add_argument("--sub-model", default=None,
                    help="cheap sub-LM model (defaults to --model for openrouter; otherwise default per-provider)")
    rl.add_argument("--chunk-tokens", type=int, default=4000)
    rl.add_argument("--max-depth", type=int, default=1)
    rl.add_argument("--no-prefilter", action="store_true",
                    help="disable keyword pre-filtering of chunks")
    rl.add_argument("--graph", help="optional Graphify graph.json to expose in repl mode")
    rl.add_argument("--include-secrets", action="store_true",
                    help="when scanning a directory, DO send .env/keys/secrets to the LLM")
    rl.add_argument("--json", action="store_true", help="emit full result as JSON")
    rl.set_defaults(fn=cmd_rlm)

    gl = sub.add_parser(
        "gemini-login",
        help="log in to Gemini by Google subscription (OAuth) for --provider gemini-oauth")
    gl.set_defaults(fn=cmd_gemini_login)

    rep = sub.add_parser(
        "report",
        help="savings report from .ctx/ledger.jsonl (tool-computed, not model-estimated)")
    rep.add_argument("--price", type=float, default=5.0,
                     help="input price $/MTok for the cost estimate (default 5.0)")
    rep.add_argument("--reset", action="store_true", help="clear the ledger")
    rep.set_defaults(fn=cmd_report)

    args = ap.parse_args(argv)
    if getattr(args, "command", None) and args.command and args.command[0] == "--":
        args.command = args.command[1:]
    return args.fn(args)


def rlm_entry() -> int:
    """Console-script entry: `rlm ...` behaves as `ctx rlm ...`."""
    return main(["rlm", *sys.argv[1:]])


def gemini_login_entry() -> int:
    """Console-script entry: `ctx-rlm-login` == `ctx gemini-login`."""
    return main(["gemini-login", *sys.argv[1:]])


if __name__ == "__main__":
    sys.exit(main())
