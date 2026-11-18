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
| Work frame | A window where flexible blocks are allowed to live, unless the item gives its own time range | Weekdays 9am to 6pm |
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
| Exact time (pinned) | Lecture, Tue 11am to 12:30pm | One window exactly the item's length, kept at its real times even off the slot grid (a 9:10 class stays at 9:10) |
| Any time on a day | Lab, sometime Wednesday | That day's work frame |
| Time range on a day | Call home, Thu 5 to 9pm | That range on that day |
| Any of these days | Gym, Mon, Wed or Fri | The work frame on each chosen day (optional time range) |
| Every one of these days | Piano, 30 min every day Mon to Fri | The same as any of these days, cut at local midnight, with one session on each chosen day that is still open |
| Any time before a deadline | Write code, by Friday | Every work frame from now until the deadline |
| Custom | Anything else | Paint the allowed time on a week grid |

**Preset params.** What `preset_params` holds for each preset. Local dates and times use my home timezone, which is passed in when presets are compiled. Windows are compiled for a planning horizon (usually now to the end of the week), clipped to it, and merged where they overlap or touch.

| Preset | preset_params | Notes |
| --- | --- | --- |
| Exact time | start, end (UTC) | Never cut short or rounded; dropped only if entirely outside the horizon |
| Any time on a day | day (local date) | Every work frame that starts on that day |
| Time range on a day | day, start_time, end_time (local) | End before start crosses midnight |
| Any of these days | week (local date of its Monday), weekdays[], optional start_time and end_time | Only that week: the time range if given, else the work frames that start on those weekdays of that week. Week files fill week from week_start, and the New item dialog from the week being viewed |
| Every one of these days | the same as any of these days, plus every_day = true and session_min | Stored as an "any of these days" item. Windows are cut at local midnight, so each lies inside one chosen day. The item's work is worked out when it is planned (see the decision log), not read from estimate_min |
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

**How check-ins work (Milestone 7)**

- A checkable block asks for a check-in once it ends. The week page lists pending check-ins in an orange banner (refreshed every minute) and a past block's popover can check in or change an answer. Push notifications wait for the PWA install.
- Yes sets the block to done with actual_min = its length. Partly asks how much got done, sets the block to partial with actual_min = that amount, and runs the on-miss policy on the rest. No sets it to missed and runs the policy on all of it.
- A check-in left unanswered for 4 hours becomes unanswered and counts as No. An Ask item keeps waiting, with nothing moved, until it is answered. Any answer can be changed later, which undoes the earlier result (a catch-up item with no finished sessions is deleted).
- The solver does not change. Each block records the policy that ran on its missed part (`missed_action`), and that decides how many minutes of the item's work the block still covers: a rescheduled part covers nothing, so the work goes back to the pool and is placed after now; a skipped or caught-up part covers its minutes, so the item is settled (the work moved to the catch-up item, or was dropped); a part waiting on Ask covers its minutes until answered, so nothing moves meanwhile.
- Reschedule needs somewhere to go. An exact-time item can't move, so its choices are Catch up, Skip and Ask, and an exact item set to Reschedule behaves as Skip. An "every one of these days" item can only use what is left of the same day. An "N times a week" item needs another day left in its week; if too few are left, it gets fewer sessions (see below).
- A catch-up item is a flexible item with catch_up_of = the missed block, titled "Catch up: <title>" (renamable). Its estimate is the missed minutes (1.25x for exact-time items, which are usually recordings), its deadline is the start of the series' next occurrence, else the deadline of an item that depends on it, else 7 days after the missed block, and its windows are the normal work frames. It is checkable and reschedules when missed.
- An "N times a week" item that needs more days than are left in its week (a missed session, or an occurrence created partway through its week) gets one session per day that is left instead of making the week unplannable. A change that causes it (a check-in, adding or editing) asks first: "Workout will get 2 of 3 sessions this week (only Thu and Sat are left). Accept?". When only viewing a week causes it, the week is planned that way and a banner says so until acknowledged.
- New items are checkable by default when they have an estimate, not when they are exact-time (meetings); a lecture can be switched on. The item dialogs show "Check in when it ends" and "If missed".
- An item with check-in history is archived instead of deleted: its finished blocks stay as history, its planned blocks are removed and it leaves the week view. Items without history are still deleted. For a series, This and All archive the occurrences with history and delete the rest.
- Finished blocks stay in the week grid: done ones crossed out, missed ones marked missed. The Today view and its daily bar come later.

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
4. Earlier week: each block's minutes times how many weeks after the first week of the solve it starts in. It only picks the week; within a week the tiers below pick the day. Work lands in the earliest week with room and spills into a later week only when it has to. Below preferences, since a rule I wrote beats "this week rather than next"; above balance, so a lighter day next week never pulls work out of this week. A one-week solve has nothing to choose here
5. Balance: the fullest local day, measured as scheduled minutes divided by that day's work-frame minutes, kept blocks included. A short weekend frame gets proportionally less work. Days with no work-frame time are left out
6. Earlier in the frame: how far into its work-frame occurrence each block starts, counting the whole occurrence even when it began before the planning week. A block outside every frame counts from the start of its item window

