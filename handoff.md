# Handoff

## Now

- Rewrote agent instructions around a context-saving ladder (memory -> CodeGraph
  -> map -> digest -> read -> run -> RLM). RLM is now optional (only with a
  configured model); CodeGraph + Obsidian memory framed as everyday savings.
  Files: `templates/AGENT_CONTEXT.md`, `templates/adapters/{CLAUDE,AGENTS}.md`,
  `README.md`.
- Broadened and enriched ledger logging:
  - `map` and `memory context` now write ledger records (were invisible before).
  - `rlm` records carry provider/model/sub-LM calls/duration.
  - New `ctx read <file>` funnel logs uncompressed pulls as the savings
    denominator (`op:"read"`, raw == kept).
  - `ctx report` shows an honest saved-% over content pulls only (recon `map`
    excluded), a coverage line, and a per-provider rlm breakdown. Schema tagged
    `v: 2`; additive and backward compatible. Covered by new `LedgerTests`.
  - New `ctx hook` (silent PostToolUse hook, JSON on stdin) logs direct
    `Read`/`Bash` pulls as `op:"direct"`, so coverage reflects context that
    bypasses ctx. Opt-in via settings.json (see below); not yet wired by default.
- Added `ctx rawcount <path|->` as the no-compression baseline token meter.
- Created `C:\Users\renf\Desktop\TravelAgent-noctx` as a copy of `TravelAgent`
  without ctx/RLM/CodeGraph/memory tooling instructions or files.
- Added local `ctx.py` and `rlm.py` to the original
  `C:\Users\renf\Desktop\TravelAgent`.
- Created `C:\Users\renf\Desktop\ctx-benchmark-lab` with `with-ctx` and
  `without-ctx` fixture projects plus prompts for fresh-session benchmarking.
- Added explicit OpenRouter provider support: `--provider openrouter --model
  <openrouter-model-slug>` with `OPENROUTER_API_KEY`.

## Next

### TASK-20260616-001 A/B benchmark for actual provider-token impact

- Status: next
- Goal: Prove or disprove actual end-to-end provider-token reduction versus normal agent workflow.
- Acceptance: Benchmark design covers 20-50 comparable tasks, baseline vs CTX runs, same model, fresh sessions, provider usage metrics, tool-output volume, files read, repeated reads, runtime, and task success.
- Links: `docs/token-memory-audit.md`

### TASK-20260616-002 SQL/CSS-aware digest quality

- Status: next
- Goal: Replace misleading high-compression cases with file-type-aware digests and recall checks.
- Acceptance: SQL digest preserves schema objects, table names, insert targets, column lists, row counts, representative values, policies/indexes/constraints; CSS digest preserves selectors, custom properties, media queries, and layout-critical properties. `seed.sql`-style extreme compression is reported as a warning unless recall is validated.
- Links: `ctx.py`, `docs/token-memory-audit.md`

### TASK-20260616-003 RLM quality benchmark on permitted data

- Status: next
- Goal: Measure RLM answer quality without violating private-repository data policy.
- Acceptance: Add a sanitized/public benchmark repository or fixture, run real provider RLM on broad questions, compare answers against ground truth, and report accuracy/failure modes separately from token reduction.
- Links: `rlm.py`, `docs/token-memory-audit.md`

### TASK-20260616-004 CodeGraph project mismatch guard

- Status: next
- Goal: Prevent agents from trusting CodeGraph output built for the wrong project.
- Acceptance: `ctx memory context` or CodeGraph integration detects missing/stale/wrong `.codegraph` project roots and fails loudly instead of returning unrelated symbols.
- Links: `ctx.py`, `docs/token-memory-audit.md`

### TASK-20260616-005 Memory schema migration for existing projects

- Status: next
- Goal: Normalize older project memories without overwriting user notes.
- Acceptance: `ctx memory init` preserves existing files, creates missing schema files/templates/checksums, and documents how to split durable facts from task-only handoff.
- Links: `memory/`, `docs/token-memory-audit.md`

## Blocked

### TASK-20260616-006 Private-repo external RLM run

- Status: blocked
- Goal: Run RLM quality tests on the private `TravelAgent` repository through OpenAI/opencode providers.
- Blocker: Current execution policy rejects sending private repository content to external providers, even after user approval.
- Unblock: Use a local model, a sanitized public fixture, or a different execution environment where the data-transfer policy permits the run.

## Done this session

### 2026-06-16 Raw baseline meter and TravelAgent A/B copy

- Added `ctx rawcount` for file/directory/stdin baseline token counts with no
  compression, no LLM call, and no ledger write.
- `rawcount` reuses the directory skip rules and reports skipped secret-looking
  files.
- Added a unit test covering directory counting, secret exclusion, and no
  ledger side effect.
- Created `TravelAgent-noctx` outside this repo and stripped ctx/RLM/CodeGraph
  context tooling from agent docs and local files.
- Original `TravelAgent` now has local `ctx.py` and `rlm.py`.
- Created `ctx-benchmark-lab` on the Desktop. It contains a copy of this ctx
  repository, a `with-ctx` synthetic weather task with strict digest/run rules,
  a matching `without-ctx` control, and prompt files for both runs.

### 2026-06-16 OpenRouter provider support

- Added `--provider openrouter` for RLM calls.
- OpenRouter requires `OPENROUTER_API_KEY` and an explicit `--model` slug.
- If `--sub-model` is omitted, OpenRouter reuses `--model` for sub-LM calls.

### 2026-06-16 Token/memory audit

- Created `docs/token-memory-audit.md`.
- Bootstrapped project memory and opened the Obsidian vault once.
- Audited deterministic CTX context reduction on a safe copy of `TravelAgent` under `.ctx/audit/TravelAgent-copy`; original `TravelAgent` was not modified.
- Confirmed real measured context reduction for `ctx digest` and startup memory routing.
- Attempted real external RLM through OpenAI OAuth and opencode free providers, but both were blocked by execution policy because they would send private repository content to external services.
- Added README status language: current numbers prove measured context reduction, not confirmed provider-billing savings or RLM answer-quality improvement.
