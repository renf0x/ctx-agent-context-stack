# Claude Code CTX A/B Benchmark

Date: 2026-06-16

## Summary

A single paired Claude Code benchmark showed a visible session-limit reduction
when CTX rules were enforced.

Both runs used the same synthetic weather-state task:

- fix missing departure-date behavior so the summary warns instead of checking
  today's weather;
- fix missing departure-city behavior so the detail section asks the user to
  choose a city instead of showing a generic fetch error;
- pass the same focused Node test.

The no-CTX run used normal search/read commands. The CTX run used mandatory
`ctx rawcount`, `ctx map`, `ctx digest`, and `ctx run` rules before source
inspection and verification.

## Observed Claude Code Limit Meter

| Metric | Without CTX | With CTX | Difference |
|---|---:|---:|---:|
| Session before | 19% | 22% | n/a |
| Session after | 22% | 24% | n/a |
| Visible session spend | **3 percentage points** | **2 percentage points** | **1 pp lower** |
| Weekly before | 2% | 3% | n/a |
| Weekly after | 3% | 3% | n/a |
| Visible weekly spend | **1 percentage point** | **0 visible pp** | below display threshold |

In this one run, visible five-hour session spend went from 3 percentage points
without CTX to 2 percentage points with CTX. That is roughly one third lower
visible spend for the paired task.

Because the UI meter is rounded and does not expose prompt cache, reasoning
tokens, or exact internal accounting, this is a preliminary signal rather than
statistical proof. Repeated runs are needed before claiming an average savings
rate.

## CTX Ledger

The CTX run produced this `ctx report`:

```text
op        calls   raw tokens     admitted        saved   ratio
digest        1       17,590        4,217       13,373    4.2x
run           1            7            7            0    1.0x
TOTAL         2       17,597        4,224       13,373    4.2x

# saved this session: 13,373 input tokens (~$0.07 at $5.0/MTok, single pass).
```

The main source file was reduced from about 17,590 estimated tokens to 4,217
admitted tokens before it entered the agent-visible context. That is a 4.2x
reduction and about 76% less admitted text for the key file.

## Raw Baselines

After the task:

| Run | Files | Chars | Estimated raw tokens |
|---|---:|---:|---:|
| Without CTX | 9 | 96,875 | 27,679 |
| With CTX | 14 | 187,957 | 53,702 |

The raw baselines are not directly comparable as actual Claude spend. The CTX
fixture intentionally includes local tooling files such as `ctx.py`, `rlm.py`,
memory, handoff, and project context files. They describe the available project
text if read wholesale, not what the agent necessarily admitted into context.

The more relevant CTX measurement is the ledger entry for actual CTX-mediated
operations.

## Verification

Both runs passed:

```text
weatherPanel tests passed
```

The CTX run changed only:

```text
src/weatherPanel.js
```

The key behavior changes were:

- missing `departureDate` now returns a warning in the summary instead of using
  today's date;
- missing `originCityId` now returns `setup_required` with a city-selection
  message instead of a generic forecast load error.

## Interpretation

This paired run supports two claims:

1. CTX measurably reduced admitted source text for the large file used by the
   task: 17,590 to 4,217 estimated tokens.
2. The visible Claude Code session meter increased less in the CTX run:
   2 percentage points versus 3 percentage points.

This does not yet prove a universal savings rate. The result should be treated
as the first practical signal that CTX can reduce real Claude Code limit usage,
to be validated by repeated paired tasks.
