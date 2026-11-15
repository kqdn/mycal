# Smart Scheduler PRD

Nov 13, 2026 · Kaden

> This file is the source of truth. It started as an export of the [claude.ai PRD](https://claude.ai/artifact/H1sVy8vF88wePc72n8Utcj) on Nov 13, 2026; that doc is an older copy and is no longer updated.

## Overview

A personal planner that places flexible work into your calendar with a constraint solver, then makes finishing it feel rewarding with visible progress.

**Problem.** Google Calendar and Tasks are utilities, not motivators. Completed tasks disappear, events look the same done or not, and there is no daily total to measure against. Scheduling flexible work is also manual: you play calendar Tetris yourself, and when you fall behind, you reshuffle by hand.

**Vision.** You describe what needs to happen (durations, windows, deadlines, subtasks) and the app finds the best arrangement. As you check things off, progress bars fill for the day and for each project. When something slips, the app re-plans the remaining work and warns you early if a deadline is no longer reachable.

## Goals and non-goals

The first version plans one person's schedule well; everything else waits.

**Goals**

- Auto-place flexible tasks into open time, respecting windows, deadlines and order
- Make completion satisfying: progress bars, finished items stay visible, streaks
- Re-plan on demand (one button) when something slips, with an early warning if a deadline is at risk
- Be able to add more time to events/tasks (+15 to start or end of task which will then move adjacent events if possible)
- Be a project I use every day and can explain in an interview

**Non-goals (for now)**

- Group scheduling and shared availability (Timeful-style)
- Matching every TickTick premium feature
- Collaboration, sharing, multiple users

## Core concepts

Everything is an **Item** (the what); every appearance on the calendar is a **Block** (the when). There are no separate event and task types.

| Concept | What it is | Example |
| --- | --- | --- |
| Item | The thing itself: title, flags, optional estimate, deadline, subtasks | CS 70 lecture, Gym, Write code |
| Block | One calendar slot for an item; an item has zero, one or many | Write code, Tue 2 to 4pm |
| Work frame | A window where flexible blocks are allowed to live | Weekdays 9am to 6pm |
| Project | An item with subtask items and a deadline; shown as a deadline reminder | Project 3 due Friday |
| Check-in | Prompt when a checkable block ends: Yes / Partly / No | "Did you go to lecture?" |
| On-miss policy | What a "No" (or the unchecked part of "Partly") triggers | Missed lecture creates a catch-up item |

**Item flags**

- `flexibility`: chosen from a dropdown when adding an item (presets below). Every preset turns into a list of allowed **windows**, which is all the solver sees.
- `checkable`: does it get a check-in? (lectures can be checkable even though they never move)
- `estimate`: how long it takes; needed for everything except exact-time items
- `on_miss`: reschedule, catch-up, skip, or ask

**Flexibility presets**

| Preset | Example | Windows it creates |
| --- | --- | --- |
| Exact time (pinned) | Lecture, Tue 11am to 12:30pm | One window exactly the item's length |
| Any time on a day | Lab, sometime Wednesday | That day's work frame |
| Time range on a day | Call home, Thu 5 to 9pm | That range on that day |
| Any of these days | Gym, Mon, Wed or Fri | The work frame on each chosen day (optional time range) |
| Any time before a deadline | Write code, by Friday | Every work frame from now until the deadline |
| Custom | Anything else | Paint the allowed time on a week grid |

**Preset params.** What `preset_params` holds for each preset. Local dates and times use my home timezone, which is passed in when presets are compiled. Windows are compiled for a planning horizon (usually now to the end of the week), clipped to it, and merged where they overlap or touch.

| Preset | preset_params | Notes |
| --- | --- | --- |
| Exact time | start, end (UTC) | Never cut short; dropped only if entirely outside the horizon |
| Any time on a day | day (local date) | Every work frame that starts on that day |
| Time range on a day | day, start_time, end_time (local) | End before start crosses midnight |
| Any of these days | weekdays[], optional start_time and end_time | Uses the time range if given, else the work frames on those weekdays |
| Any time before a deadline | none | Uses the item's deadline; also clipped to it |
| Custom | windows[] (UTC) | Clipped to the horizon |

**How items map to blocks**

| Item | Blocks | Why |
| --- | --- | --- |
| CS 70 lecture | One fixed block each week | Pinned, never moves |
| Gym, 1h | One flexible block | Solver places it |
| Write code, 4h | Two 2h blocks, usually on different days | Split across the week (max chunk size); spreading is a soft penalty, not a rule |
| Email advisor | Zero, for now | Sits in the task list until scheduled |

**On-miss policies**

| Policy | What happens | Example |
| --- | --- | --- |
| Reschedule | The block goes back into the pool and the solver re-places it | Write code, study session |
| Catch-up | A new flexible item is created to make up for it | Missed lecture becomes "Watch CS 70 lecture recording" |
| Skip | Nothing is rescheduled, just logged | Optional gym day |
| Ask me | The app asks what to do | Anything uncertain |

A catch-up item fills itself in: estimate = the missed block's length (about 1.25x for recordings at first, tuned later by estimate learning), deadline = before the next lecture or the dependent homework, windows = normal work frames.

**Check-in answers**

- **Yes:** block marked done, daily progress bar fills
- **Partly:** log how much got done; the rest goes back to the pool or into a catch-up item
- **No:** run the item's on-miss policy

**What "done" means.** Checking off a block fills today's bar. An item is done when its blocks are done, or when marked done early. A project's bar fills from its subtask items. When you fall behind, the solver moves blocks; the item, its deadline and its subtasks stay put.

## Features

The MVP is "plan my week and show my progress"; the smarter re-planning comes right after.

| Feature | Phase | Notes |
| --- | --- | --- |
| Add pinned, day-locked and flexible items | MVP | Manual input first; Google Calendar import later |
| Solver places flexible blocks | MVP | Windows, no overlap, deadlines, order |
| Drag a block to move it; moved blocks lock | MVP | Solver plans around locked blocks |
| Today view with daily progress bar | MVP | Completed blocks stay visible, crossed out |
| Calendar view of the planned week | MVP | Read-only is fine at first |
| Projects with subtask items, estimates, deadline | MVP | Split into blocks across days |
| Per-project progress bar | MVP | Fills as subtask items get done |
| Step through alternative arrangements | v2 | 3 to 5 meaningfully different options, changes highlighted |
| Compare an arrangement with the current plan | v2 | Current plan / Option toggle, From or To tags with an arrow, a changes list, one old spot shown at a time |
| Check-in when a checkable block ends | v2 | Yes / Partly / No; same flow for tasks, lectures, habits |
| On-miss policies | v2 | Reschedule, catch-up, skip, ask; covers falling behind and missed lectures |
| Free-move push | v2 | Drop an item on a flexible one; it shifts to the nearest gap in its frame |
| Re-optimize button | v2 | Full re-solve, with a penalty for moving things |
| Hard daily limits | v2 | Built: the daily_limit Constraint kind, e.g. "at most 3h on weekends" (see Constraint kinds) |
| Time preferences | v2 | Built: the soft time_preference Constraint kind, e.g. "gym in the afternoon", "no essays after 11pm" (see Constraint kinds) |
| Rest days between sessions | v2 | Built: the soft rest_between Constraint kind, e.g. a free day between gym sessions, re-spacing around a session that moved (see Constraint kinds) |
| Feasibility warning | v2 | "You need 6h but only have 4h before Friday" |
| Streaks / days at 100% | v2 |  |
| Google Calendar sync | v2 | Read first, two-way later |
| Estimate learning | v3 | Track actual vs estimated time; pad future estimates, including catch-up items |
| Conditional rules | v3 | "If study is Tuesday, gym is not Tuesday" |
| Habits, Pomodoro, stats | Later | Only once I actually want them |
| Group availability | Not planned | Out of scope for now |

**Prototype.** A clickable canvas with the Today, Check-in, Add item, Project and Week screens ([open it](https://claude.ai/artifact/PvchykUMuxnw5buWFihuQG)). The Week screen keeps four versions (v1 to v4) so the preview decisions stay traceable; v4 is current. Not shown yet: dragging blocks, the re-optimize button, free-move push, the +15 minutes control, Google Calendar import and estimate learning.

## Scheduling engine

Scheduling is a constraint problem solved with Google OR-Tools CP-SAT; the hard design work is the scoring, not the search.

**Model.** Time is split into 15-minute slots. Each block's start slot is a variable. The general problem is NP-hard, but a week of 10 to 30 flexible blocks solves in well under a second.

**Hard constraints** (must hold)

- Each block sits inside one of its allowed windows / work frames
- No two blocks overlap, and nothing overlaps a pinned event
- All blocks of a task finish before its deadline
- Dependencies: a subtask starts after the ones it depends on end
- One block per day: if an item has one_block_per_day set, no two of its blocks fall on the same local day. Off by default; without it, only the soft spread-out penalty applies, so a deadline-tight item can still double up on one day

**Soft constraints** (weighted penalties)

- Stability: penalize moving a block away from where it already is
- Time preferences: mornings for deep work, evenings free
- Buffer between events; avoid long back-to-back runs
- Spread a project's work out instead of cramming the last day

**Implemented so far** (CP-SAT engine, strict priority order: each tier always beats everything below it)

1. Stability: number of blocks moved from their current start
2. Spread: extra blocks of the same item on one local day
3. Preferences: weighted soft Constraints, summed (see Constraint kinds). Above balance because a rule I wrote down should beat the general wish for a light busiest day
4. Balance: the fullest local day, measured as scheduled minutes divided by that day's work-frame minutes, kept blocks included. A short weekend frame gets proportionally less work. Days with no work-frame time are left out
5. Earlier in the frame: how far into its work-frame occurrence each block starts, counting the whole occurrence even when it began before the planning week. A block outside every frame counts from the start of its item window

Buffers come later as Constraint kinds. The backtracking engine does not score; it returns the first valid arrangement.

**Objective.** Minimize the weighted sum of soft penalties, subject to all hard constraints. No feasible solution means a deadline is at risk, which triggers the feasibility warning.

**Solver input rules**

- Kept blocks: locked blocks and completion history (any status other than planned) are returned unchanged and nothing may overlap them. Unlocked planned blocks are the current plan and get re-placed.
- Remaining work: estimate minus time already covered (done and partial blocks count actual_min, or their length if missing; locked planned blocks count their length).
- Chunks: remaining work, rounded up to whole slots, is split into the fewest near-equal blocks no longer than max_chunk_min (5h with a 2h max is 105 + 105 + 90 min).
- An item with no estimate gets one block filling its single window exactly (how Exact items are placed); no estimate with several windows is an error. An item with no windows is skipped and stays in the task list.
- Stability: chunk i reuses the id of the item's i-th current block and tries its old start first.
- Window edges off the slot grid are rounded inward. Slots are counted from the Unix epoch in UTC.
- My home timezone is a required solver setting, used only to find a block's local day for one_block_per_day.
- Soft constraints only change the CP-SAT score, in the preferences tier. Their weight is scaled by 100 and rounded, since CP-SAT takes integer coefficients. A hard Constraint of a kind the solver does not support is an error rather than silently ignored.

**Constraint kinds**

| Kind | Params | Meaning |
| --- | --- | --- |
| time_preference (soft only) | windows[] (UTC), mode (prefer or avoid, default prefer), targets | Penalty: a block's minutes outside the windows (prefer) or inside them (avoid), times weight, so a block that half fits gets half the penalty. Authored as ranges[], each with weekdays[] plus local start_time and end_time (one range may be written at the top level instead). All ranges compile into one merged windows list for the horizon outside the solver, like presets, so a block only has to fit any one range. Days no range lists count as outside |
| rest_between (soft only) | min_gap_days (default 1), targets | Two sessions of the same matching item should have at least min_gap_days free local days between them; the same day counts as too close. Each pair too close costs the shorter session's length times weight, so a missed rest day weighs about as much as one session at a non-preferred time. Kept blocks that count as done work (done, partial, locked) are sessions too, so the rest re-space around a session that moved |
| daily_limit (hard only) | max_min, optional weekdays[] (default every day) | Scheduled minutes on each matching local day stay at or under max_min. Every block counts toward the day it starts on, fixed events included. If kept blocks alone are over, nothing more is placed that day rather than the week failing |

Soft kinds target items with item_ids[] and series_ids[] (both empty means every item). A series id covers every occurrence, so a rule keeps working when next week's occurrence gets a new item id. An unknown item id is an error. In a week file, `items = [titles]` names items or series.

Other hard kinds are rejected until supported; other soft kinds are ignored for now.

**Two modes.** Local push (instant, predictable, for drag and drop) and full re-solve (better overall layout, on demand or after falling behind). I may first write a simple backtracking search by hand to learn the problem, then switch to CP-SAT.

**Many arrangements can tie for best.** The solver should not just return one answer. It returns a handful of good options that differ in a meaningful way, and I step through them.

- After finding an arrangement, add a rule that the next one must differ (for example, at least 2 blocks on a different day), then solve again. Repeat for 3 to 5 options.
- This avoids near-duplicates that only shift a block by 15 minutes.
- Ties break toward stability first (closest to the current schedule), then earlier in the day.
- Each option shows what changed versus the current schedule, highlighted.

**Previewing an arrangement.** The week view compares an option with the current plan instead of drawing every old position at once.

- A Current plan / Option toggle flips the same week grid, so unchanged blocks stay put and changed ones jump.
- Each changed block has an orange outline and a tag with an arrow in the direction it moved: "From 6:00pm" in the option, "To 4:30pm" in the current plan. The day shows only when it changes ("From Thu 4:30pm"), and cross-day arrows point left or right.
- A changes list in the banner has one row per change. Selecting a row or a block shows that change's other spot as one dashed outline ("Was here" or "Moves here"), so only one old spot is on screen at a time.

**Manual moves lock blocks.** Dragging a block places it there and locks it. Locked blocks act as pinned for later solves, so the solver plans around my choices. Unlock to hand the block back to the solver.

## Data model

Four core entities (Item, Block, WorkFrame, Constraint), plus Series for recurrence after Milestone 1, all keyed by UUID, all times stored in UTC and converted only for display.

| Entity | Fields | Notes |
| --- | --- | --- |
| Item | id, title, flex_preset, preset_params (JSON), windows[] ({start, end}), checkable, estimate_min, deadline, parent_id, depends_on[], max_chunk_min, one_block_per_day (bool, default false), on_miss (reschedule / catch_up / skip / ask), catch_up_of, series_id, occurrence_date | windows[] is generated from the preset; the solver reads only windows. Subtasks are items with a parent_id. catch_up_of is the id of the missed Block. series_id and occurrence_date (local date) are set only on occurrences of a Series, and no two items share the same pair |
| Block | id, item_id, start, end, locked, status (planned / done / partial / missed / unanswered), completed_at, actual_min | Many blocks per item; locked = placed by hand, solver must keep it |
| WorkFrame | id, name, weekdays[], start_time, end_time, timezone | Default source of windows for flexible presets. start_time and end_time are local times in timezone (an IANA name); end before start means the frame crosses midnight, and weekdays[] names the day it starts |
| Constraint | id, kind, params (JSON), weight, hard (bool) | New rule types need no schema change |
| Series (after Milestone 1) | id, title, rule, timezone, start_date, end_date, skipped_dates[], template (flex_preset, preset_params, estimate_min, deadline_time, checkable, on_miss, max_chunk_min, one_block_per_day) | A repeat rule plus an item template; each occurrence is a normal Item. See Recurrence |

**Rules**

- Never use array indexes as identity; sync, undo and stability all depend on stable ids
- Slot size (default 15 min) is one setting, not hardcoded
- Store actual completion times from day one; estimate learning needs that history

## Recurrence

Built after Milestone 1 (model and expansion in the solver package; the solver itself does not change). A Series is a repeat rule plus an item template; each occurrence becomes a normal Item.

**Series fields**

| Field | Meaning |
| --- | --- |
| id, title | As on Item |
| rule | freq (daily or weekly), interval (every N days or weeks), weekdays[] (weekly only). Weekly intervals count Monday-starting weeks from start_date |
| timezone | IANA name; occurrence dates and template times of day are local to it |
| start_date, end_date | First and last local date the series can occur on (end_date optional) |
| skipped_dates[] | Local dates that never get an occurrence |
| Template: flex_preset, preset_params, estimate_min, deadline_time, checkable, on_miss, max_chunk_min, one_block_per_day | Copied onto each occurrence. preset_params holds times of day only, never fixed dates; deadline_time is a local time of day on the occurrence date |

**Occurrences**

- Each occurrence is an Item with series_id and occurrence_date. No two items share the same (series_id, occurrence_date) pair.
- Occurrences are created only for the week being planned, before preset compilation. Creating them is idempotent: running it twice creates nothing new.
- Template values are copied once, when an occurrence is created. Editing a series changes future occurrences only.
- An existing occurrence is edited directly. That is how a one-off moved meeting is handled.
- Skipping an occurrence adds its date to skipped_dates, so it is not created again.

**Template params per preset** (times of day only; the occurrence date fills in the day)

| Preset | Template params | Occurrence gets |
| --- | --- | --- |
| Exact time | start_time, end_time | start and end on the occurrence date, in UTC (end before start crosses midnight) |
| Any time on a day | none | day = occurrence date |
| Time range on a day | start_time, end_time | the same, plus day = occurrence date |
| Any of these days | weekdays[], optional start_time and end_time | unchanged |
| Any time before a deadline | none; deadline_time required | deadline = occurrence date at deadline_time |
| Custom | not allowed | Painted windows are fixed dates; a weekday-pattern version can come later if needed |

**Patterns**

| Pattern | How it is modeled | Example |
| --- | --- | --- |
| Fixed weekly event | Weekly rule, Exact time preset | CS 70 lecture, Tue and Thu 11am |
| N times a week | One weekly occurrence (weekly rule on Monday) with an "any of these days" preset, estimate = N sessions, max_chunk_min = one session, and one_block_per_day set so sessions land on different days | Gym 3x a week: estimate 3h, max chunk 1h, one block per day |

**Links to other features**

- Catch-up items take their deadline from the series' next occurrence (for example, before the next lecture).
- Estimate learning can average actual time per series.
- The rule format stays a subset of iCalendar RRULE (FREQ=DAILY or WEEKLY, INTERVAL, BYDAY, UNTIL, COUNT, WKST=MO), so a Google Calendar import maps across. COUNT converts to end_date on import; this is exact because iCalendar counts occurrences before removing excluded dates, just as a fixed end_date does. Weekly without BYDAY uses the start date's weekday. Anything else (monthly, BYMONTHDAY, BYDAY=1MO and the like) is rejected.

## Architecture and foundational decisions

Keep the core data model and the solver interface clean; let everything around them stay scrappy.

_(Architecture diagram: see the live PRD.)_

The solver takes tasks, blocks, frames and constraints and returns placements. It has no database or UI code, so it can be tested alone and swapped out later.

**Get right now**

- Solver separated from everything else, as a pure function
- UTC storage, local time only at display
- Task vs block split in the data model
- Stable UUIDs on everything
- Completion history saved from the start

**Fine to keep scrappy**

- UI and styling (will be rebuilt once I know how I use it)
- Auth, sync, multiple devices (local SQLite first)
- Performance (data is tiny)
- Extra constraint types (the `kind` field makes them cheap to add)

**Stack (decided: PWA)**

| Layer | Choice | Why |
| --- | --- | --- |
| Frontend | React + TypeScript (Vite), installable as a PWA | One codebase on iOS, Mac and Windows; fastest iteration; web React is the most useful skill for internships |
| Solver | Python service (FastAPI + OR-Tools CP-SAT) | CP-SAT has a first-class Python API; stays a pure function behind an endpoint |
| Storage | SQLite first, Supabase later | Local and simple until sync matters |
| Escape hatch | Capacitor wrap or React Native for the phone | Only if PWA notifications or widgets fall short; components and logic mostly carry over |

**Risk to test early:** check-in notifications on iPhone. They work for a PWA added to the home screen, but are more limited than native.

**Milestones** (in order; each one is usable before the next starts)

1. Solver package: the data model and solver as a Python package with tests. Feed in this week's items, print the schedule. Done.
2. Read-only week view: a FastAPI endpoint loads a week file and returns the solved schedule as JSON, and a React + TypeScript + Vite page shows it as a read-only week grid. No database, no editing, no check-ins.
3. Storage and adding items: SQLite, and creating items in the app instead of a week file.
4. Recurrence in the app: series stored and created or edited in the app. The Series model and its expansion are already built in the solver package.
5. Check-ins and on-miss policies: Yes / Partly / No when a checkable block ends, then reschedule, catch-up, skip or ask.

## Open questions and decision log

**Open questions**

- [ ] Name for the app
- [ ] rest_between sees only this week's input, so last Sunday's session does not stop one on Monday. Pass recent done blocks from the previous week, or a rule of its own?
- [ ] Balance only limits the fullest day; should a second term even out the other days too? Revisit if real weeks look uneven

**Decision log** (newest first)

| Date | Decision |
| --- | --- |
| Nov 14, 2026 | Stopgap until Milestone 3: the API caches solved weeks on disk (solver/cache/, gitignored), keyed on week_start, the week file's bytes and a solver version. The version hashes every .py file in the package plus the OR-Tools version, since the parser and response models shape the cached JSON too, so nothing needs a manual bump. A cache file that fails to load or validate is a miss, and errors are not cached. Cause of the 10 s loads: on the real week CP-SAT finds the optimum quickly but cannot prove it with one worker, so it stops at the time limit (FEASIBLE, a gap of 14 in the lowest tier). solve() now reports that status. A stopping rule comes next |
| Nov 14, 2026 | Read-only week page in web/: the week comes from ?week= (default this week's Monday), with previous and next arrows. Times show in the week's own timezone, not the browser's, using Intl with no date library. A block that crosses midnight is split into one piece per day. Work frames are shaded, fixed events and placed work look different, and the grid shows all 24 hours, scrolled to the earliest block. Vite forwards /api to the local API in development, so no CORS setup |
| Nov 14, 2026 | Week API: GET /api/weeks/{week_start} lives in the solver package as mycal.api, a caller like the demo. It returns week_start, timezone, feasible, blocks (id, item_id, title, start, end, fixed), frames (the week's work-frame time as merged UTC windows) and unscheduled items. All times are UTC; the page converts to the week's timezone for display. Only a valid date reaches the file lookup. A week that cannot be solved is still 200 with feasible false. It listens on 127.0.0.1 only. Ids come from the week file load, so they are new on each request until storage arrives |
| Nov 14, 2026 | Milestones written down: 1 solver package (done), 2 read-only week view, 3 storage (SQLite) and adding items in the app, 4 recurrence in the app, 5 check-ins and on-miss. Milestone 2 stays small: one endpoint and a read-only grid, no database, editing or check-ins |
| Nov 14, 2026 | A time_preference takes several ranges ("gym 6-7pm or 9-10pm on weekdays, around 1pm on weekends"). They merge into one windows list when compiled, so the solver is unchanged. Two separate prefer rules were the workaround, but a block in one range was still penalized by the other |
| Nov 14, 2026 | Rest days built as the soft rest_between Constraint kind, in the preferences tier. Rest is counted per item (an "N times a week" series has one occurrence per week, so this covers gym), and done or locked sessions count so a moved session re-spaces the rest. Sessions from the previous week are not seen yet (see Open questions) |
| Nov 14, 2026 | Time preferences built as the soft time_preference Constraint kind (prefer or avoid a local time range). Soft constraints get a new score tier between spread and balance, so a written preference beats a light busiest day. Local times compile to UTC windows outside the solver, and constraints target item or series ids so weekly occurrences stay covered |
| Nov 14, 2026 | "Earlier in the day" becomes "earlier in the frame": offsets count from the start of the work-frame occurrence holding the block, not local midnight, so a 12pm to 2am frame prefers 12pm over 12am. Sunday's overnight frame keeps its real start, so Mon 12am is late, not early. Starts outside every frame fall back to the item window's start |
| Nov 14, 2026 | Hard daily limits built as the daily_limit Constraint kind in both engines. Everything on the day counts, including fixed events; limits are by weekday only (a dates param can come later); soft limits are rejected for now. Kept blocks over a limit close that day instead of making the week infeasible |
| Nov 14, 2026 | Days with no work frame stay out of balance. Only explicitly placed items can land there, since flexible windows come from work frames, so the effect is small |
| Nov 14, 2026 | Tie-breakers after stability are settled by the CP-SAT score order: spread an item across days, then a light fullest day, then earlier in the day. Revisit when time preferences are added. Hard daily limits move from open questions to Features (v2) |
| Nov 14, 2026 | The demo week file supports [[series]] tables, written as an RRULE string plus template fields, expanded for the week before compiling. RRULE instead of separate fields avoids a clash with the "any of these days" weekdays param and reuses the import parser |
| Nov 14, 2026 | Recurrence built: Rule (daily or weekly, interval, weekdays), ItemTemplate and Series, with expansion into occurrence Items outside the solver. Custom is not allowed in a series template (fixed dates). RRULE COUNT is accepted and converted to end_date. "N times a week" series anchor on Monday |
| Nov 14, 2026 | Balance compares how full each day is relative to its work frames, not raw hours, so a shorter weekend frame gets proportionally less work. Days with no work frame are left out for now; evening out the other days and hard daily limits are open questions |
| Nov 14, 2026 | CP-SAT is the default engine and scores arrangements in strict priority order: stability, spreading an item's blocks across days, a light busiest day, then earlier in the day. Tier weights are computed from the size of the week instead of hand-tuned, so the order always holds |
| Nov 14, 2026 | CP-SAT engine added behind solve() alongside backtracking, sharing the same problem setup and tests. It runs with one worker and a fixed seed so the same week always gives the same schedule, stops at a time limit (default 10s), and raises an error if time runs out before any arrangement is found instead of reporting the week as infeasible |
| Nov 14, 2026 | Milestone 1 demo reads a TOML week file (local times in its timezone, dependencies by title) and prints the schedule by day. Only a made-up example week is committed; real weeks stay in a gitignored folder because the repo will be public |
| Nov 14, 2026 | First solver is hand-written backtracking behind solve(); CP-SAT comes later behind the same interface. Chunks split evenly by slots, an item with no estimate fills its single window, and the home timezone is a required solver setting. See Solver input rules |
| Nov 14, 2026 | "Blocks on different days" is a per-item flag, one_block_per_day, off by default and copied from a series template (gym sets it, homework does not). When on, it is a hard constraint; otherwise only the soft spread-out penalty applies. An always-on rule would make a problem set due tomorrow with 4h left infeasible |
| Nov 14, 2026 | Recurrence design (build after Milestone 1): a Series entity with a repeat rule and an item template; occurrences are normal Items with series_id and occurrence_date, created idempotently for the planned week before preset compilation. Template values copy once; series edits affect future occurrences only; skips go in skipped_dates. "N times a week" is one weekly occurrence split into sessions. Rules stay a subset of iCalendar RRULE. Replaces the open question on recurring items |
| Nov 14, 2026 | Presets compile to windows for a planning horizon using my home timezone; params per preset are in the Preset params table. Exact windows are never cut short. Recurring items are deferred (see Open questions) |
| Nov 14, 2026 | A WorkFrame's weekdays name the day it starts, so a Fri 9pm to 1am frame belongs to Friday. Local times convert to UTC separately for each date, so frames keep their local hours across DST |
| Nov 14, 2026 | This file becomes the source of truth instead of the claude.ai doc. WorkFrame times are local times plus an IANA timezone (UTC times of day drift across DST); a frame whose end is before its start crosses midnight. catch_up_of holds the missed Block's id |
| Nov 13, 2026 | Arrangement preview compares against the current plan: a toggle on the same grid, From or To tags with a direction arrow (day shown only when it changes), a changes list, and one old spot shown at a time. Always-on dashed strips for old positions were dropped because they do not scale past a few moves |
| Nov 13, 2026 | Prototype is a clickable canvas of five screens; earlier Week versions are kept (v1 to v4) so design choices stay traceable |
| Nov 13, 2026 | Stack: React + TypeScript PWA, with the solver as a Python (FastAPI + OR-Tools) service |
| Nov 13, 2026 | Re-planning runs only when I press the button, not automatically |
| Nov 13, 2026 | Slot size is 15 minutes |
| Nov 13, 2026 | An unanswered check-in counts as missed after a few hours, but can still be marked done later |
| Nov 13, 2026 | Flexibility is a dropdown of presets plus Custom; every preset compiles to allowed windows, the solver's only input |
| Nov 13, 2026 | Three flexibility levels: pinned, day-locked, flexible (now generalized into presets) |
| Nov 13, 2026 | Solver offers several good arrangements to step through; manual moves lock blocks |
| Nov 13, 2026 | One check-in flow plus a per-item on-miss policy handles falling behind, missed lectures and skipped habits |
| Nov 13, 2026 | One Item type with flags (pinned / flexible, checkable) instead of separate event and task types; Blocks stay separate |
| Nov 13, 2026 | Build my own planner as a project instead of switching to TickTick |
| Nov 13, 2026 | Solo scheduling only; group availability is out of scope for now |
| Nov 13, 2026 | Separate tasks from blocks in the data model |
| Nov 13, 2026 | Solver as a pure function; start with the data model and solver before UI |
