# Design spec for web/

This is how the app looks. It comes from the Smart Scheduler Prototype canvas on claude.ai (the Week v4, Today and Add item screens). Colors, fonts and sizes live as variables in `src/tokens.css`. Components use those variables and never raw hex values.

`week-preview.png` next to this file shows the week grid built to this spec with a sample week.

## Principles

- **Light theme only** for now: a warm off-white page, white cards and one green accent. No dark theme until it's asked for.
- **Three kinds of blocks, told apart at a glance:** fixed events are dark slate, work the solver placed is light green, and finished work is grey and struck through.
- **Orange means "needs you":** deadlines, check-ins, changes and infeasible weeks. Nothing else uses it.
- **Everything clickable is at least 44px tall** (`--tap`). Blocks in the grid are the one exception (see Item details popover).
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

- **Card:** `--surface`, 1px `--border`, radius `--radius-card`, overflow hidden. Inside, one scroller for both directions with an 840px minimum width, so narrow screens scroll instead of squashing the columns. The day header row is sticky at its top, inside that scroller, so the header and the columns always share one width, even when a scrollbar takes up room.
- **Columns:** a `--gutter` (56px) time column, then 7 equal day columns. Each day column has a 1px `--border` left edge.
- **Day header row:** 88px minimum height, 1px `--border` bottom edge. Each cell is centered, with 12px top padding and a 4px gap, and shows:
  - the weekday (12px / 600, `--text-muted`)
  - the date number in a 30px circle (16px / 600)
  - **Today:** the circle is filled `--accent` with white text, and the weekday turns `--accent`.
  - **Later:** a deadline pill goes under the date (`--attention-bg` background, `--attention-text` text, 12px / 600, radius `--radius-pill`, padding 2px 8px), for example "HW 10 due".
- **Hours:** each hour is `--hour-height` (52px) tall, with a 1px `--grid-line` line at each hour. Hour labels are right-aligned 8px from the gutter's edge and centered on their line.
- **Work frames:** time inside a work frame is `--surface` (white). Time outside every frame is `--bg`, the same warm off-white as the page, so the two read clearly apart. The prototype had no frames, so this is an adaptation: working hours read as the "paper," and the legend explains it.
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

Under the grid: a 1px `--border` top edge, 14px 16px padding, 12px `--text-muted` text, with 8px 22px gaps between items. Each item is a 14px swatch with radius 4px, styled like its block kind, followed by its label: "Fixed", "Placed by the solver", then "Work hours" (an `--surface` swatch with a 1px `--border`, for the white time inside work frames). Add "Done" and "Locked by you" when those exist.

## Other pieces

- **Unscheduled list:** a card (`--surface`, 1px `--border`, radius `--radius-card`) under the grid, headed "Unscheduled" as a section label. Each row is at least 56px tall with 14px side padding and a 1px `--divider` between rows. It shows the title (15px / 600) and the estimate under it (12px, `--text-muted`), for example "15m". An item whose work waits on a week that can't be planned adds the reason after the estimate, in `--attention-text` (that week needs you), and the line wraps: "12h · Waiting on Nov 30 to Dec 6, which can't be planned." Work that is only waiting for its deadline to come within planning range is normal and gets no reason, so it isn't listed here.
- **Attention banner** (infeasible week, missing week file): `--attention-bg` background, 1px `--attention-border`, radius 12px, 12px 16px padding. The title is 14px / 600 in `--text`. The body is 13px in `--attention-text`. Example: "This week can't be planned" / "6h of work doesn't fit before Wed 11:59pm." A banner about something you did, like a delete that failed after its popover closed, has a close button on the right: a 44px square, no background, "×" at 20px in `--attention-text`. Banners about the week itself have none.

## Add item dialog (Milestone 3)

This is the prototype's Add item screen, adapted from a phone sheet to a desktop dialog. `add-item-preview.png` shows it with "Any of these days" selected.

It adds one token to `tokens.css`: `--scrim`, the backdrop behind dialogs (`--text` at 40%).

### Container

