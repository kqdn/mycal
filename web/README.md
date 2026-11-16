# mycal web

The week page: React + TypeScript + Vite. It shows the planned week, and items are added, edited and deleted from it. To run it, see the [top-level README](../README.md); every command is in the repo's `CLAUDE.md`.

It looks the way [`DESIGN.md`](DESIGN.md) says: colors, fonts and sizes come only from `src/tokens.css`. `week-preview.png` and `add-item-preview.png` are the design mockups, not screenshots.

Logic lives in plain `.ts` files with tests next to them; the `.tsx` components only render it.

- `src/api.ts`: types for the API's JSON, the fetch calls and a cache of loaded weeks
- `src/time.ts`: UTC to wall-clock time in the week's timezone, 12-hour formatting, date helpers
- `src/layout.ts`: splits blocks and frames into per-day pieces, the text-by-height rule and the initial scroll
- `src/itemForm.ts`: the item form: lengths, validation, the request and the summary line
- `src/itemDetails.ts`: the item details popover: its text lines, where it goes and which week to show after a delete
- `src/App.tsx`: the page, the week it shows and the week navigation
- `src/WeekGrid.tsx`: the week grid
- `src/NewItemDialog.tsx`: the dialog for adding and editing an item
- `src/ItemPopover.tsx`: the item details popover
