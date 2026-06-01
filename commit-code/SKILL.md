---
name: commit-code
description: Split repository changes into dedicated git branches and merge them back to main. Use when the user asks to commit code, submit code, 提交代码, or specifically wants files under runs/ committed to a runs branch, all other skill/source changes committed to a skill branch, then both branches merged into main.
---

# Commit Code

## Overview

Use this skill to separate generated run artifacts from skill/source edits before committing. The required policy is:

- Commit only `runs/` changes to the `runs` branch.
- Commit every non-`runs/` change to the `skill` branch.
- Merge both `runs` and `skill` back into `main` after the branch commits succeed.

## Preflight

1. Run `git status --short --branch` and read it carefully.
2. Identify changes in two groups:
   - `runs/`: reports, outputs, dated run artifacts.
   - non-`runs/`: skill folders, scripts, agents, configs, docs, and other source files.
3. If `main` is behind `origin/main`, or local and remote have diverged, tell the user before pulling, rebasing, or pushing. Do not perform network sync unless the user asked for it or approved it.
4. Do not stage or revert unrelated user changes. If a file is ambiguous, inspect it before deciding which branch should own it.
5. If a branch does not exist, create it from the current `main`.

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

Skip the commit if there are no non-`runs/` changes. After staging, verify that no `runs/` path is staged on the `skill` branch.

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
- The merge result on `main`.
- Any skipped group, conflict, uncommitted change, or remote divergence.