- **Editing:** the same dialog edits an item (see Item details popover, Editing).
- **Element:** a native `<dialog>` opened with `showModal()`. That keeps focus inside the dialog and makes Esc cancel, with no extra code.
- **Backdrop:** `--scrim`.
- **Box:** 480px wide (full width minus 32px on narrow screens), at most the window height minus 64px (minus 32px on narrow screens, where the header and body side padding drop to 16px). `--bg` background (the off-white, as in the prototype), radius `--radius-card`, no border, no shadow.
- **Header:** stays put while the body scrolls. Padding is 20px 24px 12px. It has three parts in a row:
  - "Cancel" on the left: a text button, 15px / 500, `--text-muted`, 44px tall, no background.
  - "New item" in the middle, centered: Space Grotesk 18px / 600.
  - "Add" on the right: a primary button.
- **Body:** 0 24px 24px padding, a 16px gap between field groups, and it scrolls when the dialog is taller than the window.
- **Page behind:** doesn't scroll while the dialog is open. Wheel and touch scrolling stay inside the body and never reach the week grid.
- **On open:** focus goes to the Title field.

### Fields, in this order

Flexibility comes before Estimate, unlike the prototype. Choosing "Exact time" hides the estimate fields, and hiding things below the control you just clicked doesn't make the page jump under your cursor.

1. **Title:** a text input. Required.

2. **Flexibility:** a label, then a radio group inside a card (`--surface`, 1px `--border`, radius `--radius-input`, overflow hidden).
   - **Rows:** one 44px row per preset, 15px text, 14px side padding, and a 1px `--divider` between rows. The presets are Exact time, Any time on a day, Time range on a day, Any of these days, Every one of these days, and Before a deadline. Custom stays out until painted windows exist.
   - **The selected row:** `--accent-tint` background, 600 weight, and an 18px `--accent` check on the right.
   - **Its fields panel:** directly under the selected row, with an `--surface-sunken` background, 12px 14px padding, a 10px gap, and a 1px `--divider` below. Only the selected preset's panel is shown.

   | Preset | Panel fields |
   | --- | --- |
   | Exact time | Date, then start time "to" end time |
   | Any time on a day | Date |
   | Time range on a day | Date, then start "to" end |
   | Any of these days | Weekday picker, then an optional "Only between" start "to" end |
   | Every one of these days | The same as Any of these days |
   | Before a deadline | Due date and due time |

   - **Time pairs:** on one row, as `[start] to [end]`. The inputs are 44px tall, radius `--radius-control`, with centered text. "to" is 14px in `--text-muted`.
   - **Overnight times:** an end time earlier than the start time means the next day. The summary line says so.
   - **Outside your work hours:** when any part of a Time range on a day, Any of these days or Every one of these days range falls outside the work frames on the days it applies to, a 12px `--text-muted` line "Outside your work hours" shows under the start/end pair. It is informational only and never blocks Add, since a range overrides the work frames.
   - **Weekday picker:** seven segmented buttons (Mon to Sun) with a 6px gap, sharing one row. Each is 44px tall, 13px / 600. At least one day is required.
   - **Optional fields:** labels inside a panel use the normal label style (13px / 600), and optional ones end with "(optional)" in `--text-muted` 400, as in "Only between (optional)".
   - **Dates and times:** use native `<input type="date">` and `<input type="time">`, styled like the text inputs. No date library.
   - **Summary line:** every panel ends with one line saying what the solver will get, in 12px `--text-muted`. It updates as you type. This comes straight from the prototype. Examples:
     - "The solver sees: Mon, Wed, Fri this week (Nov 16 to 22), 4:00 to 9:00pm". An "Any of these days" item belongs to the week being viewed, so its summary always names that week. (`add-item-preview.png` predates this and shows the line without the week.)
     - "The solver sees: 30m on each of Wed, Thu, Fri this week (Nov 16 to 22), 6:00 to 8:00pm". An "Every one of these days" item lists only the picked days that still have room for a whole session (picked days that have passed, and today if too little of it is left, drop out). It leaves out the length until Each day is valid, and says nothing when no picked day is left.
     - "Due Wed, Nov 18 at 11:59pm"
     - "Thu, Nov 19, 11:00pm to 1:00am (ends the next day)"

