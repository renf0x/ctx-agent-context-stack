# Universal Agent Context Protocol

This file is vendor-neutral. Any coding agent working in this project should
follow it, whether it is Claude, Codex, Cursor, Copilot, Gemini, Cline, Roo,
OpenCode, or another tool.

The goal is simple: **answer the task while pulling as few tokens into context as
possible.** Reading whole files and dumping raw command output is the expensive
default. The tools below exist so you almost never have to.

## Start Of Work

1. If `memory/MEMORY.md` is missing, run:
   `python ctx.py memory init --with-codegraph`.
2. After first-time initialization, run once:
   `python ctx.py memory open --install-obsidian`.
3. Read only these three at session start — nothing else yet:
   - `memory/MEMORY.md`
   - `handoff.md`
   - `memory/project-rules.md`
4. For anything about code structure ("where is X", "who calls Y", "what does
   this import"), use CodeGraph first — not grep-then-read:
   `codegraph context "<task>"`.
5. For a broad question about durable project knowledge, ask the memory vault:
   `python ctx.py memory query "<question>"`
   (add `--scope project` only when the answer truly needs the whole codebase).

## The Context-Saving Ladder

Always climb from cheap to expensive. Stop at the first rung that answers the
question — do not jump straight to reading files.

1. **Memory** — `memory/MEMORY.md` + journals already hold decided facts. Check
   here before re-investigating anything.
2. **CodeGraph** — `codegraph context "<task>"` for symbols, callers, and
   dependencies. One call replaces many grep + open-file round trips.
3. **Map** — `python ctx.py map` to see where the tokens are before touching a
   file. Anything flagged EXPENSIVE should be digested, not read.
4. **Digest** — `python ctx.py digest <file>` for the structure (signatures,
   imports, classes) of any file over ~300 lines. Read the full file only after
   the digest proves you need a specific part.
5. **Read (funnelled)** — when you genuinely must read a whole file, pull it with
   `python ctx.py read <file>` instead of the bare editor read. It returns the
   same bytes but logs the pull, so `ctx report` reflects real coverage. Direct
   `Read`/`Bash` are also captured automatically when the `ctx hook` is wired.
6. **Run** — never let a noisy command dump into context. Wrap it:
   `python ctx.py run -- <command>` keeps only the salient extract and writes the
   full log to `.ctx/logs/`.
7. **RLM (optional)** — only when a question spans more content than is
   reasonable to digest, AND an RLM provider/model is configured. If none is set
   up, skip this rung and stay on digest/map — do not block on it.

After a chunk of work, run `python ctx.py report` to see admitted-vs-avoided
tokens and coverage. Rising "direct"/"read" raw tokens with low coverage means
you are bypassing the ladder — climb it instead.

## Obsidian Memory Vault — Write What You Learn

The `memory/` vault is the project's durable brain, browsable in Obsidian. It is
how the *next* session avoids re-reading what this one already understood.

- Record durable findings in the right journal: `architecture.md`,
  `decisions.md`, `bugs.md`, `investigations.md`, `operations.md`.
- Link related notes with `[[wiki-links]]` so the graph stays navigable.
- Keep `MEMORY.md` as a thin index — one line per note, no content.
- Never store full source files, large logs, secrets, or generated output in
  memory. Store the conclusion, not the raw material.

## Context Budget Rules

- Prefer digest over read; prefer `ctx run` over raw command output.
- Funnel unavoidable full reads through `ctx read` (or rely on the `ctx hook`).
- RLM is by choice, not by default — use it only with a configured model.
- Use `/compact` between substantial tasks and `/clear` for unrelated work.

## Handoff Contract

`handoff.md` is the shared queue for every agent. It contains only:

- `Now`: task currently being executed.
- `Next`: ordered future tasks.
- `Blocked`: blockers requiring user or external action.
- `Done this session`: completed work, checks, and important file changes.

Every task uses a stable `TASK-YYYYMMDD-NNN` identifier and includes:

- Status
- Goal
- Acceptance criteria
- Relevant links

At task completion:

1. Update the relevant memory journal (durable knowledge, not chatter).
2. Move/update the task in `handoff.md`.
3. Run `python ctx.py memory check`.
4. Leave the next agent a concrete next action rather than conversational history.

## Permanent Rules

Never edit `memory/project-rules.md` without explicit user instruction or
confirmation. After an approved change run:

```text
python ctx.py memory rules-approve --user-approved
```
