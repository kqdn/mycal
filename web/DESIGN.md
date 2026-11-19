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

- **Top bar:** 64px tall, `--surface` background, 1px `--border` bottom border, 32px side padding. Tabs on the left are 64px tall with a 3px bottom border. The active tab has an `--accent` border and text. Inactive tabs have a transparent border and `--text-muted` text. The tabs are "Week" and "Frames and rules" (see Frames and rules), with the "New item" primary button on the right on the Week page. Add "Today" and "Projects" when those features are built.
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
| Done | block status done or partial | `--block-done-bg` | 1px `--block-done-border` | `--text-muted`, line-through | `--text-muted` |
| Missed | block status missed or unanswered | `--bg` | 1px dashed `--block-done-border` | `--text-muted` | `--text-muted` |
| Waiting for a check-in | checkable, ended, still planned | as its kind | 2px `--attention-border` | as its kind | as its kind |
| Locked (later) | placed by hand | same as Placed, plus a 14px lock icon at the top right | | | |

**Text by height** (fixes clipped titles on short blocks). The title never wraps: it stays on one line and ends with an ellipsis when it doesn't fit.

| Block height | Shows |
| --- | --- |
| 40px or more (1 hour and longer) | Title on line 1, time range on line 2 |
| 20 to 39px (30 and 45 min) | One line: "Title · 2:00pm" (start time only), padding 2px 8px |
| Under 20px (15 min) | Title only at 11px with line-height 11px, no vertical padding (a 15 min block is 13px tall, 11px inside its borders) |

Each block also gets an accessible name with the full details, for example `aria-label="Call home, Thu 6:00 to 6:30pm"`.

### Legend

Under the grid: a 1px `--border` top edge, 14px 16px padding, 12px `--text-muted` text, with 8px 22px gaps between items. Each item is a 14px swatch with radius 4px, styled like its block kind, followed by its label: "Fixed", "Placed by the solver", "Done", "Missed", then "Work hours" (an `--surface` swatch with a 1px `--border`, for the white time inside work frames). Add "Locked by you" when that exists.

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

5. **Check in when it ends (Milestone 7):** a switch row like One session per day, always shown.
   - **Text:** the title "Check in when it ends" (15px / 600), with "Asks Yes, Partly or No after each session." under it (12px, `--text-muted`).
   - **Default:** on, except for Exact time, where it starts off (meetings and appointments). A lecture can be switched on. Once switched by hand, changing the preset doesn't change it.
   - **If missed:** shown under the switch while it is on, 8px below it. A label "If missed", then a segmented choice like Repeats: "Reschedule", "Catch up", "Skip", "Ask me". Default: Reschedule. Exact time has no Reschedule, since it can't move, and Skip is selected in its place. A 12px `--text-muted` line under the choice says what it does:
     - Reschedule: "The missed time goes back into the plan."
     - Catch up: "Adds a catch-up item, due before the next one."
     - Skip: "Nothing moves. It's only logged."
     - Ask me: "You choose each time."

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
4. **Actions:** a row of buttons at the bottom, centered, with an 8px gap. Every button row in the popover is centered: the actions, the delete confirm, and a series' Edit which? / Delete which? choice.
   - "Edit", a secondary button, left of "Delete item", also secondary. Edit opens the item in the edit dialog (see Editing). While the item loads it reads "Opening..." and both buttons are disabled. If loading fails, a 12px `--attention-strong` line under the actions says "Couldn't open it:" and the server's message.
   - For a Custom item, Edit is disabled, and a 12px `--text-muted` line under the actions says "Change Custom items in their week file."
   - For a checkable block that has started, "Check in" (or "Change answer" once answered) comes first in the row. It closes the popover and opens the check-in dialog (see Check-ins).
   - A kept session of a deleted item (see Deleting) shows its lines and "Deleted. This session stays as a record." in hint text, with no buttons. E and Delete do nothing on it.
