<!-- CTX-AGENT-CONTEXT-STACK:START -->
## CTX Agent Context Stack

Follow `AGENT_CONTEXT.md`. The point is to answer tasks while pulling as few
tokens into context as possible — climb the context-saving ladder instead of
reading whole files.

At session start read only `memory/MEMORY.md`, `handoff.md`, and
`memory/project-rules.md`. Then:

- **CodeGraph first** for any code-structure question (`codegraph context
  "<task>"`) — symbols, callers, dependencies — instead of grep + open file.
- **CTX** for bulk: `ctx map` before touching files, `ctx digest <file>` for big
  files, `ctx read <file>` when a full read is unavoidable, `ctx run -- <cmd>`
  for noisy commands. Check `ctx report` to see real savings and coverage.
- **Obsidian memory vault** is the durable brain: write findings into the right
  journal and link with `[[wiki-links]]`; keep `MEMORY.md` a thin index.
- **RLM is optional** — use `ctx rlm`/`rlm --query` only when a question spans
  more than is reasonable to digest AND an RLM model is configured. With no
  model set up, skip it and stay on digest/map.

If the memory vault is missing, run:

```powershell
python ctx.py memory init --with-codegraph
python ctx.py memory open --install-obsidian
```

Do not change permanent project rules without explicit user approval. At task
completion update the universal handoff, record durable findings in the memory
journals, and run `python ctx.py memory check`.
<!-- CTX-AGENT-CONTEXT-STACK:END -->
