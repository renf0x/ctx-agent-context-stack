from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".ctx" / "benchmark-lab-src"
PYTHON_EXE = r"C:\Users\renf\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
NODE_EXE = r"C:\Users\renf\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"


COMMON_PACKAGE = """{
  "name": "weather-context-benchmark",
  "version": "1.0.0",
  "type": "module",
  "private": true,
  "scripts": {
    "test": "node tests/weatherPanel.test.mjs"
  }
}
"""


TEST = """import assert from "node:assert/strict";
import { renderTravelWeather } from "../src/weatherPanel.js";

const service = {
  getForecast(cityId, date) {
    return { cityId, date, tempC: 29, condition: "sunny" };
  }
};

const noDate = renderTravelWeather({
  originCityId: "mow",
  originCityName: "Moscow",
  departureDate: ""
}, service);

assert.equal(noDate.summary.kind, "warning");
assert.match(noDate.summary.message, /date is not selected/i);
assert.equal(noDate.detail.status, "blocked");
assert.match(noDate.detail.message, /choose a departure date/i);

const noCity = renderTravelWeather({
  originCityId: "",
  originCityName: "",
  departureDate: "2026-07-02"
}, service);

assert.equal(noCity.detail.status, "setup_required");
assert.equal(noCity.detail.title, "Departure weather");
assert.doesNotMatch(noCity.detail.message, /try later/i);
assert.match(noCity.detail.message, /choose a departure city/i);

const ready = renderTravelWeather({
  originCityId: "mow",
  originCityName: "Moscow",
  departureDate: "2026-07-02"
}, service);

assert.equal(ready.summary.kind, "weather");
assert.equal(ready.detail.status, "ready");
assert.equal(ready.detail.forecast.date, "2026-07-02");

console.log("weatherPanel tests passed");
"""


def large_weather_panel() -> str:
    parts = [
        "import { cityCatalog, lookupCityLabel } from './cityCatalog.js';",
        "",
        "const TODAY = '2026-06-16';",
        "",
        "export function renderTravelWeather(profile, forecastService) {",
        "  const summary = buildWhatMattersWeather(profile, forecastService);",
        "  const detail = buildDepartureWeatherSection(profile, forecastService);",
        "  return { summary, detail };",
        "}",
        "",
        "export function buildWhatMattersWeather(profile, forecastService) {",
        "  const cityId = profile.originCityId;",
        "  if (!cityId) {",
        "    return { kind: 'setup_required', message: 'Departure city is not selected.' };",
        "  }",
        "  const date = profile.departureDate || TODAY;",
        "  const forecast = forecastService.getForecast(cityId, date);",
        "  return {",
        "    kind: 'weather',",
        "    title: 'What matters before departure',",
        "    message: `${lookupCityLabel(cityCatalog, cityId)} weather on ${date}: ${forecast.condition}, ${forecast.tempC}C`,",
        "    forecast",
        "  };",
        "}",
        "",
        "export function buildDepartureWeatherSection(profile, forecastService) {",
        "  if (!profile.originCityId) {",
        "    return {",
        "      status: 'error',",
        "      title: 'Departure city',",
        "      heading: 'Departure city',",
        "      message: 'Could not load forecast. Try later.'",
        "    };",
        "  }",
        "  if (!profile.departureDate) {",
        "    return {",
        "      status: 'blocked',",
        "      title: 'Departure weather',",
        "      message: 'Choose a departure date to check weather for the day you leave.'",
        "    };",
        "  }",
        "  const forecast = forecastService.getForecast(profile.originCityId, profile.departureDate);",
        "  return {",
        "    status: 'ready',",
        "    title: 'Departure weather',",
        "    message: `${profile.originCityName} weather is available for ${profile.departureDate}.`,",
        "    forecast",
        "  };",
        "}",
        "",
    ]
    for i in range(1, 180):
        parts.extend([
            f"export function formatWeatherRow{i}(forecast) {{",
            f"  const label = forecast?.condition || 'unknown';",
            f"  return `row-{i}: ${{label}} / ${{forecast?.tempC ?? 'n/a'}}C`;",
            "}",
            "",
            f"export const WEATHER_COPY_{i} = {{",
            f"  title: 'Weather planning copy {i}',",
            f"  body: 'Long explanatory copy block {i} used to simulate a production file with many UI branches.'",
            "};",
            "",
        ])
    return "\n".join(parts)


