#!/usr/bin/env python3
"""rlm.py - Recursive Language Models (RLM) engine for the TVL toolkit.

Faithful-but-pragmatic re-implementation of the Recursive Language Models idea
(Zhang, Kraska, Khattab - MIT CSAIL, arXiv:2512.24601; github.com/alexzhang13/rlm):
the big *context* never enters the root model's attention window - it stays in a
variable, gets sliced/grepped/chunked programmatically, and sub-LM calls handle the
pieces. The root only ever sees the query and short intermediate results.

Two engines, one API:
  * mode="mapreduce" (default) - deterministic recursion: leaf-summarise chunks via a
    cheap sub-LM, then synthesise. Fully offline-testable with an injected fake LM.
  * mode="repl" - the faithful variant: the root LM writes Python against a restricted
    namespace exposing CONTEXT/peek/grep/chunk/llm/llm_batch and ends with FINAL(...).

Providers (auth variants): api (ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / gateway),
cli (local `claude -p` headless - reuses your existing subscription/OAuth login),
auto (api->cli), fake (injected, for tests). Optional Graphify graph.json substrate
adds get_node/get_neighbors/shortest_path to the REPL namespace.

This module is import-safe and stdlib-only at its core; `anthropic`, the `claude`
CLI and a Graphify export are all optional and only touched by the real backends.
"""

from __future__ import annotations

__version__ = "0.0.2"

import base64
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import redirect_stdout
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

# Portability: make `from ctx import ...` work no matter the cwd, so the two
# files can be copied into any project and run as-is.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Reuse the toolkit's primitives instead of duplicating them.
from ctx import CHARS_PER_TOKEN, est_tokens, ledger_log, read_text  # noqa: E402,F401

LLMFn = Callable[[str], str]

STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "is", "are",
    "what", "which", "who", "how", "why", "when", "where", "does", "do", "did",
    "with", "from", "this", "that", "these", "those", "it", "its", "as", "by",
    "be", "was", "were", "can", "will", "about", "into", "your", "you",
}


# --------------------------------------------------------------- config ----

@dataclass
class RLMConfig:
    mode: str = "mapreduce"          # mapreduce | repl
    chunk_tokens: int = 4000         # leaf threshold / chunk size
    max_depth: int = 1               # recursion depth (paper: 1 is enough)
    max_parallel: int = 8            # llm_batch worker threads
    prefilter: bool = True           # keyword-grep chunks before mapping
    output_cap: int = 8192           # REPL stdout cap per step (chars)
    max_steps: int = 12              # REPL turn cap
    leaf_max_words: int = 80


@dataclass
class RLMResult:
    answer: str
    calls: int = 0
    context_tokens: int = 0
    answer_tokens: int = 0
    trajectory: list = field(default_factory=list)


# --------------------------------------------------- programmatic helpers ----

def peek(text: str, n: int = 2000) -> str:
    """First n chars (the article's `peek` primitive)."""
    return text[:n]


def grep(text: str, pattern: str, flags: int = re.IGNORECASE) -> list[str]:
    """Lines matching a regex - the REPL's narrowing primitive."""
    rx = re.compile(pattern, flags)
    return [ln for ln in text.splitlines() if rx.search(ln)]


def chunk_text(text: str, chunk_tokens: int) -> list[str]:
    """Split on line boundaries into ~chunk_tokens-sized pieces."""
    budget = max(1, int(chunk_tokens * CHARS_PER_TOKEN))
    out: list[str] = []
    buf: list[str] = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > budget and buf:
            out.append("".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line)
    if buf:
        out.append("".join(buf))
    return out or [text]


def _keywords(query: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z_]{3,}", query.lower())
            if w not in STOPWORDS]


def prefilter_chunks(chunks: list[str], query: str) -> list[str]:
    """Keep chunks mentioning a query keyword; fall back to all if none match."""
    kws = _keywords(query)
    if not kws:
        return chunks
    kept = [c for c in chunks if any(k in c.lower() for k in kws)]
    return kept or chunks


# ------------------------------------------------------------- prompts ----