Each tier's weight is at least the most all lower tiers can add up to, plus the slack, plus one. The slack is earliness_slack_min (default 15) per flexible block, in slots, and CP-SAT stops once it proves its plan is within the slack of the best. So tiers 1 to 5 are always exact, and only tier 6 can come out worse, by at most the slack summed over the week. Proving the exact tier-6 optimum can take minutes on a real week, because many arrangements tie in the tiers above

Buffers come later as Constraint kinds. The backtracking engine does not score; it returns the first valid arrangement.

**Objective.** Minimize the weighted sum of soft penalties, subject to all hard constraints. No feasible solution means a deadline is at risk, which triggers the feasibility warning.

**Solver input rules**

- Kept blocks and fixed events: locked blocks and completion history (any status other than planned) are returned unchanged, and nothing may overlap the slots they touch, rounded outward. Unlocked planned blocks are the current plan and get re-placed.
- Remaining work: estimate minus time already covered (done and partial blocks count actual_min, or their length if missing; locked planned blocks count their length).
- Lengths are stored as typed. The planner rounds them to the slot grid in effective_item: estimate up, longest session down (at least one slot), an every-day session up, so 20m is planned as 30m and a 20m longest session as 15m. The stored value never changes.
- Chunks: remaining work is split into the fewest near-equal blocks no longer than max_chunk_min (5h with a 2h max is 105 + 105 + 90 min). The solver still rounds remaining work up to whole slots, for callers that don't round first.
- An item with no estimate is a fixed event (how Exact items are placed): one block at its window's real times, never moved or rounded to the slot grid, and returned with those times. For other work it blocks every slot it touches, rounded outward (9:10 to 10:00 blocks 9:00 to 10:00). Two fixed events, or a fixed event and a kept block, clash only if their real times overlap, so 9:00 to 9:10 and 9:10 to 10:00 can both be planned. No estimate with several windows is an error. An item with no windows is skipped and stays in the task list.
- Stability: the item's current blocks, in start order, each pass their id and start on to a chunk of their own length when one is left (else the next chunk), and the engines try that old start first. Pairing by position alone would stretch a shorter session that was placed first.
- For flexible work, window edges off the slot grid are rounded inward. Slots are counted from the Unix epoch in UTC.
- My home timezone is a required solver setting, used only to find a block's local day for one_block_per_day.
- Stopping is deterministic: one worker, a fixed seed, the gap limit above, and a deterministic work limit (CP-SAT's max_deterministic_time, setting work_limit, default 10) as the backstop. There is no wall-clock limit, so the same input and OR-Tools version give the same plan on any machine. The status says how it ended: OPTIMAL (within the slack), FEASIBLE (stopped by the work limit) or INFEASIBLE.
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
| Any of these days | weekdays[], optional start_time and end_time | week = the Monday of the occurrence date |
| Every one of these days | weekdays[], every_day, session_min, optional start_time and end_time | week = the Monday of the occurrence date |
| Any time before a deadline | none; deadline_time required | deadline = occurrence date at deadline_time |
| Custom | not allowed | Painted windows are fixed dates; a weekday-pattern version can come later if needed |

**Patterns**

| Pattern | How it is modeled | Example |
| --- | --- | --- |
| Fixed weekly event | Weekly rule, Exact time preset | CS 70 lecture, Tue and Thu 11am |
| N times a week | One weekly occurrence (weekly rule on Monday) with an "any of these days" preset, estimate = N sessions, max_chunk_min = one session, and one_block_per_day set so sessions land on different days | Gym 3x a week: estimate 3h, max chunk 1h, one block per day |
| Every day | An "every one of these days" item: one session of session_min on each chosen day | Piano 30 min, Mon to Fri |

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
2. Read-only week view: a FastAPI endpoint loads a week file and returns the solved schedule as JSON, and a React + TypeScript + Vite page shows it as a read-only week grid. No database, no editing, no check-ins. Done.
3. Storage and adding items: SQLite, and adding and deleting items in the app instead of a week file. Week files are imported once. Done.
4. Edit items: change an existing item's fields from the page, then re-plan. Done.
5. Work frames and rules in the app: view, add, edit and delete work frames and constraints (daily_limit, time_preference, rest_between) from the page, then re-plan. Settles how imports treat these app edits. Week files stay for importing. Done.
6. Recurrence in the app: series stored and created or edited in the app. The Series model and its expansion are already built in the solver package. Done.
Between 6 and 7: keyboard shortcuts in the app (see the decision log, Nov 17). Done.
7. Check-ins and on-miss policies: Yes / Partly / No when a checkable block ends, then reschedule, catch-up, skip or ask. Also fewer sessions for an "N times a week" item short of days, archiving items with history, and the check-in fields in the item dialogs. See How check-ins work. Changes still re-plan and save right away.
8. Preview and accept re-plans: every change (adding, editing or deleting an item, a check-in, a frame or rule edit) makes a proposed plan instead of saving one. The week shows it in the compare view (see Previewing an arrangement) with Accept and Discard. Discard keeps the old plan, and a new item or rescheduled work stays unscheduled until a plan with it is accepted. A week planned for the first time needs no Accept.

## Open questions and decision log

**Open questions**

- [ ] After Milestone 7: retire week file imports (TOML) now that items, rules, frames and series are all made in the app, or replace them with a Google Calendar or .ics import. The RRULE parser and the source and --replace handling would carry over; the TOML format would not. examples/week.toml stays as test data either way
- [ ] rest_between sees only this week's input, so last Sunday's session does not stop one on Monday. Pass recent done blocks from the previous week, or a rule of its own?
- [ ] Follow-up: count the span cap from now instead of the current week's Monday, so an add on a weekend still looks two weeks ahead (today a Saturday add's span is that weekend plus one week)
- [ ] Follow-up: give an item cut off by the span cap a pro-rata share of its remaining work in the capped span, through a reduced estimate in the planner (solve() unchanged), so long-deadline work starts early instead of only in the 2 weeks before its deadline
- [ ] Later (left out of Milestone 7): partial placement. Let an item place less than its remaining work (optional chunks, a top score tier per unplaced minute, and SolveResult reporting unplaced minutes per item), so an item waiting on a broken week gets as much work as fits instead of none. It changes solve()'s outputs
- [ ] Follow-up: 5-minute slots would allow 10m lengths, but cost about 4.6x the deterministic time per solve. Measured Nov 15, 2026 on a stand-in (shifted copies of the template week, lighter than the real weeks): a 2-week span went from 1.37 to 6.28 units, and five weeks from 2.96 to 14.43 in total, all OPTIMAL. The real weeks needed 5.5 units per 2-week span at 15-minute slots, so 5-minute slots would likely land around 25, over the work limit of 10 (FEASIBLE or a planner timeout). Re-measure on the real week files before changing slot_min
- [ ] Fixed events that really overlap (double-booking, like two classes at the same hour) still make the week unplannable. Consider planning the week anyway with a warning instead
- [ ] Balance only limits the fullest day; should a second term even out the other days too? Revisit if real weeks look uneven

