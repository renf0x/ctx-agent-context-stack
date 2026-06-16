# CTX/RLM/Memory Token Savings Audit

Date: 2026-06-16

## Executive Summary

The deterministic parts of CTX produce real, measurable **context reduction**
on a large project. On a safe copy of `TravelAgent`, `ctx digest` reduced 10
expensive files from 98,930 estimated tokens to 5,042 admitted tokens, avoiding
93,888 estimated tokens of agent-visible text in one pass, a 19.6x reduction.
A normal startup route through
`AGENTS.md`, `handoff.md`, `PROJECT_CONTEXT.md`, and `memory/MEMORY.md` is
about 5,951 tokens versus about 354,281 tokens for reading the copied project,
about 59.5x smaller.

RLM answer quality was not proven in this run. Real external-provider attempts
were made, but the execution policy blocked sending private repository content
to both OpenAI-backed `openai-oauth` and the free `opencode` provider. The
previous fake-provider path is intentionally excluded from this report because
it proves plumbing only, not answer quality.

The memory system is useful but currently inconsistent in `TravelAgent`.
Existing notes preserve stable project facts, but the vault does not satisfy
the current CTX memory schema, and `handoff.md` is carrying durable architecture
and operations history that should be moved into memory notes.

## Method

All `TravelAgent` experiments were run against:

```text
.ctx/audit/TravelAgent-copy
```

The original `C:\Users\renf\Desktop\TravelAgent` was not modified. The copy
excluded `.git`, `node_modules`, `dist`, `.ctx`, `.claude`, `.codegraph`,
`.env*`, caches, and binary image/archive/runtime files.

The current toolkit project was bootstrapped first with:

```powershell
python ctx.py memory init --with-codegraph
python ctx.py memory open --install-obsidian
```

Token counts are CTX heuristic counts, `chars / 3.5`, not exact provider
billing counts.

## Measured Results

| Scenario | Raw tokens | Admitted tokens | Saved tokens | Ratio | Evidence |
|---|---:|---:|---:|---:|---|
| `ctx-agent-context-stack` full map after memory bootstrap | 34,749 | n/a | n/a | n/a | `ctx map . --top 20` |
| `TravelAgent` safe copy full map | 354,281 | n/a | n/a | n/a | Full-read size baseline, not normal-agent baseline |
| Startup context (`AGENTS.md`, `handoff.md`, `PROJECT_CONTEXT.md`, `memory/MEMORY.md`) | 354,281 | 5,951 | 348,330 | 59.5x | Smaller than full-read baseline, not proven session savings |
| Memory Markdown only | 354,281 | 3,244 | 351,037 | 109.2x | summed `memory/*.md` |
| 10 expensive-file digest sample | 98,930 | 5,042 | 93,888 | 19.6x | Text reduction; utility varies by file type |
| Safe-copy `ctx run -- npm run miniapp:typecheck` | 55 | 55 | 0 | 1.0x | dependencies intentionally excluded |

Final ledger from the copied project:

```text
op        calls   raw tokens     admitted        saved   ratio
digest       10       98,930        5,042       93,888   19.6x
run           1           55           55            0    1.0x
TOTAL        11       98,985        5,097       93,888   19.4x

# saved this session: 93,888 input tokens (~$0.47 at $5.0/MTok, single pass).
```

Digest sample:

| File | Raw | Digest | Ratio |
|---|---:|---:|---:|
| `src/api/adminApi.ts` | 18,586 | 729 | 25.5x |
| `src/admin/src/ui/MapPanel.tsx` | 14,888 | 663 | 22.5x |
| `src/miniapp/src/ui/icons.ts` | 12,227 | 54 | 226.4x |
| `src/core/ui/premiumCards.ts` | 10,992 | 1,250 | 8.8x |
| `src/landing/main.jsx` | 8,670 | 543 | 16.0x |
| `src/admin/src/pages/ReferenceDataPages.tsx` | 8,599 | 977 | 8.8x |
| `supabase/seed.sql` | 8,500 | 19 | 447.4x |
| `src/admin/src/styles/map.css` | 7,169 | 263 | 27.3x |
| `supabase/schema.sql` | 5,994 | 260 | 23.1x |
| `src/miniapp/src/screens/OnboardingScreen.tsx` | 3,305 | 284 | 11.6x |

The `supabase/seed.sql` result is a warning, not a win. A 447.4x reduction
likely means the generic digest discarded most seed data. This is useful as a
signal that SQL needs a specialized digester, but it should not be counted as
high-quality compression for SQL-data questions.

The CSS result has the same caveat at a lower severity. Regex-based digesting
can expose some selectors and comments, but it does not yet preserve enough
selector/property/media-query structure to be trusted as a CSS semantic summary.

## RLM Attempts

Two real external-provider attempts were made and blocked by execution policy:

- `ctx.py rlm . --provider auto` resolved to `openai-oauth`, but was rejected
  because it would transmit private repository content to an external
  OpenAI-backed service.
- `ctx.py rlm README.md --provider opencode` using the free opencode provider
  was also rejected because it would send local repository file content to an
  external provider.