def leaf_prompt(query: str, fragment: str, max_words: int) -> str:
    return (
        "Answer the QUESTION using ONLY the FRAGMENT below.\n"
        "If the fragment has nothing relevant, reply exactly: NO_INFO\n"
        f"Be terse - facts only, at most ~{max_words} words.\n\n"
        f"QUESTION: {query}\n\n--- FRAGMENT ---\n{fragment}"
    )


def reduce_prompt(query: str, notes: list[str]) -> str:
    joined = "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes))
    return (
        "Synthesise ONE answer to the QUESTION from the partial NOTES below.\n"
        "Notes saying NO_INFO carry no information - ignore them.\n"
        "Do not invent facts beyond the notes. Be concise.\n\n"
        f"QUESTION: {query}\n\nNOTES:\n{joined}"
    )


# -------------------------------------------------------- mapreduce engine ----

class _Counter:
    def __init__(self) -> None:
        self.n = 0

    def wrap(self, fn: LLMFn) -> LLMFn:
        def inner(prompt: str) -> str:
            self.n += 1
            return fn(prompt)
        return inner


def _batch(fn: LLMFn, prompts: list[str], workers: int) -> list[str]:
    if len(prompts) <= 1:
        return [fn(p) for p in prompts]
    with ThreadPoolExecutor(max_workers=min(workers, len(prompts))) as ex:
        return list(ex.map(fn, prompts))


def _solve(context: str, query: str, root: LLMFn, sub: LLMFn,
           cfg: RLMConfig, depth: int, traj: list) -> str:
    is_leaf = est_tokens(context) <= cfg.chunk_tokens or depth >= cfg.max_depth
    if is_leaf:
        ans = sub(leaf_prompt(query, context, cfg.leaf_max_words))
        traj.append({"depth": depth, "kind": "leaf",
                     "tokens": est_tokens(context), "preview": ans[:120]})
        return ans

    chunks = chunk_text(context, cfg.chunk_tokens)
    if cfg.prefilter:
        chunks = prefilter_chunks(chunks, query)
    traj.append({"depth": depth, "kind": "split",
                 "tokens": est_tokens(context), "chunks": len(chunks)})

    results: list[Optional[str]] = [None] * len(chunks)
    leaf_idx, leaf_prompts = [], []
    for i, ch in enumerate(chunks):
        child_leaf = est_tokens(ch) <= cfg.chunk_tokens or depth + 1 >= cfg.max_depth
        if child_leaf:
            leaf_idx.append(i)
            leaf_prompts.append(leaf_prompt(query, ch, cfg.leaf_max_words))
        else:
            results[i] = _solve(ch, query, root, sub, cfg, depth + 1, traj)
    if leaf_prompts:
        for i, out in zip(leaf_idx, _batch(sub, leaf_prompts, cfg.max_parallel)):
            results[i] = out

    notes = [r for r in results if r and r.strip() and r.strip() != "NO_INFO"]
    if not notes:
        return "NO_INFO"
    ans = root(reduce_prompt(query, notes))
    traj.append({"depth": depth, "kind": "reduce", "notes": len(notes),
                 "preview": ans[:120]})
    return ans


# ------------------------------------------------------------- repl engine ----

class _Done(Exception):
    def __init__(self, value: str) -> None:
        self.value = str(value)


REPL_SYSTEM = """You are the root of a Recursive Language Model. The full context is \
already loaded as the Python variable CONTEXT (a string) - it is NOT in this prompt, so \
you must explore it with code. Reply with ONE ```python ...``` block per turn. Available \
helpers: peek(text, n), grep(text, regex), chunk(text, n_tokens), llm(prompt) -> str, \
llm_batch(prompts) -> list[str]{graph}. Print only what you need (output is capped). When \
you can answer the QUESTION, call FINAL(answer_string) or FINAL_VAR("var_name"). Do not \
print CONTEXT wholesale.{graph_hint}

QUESTION: {query}
"""

GRAPH_HINT = (
    "\nA code knowledge-graph is loaded: prefer get_neighbors(id)/shortest_path(a, b) to "
    "follow real call/import edges instead of blind grep, then llm() over the bodies you "
    "find. Node ids are module-prefixed, e.g. 'ctx_est_tokens'."
)