5. **Check-in line (Milestone 7):** under the kind line, 13px `--text`, when there is something to say: "Waiting for a check-in", "Done", "Partly done: 30m of 1h · The rest is rescheduled", "Missed · Caught up later", "No answer · Skipped", or "Missed · Waiting for your choice" while an Ask waits.

### Deleting

- **What it deletes:** the whole item, with every session in every week, past sessions included. The button says "Delete item" for that reason. Deleting a single session isn't offered: the solver would just place that work again.
- **Imported items:** deleting an item that came from a week file doesn't stop a later `mycal-import --replace` of that file from bringing it back.
- **Confirming:** pressing "Delete item" swaps the actions row, in place, for a confirm row. Nothing else opens.
  - The question, 13px / 600 `--text`: "Delete this item?", then a 12px `--text-muted` line saying what goes: "All 4 sessions go, in every week." or "Its one session goes." or "It has no sessions yet."
  - Two buttons, centered: "Cancel" (secondary) and "Delete" (secondary, with `--attention-strong` text and border). Focus moves to "Cancel".
  - Cancel brings the actions row back. Escape still closes the whole popover.
- **While deleting:** the solver re-plans the weeks the item was in. That usually takes a second or two, and can take longer on busy weeks, up to the planner's work limit. "Delete" reads "Deleting..." and both buttons are disabled. The grid stays as it was until the delete finishes, so nothing jumps around. Closing isn't blocked: Escape and clicking outside close the popover as usual (plain `popover="auto"`), the delete keeps running, and the grid updates when it finishes.
- **When it's done:** the popover closes and the grid shows the re-planned week. Focus goes to the grid's scroll area, since the block it came from is gone.
- **If the planner runs out of time:** the item is still deleted, and the weeks it was in re-plan when next viewed. The popover closes as when it's done.
- **If it fails:** if the popover is still open, the confirm row stays, and a line under it in 12px `--attention-strong` says what went wrong, using the server's message, for example "Couldn't delete it: Can't reach the planner." The buttons are enabled again so it can be retried. If the popover was already closed, the page's attention banner shows the same message instead.
- **If the item was already gone** (a 404, say it was deleted from another tab): the popover closes and the week reloads, without an error.
- **Items with check-in history (Milestone 7):** they are archived, not deleted, but the page still says Delete everywhere: "Delete item", "Delete this item?", "Delete" ("Deleting..."). The confirm's detail says what stays instead of "All 4 sessions go": "The 2 sessions ahead go. The 3 sessions that already started stay on your calendar." (or "The one session ahead goes.", "The session that already started stays on your calendar.", and only the second sentence when nothing is ahead). The sessions that started stay in the grid as they were, as a record. For a series, This adds ", keeping its sessions that started on your calendar" to its line.

### Editing (Milestone 4)

- **Opening:** Edit closes the popover and opens the Add item dialog in edit mode, filled in with the item as stored. Lengths show as typed, so a 20m estimate shows "20m" with "Planned as 30m" under it. If the item is already gone (a 404), the popover closes and the week reloads, as for a delete.
- **Header:** "Edit item", and the primary button reads "Save" ("Saving..." while saving). Everything else matches adding: the same fields, errors at their field, and server errors in the banner (titled "Couldn't save it").
- **Imported items:** an item from a week file shows a 12px `--text-muted` line at the top of the body: "From 2026-11-16.toml. Importing that file again with --replace undoes this edit."
- **Past items:** a title or length can always be changed. When the item is (its day, times, days or deadline) only has to lie ahead if it changes, so a past item doesn't show "already passed" errors until its time is changed.
- **What carries over:** sessions that already started or are done stay and count toward the work, and the rest is re-planned. A change that doesn't fit is refused with the reason, and nothing changes.
- **Done:** the dialog closes, the grid shows the re-planned week, and focus goes to the grid's scroll area, since the block may have moved.

### Past blocks

Blocks that already started can be opened like any other, with the "Already started" line as the reminder. A checkable one can be checked in from its popover. Deleting an item with check-in history keeps its sessions that started (see Deleting); one without is deleted as before.

