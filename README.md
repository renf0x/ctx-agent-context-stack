# CTX Agent Context Stack

**Token budgeting, RLM delegation, CodeGraph retrieval, durable memory, and
cross-agent handoff for coding agents.**

**Version: 0.0.1**

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
| **TVL ledger** | Measures admitted and avoided tokens instead of guessing savings |
| **RLM** | Delegates questions over large contexts to recursive sub-agent calls |
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

Manual commands are useful for diagnostics:

```powershell
# Estimate repository context cost
ctx map

# Summarize a large file structurally
ctx digest src/large-file.ts

# Filter noisy output while retaining the complete local log
ctx run -- npm test

# Build a small task context
ctx memory context "fix progress persistence"

# Ask about durable project memory
ctx memory query "which architectural decisions affect progress?"

# Ask about memory plus the entire source tree
ctx memory query "how does progress persistence work?" --scope project

# Validate links, size limits, journals, and protected rules
ctx memory check

# Show measured savings
ctx report
```

## RLM Sub-Agent Options

RLM processes large context in chunks with multiple sub-model calls and returns
only a short synthesized answer to the main agent.

Available providers:

| Provider | Example | Uses |
|---|---|---|
| **Auto** | `--provider auto` | First available configured provider |
| **OpenAI OAuth** | `--provider openai-oauth` | Existing Codex/ChatGPT subscription login |
| **Codex CLI** | `--provider codex` | `codex exec` child processes |
| **OpenAI API** | `--provider openai` | `OPENAI_API_KEY` |
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

The memory directory is a plugin-free Obsidian-compatible vault. Obsidian is
optional; all files remain normal Markdown.

```powershell
ctx memory open --install-obsidian
```

On Windows the command uses `winget` when available. Otherwise it downloads the
installer only from the official `obsidianmd/obsidian-releases` GitHub repository.

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

Commit the memory Markdown files if shared durable project knowledge is desired.

## Status

This is an experimental context-engineering toolkit, not a guarantee of lower
billing or better answers. Measure results with your own repositories and model
providers.

## License

MIT