CODE_RE = re.compile(r"```(?:python)?\s*(.*?)```", re.DOTALL)


def _build_namespace(context: str, sub: LLMFn, cfg: RLMConfig,
                     graph: Optional["Graph"]) -> dict:
    ns: dict = {
        "CONTEXT": context,
        "peek": peek,
        "grep": grep,
        "chunk": lambda t=None, n=cfg.chunk_tokens: chunk_text(t if t is not None else context, n),
        "llm": sub,
        "llm_batch": lambda ps: _batch(sub, list(ps), cfg.max_parallel),
        "re": re,
        "FINAL": lambda v: (_ for _ in ()).throw(_Done(v)),
    }
    ns["FINAL_VAR"] = lambda name: (_ for _ in ()).throw(_Done(ns.get(name, "")))
    if graph is not None:
        ns["get_node"] = graph.get_node
        ns["get_neighbors"] = graph.get_neighbors
        ns["shortest_path"] = graph.shortest_path
    return ns


def _repl_solve(context: str, query: str, root: LLMFn, sub: LLMFn,
                cfg: RLMConfig, graph: Optional["Graph"], traj: list) -> str:
    graph_help = (", get_node(id), get_neighbors(id), shortest_path(a, b)"
                  if graph is not None else "")
    system = REPL_SYSTEM.format(query=query, graph=graph_help,
                                graph_hint=GRAPH_HINT if graph is not None else "")
    ns = _build_namespace(context, sub, cfg, graph)
    history = system
    last = "NO_INFO"
    for step in range(cfg.max_steps):
        reply = root(history)
        m = CODE_RE.search(reply)
        code = m.group(1) if m else reply
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                exec(compile(code, "<rlm-repl>", "exec"), ns)  # noqa: S102
            out = buf.getvalue()[: cfg.output_cap]
        except _Done as done:
            traj.append({"step": step, "kind": "final", "preview": done.value[:120]})
            return done.value
        except Exception as exc:  # surface the error to the root, keep looping
            out = buf.getvalue()[: cfg.output_cap] + f"\n[error] {type(exc).__name__}: {exc}"
        last = out
        traj.append({"step": step, "kind": "exec", "code": code[:200],
                     "out": out[:200]})
        history = f"{system}\n\n[turn {step} code]\n{code}\n[turn {step} output]\n{out}\n"
    return last


# ----------------------------------------------------------- graph (Graphify) ----

class Graph:
    """Minimal reader for a Graphify-style graph.json export.

    Tolerant of schema variation: nodes may be a list of dicts or a dict keyed by
    id; edges use source/target or from/to. Absent/odd fields degrade gracefully."""

    def __init__(self, data: dict) -> None:
        raw_nodes = data.get("nodes", [])
        if isinstance(raw_nodes, dict):
            self.nodes = {str(k): v for k, v in raw_nodes.items()}
        else:
            self.nodes = {str(n.get("id", i)): n for i, n in enumerate(raw_nodes)}
        self.adj: dict[str, set] = {nid: set() for nid in self.nodes}
        # accept both {"edges":[...]} and networkx node-link {"links":[...]}
        for e in data.get("edges") or data.get("links") or []:
            a = str(e.get("source", e.get("from", "")))
            b = str(e.get("target", e.get("to", "")))
            if a and b:
                self.adj.setdefault(a, set()).add(b)
                self.adj.setdefault(b, set()).add(a)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "Graph":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def get_node(self, node_id) -> dict:
        return self.nodes.get(str(node_id), {})

    def get_neighbors(self, node_id) -> list:
        return sorted(self.adj.get(str(node_id), set()))

    def shortest_path(self, a, b) -> list:
        a, b = str(a), str(b)
        if a not in self.adj or b not in self.adj:
            return []
        seen, queue = {a}, [[a]]
        while queue:
            path = queue.pop(0)
            if path[-1] == b:
                return path
            for nxt in self.adj.get(path[-1], ()):
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append(path + [nxt])
        return []


# ----------------------------------------------------------- providers ----

@dataclass
class Provider:
    root: LLMFn
    sub: LLMFn