def city_catalog() -> str:
    parts = [
        "export const cityCatalog = [",
        "  { id: 'mow', label: 'Moscow', country: 'Russia' },",
        "  { id: 'led', label: 'Saint Petersburg', country: 'Russia' },",
        "  { id: 'bkk', label: 'Bangkok', country: 'Thailand' },",
        "];",
        "",
        "export function lookupCityLabel(catalog, id) {",
        "  return catalog.find((city) => city.id === id)?.label || 'Selected city';",
        "}",
        "",
    ]
    for i in range(1, 140):
        parts.extend([
            f"export function normalizeCityAlias{i}(value) {{",
            "  return String(value || '').trim().toLowerCase();",
            "}",
            "",
        ])
    return "\n".join(parts)


def css_fixture() -> str:
    parts = [
        ".weather-panel { display: grid; gap: 12px; }",
        ".weather-panel__warning { color: #7a4b00; background: #fff4d6; }",
        ".weather-panel__error { color: #8a1f17; background: #ffe7e4; }",
        "",
    ]
    for i in range(1, 220):
        parts.append(f".weather-row-{i} {{ display: grid; grid-template-columns: 1fr auto; gap: {i % 9 + 4}px; }}")
    return "\n".join(parts) + "\n"


def write_fixture(path: Path, with_ctx: bool) -> None:
    if path.exists():
        shutil.rmtree(path)
    (path / "src").mkdir(parents=True)
    (path / "tests").mkdir()
    (path / "docs").mkdir()
    (path / "src" / "weatherPanel.js").write_text(large_weather_panel(), encoding="utf-8")
    (path / "src" / "cityCatalog.js").write_text(city_catalog(), encoding="utf-8")
    (path / "src" / "weatherPanel.css").write_text(css_fixture(), encoding="utf-8")
    (path / "tests" / "weatherPanel.test.mjs").write_text(TEST, encoding="utf-8")
    (path / "package.json").write_text(COMMON_PACKAGE, encoding="utf-8")
    (path / "README.md").write_text(
        "# Weather Context Benchmark\n\n"
        "Synthetic project for comparing ctx-assisted and normal agent workflows.\n",
        encoding="utf-8",
    )
    task = (
        "# Benchmark Task\n\n"
        "Fix the departure weather behavior.\n\n"
        "Required behavior:\n"
        "- If departure date is missing, the summary block must warn that the date is not selected instead of using today's weather.\n"
        "- The detailed departure weather section must explain that weather cannot be checked until a departure date is chosen.\n"
        "- If departure city is missing, the detailed section must not show a generic fetch error or duplicate 'Departure city' title; it must ask the user to choose a departure city.\n"
        f"- Focused verification must pass: `& '{NODE_EXE}' tests/weatherPanel.test.mjs`.\n"
    )
    (path / "docs" / "TASK.md").write_text(task, encoding="utf-8")
    if with_ctx:
        shutil.copy2(ROOT / "ctx.py", path / "ctx.py")
        shutil.copy2(ROOT / "rlm.py", path / "rlm.py")
        (path / "memory").mkdir()
        (path / "memory" / "MEMORY.md").write_text(
            "# Project Memory\n\n"
            "- This benchmark is designed to force source-file inspection through ctx digest.\n"
            "- The target behavior is described in docs/TASK.md.\n",
            encoding="utf-8",
        )
        (path / "handoff.md").write_text(
            "# Handoff\n\n"
            "- Active task: fix departure weather missing-date and missing-city states.\n"
            f"- Run `& '{PYTHON_EXE}' ctx.py report --reset` before work and `& '{PYTHON_EXE}' ctx.py report` after work.\n",
            encoding="utf-8",
        )
        (path / "PROJECT_CONTEXT.md").write_text(
            "# Project Context\n\n"
            "This is a small synthetic weather UI logic project. The large source files are intentional.\n",
            encoding="utf-8",
        )
        (path / "CLAUDE.md").write_text(CTX_RULES, encoding="utf-8")
        (path / "AGENTS.md").write_text(CTX_RULES, encoding="utf-8")
    else:
        (path / "CLAUDE.md").write_text(NOCTX_RULES, encoding="utf-8")
        (path / "AGENTS.md").write_text(NOCTX_RULES, encoding="utf-8")