### Exception to the 44px rule

Blocks are clickable, but a block's height comes from its length (a 15 min block is 13px tall), so it can't always be 44px. This is the one exception to "everything clickable is at least 44px". Every block is still reachable with the keyboard, and the Unscheduled "More" button is a full 44px.

## Check-ins (Milestone 7)

When a checkable session ends, the page asks how it went. Push notifications wait for the PWA install, so for now the asking happens on the Week page.

- **Banner:** above the grid, in the attention style (orange: check-ins need you), on any week while something waits. Title: "1 session to check in" or "3 sessions to check in". Then one row per session, earliest first, at least 56px tall with a 1px `--attention-ring` line between rows: the title (15px / 600) and its day and time under it (12px `--text-muted`), with " · Waiting for your choice" for an Ask that went unanswered, and a "Check in" secondary button on the right.
- **Refreshing:** the page asks the server for the list when it loads, after every change, and every minute. A session left unanswered for 4 hours counts as No, and that can re-plan, so when the server's list changes on its own, the week reloads.
- **Dialog:** a native `<dialog>` like the Add item dialog (same box, header and body), titled "Check in", or "Change answer" for a block already answered. The primary button reads "Save" ("Saving..."). In the body, in order:
  1. The session: its title (15px / 600) and "Tue, Nov 17, 9:00 to 10:00am · 1h" (12px `--text-muted`).
  2. **Did you do it?** A segmented choice: "Yes", "Partly", "No". Nothing is picked at first, except the earlier answer when changing one.
  3. **How much did you get done?** (Partly only): a length input like Estimate, placeholder "30m", with "The rest counts as missed." under it. It must be shorter than the session.
  4. **The time you missed** (No), or **The rest** (Partly): a segmented choice of "Reschedule", "Catch up", "Skip" (no Reschedule for a fixed block), starting on the item's If missed choice, or on nothing for Ask me. The line under it says what the choice does, as in the Add item dialog.
- **Errors:** at their field, like the Add item dialog: "Pick Yes, Partly or No.", "Use a length shorter than the session's 1h, like 30m.", "Pick what happens to the time you missed." A refusal from the server (the missed time can't go anywhere) shows in the banner at the top of the body, "Couldn't save it", and the form stays, so another choice can be picked.
- **Fewer sessions:** when the answer would leave an "N times a week" item with fewer sessions, the server asks first. The dialog shows a banner, "Fewer sessions", with the server's sentence ("Workout gets 2 of 3 sessions this week: only Wed and Fri are left.") and "Save anyway to accept it.", and the primary button reads "Save anyway". Changing the answer takes the question away.
- **Done:** the dialog closes, the grid shows the re-planned week, and the banner drops the session.

## Repeat (Milestone 6)

Draft by Claude, for Kaden to review. A repeating item is a series: the item's fields plus how it repeats. Each date it repeats on gets its own occurrence, which is a normal item on the grid.

### Repeats field (New item dialog)

- **Where:** right after Flexibility, before Estimate. It changes which date fields Flexibility shows, so it sits next to them.
- **Choice:** a label "Repeats", then a segmented choice filling the row: "Never", "Weekly", "Daily". Default: Never, so a one-off item is added exactly as before. For "Any of these days" and "Every one of these days" the choice is "Never" and "Every week", since those repeat as a whole week. Switching to one of those presets while Daily is picked switches to Every week.
- **Its fields:** when it isn't Never, a card under the choice (`--surface-sunken`, 1px `--border`, radius `--radius-input`, 12px 14px padding, a 10px gap, 8px below the choice) holds, in order:
  - **On** (Weekly only, not for days presets): the weekday picker. Choosing Weekly picks the start date's weekday to begin with. At least one day is required.
  - **Every N weeks / days:** "Every", a 72px wide numeric input (default 1), then "weeks" or "days", on one row.
  - **Starts and Ends (optional):** two date inputs side by side, like Estimate and Longest session. Starts defaults to the form's date (today if it is in the viewed week, else its Monday). A days item repeats from the Monday of the week Starts falls in, and a hint under the dates says so: "Repeats as a whole week, starting on the Monday of its start date."
- **While repeating, the preset's own dates hide:** Exact time, Any time on a day and Time range on a day lose their Date, and Before a deadline keeps only its due time. Each occurrence's date fills them in.
- **Summary line:** the preset panel's line describes the series instead: "Every Tue and Fri, 8:00 to 9:00am, from Tue, Nov 17", "Each of Mon, Tue, Wed, Thu and Fri, every week, 6:00 to 8:00pm, from Mon, Nov 16", "Due every Wed at 5:00pm, from Tue, Nov 17 until Wed, Dec 16".
- **Errors**, at their field like the others:
  - "Pick at least one day to repeat on."
  - "Use a whole number of 1 or more."
  - "A repeating item can't start in the past." (A days item may start any day of this week.)
  - "The end date is before the start date."
  - "Pick a due time." (Before a deadline)
- **Adding:** the series re-plans every week from this one on, like a work frame, so it can take a few seconds. A week that would stop fitting refuses it, with the server's message in the banner.
- **Editing a one-off item:** the Repeats field shows too, on Never. Picking Weekly or Daily and saving turns the item into a repeating item, with the item as its first date: it keeps its sessions, and done work stays. Starts begins on the item's own date (its day, its due date, or its week's Monday), which may have passed; only a different start has to lie ahead. If the item already started, or the repeat days don't include its date, it stays exactly as it is and the series continues on its own days.