def _anthropic_provider(model: str, sub_model: str) -> Provider:
    import anthropic  # optional dependency

    kwargs: dict = {}
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        kwargs["auth_token"] = os.environ["ANTHROPIC_AUTH_TOKEN"]
    if os.environ.get("ANTHROPIC_BASE_URL"):
        kwargs["base_url"] = os.environ["ANTHROPIC_BASE_URL"]
    client = anthropic.Anthropic(**kwargs)

    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            resp = client.messages.create(
                model=mdl, max_tokens=1024,
                messages=[{"role": "user", "content": prompt or " "}],
            )
            return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def _cli_provider(model: str, sub_model: str) -> Provider:
    exe = shutil.which("claude")
    if not exe:
        raise RuntimeError("provider 'cli' needs the `claude` CLI on PATH")

    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            proc = subprocess.run(
                [exe, "-p", prompt, "--model", mdl, "--output-format", "json"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
            )
            if proc.returncode != 0:
                raise RuntimeError(f"claude cli failed: {proc.stderr.strip()[:200]}")
            try:
                return json.loads(proc.stdout).get("result", proc.stdout)
            except json.JSONDecodeError:
                return proc.stdout
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def _http_json(url: str, payload: dict, headers: dict, timeout: int = 600) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")


def _gemini_provider(model: str, sub_model: str) -> Provider:
    """Google AI Studio (Gemini) via the Generative Language REST API - stdlib only."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        raise RuntimeError("provider 'gemini' needs GEMINI_API_KEY or GOOGLE_API_KEY")
    base = os.environ.get("GEMINI_BASE_URL",
                          "https://generativelanguage.googleapis.com/v1beta")

    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            url = f"{base}/models/{mdl}:generateContent?key={key}"
            data = _http_json(url, {"contents": [{"parts": [{"text": prompt or " "}]}]}, {})
            return "".join(
                p.get("text", "")
                for c in data.get("candidates", [])
                for p in c.get("content", {}).get("parts", []))
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def _openai_provider(model: str, sub_model: str) -> Provider:
    """OpenAI-compatible chat completions (OpenAI, Codex gateways, vLLM, Gemini's
    OpenAI endpoint...) via REST - stdlib only. Set OPENAI_BASE_URL to retarget."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("provider 'openai' needs OPENAI_API_KEY (and optional OPENAI_BASE_URL)")
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")

    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            data = _http_json(
                f"{base}/chat/completions",
                {"model": mdl, "messages": [{"role": "user", "content": prompt or " "}]},
                {"Authorization": f"Bearer {key}"})
            return data["choices"][0]["message"]["content"]
        return inner

    return Provider(root=call(model), sub=call(sub_model))


# ---------------------------------------- Gemini subscription (OAuth) ----
# Uses caller-supplied Google OAuth application credentials. The toolkit does not
# embed third-party client credentials. Prefer `gemini-cli` unless you operate
# your own OAuth client for the Code Assist flow.
GEMINI_OAUTH_CLIENT_ID = os.environ.get("GEMINI_OAUTH_CLIENT_ID", "")
GEMINI_OAUTH_CLIENT_SECRET = os.environ.get("GEMINI_OAUTH_CLIENT_SECRET", "")
GEMINI_OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
CODE_ASSIST = "https://cloudcode-pa.googleapis.com/v1internal"


def _gemini_oauth_client() -> tuple[str, str]:
    if not GEMINI_OAUTH_CLIENT_ID or not GEMINI_OAUTH_CLIENT_SECRET:
        raise RuntimeError(
            "gemini-oauth requires GEMINI_OAUTH_CLIENT_ID and "
            "GEMINI_OAUTH_CLIENT_SECRET. Prefer --provider gemini-cli when possible.")
    return GEMINI_OAUTH_CLIENT_ID, GEMINI_OAUTH_CLIENT_SECRET


def gemini_creds_path() -> Path:
    return Path(os.environ.get("GEMINI_OAUTH_CREDS")
                or (Path.home() / ".gemini" / "oauth_creds.json"))


def _oauth_expired(creds: dict, skew_ms: int = 60_000) -> bool:
    """True if the access token is missing or within skew of expiry."""
    if not creds.get("access_token"):
        return True
    return time.time() * 1000 >= (creds.get("expiry_date", 0) - skew_ms)


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"OAuth HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")


