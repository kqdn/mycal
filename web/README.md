# mycal web

The read-only week page (Milestone 2). React + TypeScript + Vite.

It looks the way `DESIGN.md` says: colors, fonts and sizes come from `src/tokens.css`, and `week-preview.png` shows the target.

Start the week API first (`uv run mycal-api` in `solver/`), then run `npm run dev` here and open
http://localhost:5173/?week=2026-11-16. Other commands are in the repo's CLAUDE.md.

- `src/api.ts`: types for the week JSON and the fetch
- `src/time.ts`: UTC to wall-clock time in the week's timezone, 12-hour formatting, date helpers
- `src/layout.ts`: splits blocks and frames into per-day pieces, the text-by-height rule and the initial scroll
- `src/WeekGrid.tsx`: the grid itself