3. **Estimate and Longest session:** two inputs side by side with a 12px gap. Both are hidden when Exact time is selected, since the start and end set the length, and when Every one of these days is selected, which uses Each day instead.
   - **Estimate** (required): a text input with the placeholder "1h 30m". It accepts "45m", "2h", "1h 30m", or a plain number of minutes.
   - **Longest session** (optional): the same format, with the placeholder "No limit". Under the pair, a 12px `--text-muted` hint: "Longer work is split into sessions up to this length."

   - **Each day** (Every one of these days only, required): in place of the pair, one text input in the same format, with the placeholder "30m". Under it, a 12px `--text-muted` hint: "One session this long on every day you picked that hasn't passed."

   - **Planned as:** when a length is off the slot grid, a 12px `--text-muted` line under its field gives the length the planner uses, such as "Planned as 30m". Estimate and Each day round up, and Longest session rounds down, never below one slot. The summary line uses the planned length too. It's informational only and never blocks Add.

4. **One session per day:** a switch row inside a card, styled like the prototype's "Check in when it ends" row.
   - **Text:** the title "One session per day" (15px / 600), with "Puts each session on a different day." under it (12px, `--text-muted`).
   - **When it shows:** only when Longest session is set and shorter than Estimate, because otherwise there's only one session.

### States

- **Add button:** enabled except while saving. Pressing it with errors sends nothing: every error shows at its field, and the first one in the form scrolls into view and gets focus. While saving, it reads "Adding..." and the whole form is disabled. Saving re-plans the weeks the item touches. That usually takes a second or two, and can take longer on busy weeks, up to the planner's work limit.
- **Field errors:** shown under the field in 12px `--attention-strong`, with the field's border in `--attention-strong`, never only in the banner. The field is marked invalid and points at its message, for screen readers. Messages say how to fix the problem:
  - "Use a length like 45m or 1h 30m."
  - "Pick at least one day."
  - "That deadline has already passed."
  - "None of these days has room left this week." (Every one of these days, under the weekday picker)
- **Server errors** (a 422 or anything else): errors that aren't about one field, like "doesn't fit", show in an attention banner at the top of the body with the server's message, and the body scrolls to the top so the banner is in view. Everything you typed stays in the form.
- **Success:** the dialog closes and the grid shows the re-planned week.

## Item details popover (Milestone 3)

The popover is where an item's details and actions live. Milestone 3 has one action, Delete. Milestone 4 adds Edit next to it, so the layout already has room for a second action.

### Opening and closing

- **From a block:** clicking a block, or pressing Enter or Space on it, opens the popover for that block. Blocks are buttons, so the keyboard reaches each one.
- **From an Unscheduled row:** a "More" icon button at the right end of the row opens the same popover, anchored to the row. The icon is three horizontal dots, 18px, stroke `--text-muted`, inside a 44px square transparent button.
- **Closing:** Escape, clicking anywhere outside it, or opening another block's popover closes it. Use the native `popover="auto"` attribute, which does all three with no extra code. Focus then returns to the block or button that opened it.
- **Only one at a time.**

### Box

- **Position:** next to what opened it, 8px away. To the right of a block when there is room, otherwise to its left. Its top lines up with the block's top, moved up or down as needed so it stays inside the window with 16px to spare. Under an Unscheduled row's button, right-aligned with it.
- **Look:** 300px wide (full width minus 32px on narrow screens), `--surface` background, 1px `--border`, radius `--radius-card`, 16px padding, a 12px gap between parts. No shadow; the border and the white card on the off-white page are enough.

### Content, top to bottom