def _refresh_oauth(creds: dict) -> dict:
    if not creds.get("refresh_token"):
        raise RuntimeError("Gemini OAuth creds have no refresh_token; re-run gemini-login")
    client_id, client_secret = _gemini_oauth_client()
    resp = _post_form(GOOGLE_TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": creds["refresh_token"],
        "grant_type": "refresh_token",
    })
    creds["access_token"] = resp["access_token"]
    creds["expiry_date"] = int(time.time() * 1000) + int(resp.get("expires_in", 3600)) * 1000
    return creds


def gemini_access_token() -> tuple[str, Optional[str]]:
    """Return a fresh (access_token, project), refreshing and re-saving as needed."""
    path = gemini_creds_path()
    if not path.is_file():
        raise RuntimeError(
            "no Gemini subscription login found. Run:  python ctx.py gemini-login")
    creds = json.loads(path.read_text(encoding="utf-8"))
    if _oauth_expired(creds):
        creds = _refresh_oauth(creds)
        path.write_text(json.dumps(creds), encoding="utf-8")
    project = (os.environ.get("GOOGLE_CLOUD_PROJECT")
               or os.environ.get("GEMINI_PROJECT_ID") or creds.get("project"))
    return creds["access_token"], project


def _codeassist_body(model: str, project: Optional[str], prompt: str) -> dict:
    body: dict = {"model": model,
                  "request": {"contents": [{"role": "user",
                                            "parts": [{"text": prompt or " "}]}]}}
    if project:
        body["project"] = project
    return body


def _parse_codeassist(data: dict) -> str:
    resp = data.get("response", data)
    return "".join(
        p.get("text", "")
        for c in resp.get("candidates", [])
        for p in c.get("content", {}).get("parts", []))