**Decision log** (newest first)

| Date | Decision |
| --- | --- |
| Nov 17, 2026 | Milestone 7 plan (details in How check-ins work). The solver is unchanged: a block's new missed_action field (the policy that ran on its missed part) sets the minutes it covers, which is how reschedule, catch-up, skip and ask reach the plan. Unanswered after 4 hours counts as No. New items are checkable by default unless exact-time. An "N times a week" item short of days gets fewer sessions after a confirm, or a banner when viewing caused it, which closes that open question. Items with check-in history are archived, not deleted. The popover says "6h placed, more than the 4h estimate" when more is placed than the estimate, with finished sessions counting their real minutes, which closes that open question. Left out: the Today view and daily bar (later) and partial placement (stays open) |
| Nov 17, 2026 | Milestone 8 added: preview and accept re-plans. Re-planning after a change waits for Accept in the compare view, which replaces the Nov 13 rule that re-planning runs only on a button press (since Milestone 3, changes re-plan and save right away, and they keep doing so through Milestone 7). Accept went in Milestone 8, not 7, because accepting needs the compare view to show what changed |
| Nov 17, 2026 | Milestone 6 (recurrence in the app) is done: Kaden checked on the real week that a repeating item can be created from the page, shows in every week it repeats in, and can be changed or deleted (This and All). Keyboard shortcuts are done too. Milestone 7, check-ins and on-miss policies, is next |
| Nov 17, 2026 | Keyboard shortcuts, built before Milestone 7 as a small step of their own: 1 and 2 switch tabs, N adds an item, the arrows or K and J move a week, T goes to this week, E edits and Delete (or D) deletes the block under the mouse (or with keyboard focus) or the one whose popover is open, Delete always through the confirm step, F and R add a frame or a rule on the Frames and rules page, and ? lists them. Tabs use numbers so R can mean a new rule. Single keys, ignored while typing or with a dialog open, and never taken with Cmd, Ctrl or Alt. Kept as pure logic (web/src/shortcuts.ts) with each component acting on its own keys. Spec in web/DESIGN.md, Keyboard shortcuts |
| Nov 17, 2026 | The app is called MyCal wherever it is displayed (the page title, the favicon). Code names stay lowercase: the mycal package, the mycal-api and mycal-import commands, and the folder. Settles the open question on a name for the app |
| Nov 17, 2026 | A one-off item can be made to repeat from its edit dialog, which shows the Repeats field (on Never) for one-off items, though not for occurrences. POST /api/items/{id}/repeat takes the series fields and makes the item the series' occurrence on the item's own date (its day, its due date, or its week's Monday for a days item), so it keeps its id and sessions, and done work stays (rule 8). If it hasn't started and the rule falls on that date, it is rebuilt from the new template; otherwise it is kept as it is and marked hand_edited, so later series edits leave it alone. The series may start on the item's own date even if it has passed; any other start must lie ahead. An occurrence is refused ("It already repeats"). It re-plans like adding a series. recurrence gains occurrence_on, building one date's occurrence whether or not the rule falls on it |
| Nov 17, 2026 | Repeating items in the app (Milestone 6). The New item dialog gets a Repeats field (Never by default; Weekly or Daily, every N, on chosen days, from a start date to an optional end date), drafted in web/DESIGN.md under Repeat for Kaden to review. POST /api/series takes the dialog's fields plus the rule and builds the template from the first occurrence through the same checks as a one-off item, so a series is refused for the same reasons. GET, PUT and DELETE /api/series/{id} edit and end it. Adding or editing a series re-plans like a work frame change (this week through the last planned week, all or nothing, refused if a week stops fitting). Editing rebuilds occurrences that haven't started and weren't edited by hand; editing an occurrence directly sets hand_edited. Deleting one occurrence (This one) adds its date to skipped_dates, since the planner would otherwise create it again. Ending a series (The series) deletes the occurrences that haven't started; if none are left it deletes the series, otherwise end_date becomes the last date left. An "any of these days" or "every one of these days" series repeats weekly on Monday, starting on the Monday of the start date's week. The week response marks occurrences of stored series with series_id and lists how each of the week's series repeats, for the popover's Repeats line and its This one / The series choice |
| Nov 17, 2026 | The planner creates occurrences. Before planning (and before a view works out its span, so a repeating deadline due next week can stretch it), every stored series gets its missing occurrences for the weeks being planned. An occurrence is created only if it still has a day from today on: its date, or for a days item dated its Monday, any day of its week, so this week's Gym still comes on a Wednesday. Each takes its series' source. Rule targets list stored series too (by the series' own title), so a new series can be named before it has occurrences, and leave out series that have ended unless a rule names them |
| Nov 17, 2026 | Imports keep a series already stored, replacing the Nov 16 plan to refuse them. A week file usually repeats last week's series, and refusing it would also break the file's rules that name the series by title. Now a file's series whose title is already stored from another file or the app is kept as stored, the summary says so, and the file's rules point to the stored series, as later imports already treat work frames. The import still adds that file's own series (with this week's occurrences) and replaces them on --replace, keeping their ids so rules made in the app still name them. Week files only need to keep working for the files that exist: once series are made in the app, they are no longer needed for anything new |
| Nov 16, 2026 | Series are stored (schema migration 5): a series table with the rule, skipped dates and template as JSON, and a source like items, so `--replace` can replace a file's series. Occurrences point to their series by series_id with no foreign key, since occurrences imported before this point to series that were never saved. Deleting a series takes every occurrence and its blocks; ending one (below) is a separate, softer change. Items gain hand_edited, set when an occurrence is edited directly; like source it lives only in the database, not on the model. A rule's series target counts as existing while the series is stored or any item still points to it, and a rule left with no targets is deleted as before |
| Nov 16, 2026 | Milestone 6 plan, settling its four open questions. Editing a series rebuilds future occurrences that haven't started, except ones edited by hand (hand_edited), which are kept, so a moved lecture stays moved. Deleting an occurrence offers This one (its date goes in skipped_dates and the occurrence is deleted) or The series (end_date becomes yesterday, occurrences that haven't started are deleted, past and done ones and the series itself stay, for completion history and rule targets). A series can't start in the past, and occurrences are created only for dates from today on, never filled in for past weeks. The planner creates the missing occurrences of every stored series for the weeks it plans, before compiling presets. Imports store a file's series (with the file as source) instead of only that week's occurrences, and an import whose series has the same title as a series already stored from somewhere else is refused, so two week files can't double a weekly class. The New item dialog gets a Repeats field defaulting to Never; Claude drafts the Repeat section of web/DESIGN.md for Kaden to review before building it |
| Nov 16, 2026 | Fix: an "every one of these days" series template accepts every_day and session_min, as the Template params table already said. The template check was not updated when the preset was added on Nov 15, so such a series was refused |
| Nov 16, 2026 | Rules are edited through the API (Milestone 5): GET /api/rules gives them in the dialog's terms (daily limits, then time preferences, then rest days, each in the order added; a file's single top-level range comes back as one range), GET /api/rules/targets lists what a rule can name (series first, then one-off items with work or blocks from this week on, plus any item a rule already names), and POST, PUT and DELETE /api/rules?week= re-plan like a work frame change. Rules are stored the way week files store them. A rule's kind can't change, and an edit keeps its weight and source, so --replace brings back the file's version. A daily limit has no targets and is rounded down to the slot grid like a longest session (never below one slot). Because stability is the top score tier, a new wish would never move work already planned, so adding, editing or deleting a time preference or rest-days rule first drops the planned sessions ahead of the items it covers (old and new targets), which are then placed again under the change; everything else stays put. A daily limit, like a work frame, moves only what it must. Rule targets stay as they are (no ids means every item; deleting a rule's last target deletes the rule). The Rule dialog makes "Every item" its own choice, so an empty pick never means everything by accident. Settles the open question on an explicit "all items" flag |
| Nov 16, 2026 | Work frames are edited through the API (Milestone 5): GET /api/frames lists them by first weekday then start time, and POST, PUT and DELETE /api/frames?week= return the viewed week. Frames apply to every week, so a change re-plans every week from this one through the last week with a plan or planned blocks (at least the planning span), all or nothing on an in-memory copy like adding an item, and is refused naming the weeks that would stop fitting. A week that already didn't fit doesn't count against it. Earlier weeks lose their plan marks and re-plan when next viewed. New frames use my home timezone |
| Nov 16, 2026 | Imports stop overwriting what the app edits. The timezone, slot size and work frames come only from the first import into an empty database; later imports leave them alone and say so, since they are now edited in the app. Engine settings (engine, work_limit, earliness_slack_min) never come from a file: they use the code's defaults, and schema migration 4 drops the values old imports stored (one database still had a work limit of 20). A file's items and constraints stay tied to it, so --replace still brings back the file's version of both, the file winning as before. Settles the open questions on engine settings from imports and on one rule for imports overwriting app edits |
| Nov 16, 2026 | New Milestone 5: work frames and rules (constraints) are viewed, added, edited and deleted in the app. It goes before recurrence because until now they could only be changed in a week file and re-imported, which also brings back the file's version of edited items. Recurrence moves to 6 and check-ins to 7. It also settles the open questions on how imports treat app edits to work frames, whether engine settings should come from week files, and the "all items" flag for constraint targets |
| Nov 15, 2026 | Constraint targets stay as they are: no item_ids and no series_ids means every item, and deleting a rule's last target deletes the rule, so it never turns into a rule for everything. An explicit "all items" flag was considered and put off: it only helps once rules can be edited in the app, where a leftover rule could be pointed at a new item. Until then a leftover rule would be invisible clutter. Milestone 5 also makes the case rare, since rules on repeating things name the series, which outlives any one week's occurrence. Settles the "decide before Milestone 4 or 5" open question |
| Nov 15, 2026 | The week response marks each block and Unscheduled item as editable or not, so the item details popover can disable Edit for Custom items without asking the server first |
| Nov 15, 2026 | Editing items through the API (Milestone 4). GET /api/items/{id} gives the stored item in the dialog's terms (local dates and times, lengths as typed, a days item's own week), plus its source and whether the dialog can edit it: Custom items, and flexible items with no estimate, can't be edited there. PUT /api/items/{id}?week= takes the same fields as adding and returns the viewed week. The item keeps its id and everything the dialog doesn't show (dependencies, checkable, on_miss, parent, series, source, and an imported item's deadline on a preset without one). A changed time, deadline or week must still lie ahead, but an unchanged one may have passed, so a past item's title or estimate can always be fixed; a fixed event that already started can't change its time. Sessions that already started or are done stay and count toward the work, and the rest is re-planned over the weeks of its current plan and the weeks the changed item can go in. Like adding, it's all or nothing on an in-memory copy, refused with the reason if a week that fit before stops fitting or the item's work can't all be placed. An edited imported item keeps its source, so importing its file again with --replace brings back the file's version (the file wins, as for deleted items) |
| Nov 15, 2026 | New item dialog: Add is enabled except while saving, replacing "Add is simply disabled" from the Nov 14 dialog entry. Pressing Add with errors sends nothing, shows every error at its field, and scrolls to and focuses the first one, since an error shown only in the top banner was far from its field on a tall form. The banner is kept for errors that aren't about one field, like "doesn't fit", and scrolls into view when it appears |
| Nov 15, 2026 | The week response includes slot_min, so the New item dialog can show the length the planner will use ("Planned as 30m") without hardcoding the slot size |
| Nov 15, 2026 | Lengths off the slot grid are allowed. Estimate, longest session and an every-day session are stored as typed, and the planner rounds them in effective_item: estimate up, longest session down (never below one slot), every-day session up. So 20m is planned as 30m, and a 20m longest session as 15m. Before, an off-grid every-day session was refused (API, week files and the planner), while estimates and longest sessions were rounded silently inside the solver. The week response reads items through effective_item, so its estimates are the planned lengths and the progress bar agrees with the blocks. The New item dialog shows "Planned as 30m" under a length that will be rounded, and never blocks Add. Slots stay 15 minutes, so a 10m length is planned as 15m (see the 5-minute follow-up) |
| Nov 15, 2026 | Fixed events keep their real times. An item with no estimate (an Exact item) is no longer a chunk on the slot grid but a pinned block at its window's real times, returned unchanged by solve(). Before, its window edges were rounded inward like flexible work: a 9:10 to 10:00 class was stored as 9:15 to 10:00, flexible work could overlap its first 5 minutes, a 9:10 to 9:20 event rounded to nothing and made the week unplannable, and two events that really overlapped could both be planned. Now, for flexible work, a fixed event blocks every slot it touches, rounded outward, as kept blocks already did; daily limits count its real minutes; and fixed events clash with each other or with kept blocks only on real times. Flexible work stays on the 15-minute grid. Berkeley classes start at :10 |
| Nov 15, 2026 | A time range overrides the work frames. On "Time range on a day", "Any of these days" and "Every one of these days", a range given with the item replaces the work frames instead of being cut to them, so a range outside work hours (piano 6 to 8pm) is placed there. Work frames are not a solver constraint: they only feed windows for presets without a range, plus the balance and earlier-in-the-day scores. Item windows stay hard. The New item dialog says so with an "Outside your work hours" hint that never blocks adding. This settles the contradiction between the Work frame definition (flexible blocks live in work frames) and the preset tables (the range is used instead of the frames), found when ranged items landed after 6pm |
| Nov 15, 2026 | "Every one of these days" items: the same length on every chosen day of one week (different lengths per day are separate items). Stored as an "any of these days" item with every_day and session_min in preset_params, and weekdays as picked. The solver never sees the flag. The planner (a caller) works out the item's work as of now with effective_item: what its kept sessions cover (done, partial, locked, or already started) plus one session_min for each open day, meaning a chosen day with no kept session and room for a whole session after now. It also sets max_chunk_min to session_min and one_block_per_day. So k open days give exactly k sessions of session_min, and "at most one per item per day" puts one on each. Windows are cut at local midnight so an overnight frame can't push a session onto the next, unchosen day. Everything that reads an item's remaining work (planning, waiting on broken weeks, the refused-add check, the week response's estimates) goes through effective_item, never estimate_min, because a stored estimate is out of date once a day passes. Leftover time never carries into another day or week: once a day passes it simply has no work. Adding is refused if no chosen day is open. Rule for Milestone 6: a session of an every_day item belongs to its day. Done, partial or missed, it never adds work to another day or week (on_miss acts as skip, a partial leaves no remainder, no catch-ups), and every read of remaining work keeps going through effective_item |
| Nov 14, 2026 | Item details popover built to web/DESIGN.md: blocks and Unscheduled rows open it, and "Delete item" deletes the whole item after an inline confirm. A delete runs in the page, not the popover, so closing the popover (Escape, a click outside) never stops it; when it finishes, the shown week updates only if it is still the one being viewed, and other weeks reload when viewed. A failure goes in the popover if it's still open, else in a page banner with a close button. One addition to the spec: "2h of 4h placed" also shows for a single session when work is waiting, since it says the item isn't all planned. Milestone 3 (storage and adding items) is complete with this |
| Nov 14, 2026 | Deleting an item (in the app, or by mycal-import --replace) also removes its id from every constraint's item_ids, in the same transaction. A constraint left with no targets is deleted, since no targets would mean every item. Found when deleting Gym left its rest and time-preference rules naming a missing item: the solver refuses unknown ids (on purpose, so a rule is never silently dropped), and every week after that failed to plan with a 500 |
| Nov 14, 2026 | Each block in the week response also carries session (its place among the item's blocks in every week, in start order), sessions, placed_min (the item's minutes placed so far, in every week) and estimate_min; unscheduled items carry sessions. This feeds the details popover's "Session 2 of 4 · 2h in all" or "2h of 4h placed". Requests that plan or write never overlap: the API holds one lock per process around each request. That holds while the API runs as one process; several workers would need a lock across processes. mycal-import runs outside it, but it clears every plan mark, so the next view re-plans |
| Nov 14, 2026 | A planner timeout is not "doesn't fit". When CP-SAT hits the work limit before finding any arrangement, the solver still raises (no proof either way) and the planner turns it into PlannerTimeout with nothing saved. The API answers 503 with a sentence: viewing keeps the week's old plan and leaves it unmarked so the next view tries again; adding changes nothing; deleting still deletes, and weeks that didn't finish re-plan when next viewed. Before this, a timeout was an unexplained 500 |
| Nov 14, 2026 | Weeks are planned together in spans of at most 2 weeks, in one solve, so work due in a later week can start earlier; the earlier-week tier keeps it in the earliest week with room. This closes the open question on work that couldn't spill over. Viewing a week plans it through the latest deadline week of the deadline items that can go in it; adding plans the item's last week and the week before; deleting plans the weeks its blocks were in. Only the first week of a span that fits is marked planned, so the next week re-plans when viewed and can take work due the week after. A deadline item due after a span's end is deferred in it: no windows, its blocks stay put. Known limit: work for a deadline more than 2 weeks away is only placed in the 2 weeks up to its deadline (see the pro-rata follow-up in Open questions). A span that doesn't fit is shortened from the end, first with every item it reaches required, then with items due after the shorter span deferred; the week after the longest span that fits is marked as unplannable on its own, keeping its old blocks, and planning resumes after it as a joint span. Items whose work waits on an unplannable week are listed in Unscheduled with a reason naming that week; items deferred by the cap are normal and aren't listed. Adding is refused if it breaks a week that fit before, or if the new item itself would be left waiting on an unplannable week; it is never stored unplaced. The cap of 2 and the work limit of 10 (down from 20) come from timing: on five imported weeks a 2-week span solved to OPTIMAL in 5.5 deterministic units, while 3 weeks or more hit the limit, and deterministic time ran 2 to 5 seconds per unit on those models, so 20 could mean almost two minutes of waiting |
| Nov 14, 2026 | Earlier week becomes score tier 4, between preferences and balance: deadline work lands in the earliest week with room and spills into a later week only when it has to. It counts weeks, not days, so it never piles work onto Monday. The reference week is the Monday of the earliest day any block could start on, worked out inside the solver, so solve()'s inputs and outputs don't change. This prepares planning several weeks in one solve, the fix for work that couldn't spill over |
| Nov 14, 2026 | New item dialog built to the Add item section of web/DESIGN.md. Where the spec is silent: the form opens on "Any of these days" with no days picked, dates default to today if it is in the viewed week (else its Monday), and the due time to 11:59pm. Field errors show once a field has been left, so Add is simply disabled before that. Fields that are hidden (the estimate for exact times, the one-session switch when there is one session) are never sent. After an add the page keeps only the returned week in memory, since a deadline item can change several weeks |
| Nov 14, 2026 | Adding and deleting items through the API. POST /api/items takes the dialog's local fields plus the viewed week (a days item belongs to it), validates them with messages the dialog can show, and saves the item as added in the app. It then re-plans the weeks the item can touch, earliest first: the week of its day or days, or every week from now to its deadline. Adding is all or nothing: it runs on an in-memory copy of the database and is refused with a 422 only if it breaks a week that fit before; a week that already didn't fit keeps its old blocks. DELETE /api/items/{id} removes the item and its blocks and re-plans the weeks they were in. Custom items can't be added yet |
| Nov 14, 2026 | The API serves weeks from the database. A week is planned the first time it's viewed and the result is stored, with a planned_weeks row (schema migration 3) so a planned empty week isn't mistaken for an unplanned one; importing clears every week's plan. Re-planning week W passes W's planned, unlocked blocks that start after now as the current plan; blocks that already started and blocks in other weeks go in as kept (locked copies), so they don't move but still count toward an item's remaining work. New blocks only go after now, but exact-time items compile for the whole week. A week that can't be planned is stored as infeasible and keeps its old blocks. Requests run one at a time, since the page prefetches neighbor weeks. Unscheduled now means a custom item with no windows painted. The stopgap disk cache is gone, and with nothing imported the API answers 404 |
| Nov 14, 2026 | The "Any of these days" preset takes a week param (the local Monday) and compiles only inside that week. With items stored in a database instead of one week file, a days item had no week and would be planned in every week forever. Week files fill it from week_start, series expansion from the occurrence's Monday, and the New item dialog from the week being viewed; templates still hold no dates. A missing week or one that is not a Monday is an error |
| Nov 14, 2026 | Week file import built (mycal-import). Until recurrence and a calendar import exist, a new week file is imported every week, so each import adds to the database. Items and constraints record their source (the file's name; NULL for things added in the app) in a source column, added by schema migration 2. Importing a file already in the database is refused unless --replace is given, and then only that file's items and constraints are replaced, with their blocks; other files' items and items added in the app are never touched. Saving an item or constraint again keeps its source. Settings and work frames describe me, not a week, so each import replaces them and the latest file wins. Series come in as that week's occurrences, and no blocks are imported. The whole import is one transaction, and the file is parsed fully before the database is touched |
| Nov 14, 2026 | SQLite store built (mycal.store): tables settings, items, item_deps (ordered), blocks, work_frames and constraints, with foreign keys on, so deleting an item takes its blocks, subtasks and dependency links. Moments are UTC ISO text with one fixed +00:00 suffix, so text order is time order and blocks can be listed by time range. preset_params and constraint params are JSON with tagged values for datetimes, dates, times, UUIDs and windows, so they load back exactly. Series are not stored yet (Milestone 5); imported occurrences keep series_id and occurrence_date, which stay unique as a pair. The database lives in solver/data/ (gitignored) |
| Nov 14, 2026 | Milestone 3 plan. Storage is SQLite through Python's built-in sqlite3 (no new dependency) in mycal.store, a caller like the API and the demo. Tables mirror the Data model, with UUIDs as text, times as UTC ISO strings and JSON for params; Item.windows is not stored but compiled when solving, and the schema is versioned with PRAGMA user_version. Week files are imported once (mycal-import; series come in as that week's occurrences). Plans are stored, so the stopgap disk cache goes; a week is solved on first view and re-planned after an item is added or deleted. When re-planning a week: its current planned blocks are the current plan (stability keeps them), planned blocks in other weeks and blocks that already started are passed as kept, and new blocks go only after now. The app adds and deletes items; editing becomes Milestone 4, which moves recurrence to 5 and check-ins to 6. The New item dialog is built to an Add item section the user adds to web/DESIGN.md |
| Nov 14, 2026 | The web UI follows web/DESIGN.md (from the prototype canvas) with colors, fonts and sizes in web/src/tokens.css: light theme only, Inter and Space Grotesk, 12-hour times. A block's text goes by its height in pixels: two lines from 40px (1 hour and longer), one line "Title · 2:00pm" from 20px (30 and 45 min), the title only below that (15 min). The grid first scrolls to the earliest block on any day, weekends included, minus 30 minutes, or the earliest work frame when there are no blocks |
| Nov 14, 2026 | CP-SAT stopping rule: a gap limit of earliness_slack_min (15) per flexible block, with tier weights rebuilt so each tier outweighs everything below it plus the slack, so only the lowest tier can come out worse. The wall-clock limit is replaced by a deterministic work limit (20). On the real week: 1.4 s, OPTIMAL, earliness 2 slots worse than the true optimum, where before it stopped at 10 s without proof. Smaller gaps (8 slots or less) never closed on that week, because the lower bound stays 14 below the optimum. CLAUDE.md gains the determinism rule |
| Nov 14, 2026 | Stopgap until Milestone 3: the week page keeps every week it fetched in memory for the session, so going back to a week is instant, and prefetches the previous and next week once the current one loads. Failed fetches are not kept, so a missing week is asked for again. The arrows already update the URL with pushState, without reloading the page |
| Nov 14, 2026 | Stopgap until Milestone 3: the API caches solved weeks on disk (solver/cache/, gitignored), keyed on week_start, the week file's bytes and a solver version. The version hashes every .py file in the package plus the OR-Tools version, since the parser and response models shape the cached JSON too, so nothing needs a manual bump. A cache file that fails to load or validate is a miss, and errors are not cached. Cause of the 10 s loads: on the real week CP-SAT finds the optimum quickly but cannot prove it with one worker, so it stops at the time limit (FEASIBLE, a gap of 14 in the lowest tier). solve() now reports that status. A stopping rule comes next |
| Nov 14, 2026 | Read-only week page in web/: the week comes from ?week= (default this week's Monday), with previous and next arrows. Times show in the week's own timezone, not the browser's, using Intl with no date library. A block that crosses midnight is split into one piece per day. Work frames are shaded, fixed events and placed work look different, and the grid shows all 24 hours, scrolled to the earliest block. Vite forwards /api to the local API in development, so no CORS setup |
| Nov 14, 2026 | Week API: GET /api/weeks/{week_start} lives in the solver package as mycal.api, a caller like the demo. It returns week_start, timezone, feasible, blocks (id, item_id, title, start, end, fixed), frames (the week's work-frame time as merged UTC windows) and unscheduled items (id, title, estimate_min). All times are UTC; the page converts to the week's timezone for display. Only a valid date reaches the file lookup. A week that cannot be solved is still 200 with feasible false. It listens on 127.0.0.1 only. Ids come from the week file load, so they are new on each request until storage arrives |
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
