# CTX Agent Context Stack

**Token budgeting, RLM delegation, CodeGraph retrieval, durable memory, and
cross-agent handoff for coding agents.**

**Version: 0.0.3**

CTX Agent Context Stack is an experimental, portable toolkit that combines
several context-engineering methods. Its goal is to stop coding agents from
re-reading an entire repository and a long chat history on every turn.

It works with Claude Code, Codex, Cursor, Copilot, Gemini, Cline, Roo,
OpenCode, and other agents that can read project files or run shell commands.

## What It Combines

| Method | Purpose |
|---|---|
| **CTX map** | Estimates which project files are expensive to read |
| **CTX digest** | Replaces a large file with a structural summary |
| **CTX run** | Filters long test/build logs and saves the full output locally |
| **CTX rawcount** | Measures the unsqueezed baseline context size with no compression |
| **TVL ledger** | Measures admitted and avoided tokens instead of guessing savings |
| **RLM** *(optional)* | Delegates questions over large contexts to recursive sub-agent calls — only when an RLM model is configured |
| **CodeGraph** | Retrieves symbols, dependencies, and affected tests |
| **Durable memory** | Stores stable knowledge in Markdown/Obsidian outside chat history |
| **Universal handoff** | Transfers tasks and verified state between different agents |
| **Context routing** | Selects the smallest suitable tool for each kind of question |

These techniques solve different problems. RLM is not a replacement for
CodeGraph, and memory is not a replacement for source code. The stack routes
each question to the least expensive useful source.

## Why This Can Save Agent Limits

A normal long-running agent session may repeatedly send:

- project instructions;
- conversation history;
- full source files;
- test and build logs;
- repeated architecture explanations.

This toolkit keeps startup context small:

```text
memory/MEMORY.md
handoff.md
memory/project-rules.md
limited CodeGraph context
```

Detailed notes, archives, source files, and logs are retrieved only when needed.

## Current Evidence and Limits

This project is still being tested. The current evidence supports **measured
context reduction**, not a blanket claim of lower provider billing or better
answers in every agent session.

What has been observed in a real-project audit on a safe copy of `TravelAgent`
(`docs/token-memory-audit.md`):

- Full copied project size: approximately **354,000 estimated tokens**.
- Recommended startup packet (`AGENTS.md`, `handoff.md`, `PROJECT_CONTEXT.md`,
  `memory/MEMORY.md`): approximately **5,900 estimated tokens**. This is a
  **59.5x smaller startup baseline than a full-project read**, not proof that a
  normal Codex/Claude session would otherwise read the entire project.
- `ctx digest` on 10 expensive files reduced admitted text from approximately
  **98,900 to 5,000 estimated tokens** (**19.6x smaller**). This proves
  deterministic text reduction by the tool, not actual provider usage savings
  unless the agent would otherwise have read those full files.
- The memory vault improved continuity by preserving stable architecture,
  operations, CRM/admin, CSS, and SQL-consolidation facts outside chat history.

What is **not yet proven**:

- Statistically robust end-to-end provider-token savings for Codex/Claude
  sessions. That requires repeated A/B benchmarks using provider usage metrics,
  equal tasks, equal models, fresh sessions, measured tool output, and task
  success scoring.
- RLM answer-quality improvement on private repositories. Real external-provider
  runs were blocked in the audit environment because they would send private
  repository content to external services.
- Higher compression is not automatically better. The audit found that
  `supabase/seed.sql` compressed from about **8,500 to 19 tokens**; this is a
  warning sign that the current generic digest can discard too much SQL meaning.
  SQL and CSS need file-type-aware digesters and recall tests.

Use the current numbers as **context-admission evidence**: CTX can show how much
text it avoided putting in the agent-visible context. Treat the current
end-to-end limit result below as preliminary until it is repeated.

### Preliminary Claude Code A/B Benchmark

A controlled synthetic task was run once in two fresh Claude Code sessions:

- `without-ctx`: normal search/read workflow.
- `with-ctx`: mandatory `ctx rawcount`, `ctx map`, `ctx digest`, and `ctx run`
  rules before source inspection and verification.

Both runs solved the same weather-state bug and passed the same focused test.
The observed Claude Code session-limit meter changed as follows:

| Metric | Without CTX | With CTX | Difference |
|---|---:|---:|---:|
| Session before | 19% | 22% | n/a |
| Session after | 22% | 24% | n/a |
| Visible session spend | **3 percentage points** | **2 percentage points** | **1 pp lower** |
| Weekly before | 2% | 3% | n/a |
| Weekly after | 3% | 3% | n/a |
| Visible weekly spend | **1 percentage point** | **0 visible pp** | below display threshold |

The CTX ledger for the `with-ctx` run recorded:

```text
op        calls   raw tokens     admitted        saved   ratio
digest        1       17,590        4,217       13,373    4.2x
run           1            7            7            0    1.0x
TOTAL         2       17,597        4,224       13,373    4.2x
```

Interpretation: in this single paired run, CTX reduced visible session spend
from 3 percentage points to 2 percentage points, roughly one third lower. This
is a practical signal, not a statistical claim: the UI meter is rounded, prompt
cache and reasoning tokens are not exposed, and one run cannot establish a
general average. If the same ratio holds across repeated similar tasks, it would
be equivalent to roughly 1.5x more work per visible session-limit budget.

See `docs/claude-code-ab-benchmark.md` for the detailed run notes.

Example from the project where this toolkit was developed:

- Full textual project: approximately **152,000 tokens**.
- Task startup context: approximately **2,700 tokens**.
- CodeGraph index after correct exclusions: **69 project files / ~1.2 MB**,
  rather than accidentally indexing thousands of dependency files.

Actual results depend on the repository and agent. Use `ctx report`; do not rely
on marketing estimates.

## Quick Start

### Requirements

- Python 3.10+
- Optional: Node.js and CodeGraph
- Optional: Obsidian (a human-facing viewer for the memory vault)
- A supported RLM provider if you want semantic large-context queries

Install CodeGraph:

```powershell
npm install -g @colbymchenry/codegraph
```

### Install Into Any Project

Clone this repository, then run:

```powershell
git clone https://github.com/renf0x/ctx-agent-context-stack.git
cd ctx-agent-context-stack
python install.py C:\path\to\your-project --agents all --open-obsidian
```

The installer places the portable toolkit in the **root of the target project**:

```text
your-project/
  ctx.py
  rlm.py
  AGENT_CONTEXT.md
  AGENTS.md
  CLAUDE.md
  handoff.md
  memory/
```

It does not overwrite existing `AGENTS.md` or `CLAUDE.md`. It appends one
marked adapter block and remains idempotent on repeated installation.

Agent selection:

```powershell
python install.py . --agents generic
python install.py . --agents generic,codex
python install.py . --agents generic,claude
python install.py . --agents all
```

Different agents read different instruction files, so pick the ones you
actually use. The installer never overwrites them — it appends one marked,
idempotent adapter block:

| Option | Wires the protocol into |
|---|---|
| `generic` | `AGENT_CONTEXT.md` — the vendor-neutral protocol every agent follows |
| `codex` | `AGENTS.md` — read by Codex, Cursor, Copilot, Gemini, Cline, Roo, … |
| `claude` | `CLAUDE.md` — read by Claude Code |
| `all` (default) | all of the above |

So: only Claude Code → `--agents generic,claude`; only Codex → `generic,codex`;
several agents → `all`.

### Global install (optional)

`install.py` drops a local `ctx.py` / `rlm.py` copy into each project, invoked
as `python ctx.py <cmd>`. To get the shorter `ctx` / `rlm` commands that resolve
from any folder, install the package once:

```powershell
pip install .
```

This registers three console scripts — `ctx`, `rlm`, and `ctx-rlm-login`. A
local `ctx.py` copy still takes priority when present, so per-project pinning
keeps working.

### Quick use in a project

1. Install once into the project:
   `python install.py . --agents <yours> --open-obsidian`
   (also scaffolds the shared `memory/` vault and the handoff/adapter files).
2. After that the agent applies the protocol automatically — its instruction
   file now points at `AGENT_CONTEXT.md`, so you rarely type commands yourself.

When you do, these cover almost everything:

```powershell
ctx map                          # see what is expensive to read first
ctx run -- npm test              # filter a noisy command; full log saved locally
rlm --query "<question>"         # answer over a huge context, not your window
ctx memory query "<question>"    # ask durable project memory
ctx report                       # admitted-vs-raw context reduction report
```

## Normal Usage

### How to invoke (`ctx`/`rlm` vs `python ctx.py`)