### Details popover

- **Repeats line:** an occurrence of a series adds a line under the kind line, same style (12px `--text-muted`): "Repeats every Tue and Fri", "Repeats every week", "Repeats every 2 weeks on Tue", "Repeats every day", plus " until Fri, Dec 18" when it ends.
- **Edit:** for an occurrence, Edit swaps the actions row for a choice row, like the delete confirm: "Edit which?" (13px / 600), then "This changes only this date. All changes every date that hasn't started." (12px `--text-muted`), and three secondary buttons: "Cancel", "This", "All". The row wraps when the buttons don't fit. Focus moves to Cancel.
  - **This** opens the normal edit dialog for that date, without the Repeats field. A date edited this way keeps its changes when the series is edited later.
  - **All** opens the dialog as "Edit repeating item", with the Repeats field (no Never) and the series' fields. Saving rebuilds every date that hasn't started, except ones edited on their own. Past dates stay as they were. A start date that has passed can stay; only a changed start has to lie ahead.
- **Delete:** for an occurrence, "Delete item" asks "Delete which?" with "This skips only this date. All stops it repeating: dates that haven't started go, and past ones stay." The buttons are "Cancel", "This" and "All", the last two styled like Delete (`--attention-strong`). The one pressed reads "Deleting..." and all three are disabled while it runs. Everything else (errors, closing while it runs, a 404) works as for deleting an item.

## Frames and rules (Milestone 5)

A second page, reached from a second top-bar tab, where work frames and rules (constraints) are viewed, added, edited and deleted. Until now they could only be changed in a week file and re-imported. It adds no tokens and no libraries.

### Tab and page

- **Tab:** "Frames and rules", right of "Week", styled like it (see Page layout). The page is chosen by a `view=rules` URL param next to `week=`, so the browser's back button works and going back to Week returns to the same week. No router library: `App` reads the param and renders one page or the other.
- **Top bar:** the "New item" button shows only on the Week page.
- **Coming back to Week:** the Week page fetches its week again every time it is shown, so it always shows the plan made after the last save here.
- **Title row:** eyebrow "Your planner", page title "Frames and rules" (Space Grotesk 28px / 600). No week arrows: frames and rules apply to every week.
- **Column:** the two sections stack in one column, at most 720px wide, left-aligned inside the content area, with a 32px gap between them. Wider rows would put the row text far from its chevron.
- **Loading:** while the page loads, each section shows its header and a card with one 56px row reading "Loading..." in 13px `--text-muted`. If loading fails, the page attention banner shows "Couldn't load frames and rules" with the server's message.

