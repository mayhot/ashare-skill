---
name: commit-code
description: Split repository changes into dedicated git branches, write a changelog before committing, and merge the branches back to main. Use when the user asks to commit code, submit code, 提交代码, write changelog before commit, or specifically wants files under runs/ committed to a runs branch, all other skill/source changes committed to a skill branch, then both branches merged into main.
---

# Commit Code

## Overview

Use this skill to separate generated run artifacts from skill/source edits before committing. The required policy is:

- Commit only `runs/` changes to the `runs` branch.
- Write or update the changelog before committing.
- Commit every non-`runs/` change to the `skill` branch.
- Merge both `runs` and `skill` back into `main` after the branch commits succeed.

## Preflight

1. Run `git status --short --branch` and read it carefully.
2. Identify changes in two groups:
   - `runs/`: reports, outputs, dated run artifacts.
   - non-`runs/`: skill folders, scripts, agents, configs, docs, and other source files.
3. If `main` is behind `origin/main`, or local and remote have diverged, tell the user before pulling, rebasing, or pushing. Do not perform network sync unless the user asked for it or approved it.
4. Do not stage or revert unrelated user changes. If a file is ambiguous, inspect it before deciding which branch should own it.
5. Review the final intended change set and write a changelog entry before the first commit.
6. If a branch does not exist, create it from the current `main`.

## Changelog

Before committing anything, create or update `CHANGELOG.md` at the repository root unless the repository already has a clearly established changelog file elsewhere.

Use a concise Markdown entry with:

- Date in `YYYY-MM-DD` format.
- `runs`: summarize generated run artifacts that will be committed to `runs`.
- `skills`: summarize non-`runs/` skill/source changes that will be committed to `skill`.
- `notes`: mention skipped groups, conflicts, validation, or remote divergence when relevant.

If there are only `runs/` changes, the changelog still belongs to the non-`runs/` group and must be committed on the `skill` branch. Do not commit changelog edits on the `runs` branch.

## Commit `runs/`

Start from `main`, then switch to or create the `runs` branch:

```powershell
git switch main
git switch runs
# If the branch does not exist:
git switch -c runs main
```

Stage and commit only the run artifacts:

```powershell
git add -- runs/
git status --short
git commit -m "chore: update run outputs"
```

Skip the commit if `runs/` has no changes. Never include non-`runs/` files in this branch commit.

## Commit Skill Changes

Switch back to `main`, then switch to or create the `skill` branch:

```powershell
git switch main
git switch skill
# If the branch does not exist:
git switch -c skill main
```

Stage all non-`runs/` changes while excluding `runs/`:

```powershell
git add --all -- .
git reset -- runs/
git status --short
git commit -m "feat: update skills"
```

Skip the commit if there are no non-`runs/` changes other than an unnecessary changelog edit. After staging, verify that no `runs/` path is staged on the `skill` branch. `CHANGELOG.md` must be staged here, not on `runs`.

## Merge Back To `main`

Merge the topic branches only after their commits are correct:

```powershell
git switch main
git merge --no-ff runs
git merge --no-ff skill
git status --short --branch
```

If a merge conflict occurs, inspect the conflict, preserve both intended change sets when possible, and explain the resolution. Do not use destructive recovery commands such as `git reset --hard` unless the user explicitly requests them.

## Verification

Before finishing, report:

- The commit SHA on `runs`, if created.
- The commit SHA on `skill`, if created.
- The changelog path and the entry date.
- The merge result on `main`.
- Any skipped group, conflict, uncommitted change, or remote divergence.
