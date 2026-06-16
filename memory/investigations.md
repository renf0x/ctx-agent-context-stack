# Investigation Log

## INV-000 Template

- Status: example
- Date: YYYY-MM-DD
- Question:
- Findings:
- Conclusion:
- Links:

## INV-20260616-001 Context reduction and memory audit

- Status: closed
- Date: 2026-06-16
- Question: Does CTX/RLM/memory produce measured context reduction and useful durable agent memory on a large project?
- Findings: On a safe copy of `private-project`, deterministic `ctx digest` avoided admitting 93,888 estimated tokens of text across 10 expensive files (19.6x), but SQL/CSS recall quality is not guaranteed and `seed.sql` over-compression is a warning case. Startup routing through instructions, handoff, project context, and memory index is about 5,951 tokens versus about 354,281 tokens for the copied project (59.5x smaller than a full-read baseline). Real external RLM attempts through OpenAI OAuth and opencode free providers were blocked by execution policy because they would transmit private repository content to external providers.
- Conclusion: Deterministic CTX context reduction is real and measurable; actual provider-token/billing savings and RLM answer-quality improvement remain unproven until an A/B benchmark or permitted provider/sanitized benchmark is used. `private-project` memory is useful but not compliant with the current CTX memory schema.
- Links: [[../docs/token-memory-audit]]
