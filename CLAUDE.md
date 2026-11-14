# mycal (Smart Scheduler)

A personal planner. I describe items (durations, windows, deadlines, subtasks), a constraint solver places them on my week, and progress bars make finishing things feel good. Solo use only for now.

Full spec: `docs/PRD.md`. Read it before changing the data model or the solver.

## Current milestone

Milestone 1: the data model and solver as a Python package with tests. No UI yet. Done when I can feed in this week's items and get a printed schedule.

I may write a simple backtracking solver by hand first to learn the problem, then switch to OR-Tools CP-SAT. Both must sit behind the same `solve()` interface so they can be swapped.

## Stack

| Part | Choice | Folder |
| --- | --- | --- |
| Solver | Python 3.12, OR-Tools CP-SAT, pytest; FastAPI wrapper later | `solver/` |
| Frontend (later) | React + TypeScript + Vite, installable PWA | `web/` |
| Storage (later) | SQLite first, maybe Supabase later | |

Python dependencies are managed with uv. Ask me before adding any new dependency.

## Commands

Run from `solver/`. Keep this section up to date when commands are added or change.

- Run tests: `uv run pytest`
- Add a dependency (after I approve): `uv add <package>`
- Demo schedule: add the command here once it exists

## Rules that must not break

These come from the PRD's "get right now" list. If a change would break one, stop and tell me instead.

1. The solver is a pure function. It takes items, blocks, work frames and constraints and returns placements. No database, HTTP, file I/O or UI code inside it.
2. Items and Blocks are separate. An Item is the what; a Block is one calendar slot for it, and an item has zero, one or many. There are no separate event and task types.
3. Every entity has a UUID. Never use list positions as identity.
4. All times are timezone-aware UTC. Convert to local time only for display.
5. Slot size is one setting (default 15 minutes). Never hardcode 15.
6. Flexibility presets compile to `windows[]`. The solver reads only windows, never the preset.
7. Locked blocks (placed by hand) are treated as pinned by the solver.
8. Blocks keep completion history (`completed_at`, `actual_min`) from day one.

## Code style

- Concise and readable over clever. Small functions, type hints everywhere, dataclasses for the model.
- Solver tests use small hand-built weeks and check that the hard constraints hold (inside windows, no overlap, deadlines met, dependencies respected). Only assert exact slot positions when a case has one valid answer.
- Never use em dashes in code, comments, docs or commit messages.

## How to work with me

- I'm a CS student with a background in Java and C++. Explain non-obvious choices in a sentence or two, especially how something is modeled in CP-SAT.
- For anything bigger than a small fix, show a short plan first and wait for my OK.
- Keep changes small: one logical change per commit, with a short imperative commit message.
- I'm on Windows. When I need to run something myself, give PowerShell commands.
- Commit only when I ask. Never push, force-push or rewrite git history without asking.
- If the code and `docs/PRD.md` disagree, or the PRD contradicts itself, ask me instead of guessing. The decision log at the bottom of the PRD is newest first and wins over older sections.
