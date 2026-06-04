# Repository Guidelines

## Project Purpose

This repository contains Codex skills for A-share research workflows. Outputs are research watchlists, post-run reports, backtests, and risk-control helpers. They are not personalized investment advice.

When working in this repo:

- Treat market data, K-line data, rankings, prices, volume, financials, announcements, and fund-flow facts as external facts that must be sourced, computed, or explicitly marked unavailable.
- Do not invent data to fill gaps. If an API, local CSV, or SQLite cache is unavailable or incomplete, report the gap plainly.
- Keep recommendation language conditional: use wording such as "observe", "wait for confirmation", "remove if invalidated", or "re-evaluate after conditions are met".

## Repository Layout

- `ashare-*/SKILL.md`: Skill instructions, trigger scenarios, rules, and output contracts.
- `ashare-*/scripts/`: Python helpers used by the skills.
- `ashare-*/agents/openai.yaml`: Agent configuration for the skill.
- `commit-code/`: Commit workflow skill and branch/changelog rules.
- `runs/`: Generated run reports and backtest outputs.
- `CHANGELOG.md`: Project change history.

Most skill folders follow the pattern:

```text
skill-name/
  SKILL.md
  agents/openai.yaml
  scripts/*.py
```

## Editing Rules

- Prefer updating the relevant skill folder instead of adding cross-cutting abstractions.
- Keep changes scoped to the requested skill, script, or documentation.
- Preserve existing output paths and report names unless the user asks for a new contract.
- If changing a script, update the matching `SKILL.md` when usage, arguments, output fields, or validation expectations change.
- Record meaningful skill, script, data-contract, or workflow changes in `CHANGELOG.md`.
- Do not store temporary API responses, raw intermediate tables, or oversized scratch data in `runs/` unless the user explicitly asks for them.
- SQLite cache artifacts should stay under the documented `runs/ashare-kline-sqlite-cache/` location unless a task specifies another path.

## Data And Report Discipline

- Confirm the intended trade date before running or generating market reports. If the user says "today", use the current Asia/Shanghai date.
- Prefer post-close runs for daily A-share workflows. The K-line cache daily guard expects same-day runs after 17:00 Asia/Shanghai unless a test or repair explicitly uses an override.
- Generated reports should include data source, latest K-line date where relevant, completeness notes, and any missing-data caveats.
- Recommendation return tracking starts after the recommendation date; do not count same-day moves as post-recommendation validation.
- Final report content shown to the user should match the saved report file.

## Validation

Use the narrowest reliable validation for the changed area.

Common commands:

```powershell
python -m compileall ashare-ai-slowbull ashare-holdings-check ashare-index-inclusion-watch ashare-kline-sqlite-cache ashare-merged-report ashare-recommendation-returns ashare-super-shortline-system ashare-trend-buy commit-code
```

For the K-line SQLite cache after script edits:

```powershell
python ashare-kline-sqlite-cache/scripts/sync_ashare_kline.py --self-test
```

For development samples, prefer bounded or offline-style runs when the script supports them, such as `--limit`, `--no-network`, `--no-fetch`, `--dry-run`, or `--allow-before-close` for explicit tests.

## Git Hygiene

- Check `git status --short --branch` before staging or committing.
- Do not revert unrelated user changes.
- Follow `commit-code/SKILL.md` when the user asks to commit:
  - Commit only `runs/` artifacts on the `runs` branch.
  - Commit non-`runs/` skill/source/docs changes on the `skill` branch.
  - Update `CHANGELOG.md` before committing.
  - Merge both branches back to `main` only after their commits are correct.
- If local and remote branches are behind, ahead, or diverged, tell the user before pulling, rebasing, or pushing.

## Style

- Markdown docs should be concise, operational, and easy for future agents to follow.
- Prefer PowerShell examples because this workspace is on Windows.
- Keep Python changes standard-library-first unless an existing script already depends on a package.
- Use structured parsers or SQLite APIs for structured data; avoid ad hoc string slicing for tables or database output.
