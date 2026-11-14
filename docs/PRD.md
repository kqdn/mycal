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
| Write code, 4h | Two 2h blocks on different days | Split across the week (max chunk size) |
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

**Soft constraints** (weighted penalties)

- Stability: penalize moving a block away from where it already is
- Time preferences: mornings for deep work, evenings free
- Buffer between events; avoid long back-to-back runs
- Spread a project's work out instead of cramming the last day

**Objective.** Minimize the weighted sum of soft penalties, subject to all hard constraints. No feasible solution means a deadline is at risk, which triggers the feasibility warning.

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

Four core entities (Item, Block, WorkFrame, Constraint), all keyed by UUID, all times stored in UTC and converted only for display.

| Entity | Fields | Notes |
| --- | --- | --- |
| Item | id, title, flex_preset, preset_params (JSON), windows[] ({start, end}), checkable, estimate_min, deadline, parent_id, depends_on[], max_chunk_min, on_miss (reschedule / catch_up / skip / ask), catch_up_of | windows[] is generated from the preset; the solver reads only windows. Subtasks are items with a parent_id. catch_up_of is the id of the missed Block |
| Block | id, item_id, start, end, locked, status (planned / done / partial / missed / unanswered), completed_at, actual_min | Many blocks per item; locked = placed by hand, solver must keep it |
| WorkFrame | id, name, weekdays[], start_time, end_time, timezone | Default source of windows for flexible presets. start_time and end_time are local times in timezone (an IANA name); end before start means the frame crosses midnight, and weekdays[] names the day it starts |
| Constraint | id, kind, params (JSON), weight, hard (bool) | New rule types need no schema change |

**Rules**

- Never use array indexes as identity; sync, undo and stability all depend on stable ids
- Slot size (default 15 min) is one setting, not hardcoded
- Store actual completion times from day one; estimate learning needs that history

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

**First step:** the data model and solver as a Python module with tests, before any UI. Input this week's tasks, print the schedule.

## Open questions and decision log

**Open questions**

- [ ] Among tied arrangements, which tie-breakers matter most after stability: earlier in the day, work spread out, or something else?
- [ ] Name for the app
- [ ] Recurring items (weekly lectures, gym): how to model "repeat every week" in the data model. For Milestone 1, presets compile only for one horizon and are recompiled each week. Needed before daily use.

**Decision log** (newest first)

| Date | Decision |
| --- | --- |
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