### Section header

Each section starts with a header row: on the left, the section label (13px / 600, `--text-muted`) with a one-line description under it (12px, `--text-muted`, 2px gap). On the right, its add button. The two sides are aligned to their bottom edge, with 10px between the header and the card.

| Section | Label | Description | Add button |
| --- | --- | --- | --- |
| 1 | Work frames | Times when flexible work may be placed, every week. | Add frame |
| 2 | Rules | Limits and wishes the planner follows when it places work. | Add rule |

- **Add buttons:** secondary buttons (44px tall), with an 18px plus icon (stroke `--text`, stroke-width 2, round caps) 6px before the text. Secondary, not primary, so the green "New item" stays the one main action in the app.

### List rows

Each section's rows sit in one card (`--surface`, 1px `--border`, radius `--radius-card`), like the Unscheduled list.

- **Row:** a `<button>` the full width of the card, at least 56px tall, 12px 14px padding, a 1px `--divider` between rows, no background. Text is left-aligned. An 18px chevron pointing right (stroke `--text-muted`) sits at the right end, vertically centered, with 12px before it. Hover gives the row an `--surface-sunken` background. Clicking it, or Enter or Space, opens the edit dialog.
- **Title line:** 15px / 600, `--text`. It wraps instead of being cut off, since a rule's whole meaning is in it.
- **Detail line:** 12px, `--text-muted`, 2px under the title. Parts are joined with " · ".
- **Accessible name:** the row's text plus "Edit", as in `aria-label="Edit work frame Weekdays, Mon to Fri, 9:00am to 6:00pm"`.

**Work frame rows**

- Title: the frame's name, "Weekdays".
- Detail: its days and times, "Mon to Fri · 9:00am to 6:00pm". An overnight frame adds "(ends the next day)": "Fri · 10:00pm to 1:00am (ends the next day)".
- Order: by the first weekday, then start time.

**Rule rows**

- Title: the rule as one sentence, the same text as the dialog's summary line (see Summary lines). For example:
  - "At most 2h on weekends"
  - "Gym: prefer 4:00 to 6:00pm on weekdays, 12:00 to 2:00pm on weekends"
  - "Read for seminar: avoid 9:00am to 12:00pm on weekdays"
  - "Gym: at least 1 day between sessions"
- Detail: the kind, then how strictly it's kept, then where it came from if imported: "Daily limit · Always kept", "Time preference · A wish", "Rest days · A wish · From 2026-11-16.toml". The file name is the only sign of an import, kept quiet like the Item details popover's.
- Order: daily limits first, then time preferences, then rest days. Within a kind, in the order they were added.

**Days and times in text**

- A frame row lists days compactly: three or more days in a row read "Mon to Fri", two read "Sat and Sun", and anything else is a list, "Mon, Wed, Fri". All seven read "Every day".
- A rule sentence uses words where they fit: Mon to Fri is "weekdays", Sat and Sun is "weekends", and all seven is "every day". Other sets use the frame form after "on": "on Mon, Wed, Fri".
- Times follow the Principles: "4:00 to 6:00pm", "9:00am to 12:00pm".
- Rule targets: one or two names are listed ("Gym", "Gym, Read for seminar"), three or more read "Gym and 2 more". Every item reads "Every item". A series shows its title once, without dates.

**Empty states**

The card holds one 56px row of 13px `--text-muted` text, not a button:

- Work frames: "No work frames. Items without their own times can't be placed until you add one."
- Rules: "No rules yet. The planner only uses your work frames and each item's times."

### Dialogs: shared parts

Adding or editing a frame or a rule opens a dialog built exactly like the Add item dialog: the same `<dialog>` with `showModal()`, `--scrim` backdrop, 480px box on `--bg`, the fixed header with "Cancel", a centered title and the primary button, the scrolling body with a 16px gap, the field and label styles, the time pairs, the weekday picker and the summary line. Only what differs is described below.

