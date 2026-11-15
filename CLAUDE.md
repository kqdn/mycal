# mycal (Smart Scheduler)

A personal planner. I describe items (durations, windows, deadlines, subtasks), a constraint solver places them on my week, and progress bars make finishing things feel good. Solo use only for now.

Full spec: `docs/PRD.md`. Read it before changing the data model or the solver.

## Current milestone

Milestone 3: storage and adding items. The week lives in SQLite instead of a TOML file: I import my week file once, add and delete items from the page, and the solver re-plans and stores the result. No editing of existing items (that is Milestone 4), no recurrence or check-ins yet. Done when I can add an item to my real week in the browser and see it placed, and the plan survives a server restart.

The New item dialog is built to the Add item dialog section of `web/DESIGN.md` (preview: `web/add-item-preview.png`). Build it after the storage and API parts it depends on.

Milestones 1 (solver package, printed schedule) and 2 (read-only week view) are done. The backtracking and CP-SAT engines both sit behind the same `solve()` interface, and the API calls `solve()` like any other caller. The full milestone order is in `docs/PRD.md` under Milestones.

## Stack

| Part | Choice | Folder |
| --- | --- | --- |
| Solver | Python 3.12, OR-Tools CP-SAT, pytest; FastAPI API | `solver/` |
| Frontend | React + TypeScript + Vite, installable PWA (PWA install later) | `web/` |
| Storage | SQLite through Python's built-in `sqlite3` (Milestone 3), maybe Supabase later | `solver/src/mycal/store.py`, data in `solver/data/` |

Python dependencies are managed with uv. Ask me before adding any new dependency.

## Commands

Run Python commands from `solver/` and web commands from `web/`. Keep this section up to date when commands are added or change.

**Solver and API** (`solver/`)

- One-time setup (installs uv): `winget install --id=astral-sh.uv -e`
- Install dependencies (also downloads Python 3.12 if needed): `uv sync`
- Run tests: `uv run pytest`
- Add a dependency (after I approve): `uv add <package>`; dev-only: `uv add --dev <package>`
- Demo schedule (sample week): `uv run mycal-demo examples/week.toml`
- Demo schedule (my real week, gitignored): `uv run mycal-demo weeks/<week-start>.toml`
- Week API on http://127.0.0.1:8000 (serves `weeks/<week-start>.toml`, reloads on code changes): `uv run mycal-api`. Another weeks folder: `$env:MYCAL_WEEKS_DIR = "<folder>"; uv run mycal-api`
- Solved weeks are cached in `cache/` (gitignored; another folder: `MYCAL_CACHE_DIR`). Editing a week file or any code in `src/mycal` re-solves automatically; to force fresh solves anyway: `Remove-Item -Recurse cache`

**Web** (`web/`)

- Install dependencies (needs Node.js): `npm install`
- Week page (start the API first): `npm run dev`, then open http://localhost:5173/?week=<week-start>. Without `?week=` it shows this week
- Run tests: `npm test`
- Type-check and build: `npm run build`
- Lint: `npm run lint`
- Add a package (after I approve): `npm install <package>`; dev-only: `npm install --save-dev <package>`

## Rules that must not break

These come from the PRD's "get right now" list. If a change would break one, stop and tell me instead.

1. The solver is a pure function. It takes items, blocks, work frames and constraints and returns placements. No database, HTTP, file I/O or UI code inside it. The core modules (`solve`, `problem`, `backtracking`, `cp_sat`, `model`, `windows`, `presets`, `recurrence`, `settings`) never import `api.py`, `demo.py` or `store.py`. Those are callers: they read files, serve HTTP, talk to the database and call `solve()`, never the other way round.
2. Items and Blocks are separate. An Item is the what; a Block is one calendar slot for it, and an item has zero, one or many. There are no separate event and task types.
3. Every entity has a UUID. Never use list positions as identity.
4. Exact moments in time (block start/end, windows, deadlines, completed_at) are timezone-aware UTC. Repeating times of day (WorkFrame start/end) are stored as local time plus an IANA timezone name and turned into UTC windows when presets are compiled.
5. Slot size is one setting (default 15 minutes). Never hardcode 15.
6. Flexibility presets compile to `windows[]`. The solver reads only windows, never the preset.
7. Locked blocks (placed by hand) are treated as pinned by the solver.
8. Blocks keep completion history (`completed_at`, `actual_min`) from day one.
9. The solver is deterministic: same input and same OR-Tools version (pinned in `uv.lock`) give the same plan. CP-SAT runs with one worker and a fixed seed and stops on a gap limit or a deterministic work limit, never on wall-clock time.

## Code style

- Concise and readable over clever. Small functions, type hints everywhere, dataclasses for the model.
- Solver tests use small hand-built weeks and check that the hard constraints hold (inside windows, no overlap, deadlines met, dependencies respected). Only assert exact slot positions when a case has one valid answer.
- Never use em dashes in code, comments, docs or commit messages.
- The web UI follows `web/DESIGN.md`: use only `web/src/tokens.css` variables, no raw hex, no shadows.

## How to work with me

- I'm a CS student with a background in Java, C++ and Python. Explain non-obvious choices in a sentence or two, especially how something is modeled in CP-SAT.
- For anything bigger than a small fix, show a short plan first and wait for my OK.
- When we make a decision, record it in the same commit as the code. A rule every session must follow goes in CLAUDE.md. Anything about how the app works goes in docs/PRD.md, plus a row at the top of its decision log.
- Keep changes small: one logical change per commit, with a short imperative commit message.
- Before staging, run `git status` and ask me about any file you didn't create or change in this session, before it goes into a commit. Then stage with `git add -A` so changes outside the current folder aren't missed.
- I'm on Windows. When I need to run something myself, give PowerShell commands.
- Commit only when I ask. Never push, force-push or rewrite git history without asking.
- The repo will be public. Keep my email out of project files (pyproject.toml, package.json and the like); my name is fine. Keep my real schedule out too: real week files go in `solver/weeks/` (gitignored), and examples and tests use made-up data.
- `docs/PRD.md` is the source of truth. If the code and the PRD disagree, or the PRD contradicts itself, ask me instead of guessing. Its decision log is newest first and wins over older sections.