def _gemini_oauth_provider(model: str, sub_model: str) -> Provider:
    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            token, project = gemini_access_token()
            data = _http_json(f"{CODE_ASSIST}:generateContent",
                              _codeassist_body(mdl, project, prompt),
                              {"Authorization": f"Bearer {token}"})
            return _parse_codeassist(data)
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def _gemini_cli_provider(model: str, sub_model: str) -> Provider:
    """Shell out to Google's own `gemini` CLI (reuses its subscription OAuth login)."""
    exe = shutil.which("gemini")
    if not exe:
        raise RuntimeError("provider 'gemini-cli' needs the `gemini` CLI on PATH "
                           "(npm i -g @google/gemini-cli, then run `gemini` to log in)")

    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            proc = subprocess.run([exe, "-m", mdl, "-p", prompt],
                                  capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(f"gemini cli failed: {proc.stderr.strip()[:200]}")
            return proc.stdout.strip()
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def gemini_login(timeout_s: int = 300) -> Path:
    """One-time Google OAuth (loopback) to mint subscription creds, like the CLI does.
    Opens a browser, captures the code on localhost, exchanges it, saves the refresh
    token to gemini_creds_path(). Returns the path written."""
    import http.server
    import secrets
    import threading
    import webbrowser

    holder: dict = {}
    state = secrets.token_urlsafe(16)
    client_id, client_secret = _gemini_oauth_client()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)
            holder["code"] = (params.get("code") or [None])[0]
            holder["state"] = (params.get("state") or [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Gemini login complete. You can close this tab.")

        def log_message(self, *a):  # silence the server
            pass

    srv = http.server.HTTPServer(("localhost", 0), Handler)
    port = srv.server_address[1]
    redirect_uri = f"http://localhost:{port}/oauth2callback"
    auth_url = GOOGLE_AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GEMINI_OAUTH_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    sys.stderr.write(f"[rlm] open this URL to authorize Gemini:\n{auth_url}\n")
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass
    threading.Thread(target=srv.handle_request, daemon=True).start()
    deadline = time.time() + timeout_s
    while "code" not in holder and time.time() < deadline:
        time.sleep(0.2)
    srv.server_close()
    if not holder.get("code") or holder.get("state") != state:
        raise RuntimeError("Gemini login did not complete (no/invalid auth code)")

    tok = _post_form(GOOGLE_TOKEN_URL, {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": holder["code"],
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    })
    creds = {
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token", ""),
        "expiry_date": int(time.time() * 1000) + int(tok.get("expires_in", 3600)) * 1000,
    }
    project = os.environ.get("GOOGLE_CLOUD_PROJECT") or os.environ.get("GEMINI_PROJECT_ID")
    if project:
        creds["project"] = project
    path = gemini_creds_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(creds), encoding="utf-8")
    return path


# ------------------------------------ OpenAI subscription (ChatGPT/Codex) ----
# Two ways to use a ChatGPT Plus/Pro *subscription* (not a paid API key):
#  - provider "codex": shell out to the official `codex exec` (fully blessed).
#  - provider "openai-oauth": reuse the Codex login at ~/.codex/auth.json and call
#    the ChatGPT backend directly (reverse-engineered, against OpenAI ToS for
#    third-party use, may break; the code reads your token only locally at runtime).
# Pick the model with --model / --sub-model; defaults are the cheap tier.

CODEX_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
CHATGPT_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"


def codex_auth_path() -> Path:
    return Path(os.environ.get("CODEX_AUTH")
                or (Path.home() / ".codex" / "auth.json"))


def _jwt_exp(token: str) -> int:
    """Best-effort: read the `exp` (epoch seconds) from a JWT without verifying it."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return int(json.loads(base64.urlsafe_b64decode(payload)).get("exp", 0))
    except Exception:
        return 0


def _http_text(url: str, payload: dict, headers: dict, timeout: int = 600) -> str:
    """POST JSON, return the raw response body as text (for SSE streams)."""
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}")


def _refresh_codex(auth: dict, path: Path) -> str:
    rt = auth.get("tokens", {}).get("refresh_token")
    if not rt:
        raise RuntimeError("Codex auth has no refresh_token; run `codex login`")
    resp = _http_json(OPENAI_TOKEN_URL, {
        "client_id": CODEX_CLIENT_ID,
        "grant_type": "refresh_token",
        "refresh_token": rt,
    }, {})
    tokens = auth.setdefault("tokens", {})
    tokens["access_token"] = resp["access_token"]
    if resp.get("refresh_token"):
        tokens["refresh_token"] = resp["refresh_token"]
    if resp.get("id_token"):
        tokens["id_token"] = resp["id_token"]
    auth["last_refresh"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path.write_text(json.dumps(auth), encoding="utf-8")
    return resp["access_token"]


def codex_access_token() -> tuple[str, Optional[str]]:
    """Return a fresh (access_token, account_id) from the local Codex login."""
    path = codex_auth_path()
    if not path.is_file():
        raise RuntimeError("no Codex login found (~/.codex/auth.json); run `codex login`")
    auth = json.loads(path.read_text(encoding="utf-8"))
    tokens = auth.get("tokens", {})
    at = tokens.get("access_token")
    if not at:
        raise RuntimeError("Codex auth.json has no access_token; run `codex login`")
    exp = _jwt_exp(at)
    if exp and time.time() > exp - 300:
        at = _refresh_codex(auth, path)
    return at, tokens.get("account_id")


def _responses_body(model: str, prompt: str) -> dict:
    return {
        "model": model,
        "instructions": "You are a helpful assistant. Answer the user directly and concisely.",
        "input": [{"type": "message", "role": "user",
                   "content": [{"type": "input_text", "text": prompt or " "}]}],
        "stream": True,
        "store": False,
        "tools": [],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }


def _parse_responses_sse(raw: str) -> str:
    """Accumulate response.output_text.delta events from a Responses SSE stream."""
    out: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            ev = json.loads(data)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "response.output_text.delta":
            out.append(ev.get("delta", ""))
        elif ev.get("type") == "response.completed" and not out:
            # fallback: pull text straight from the completed response object
            for item in ev.get("response", {}).get("output", []):
                for part in item.get("content", []):
                    out.append(part.get("text", ""))
    return "".join(out)


def _openai_oauth_provider(model: str, sub_model: str) -> Provider:
    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            token, account = codex_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "chatgpt-account-id": account or "",
                "OpenAI-Beta": "responses=experimental",
                "originator": "codex_cli_rs",
                "session_id": str(uuid.uuid4()),
            }
            raw = _http_text(CHATGPT_RESPONSES_URL, _responses_body(mdl, prompt), headers)
            return _parse_responses_sse(raw)
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def _codex_cli_provider(model: str, sub_model: str) -> Provider:
    """Shell out to the official `codex exec` (reuses its ChatGPT subscription login)."""
    exe = shutil.which("codex")
    if not exe:
        raise RuntimeError("provider 'codex' needs the `codex` CLI on PATH "
                           "(npm i -g @openai/codex, then `codex login`)")

    def call(mdl: str) -> LLMFn:
        def inner(prompt: str) -> str:
            proc = subprocess.run(
                [exe, "exec", "--skip-git-repo-check", "-s", "read-only", "-m", mdl, prompt],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                raise RuntimeError(f"codex exec failed: {proc.stderr.strip()[:200]}")
            return proc.stdout.strip()
        return inner

    return Provider(root=call(model), sub=call(sub_model))


def demo_llm(prompt: str) -> str:
    """Deterministic, backend-free stand-in so `--provider fake` runs offline.

    It does no real reasoning - it just proves the plumbing end-to-end (chunking,
    mapping, synthesis, ledger) without an API key or the `claude` CLI."""
    if "--- FRAGMENT ---" in prompt:
        frag = " ".join(prompt.split("--- FRAGMENT ---\n", 1)[1].split())
        return f"[demo] {frag[:160]}" if frag else "NO_INFO"
    if "NOTES:" in prompt:
        notes = " ".join(prompt.split("NOTES:\n", 1)[1].split())
        return f"[demo synthesis] {notes[:200]}"
    return "FINAL('[demo] no real backend configured')"  # repl root: terminate


# Per-provider default (root, sub) models. Sub is the cheap, high-volume one.
DEFAULT_MODELS = {
    "api": ("claude-opus-4-8", "claude-haiku-4-5"),
    "cli": ("claude-opus-4-8", "claude-haiku-4-5"),
    "gemini": ("gemini-2.5-pro", "gemini-2.5-flash"),
    "gemini-oauth": ("gemini-2.5-pro", "gemini-2.5-flash"),
    "gemini-cli": ("gemini-2.5-pro", "gemini-2.5-flash"),
    "openai": ("gpt-5", "gpt-5-mini"),
    "codex": ("gpt-5.4-mini", "gpt-5.4-mini"),         # cheap; override with --model
    "openai-oauth": ("gpt-5.4-mini", "gpt-5.4-mini"),  # cheap; override with --model
    "fake": ("fake", "fake"),
}
_BUILDERS = {
    "api": _anthropic_provider,
    "cli": _cli_provider,
    "gemini": _gemini_provider,
    "gemini-oauth": _gemini_oauth_provider,
    "gemini-cli": _gemini_cli_provider,
    "openai": _openai_provider,
    "codex": _codex_cli_provider,
    "openai-oauth": _openai_oauth_provider,
}


def load_dotenv(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a .env in the cwd without overriding real env.
    Makes 'drop the files in a project, put your key in .env, go' work."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def pick_provider(name: str) -> str:
    """Resolve 'auto' to a concrete provider from whatever credentials exist."""
    if name != "auto":
        return name
    load_dotenv()
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "api"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    if os.environ.get("OPENAI_API_KEY"):
        return "openai"
    if gemini_creds_path().is_file():          # Gemini subscription (OAuth) login
        return "gemini-oauth"
    if shutil.which("gemini"):                 # Google's own CLI (subscription)
        return "gemini-cli"
    if codex_auth_path().is_file():            # Codex subscription, no child process needed
        return "openai-oauth"
    if shutil.which("codex"):                  # OpenAI Codex CLI (ChatGPT subscription)
        return "codex"
    if shutil.which("claude"):                 # Claude subscription CLI
        return "cli"
    raise RuntimeError(
        "no backend found. Set ANTHROPIC_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY "
        "(a .env in this folder works), or log in by subscription "
        "(`python ctx.py gemini-login`, or the `claude`/`gemini` CLI), "
        "or pass --provider fake for an offline demo.")


def resolve_provider(name: str, model: Optional[str] = None,
                     sub_model: Optional[str] = None,
                     fake: Optional[LLMFn] = None) -> Provider:
    if name == "fake" or fake is not None:
        if fake is None:
            raise ValueError("provider 'fake' requires an injected llm function")
        return Provider(root=fake, sub=fake)
    load_dotenv()
    name = pick_provider(name)
    dm = DEFAULT_MODELS.get(name, ("", ""))
    builder = _BUILDERS.get(name)
    if builder is None:
        raise ValueError(f"unknown provider: {name}")
    return builder(model or dm[0], sub_model or dm[1])


# --------------------------------------------------------------- entry ----

def rlm_query(context: str, query: str, provider: Provider,
              cfg: Optional[RLMConfig] = None,
              graph: Optional[Graph] = None) -> RLMResult:
    """Run an RLM query over `context`. The root never receives `context` directly."""
    cfg = cfg or RLMConfig()
    rc, sc = _Counter(), _Counter()
    root = rc.wrap(provider.root)
    sub = sc.wrap(provider.sub)
    traj: list = []
    if cfg.mode == "repl":
        answer = _repl_solve(context, query, root, sub, cfg, graph, traj)
    else:
        answer = _solve(context, query, root, sub, cfg, 0, traj)
    ctx_tok, ans_tok = est_tokens(context), est_tokens(answer)
    ledger_log("rlm", ctx_tok, ans_tok, f"{cfg.mode}:{query[:60]}")
    return RLMResult(answer=answer, calls=rc.n + sc.n,
                     context_tokens=ctx_tok, answer_tokens=ans_tok,
                     trajectory=traj)


# Map our providers onto the official lib's backend names.
_OFFICIAL_BACKEND = {"api": "anthropic", "openai": "openai", "gemini": "openai", "cli": "anthropic"}


def _import_official():
    """Import the official `rlms` package, working around our local rlm.py shadowing
    its top-level `rlm` import. Returns the module or None if unavailable."""
    import importlib
    here = os.path.dirname(os.path.abspath(__file__))
    saved_self = sys.modules.pop("rlm", None)
    saved_path = [p for p in sys.path if os.path.abspath(p or ".") == here]
    for p in saved_path:
        sys.path.remove(p)
    try:
        for modname in ("rlms", "rlm"):
            try:
                return importlib.import_module(modname)
            except ImportError:
                continue
        return None
    finally:
        sys.path[:0] = saved_path or [here]
        if saved_self is not None:
            sys.modules["rlm"] = saved_self


def run_official(context: str, query: str, provider: str, model: Optional[str],
                 cfg: Optional[RLMConfig] = None) -> RLMResult:
    """Delegate to the real Recursive Language Models library (`pip install rlms`).
    Raises RuntimeError if it is not importable so the caller can fall back to ours."""
    cfg = cfg or RLMConfig()
    mod = _import_official()
    RLM = getattr(mod, "RLM", None) if mod else None
    if RLM is None:
        raise RuntimeError("official engine unavailable (pip install rlms); use --engine ours")
    concrete = pick_provider(provider)
    backend = _OFFICIAL_BACKEND.get(concrete, "openai")
    mdl = model or DEFAULT_MODELS.get(concrete, ("", ""))[0]
    rlm_obj = RLM(backend=backend, backend_kwargs={"model_name": mdl}, environment="local")
    # The official root reads context from the prompt body itself.
    result = rlm_obj.completion(f"{query}\n\n--- CONTEXT ---\n{context}")
    answer = getattr(result, "response", str(result))
    ctx_tok, ans_tok = est_tokens(context), est_tokens(answer)
    ledger_log("rlm", ctx_tok, ans_tok, f"official:{query[:60]}")
    return RLMResult(answer=answer, calls=0, context_tokens=ctx_tok,
                     answer_tokens=ans_tok, trajectory=[{"engine": "official",
                                                         "backend": backend, "model": mdl}])