| | Frame | Rule |
| --- | --- | --- |
| Title, adding | New frame | New rule |
| Title, editing | Edit frame | Edit daily limit / Edit time preference / Edit rest days |
| Primary button | Add, or Save when editing | Add, or Save when editing |
| Focus on open | Name | Adding: the selected kind row. Editing: the first field |

- **Imported rules:** editing a rule from a week file shows a 12px `--text-muted` line at the top of the body: "From 2026-11-16.toml. Importing that file again with --replace undoes this edit."
- **Delete (editing only):** a "Delete frame" or "Delete rule" button at the bottom of the body, left-aligned, separated from the fields above by a 1px `--divider` and 8px of space. It is a secondary button with `--attention-strong` text and border. See Deleting.

### Frame dialog fields, in this order

1. **Name:** a text input, required, with the placeholder "Weekdays".
2. **Days:** the label "Days", then the weekday picker (seven segmented buttons, Mon to Sun). At least one is required.
3. **Time:** the label "Time", then the start "to" end pair. An end earlier than the start crosses midnight. Each picked day is the day the frame starts on, so "Fri, 10:00pm to 1:00am" ends early Saturday.
4. **Summary line:** "The planner sees: Mon to Fri, 9:00am to 6:00pm, 9h each day (45h a week)". Overnight adds "(ends the next day)" after the times. It leaves out the hours until both times are valid.

Overlapping frames are allowed: their times merge, as they do today. Nothing warns about it.

### Rule dialog fields, in this order

1. **Kind** (adding only): a label "Kind", then a radio group in a card, styled like the Flexibility card. Each row is two lines and at least 60px tall: the kind's name (15px / 500, 600 when selected) and a 12px `--text-muted` line under it. The selected row gets `--accent-tint` and the 18px `--accent` check. Unlike Flexibility, the kind's fields go below the card, not in a panel inside it, because they are too tall to nest. Changing kind keeps the targets you picked.

   | Kind | Second line |
   | --- | --- |
   | Daily limit | Always kept. Caps scheduled time on chosen days. |
   | Time preference | A wish. Prefer or avoid times of day. |
   | Rest days | A wish. Leaves free days between sessions. |

   Default: Time preference, the most common one. When editing, the kind can't change; the dialog title names it instead, and to change kind you delete the rule and add another.

2. **The kind's fields:**

   **Daily limit**
   - "At most": a text input in the Estimate format ("2h", "1h 30m", "45m"), placeholder "2h", required. The "Planned as" line applies, rounding down.
   - "On these days": the weekday picker, required.
   - Hint under the picker, 12px `--text-muted`: "Everything on those days counts, fixed events too." A daily limit has no targets, since it counts the whole day.

   **Time preference**
   - "Prefer or avoid": a two-button segmented choice, "Prefer" and "Avoid", filling the row. Default Prefer.
   - "Times": one card per range (`--surface`, 1px `--border`, radius `--radius-input`, 12px 14px padding, a 10px gap inside, 8px between cards). Each card holds the weekday picker, then the start "to" end pair. When there is more than one range, each card's top right has a "Remove" text button (13px / 500, `--text-muted`, 44px tall, no background) on a row with "Range 1", "Range 2" (12px / 600, `--text-muted`) on the left.
   - "Add another range": a text button under the cards, 15px / 600, `--accent`, 44px tall, with the 18px plus icon in `--accent`. Up to 6 ranges; at 6 it hides.
   - Hint, 12px `--text-muted`: "Prefer: work is placed in these times when it can. Avoid: kept out of them when it can. A wish, never a promise."
   - Then **Applies to** (see Target picker).

   **Rest days**
   - "Free days between sessions": a number input (`type="number"`, `inputmode="numeric"`), 120px wide, min 1, max 6, default 1.
   - Hint, 12px `--text-muted`: "Same-day sessions count as too close. A wish: the planner breaks it before it misses a deadline."
   - Then **Applies to**.