Direct `opencode` itself is installed and can call free models. A short prompt
without repository content worked with `opencode/deepseek-v4-flash-free`, and
`opencode models` listed free options such as `opencode/deepseek-v4-flash-free`,
`opencode/north-mini-code-free`, `openrouter/openrouter/free`, and
`openrouter/qwen/qwen3-coder:free`. That proves availability of the provider,
not permission to send private code through it in this sandbox.

Because real RLM was blocked, this audit cannot claim that RLM improved answer
quality on `TravelAgent`. It can only say that RLM quality remains unmeasured
under the current execution policy.

## Ground-Truth Spot Checks

Manual `rg` spot-checks found the facts a real RLM answer should recover:

- Admin/CRM: `src/api/adminApi.ts`, `src/api/admin/crmRoutes.ts`,
  `src/api/admin/crmRepository.ts`, `src/api/adminAuth.ts`,
  `src/admin/src/App.tsx`, `src/admin/src/pages/CrmBoardPage.tsx`,
  `src/admin/src/pages/CrmUsersPage.tsx`, `src/admin/src/styles/crm.css`,
  `supabase/crm.sql`, and `memory/project_crm_qa.md`.
- E-visa/trip/weather: `src/api/miniapp/evisaRoutes.ts`, `src/core/evisa/*`,
  `src/admin/src/pages/EvisaServicesPage.tsx`,
  `src/core/tracker/stayTrackingService.ts`,
  `src/core/trip/tripSummaryService.ts`, `src/api/miniapp/tripRoutes.ts`,
  `src/core/weather/weatherSummaryService.ts`,
  `src/api/miniapp/weatherRoutes.ts`, and
  `src/api/miniapp/dashboardStateRoutes.ts`.
- Open work: `handoff.md` names `BUG-3`, `BUG-4`, VN content population,
  rate limiting, monitoring, deploy alignment, and infra hardening.
- Onboarding risk: `src/miniapp/src/screens/OnboardingScreen.tsx`,
  `src/api/miniapp/profileRoutes.ts`,
  `src/api/miniapp/dashboardStateRoutes.ts`,
  `src/miniapp/src/screens/WeatherScreen.tsx`, and
  `src/miniapp/src/screens/DashboardScreen.tsx`.

CodeGraph was not reliable in the copied project. Because `.codegraph` was
excluded, `codegraph context "admin CRM architecture"` returned toolkit
context (`ctx.py:MEMORY_REQUIRED`) instead of `TravelAgent`. This is a real
integration hazard: CodeGraph needs a project-local index or a guard that
detects project/index mismatch.

## Memory Findings

`TravelAgent` memory is compact and useful, but not compatible with the current
CTX schema. `ctx memory check` failed with missing required files including
`memory/project-rules.md`, `memory/architecture.md`, `memory/decisions.md`,
`memory/bugs.md`, `memory/investigations.md`, `memory/operations.md`,
`memory/changelog.md`, archive folders, templates, Obsidian config, and
`.rules.sha256`.

The existing notes still improve continuity:

- `memory/MEMORY.md` is a compact index.
- `memory/project_admin_panel.md` and `memory/project_crm_qa.md` preserve admin
  and CRM architecture.
- `memory/project_vds_server.md` preserves operations facts.
- `memory/project_sql_consolidation.md` and `memory/project_css_refactor.md`
  preserve historical decisions.

The main problem is separation of concerns:

- `handoff.md` is about 2,425 tokens and contains durable architecture,
  deployment, security, QA, and backlog material.
- `PROJECT_CONTEXT.md` is about 1,925 tokens and overlaps with both handoff and
  memory.
- Task-only handoff should be shorter; stable facts should move into memory
  notes and resolved history should rotate/archive.

## Conclusions

The project gives real context reduction where the tool can measure it:

- `ctx map` exposes expensive reads.
- `ctx digest` produced a reproducible 19.6x text reduction on the sampled
  expensive files, with SQL/CSS quality caveats.
- startup memory routing is about 59.5x smaller than a full copied-project
  read baseline, but this is not a normal-agent A/B baseline.
- `ctx report` is useful because it is ledger-computed rather than agent-claimed.

The project does not yet prove RLM answer-quality improvement in this
environment. That is not because RLM is necessarily ineffective; it is because
the available real providers require sending private repository content outside
the sandbox, and those calls were denied.

The project also does not yet prove actual provider billing reduction for
Codex/Claude web sessions. That requires an A/B benchmark with provider usage
metrics, equal tasks, equal models, fresh sessions, tool-output volume, and
success scoring.

## Recommendations

1. Treat deterministic context reduction as proven and RLM semantic quality as
   unproven until a provider may legally receive the repository content.
2. Add a sanitized benchmark repository for external RLM quality tests.
3. Add a `ctx rlm --dry-run-plan` or similar mode that reports chunk counts,
   selected chunks, and expected provider calls without sending content.
4. Improve SQL/CSS digest heuristics. `seed.sql` compressing to 19 tokens is
   impressive but likely too lossy for real data tasks.
5. Add CodeGraph project/index mismatch detection.
6. Normalize `TravelAgent` memory to the CTX schema without overwriting user
   notes.
7. Keep `handoff.md` task-only and move durable facts into memory journals.