1. **Title:** the item's title, 15px / 600, `--text`. It wraps instead of being cut off.
2. **When:** the block's day and time range, 13px, `--text`, for example "Tue, Nov 17, 2:00 to 2:30pm". A block that crosses midnight gives its full range: "Fri, Nov 20, 5:00pm to 2:00am (ends the next day)".
3. **Kind and sessions:** one line in 12px `--text-muted`.
   - "Fixed" or "Placed by the solver".
   - If the item has more than one session, add where this one fits and how much of the work is placed, for example "Placed by the solver · Session 2 of 4 · 2h in all". When the placed minutes are less than the estimate (work waiting on a week that can't be planned, or not yet within planning range), say so instead: "Session 2 of 2 · 2h of 4h placed". "In all" is only for an item whose work is all placed. Sessions are counted across every week, in time order. The week response carries what this needs for each block: its session number, the item's session count, its placed minutes and its estimate.
   - If the block has already started: "Already started", because the solver no longer moves it.
   - For an Unscheduled row instead of a block: its reason, the same text as the row ("Waiting on Nov 30 to Dec 6, which can't be planned."), or "Not scheduled: it has no times to go in yet" if it has none. Then its estimate, for example "· 15m".
4. **Actions:** a row of buttons at the bottom, right-aligned, with an 8px gap.
   - "Edit", a secondary button, left of "Delete item", also secondary. Edit opens the item in the edit dialog (see Editing). While the item loads it reads "Opening..." and both buttons are disabled. If loading fails, a 12px `--attention-strong` line under the actions says "Couldn't open it:" and the server's message.
   - For a Custom item, Edit is disabled, and a 12px `--text-muted` line under the actions says "Change Custom items in their week file."

### Deleting

- **What it deletes:** the whole item, with every session in every week, past sessions included. The button says "Delete item" for that reason. Deleting a single session isn't offered: the solver would just place that work again.
- **Imported items:** deleting an item that came from a week file doesn't stop a later `mycal-import --replace` of that file from bringing it back.
- **Confirming:** pressing "Delete item" swaps the actions row, in place, for a confirm row. Nothing else opens.
  - The question, 13px / 600 `--text`: "Delete this item?", then a 12px `--text-muted` line saying what goes: "All 4 sessions go, in every week." or "Its one session goes." or "It has no sessions yet."
  - Two buttons, right-aligned: "Cancel" (secondary) and "Delete" (secondary, with `--attention-strong` text and border). Focus moves to "Cancel".
  - Cancel brings the actions row back. Escape still closes the whole popover.
- **While deleting:** the solver re-plans the weeks the item was in. That usually takes a second or two, and can take longer on busy weeks, up to the planner's work limit. "Delete" reads "Deleting..." and both buttons are disabled. The grid stays as it was until the delete finishes, so nothing jumps around. Closing isn't blocked: Escape and clicking outside close the popover as usual (plain `popover="auto"`), the delete keeps running, and the grid updates when it finishes.
- **When it's done:** the popover closes and the grid shows the re-planned week. Focus goes to the grid's scroll area, since the block it came from is gone.
- **If the planner runs out of time:** the item is still deleted, and the weeks it was in re-plan when next viewed. The popover closes as when it's done.
- **If it fails:** if the popover is still open, the confirm row stays, and a line under it in 12px `--attention-strong` says what went wrong, using the server's message, for example "Couldn't delete it: Can't reach the planner." The buttons are enabled again so it can be retried. If the popover was already closed, the page's attention banner shows the same message instead.
- **If the item was already gone** (a 404, say it was deleted from another tab): the popover closes and the week reloads, without an error.

### Editing (Milestone 4)

- **Opening:** Edit closes the popover and opens the Add item dialog in edit mode, filled in with the item as stored. Lengths show as typed, so a 20m estimate shows "20m" with "Planned as 30m" under it. If the item is already gone (a 404), the popover closes and the week reloads, as for a delete.
- **Header:** "Edit item", and the primary button reads "Save" ("Saving..." while saving). Everything else matches adding: the same fields, errors at their field, and server errors in the banner (titled "Couldn't save it").
- **Imported items:** an item from a week file shows a 12px `--text-muted` line at the top of the body: "From 2026-11-16.toml. Importing that file again with --replace undoes this edit."
- **Past items:** a title or length can always be changed. When the item is (its day, times, days or deadline) only has to lie ahead if it changes, so a past item doesn't show "already passed" errors until its time is changed.
- **What carries over:** sessions that already started or are done stay and count toward the work, and the rest is re-planned. A change that doesn't fit is refused with the reason, and nothing changes.
- **Done:** the dialog closes, the grid shows the re-planned week, and focus goes to the grid's scroll area, since the block may have moved.

### Past blocks

Blocks that already started can be opened and their item deleted like any other, with the "Already started" line as the reminder. In Milestone 3 a past block is only a planned slot, not completion history. Once check-ins exist (Milestone 6), an item with finished blocks should be archived instead of deleted, to keep that history (see the "get right now" rules in the PRD). The popover will need a different action then.

### Exception to the 44px rule

Blocks are clickable, but a block's height comes from its length (a 15 min block is 13px tall), so it can't always be 44px. This is the one exception to "everything clickable is at least 44px". Every block is still reachable with the keyboard, and the Unscheduled "More" button is a full 44px.

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
