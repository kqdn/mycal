# mycal web

The read-only week page (Milestone 2). React + TypeScript + Vite.

Start the week API first (`uv run mycal-api` in `solver/`), then run `npm run dev` here and open
http://localhost:5173/?week=2026-11-16. Other commands are in the repo's CLAUDE.md.

- `src/api.ts`: types for the week JSON and the fetch
- `src/time.ts`: UTC to wall-clock time in the week's timezone, and date helpers
- `src/layout.ts`: splits blocks and frames into per-day pieces for the grid
- `src/WeekGrid.tsx`: the grid itself