3. **Summary line:** the last thing in the body before Delete. "The planner sees:" and then the rule's sentence, the same text the row will show: "The planner sees: Gym: prefer 4:00 to 6:00pm on weekdays, 12:00 to 2:00pm on weekends". It updates as you type and leaves out parts that aren't valid yet.

### Target picker ("Applies to")

- **Label:** "Applies to".
- **Choice:** a two-button segmented choice, "Every item" and "Chosen items", filling the row. Default for a new rule: Chosen items. "Every item" sends no item or series ids, which the PRD defines as every item. It is a separate choice, not "pick nothing", so an empty list never means everything by accident.
- **The list** (Chosen items only), under the choice with 8px between:
  - A filter text input, placeholder "Filter items", 44px tall (a smaller text input, otherwise the same style).
  - A card (`--surface`, 1px `--border`, radius `--radius-input`) that scrolls inside itself, at most 264px tall (six rows). Wheel scrolling stays inside it.
  - Each row is a checkbox `<label>`, at least 44px tall, 14px side padding, a 1px `--divider` between rows: a 20px square box (radius 6px, 2px `--checkbox-border`, filled `--accent` with a white check when picked), 12px gap, then the title (15px) with a second line (12px `--text-muted`) saying what it is: "Repeats weekly" for a series, or the item's week, "Nov 16 to 22", for a one-off.
  - Series come first, then one-off items, each alphabetical. Picked ones stay where they are, so rows don't jump while you pick.
  - Picking a series covers every one of its weeks. A one-off item is covered only for its own week, and that's what its second line warns about.
  - The filter matches titles, case-insensitive. No match: one 44px row, "No items match "xyz"." in 13px `--text-muted`.
  - Above the card, right-aligned, 12px `--text-muted`: "2 picked", or nothing when none are.
- **Targets that no longer exist:** the server drops deleted items from rules (see the PRD), so the picker never shows a missing one.

### Validation messages

Shown under their field in 12px `--attention-strong`, with the field's border in `--attention-strong`, exactly as in the Add item dialog. Pressing Add or Save with errors sends nothing; the first error scrolls into view and gets focus.

- Name empty: "Give it a name, like Weekdays."
- No weekday picked: "Pick at least one day."
- Start equals end: "Start and end can't be the same time."
- A time missing: "Pick a start and an end time."
- Daily limit length unreadable: "Use a length like 2h or 1h 30m."
- Daily limit 0 or less: "Use a length longer than 0m."
- Daily limit over 24h: "A day only has 24h."
- Rest days not a whole number from 1 to 6: "Use a whole number of days from 1 to 6."
- Chosen items with none picked: "Pick at least one item, or choose Every item."

### Saving

- **While saving:** the primary button reads "Adding..." or "Saving...", and the whole form is disabled. Saving re-plans every planned week from this one on, since frames and rules apply to all of them. That usually takes a few seconds, more than adding an item, because several weeks re-plan.
- **What can be refused:** frames and daily limits are hard, so a change that makes a week stop fitting is refused, all or nothing, and nothing changes. A week that already didn't fit before the change doesn't count against it. Time preferences and rest days are wishes and are never refused for fit.
- **Refused:** the attention banner at the top of the body, titled "Couldn't save it", with the server's message as the body: "Nothing changed: the week of Nov 16 to 22 wouldn't fit. 6h of work doesn't fit before Wed 11:59pm." The body scrolls to the top so the banner shows. Everything you typed stays, so you can loosen it and try again.
- **Other server errors:** the same banner, with the server's message.
- **Done:** the dialog closes and the list shows the change. Focus goes to the saved row (a new row when adding). Nothing else on the page changes. The Week tab shows the new plan when you go back.

### Deleting

