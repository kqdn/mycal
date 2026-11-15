# Design spec for web/

This is how the app looks. It comes from the Smart Scheduler Prototype canvas on claude.ai (the Week v4, Today and Add item screens). Colors, fonts and sizes live as variables in `src/tokens.css`. Components use those variables and never raw hex values.

`week-preview.png` next to this file shows the week grid built to this spec with a sample week.

## Principles

- **Light theme only** for now: a warm off-white page, white cards and one green accent. No dark theme until it's asked for.
- **Three kinds of blocks, told apart at a glance:** fixed events are dark slate, work the solver placed is light green, and finished work is grey and struck through.
- **Orange means "needs you":** deadlines, check-ins, changes and infeasible weeks. Nothing else uses it.
- **Everything clickable is at least 44px tall** (`--tap`).
- **Times are 12-hour.** A single time is "2:00pm". A range is "2:00 to 3:30pm", dropping the first am/pm when both match ("11:00am to 12:30pm" keeps both). Hour labels are "8am", "12pm". Never put a dash between times.
- **Plain CSS** with no framework or component library, as decided in Milestone 2.

## Type

Use Inter for everything and Space Grotesk only for page titles. Load both in `index.html`:

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Space+Grotesk:wght@500;600&display=swap" rel="stylesheet">
```

| Use | Font | Size / weight | Color |
| --- | --- | --- | --- |
| Page title ("Nov 16 to 22") | Space Grotesk | 28px / 600, letter-spacing -0.01em | `--text` |
| Dialog title ("New item") | Space Grotesk | 18px / 600 | `--text` |
| Eyebrow above a title ("Your week") | Inter | 13px / 500 | `--text-muted` |
| Section label ("Unscheduled") | Inter | 13px / 600 | `--text-muted` |
| Nav tab, primary button | Inter | 15px / 600 (inactive tab 500) | see Controls |
| Row title in a card | Inter | 15px / 600 | `--text` |
| Block title | Inter | 13px / 600, line-height 16px | depends on block kind |
| Block time, secondary text, hour labels, legend | Inter | 12px / 400, line-height 15px | `--text-muted` |
| Day header weekday / date | Inter | 12px / 600 and 16px / 600 | `--text-muted` / `--text` |

## Page layout

- **Top bar:** 64px tall, `--surface` background, 1px `--border` bottom border, 32px side padding. Tabs on the left are 64px tall with a 3px bottom border. The active tab has an `--accent` border and text. Inactive tabs have a transparent border and `--text-muted` text. For now only "Week" exists. Add "Today", "Projects" and the "New item" primary button on the right when those features are built.
- **Content:** max-width 1280px, centered, 24px top and bottom padding, 32px side padding, 16px gap between sections.
- **Title row:** the eyebrow and page title stacked on the left (2px gap). On the right, the previous and next week buttons (icon buttons, see Controls) with 4px between them. The two sides are aligned to their bottom edge.

## Week grid

- **Card:** `--surface`, 1px `--border`, radius `--radius-card`, overflow hidden. Inside, a horizontal scroller with a 840px minimum width, so narrow screens scroll instead of squashing the columns.
- **Columns:** a `--gutter` (56px) time column, then 7 equal day columns. Each day column has a 1px `--border` left edge.
- **Day header row:** 88px minimum height, 1px `--border` bottom edge. Each cell is centered, with 12px top padding and a 4px gap, and shows:
  - the weekday (12px / 600, `--text-muted`)
  - the date number in a 30px circle (16px / 600)
  - **Today:** the circle is filled `--accent` with white text, and the weekday turns `--accent`.
  - **Later:** a deadline pill goes under the date (`--attention-bg` background, `--attention-text` text, 12px / 600, radius `--radius-pill`, padding 2px 8px), for example "HW 10 due".
- **Hours:** each hour is `--hour-height` (52px) tall, with a 1px `--grid-line` line at each hour. Hour labels are right-aligned 8px from the gutter's edge and centered on their line.
- **Work frames:** time inside a work frame is `--surface` (white). Time outside every frame is `--surface-sunken`. The prototype had no frames, so this is an adaptation: working hours read as the "paper."
- **Now line:** only on today's column. A 2px `--accent` line across the column, with a 10px `--accent` dot centered on its left end.
- **Initial scroll** (fixes weekend mornings being hidden): on load, scroll so the earliest block start across all 7 days, minus 30 minutes, is at the top. Weekend days count the same as weekdays. If the week has no blocks, use the earliest work frame start instead.

### Blocks

Blocks are positioned absolutely in their day column, inset 12px from the column's left edge and 4px from its right. Each block has radius `--radius-block`, 4px 8px padding, `overflow: hidden` and `box-sizing: border-box`.

| Kind | When | Background | Border | Title | Time |
| --- | --- | --- | --- | --- | --- |
| Fixed | API `fixed: true` | `--block-fixed-bg` | 1px `--block-fixed-bg` | `--block-fixed-text` | `--block-fixed-sub` |
| Placed | API `fixed: false` | `--block-flex-bg` | 1px `--block-flex-border` | `--text` | `--text-muted` |
| Done (later) | block status done | `--block-done-bg` | 1px `--block-done-border` | `--text-muted`, line-through | `--text-muted` |
| Locked (later) | placed by hand | same as Placed, plus a 14px lock icon at the top right | | | |

**Text by height** (fixes clipped titles on short blocks). The title never wraps: it stays on one line and ends with an ellipsis when it doesn't fit.

| Block height | Shows |
| --- | --- |
| 40px or more (1 hour and longer) | Title on line 1, time range on line 2 |
| 20 to 39px (30 and 45 min) | One line: "Title · 2:00pm" (start time only), padding 2px 8px |
| Under 20px (15 min) | Title only at 11px with line-height 11px, no vertical padding (a 15 min block is 13px tall, 11px inside its borders) |

Each block also gets an accessible name with the full details, for example `aria-label="Call home, Thu 6:00 to 6:30pm"`.

### Legend

Under the grid: a 1px `--border` top edge, 14px 16px padding, 12px `--text-muted` text, with 8px 22px gaps between items. Each item is a 14px swatch with radius 4px, styled like its block kind, followed by its label: "Fixed", "Placed by the solver". Add "Done" and "Locked by you" when those exist.

## Other pieces

- **Unscheduled list:** a card (`--surface`, 1px `--border`, radius `--radius-card`) under the grid, headed "Unscheduled" as a section label. Each row is at least 56px tall with 14px side padding and a 1px `--divider` between rows. It shows the title (15px / 600) and the estimate under it (12px, `--text-muted`), for example "15m".
- **Attention banner** (infeasible week, missing week file): `--attention-bg` background, 1px `--attention-border`, radius 12px, 12px 16px padding. The title is 14px / 600 in `--text`. The body is 13px in `--attention-text`. Example: "This week can't be planned" / "6h of work doesn't fit before Wed 11:59pm."

## Controls

- **Primary button:** `--accent` background, `--accent-contrast` text, no border, radius `--radius-control`, min-height `--tap`, 0 18px padding, 15px / 600.
- **Secondary button:** `--surface` background, 1px `--border`, `--text`, otherwise the same as primary.
- **Icon button** (week arrows): 44 x 44px, `--surface`, 1px `--border`, radius `--radius-control`, with an 18px chevron icon (stroke `--text`, stroke-width 2, round caps and joins).
- **Segmented choice** (toggles like "Current plan / Option 2", weekday pickers): selected is `--accent` background with white text. Unselected is `--surface` with a 1px `--border`. Radius `--radius-control`, height 44px, 13 to 14px / 600.
- **Text input** (Milestone 3): 48px tall, `--surface`, 1px `--border`, radius `--radius-input`, 0 14px padding, 16px text. Its label sits above it with a 6px gap, at 13px / 600.
- **Dropdown list option:** at least 44px tall, 15px text, 1px `--divider` between options. The selected option has an `--accent-tint` background, 600 weight and an `--accent` check on the right.
- **Switch:** a 48 x 28px track (`--accent` when on) with a 22px white knob, inside a 44px tall hit area.
- **Checkbox circle** (marking a block done, later): a 24px circle with a 2px `--checkbox-border`. When done, it's a filled `--accent` circle with a white check.
- **Progress bar** (Today view, later): 8px tall `--border` track, `--accent` fill, radius 4px.
- **Focus:** the 2px `--accent` outline from `tokens.css`. Never remove it.

## Don'ts

- No raw hex values in components. Add a token to `tokens.css` if one is missing, and note it here.
- No shadows. Depth comes from borders and the off-white page.
- No new fonts, icon packs or UI libraries without asking.
- Don't change the layout of screens that the PRD says will be rebuilt (Today, check-ins, dragging). This spec only sets their look.
