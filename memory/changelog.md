# Memory Changelog

Record meaningful changes to the memory system.

## 2026-06-16

- Added a raw no-compression token baseline workflow via `ctx rawcount`.
- Prepared `TravelAgent` / `TravelAgent-noctx` folders for comparing ctx-assisted
  and non-ctx agent workflows.
- Added a generated `ctx-benchmark-lab` fixture on the Desktop for a controlled
  ctx vs no-ctx task.
- Added explicit OpenRouter RLM provider support with required model slug
  selection.
- Widened ledger coverage and richness: `map` and `memory context` now write
  records; `rlm` records carry provider/model/sub-LM-call-count/duration.
- Added `ctx read <file>`: prints a file verbatim and logs it as an uncompressed
  pull, giving `report` an honest denominator for the savings percentage.
- `ctx report` now prints a true saved-% over real content pulls (recon ops like
  `map` excluded so a hypothetical read-everything denominator cannot inflate
  it), a coverage line (compressed vs raw pulls), and an rlm provider breakdown.
- Ledger records gained a `v: 2` schema tag; extra fields are additive so old
  records and the aggregator keep working.
- Rewrote agent instructions (`templates/AGENT_CONTEXT.md`, adapter
  `CLAUDE.md`/`AGENTS.md`, README) around an explicit context-saving ladder
  (memory -> CodeGraph -> map -> digest -> read -> run -> RLM). RLM is now framed
  as optional (only with a configured model); CodeGraph and the Obsidian memory
  vault are emphasized as everyday savings tools.
- Added `ctx hook`: a silent PostToolUse hook that reads the Claude Code event
  JSON on stdin and logs context pulled by direct `Read`/`Bash` calls as
  `op:"direct"` (a raw pull). This fills the coverage denominator with reads that
  bypass ctx, so `report` coverage reflects ALL context, not just voluntary
  `ctx read` pulls.
