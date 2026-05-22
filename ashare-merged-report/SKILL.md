---
name: ashare-merged-report
description: Merge and analyze same-day A-share run reports from `runs/ashare-ai-slowbull/YYYY-MM-DD/report.md` and `runs/ashare-trend-buy/YYYY-MM-DD/result.md`, producing one consolidated Markdown report with consensus picks, conflicts, downgraded names, action conditions, and risk notes. Use when Codex needs to combine the AI hardware slow-bull watchlist with the right-side trend-buy watchlist for the same trading date. Legacy flat files named `runs/SKILL_NAME/YYYY-MM-DD.md` are supported as a fallback.
---

# A-share Merged Report

## Overview

Use this skill to combine the same-day outputs of `ashare-ai-slowbull` and `ashare-trend-buy` into one merged A-share research report. Treat the result as a research watchlist, not as personalized investment advice.

## Quick Start

From the repository root, run:

```bash
python ashare-merged-report/scripts/merge_reports.py --runs-dir runs
```

To merge a specific date:

```bash
python ashare-merged-report/scripts/merge_reports.py --runs-dir runs --date 2026-05-20
```

The script writes:

```text
runs/ashare-merged-report/YYYY-MM-DD/report.md
```

## Workflow

1. Locate the two source reports:
   - `runs/ashare-ai-slowbull/YYYY-MM-DD/report.md`
   - `runs/ashare-trend-buy/YYYY-MM-DD/result.md`
2. If the user does not specify a date, use the latest date that exists in both directories.
3. Run `scripts/merge_reports.py` to create the merged report.
4. Read the generated report and, if needed, add a short human summary for the user.

Legacy compatibility: if a source date folder is not present, the script can still read old flat files at `runs/SKILL_NAME/YYYY-MM-DD.md`. Use `--flat-output` only when the caller explicitly needs the old merged output shape `runs/ashare-merged-report/YYYY-MM-DD.md`.

## Merge Logic

Prioritize names where both skills agree:

- Slow-bull A/B plus trend-buy A/B: highest-confidence consensus watchlist.
- Slow-bull A/B plus trend-buy C or missing: strong theme or fundamental logic, but wait for technical confirmation.
- Trend-buy A/B plus slow-bull missing or C: technical strength exists, but the AI-hardware slow-bull thesis is weaker or out of scope.
- Any name downgraded or excluded by either skill must keep a visible caution note.

Use the source reports' own grades, scores, buy-point text, support or failure levels, and risk language. Do not invent fresh market data unless the user explicitly asks for a live re-check.

## Output Expectations

The merged report should include:

- Source report paths and merged date.
- A short merged conclusion.
- A consensus priority table with slow-bull grade, trend-buy grade, scores, and suggested observation action.
- Single-strategy strong signals split by source skill.
- Conflict and downgrade notes.
- A full merged table for traceability.
- A research-only risk disclaimer.

## Script Notes

`scripts/merge_reports.py` parses Markdown tables headed by `核心表格`, extracts stock code, name, grade, score, direction, trend/MACD text, and buy-point fields, then ranks merged records using both grades and source scores.