- **Confirming:** pressing "Delete frame" or "Delete rule" swaps that button, in place, for a confirm row, as the Item details popover does: the question (13px / 600 `--text`), "Delete this frame?" or "Delete this rule?", a 12px `--text-muted` line saying what follows, then "Cancel" (secondary) and "Delete" (secondary, `--attention-strong` text and border), right-aligned. Focus moves to "Cancel".
  - Frame: "Items without their own times stop using it, every week."
  - Rule: "The planner stops following it, every week."
  - Imported rule: "Importing 2026-11-16.toml again with --replace brings it back."
- **While deleting:** "Delete" reads "Deleting...", and the confirm row and the header buttons are disabled.
- **Refused:** deleting a frame can make a week stop fitting (less time to place work in). Then the confirm row stays, and a 12px `--attention-strong` line under it gives the server's message: "Nothing changed: the week of Nov 16 to 22 wouldn't fit. ..." Deleting a rule is never refused for fit.
- **Done:** the dialog closes, the row is gone, and focus goes to the section's add button.

### Narrow screens

Under 600px: the content's side padding drops to 16px, the section header stacks (the add button goes under the description, full width), and dialogs follow the Add item dialog's narrow rules. The weekday picker's buttons shrink to fit (the 44px height stays).

## Keyboard shortcuts

Draft by Claude, for Kaden to review. Single keys, no combinations to learn.

| Key | Does | Where |
| --- | --- | --- |
| 1 / 2 | Week tab / Frames and rules tab | Anywhere |
| N | New item | Week page |
| ← or K / → or J | Previous / next week | Week page |
| T | This week | Week page |
| E | Edit; for an occurrence, opens the This / All choice | A block under the mouse or with focus, or the item details popover |
| Delete, Backspace or D | Delete; opens the confirm step, never deletes outright | A block under the mouse or with focus, or the item details popover |
| F / R | New frame / New rule | Frames and rules page |
| ? | The list of shortcuts | Anywhere |

- **When they work:** never while typing in a field (text, date, time, select) or while a dialog is open, so typing "n" in a title is just text. A key held with Cmd, Ctrl or Alt is always left to the browser (Cmd+T, Cmd+R). With the item popover open, only E, Delete and ? count, so the week doesn't move out from under it. A block having focus doesn't stop them, since blocks are buttons.
- **Pointing at a block:** E and Delete (or D) work on the block under the mouse without clicking it first, or on the block with keyboard focus when the mouse isn't over one. E on a one-off item opens the edit dialog straight away (its popover shows "Opening..." meanwhile, and any error). E on an occurrence, and Delete on any block, open that block's popover on the "Edit which?" or delete confirm step, so a delete always asks first. With a popover already open, the block under the mouse still wins: E or Delete on another block opens that block's popover in place of the open one. With the mouse on the open popover's own block, or on no block (say, inside the popover), they act on the open popover.
- **Same as clicking:** each shortcut does exactly what its button does, with the same states (E does nothing while Edit is disabled or "Opening..."). In the popover, E and Delete work from any step, so they switch straight between "Edit which?" and the delete confirm; they do nothing while a delete or an edit is loading.
- **The list:** ? or a 44px "?" button at the right of the top bar (secondary-button look, `--text-muted` text, before New item) opens it. It's a native `popover="auto"`, centered with a `--scrim` backdrop, 400px wide (full width minus 32px on narrow screens), `--surface`, 1px `--border`, radius `--radius-card`, 20px padding. It has the title "Keyboard shortcuts" (15px / 600), one row per shortcut (keys on the left in 112px, the action in 14px with where it works under it in 12px `--text-muted`, a 1px `--divider` between rows), and a closing hint: "Shortcuts don't work while you type in a field or a dialog is open." Escape or a click outside closes it.
- **Keys:** each key is a `<kbd>` chip: at least 24px wide, 2px 6px padding, 1px `--border`, radius 6px, `--surface-sunken`, 12px / 600. Two keys for one action read "← or K".
- **Accessibility:** single-key shortcuts can clash with screen readers and voice control (WCAG 2.1.4). This is a one-person app and the keys only act outside text fields, so there is no setting to turn them off for now.

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
