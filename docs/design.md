# Design

CTX Agent Context Stack combines independent context-management techniques
behind one project-root workflow:

- CTX map/digest/run for deterministic input filtering.
- TVL accounting for measurable token admission and savings.
- RLM delegation for questions over large semantic contexts.
- CodeGraph retrieval for symbols, dependencies, and affected tests.
- Markdown/Obsidian durable memory for knowledge outside chat history.
- A vendor-neutral handoff contract for collaboration between different agents.

The toolkit remains two portable Python files plus an installer. Agent-specific
files are adapters; `AGENT_CONTEXT.md`, `handoff.md`, and `memory/` are the
universal protocol.