Commands below are written as `ctx <cmd>` / `rlm` — the canonical entry points
when the toolkit is installed so it resolves from any folder. `install.py`
instead drops a local `ctx.py` / `rlm.py` copy into the project root; that copy
is invoked as `python ctx.py <cmd>` / `python rlm.py`. **Rule: a local `ctx.py`
in the working directory takes priority; otherwise use the global `ctx`/`rlm`
command.** Both share the same `.ctx/ledger.jsonl` log and behave identically.

The user should not need to type these commands for every task. Installed agent
instructions tell supported agents to use the protocol automatically.

**The context-saving ladder** (climb from cheap to expensive, stop at the first
rung that answers the task): memory → CodeGraph (`codegraph context`) → `ctx map`
→ `ctx digest` → `ctx read` (funnelled full read) → `ctx run` for commands →
**RLM only if a model is configured**. RLM is optional: with no dedicated model
set up, skip it and stay on digest/map. Durable findings go into the Obsidian
memory vault so the next session does not re-read them.

Manual commands are useful for diagnostics:

```powershell
# Estimate repository context cost
ctx map

# Summarize a large file structurally
ctx digest src/large-file.ts

# Filter noisy output while retaining the complete local log
ctx run -- npm test

# Read a whole file when you truly need it -- logged as an uncompressed pull so
# the savings report's percentage reflects ALL context, not just the wins
ctx read src/config.json

# Build a small task context
ctx memory context "fix progress persistence"

# Ask about durable project memory
ctx memory query "which architectural decisions affect progress?"

# Ask about memory plus the entire source tree
ctx memory query "how does progress persistence work?" --scope project

# Validate links, size limits, journals, and protected rules
ctx memory check

# Show the full unsqueezed baseline for a file or project
ctx rawcount .

# Show measured context reduction (CONTENT FLOW vs RECONNAISSANCE)
ctx report

# If a background coverage hook is wired, give its last async write a beat to land
ctx report --settle 1500
```

### Coverage Hook And The Savings Report

`ctx report` separates two things on purpose:

- **CONTENT FLOW** — real file content pulled for the task (`digest`, `read`,
  `rlm`, plus `direct` reads captured by the hook). This is the honest headline:
  reduction %, ratio, and **tracked file-content coverage**.
- **RECONNAISSANCE** — `map` only. It lists the repo without reading it, so its
  huge ratio is *not* a real saving and is kept out of the headline.

Coverage is "tracked file-content coverage": it accounts for `Read`/`Bash` pulls
seen by the hook and the `ctx` funnels. `Grep`/`Glob`/MCP/sub-agent outputs are
not yet counted, so the true total context can be higher than reported.

To capture reads that bypass `ctx`, wire a `PostToolUse` hook (Claude Code):

```json
{
  "hooks": {
    "PostToolUse": [
      { "matcher": "Read|Bash",
        "hooks": [ { "type": "command", "command": "ctx hook", "async": true } ] }
    ]
  }
}
```

The hook is silent, always exits 0, never blocks the agent, skips `ctx`/`rlm`'s
own commands (so they are not double-counted), and de-duplicates a tool call by
its `tool_use_id`.

> **Permissions / safety.** Allow only the *installed* commands —
> `Bash(ctx *)` / `Bash(rlm *)` — never `Bash(python ctx.py *)`. A local
> `ctx.py` takes priority over the global install, so auto-allowing
> `python ctx.py` would let any cloned repo's `ctx.py` run without a prompt.

## RLM Sub-Agent Options

> **RLM is optional.** It is the last rung of the ladder and only pays off when a
> question spans more content than is reasonable to digest *and* you have an RLM
> provider/model configured. If no dedicated RLM model is set up, skip it — the
> deterministic tools (map/digest/read/run) and CodeGraph cover everyday work.

RLM processes large context in chunks with multiple sub-model calls and returns
only a short synthesized answer to the main agent.

Available providers:

| Provider | Example | Uses |
|---|---|---|
| **Auto** | `--provider auto` | First available configured provider |
| **OpenAI OAuth** | `--provider openai-oauth` | Existing Codex/ChatGPT subscription login |
| **Codex CLI** | `--provider codex` | `codex exec` child processes |
| **OpenAI API** | `--provider openai` | `OPENAI_API_KEY` |
| **OpenRouter API** | `--provider openrouter --model <slug>` | `OPENROUTER_API_KEY`; model slug is required |
| **Claude CLI** | `--provider cli` | Existing Claude CLI subscription login |
| **Anthropic API** | `--provider api` | `ANTHROPIC_API_KEY` |
| **Gemini OAuth** | `--provider gemini-oauth` | Your own Google OAuth client credentials |
| **Gemini CLI** | `--provider gemini-cli` | Installed Gemini CLI |
| **Gemini API** | `--provider gemini` | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| **Fake** | `--provider fake` | Offline plumbing test without real reasoning |