CTX_RULES = f"""# CTX Benchmark Rules

This project is a ctx benchmark. These rules are mandatory.

Use this Python executable if `python` is not available:
`{PYTHON_EXE}`

Use this Node executable for focused verification:
`{NODE_EXE}`

Before task work:
1. Read `CLAUDE.md`, `handoff.md`, `PROJECT_CONTEXT.md`, `memory/MEMORY.md`, and `docs/TASK.md`.
2. Run `& '{PYTHON_EXE}' ctx.py report --reset`.
3. Run `& '{PYTHON_EXE}' ctx.py rawcount .`.
4. Run `& '{PYTHON_EXE}' ctx.py map --top 30`.

Source inspection rules:
- `rg` is allowed only to find candidate files.
- Do not use direct file reads for `.js`, `.jsx`, `.ts`, `.tsx`, `.css`, or `.sql` files until `& '{PYTHON_EXE}' ctx.py digest <file>` has been run for that file.
- If full source is needed after a digest, state why, then read only the smallest necessary range/file.
- Run tests only through `& '{PYTHON_EXE}' ctx.py run -- "{NODE_EXE}" tests/weatherPanel.test.mjs`.
- If a source file is read directly before digest, stop and report that the benchmark was violated.

Final response:
- Run `& '{PYTHON_EXE}' ctx.py report`.
- Quote the report table.
- List files inspected via digest and any direct reads with reasons.
"""


NOCTX_RULES = f"""# No-CTX Benchmark Rules

This project is the no-ctx control.

- Do not use ctx, rlm, CodeGraph, memory tooling, or files named `ctx.py` / `rlm.py`.
- Use normal shell search/read commands.
- Inspect existing implementation before editing.
- Make the smallest safe change.
- Run focused verification with `& '{NODE_EXE}' tests/weatherPanel.test.mjs`.
- In the final response, list files changed and verification output.
"""


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copytree(ROOT, OUT / "ctx-agent-context-stack",
                    ignore=shutil.ignore_patterns(
                        ".git", ".ctx", ".codegraph", "__pycache__", "dist"))
    write_fixture(OUT / "with-ctx", with_ctx=True)
    write_fixture(OUT / "without-ctx", with_ctx=False)
    (OUT / "PROMPT_WITH_CTX.md").write_text(
        "Работай в `C:\\Users\\renf\\Desktop\\ctx-benchmark-lab\\with-ctx`.\n"
        "Строго соблюдай `CLAUDE.md`. Выполни задачу из `docs/TASK.md`.\n",
        encoding="utf-8",
    )
    (OUT / "PROMPT_WITHOUT_CTX.md").write_text(
        "Работай в `C:\\Users\\renf\\Desktop\\ctx-benchmark-lab\\without-ctx`.\n"
        "Строго соблюдай `CLAUDE.md`. Выполни задачу из `docs/TASK.md`.\n",
        encoding="utf-8",
    )
    (OUT / "README.md").write_text(
        "# ctx-benchmark-lab\n\n"
        "Folders:\n"
        "- `ctx-agent-context-stack`: copy of the ctx repository used for the test.\n"
        "- `with-ctx`: benchmark fixture with mandatory ctx rules.\n"
        "- `without-ctx`: identical control fixture without ctx tooling.\n\n"
        "Use the prompts in `PROMPT_WITH_CTX.md` and `PROMPT_WITHOUT_CTX.md` in fresh sessions.\n",
        encoding="utf-8",
    )
    print(OUT)


if __name__ == "__main__":
    main()