Examples:

```powershell
# Reuse a Codex subscription login
ctx memory query "describe the architecture" --scope project `
  --provider openai-oauth

# Reuse Claude CLI
ctx memory query "find risky architectural coupling" --scope project `
  --provider cli

# Use a specific OpenRouter model slug
ctx memory query "describe the architecture" --scope project `
  --provider openrouter `
  --model deepseek/deepseek-chat-v3.1

# Gemini subscription through Google's official CLI
ctx memory query "summarize previous investigations" `
  --provider gemini-cli

# Custom Gemini OAuth application
$env:GEMINI_OAUTH_CLIENT_ID = "your-client-id"
$env:GEMINI_OAUTH_CLIENT_SECRET = "your-client-secret"
ctx gemini-login

# API keys can also be placed in a local .env
ctx memory query "what decisions are still active?" --provider auto
```

### Important Limit Note

RLM saves the **main agent's context window**, but its recursive calls consume
the selected provider's allowance:

- `openai-oauth` consumes the OpenAI/Codex subscription allowance;
- `cli` consumes the Claude subscription allowance;
- API providers consume their API billing;
- `fake` consumes no external model allowance.

Use RLM for broad questions over large content, not for small targeted reads.

## Universal Cross-Agent Handoff

`AGENT_CONTEXT.md` is vendor-neutral. The same `handoff.md` can be continued by
Claude, Codex, Cursor, Copilot, Gemini, or another agent.

The handoff contains tasks only:

```markdown
# Project Handoff

## Now

### TASK-20260615-001
- Status: in-progress
- Goal:
- Acceptance:
- Links:

## Next

## Blocked

## Done this session
```

Conversation summaries do not belong in handoff. Durable facts go into:

```text
memory/
  MEMORY.md
  project-rules.md
  architecture.md
  decisions.md
  bugs.md
  investigations.md
  operations.md
  changelog.md
  archive/
```

This separation lets another agent continue from verified state without
receiving the previous agent's full conversation.

## Protected Project Rules

`memory/project-rules.md` belongs to the user. Agents must not edit or weaken it
without explicit approval.

After an approved change:

```powershell
ctx memory rules-approve --user-approved
```

`memory check` reports unapproved rule changes.

## Obsidian

`memory/` is itself a plugin-free Obsidian vault: `memory init` writes a
committed `.obsidian/` config (only machine-local `workspace.json`/`cache` is
ignored). Because the vault lives **in the repository**, it is shared — clone
the project and the common memory comes with it, ready to open in Obsidian and
readable by every agent, including Codex. Do not keep durable memory in any
agent's private store outside the repo.

```powershell
ctx memory open --install-obsidian
```

This registers and opens the **`memory/` folder** as the vault (it also closes
a running Obsidian first so the registration is not overwritten). Open the
`memory/` subfolder — not the project root: opening the root pulls in
`node_modules`/`dist` READMEs and clutters the graph. On Windows the command
uses `winget` when available; otherwise it downloads the installer only from the
official `obsidianmd/obsidian-releases` GitHub repository.

No Obsidian MCP server is required. The vault is plain Markdown: an agent reads
the notes, searches, and follows `[[links]]`/backlinks directly through normal
file access. Obsidian itself is only a human-facing viewer for the graph and
editing — both operate on the same files.

## CodeGraph

CodeGraph is used for structural questions:

```powershell
codegraph context "where is authentication state updated?"
codegraph affected src/auth/store.ts
```

Generated files and dependencies must be ignored. The initializer creates a
basic `.gitignore` only when the project does not already have one.

## Files Not To Commit

```text
.ctx/
.codegraph/
__pycache__/
node_modules/
dist/
build/
```

Commit the whole `memory/` vault — the notes plus `.obsidian/app.json` /
`templates.json`. It is the shared, cross-agent durable knowledge and is meant
to travel with the repo so anyone who clones gets the same memory, ready for
Obsidian. Only `memory/.obsidian/workspace.json` and `cache` stay machine-local
(handled by the vault's own `.gitignore`).

## Status

This is an experimental context-engineering toolkit, not a guarantee of lower
billing or better answers. Measure results with your own repositories and model
providers.

## License

MIT
