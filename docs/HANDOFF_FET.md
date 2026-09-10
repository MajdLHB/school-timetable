# HANDOFF - FET bridge (second engine, worked on in parallel)

**You are an AI agent asked to build a second placement engine for this
school timetable using FET (Free Timetabling Software, GPL, lalescu.ro).
Another agent is working in parallel on the CP-SAT engine
(`solver/place2.py`). Do not edit that file, `solver/place.py`,
`solver/solve.py`, `solver/data.py`, `solver/verify.py` or
`solver/emit_asc.py`. Work in `solver/fet_bridge.py` and `out/fet/`.**

Read this file, then `docs/RULES.md`, then `docs/HOW_IT_WORKS.md`. Ask the
user (Majd) only when this file does not answer.

---

## 1. The job in one paragraph

Turn `data/school_lastyear.xlsx` (later `data/school.xlsx`) into a `.fet`
file, run FET headless, read the result back, and hand the placement to the
existing checker and aSc export. The output must obey EVERY hard rule below
from the first card. No relaxations, no "exceptions". If FET cannot place a
card, report which card and which rule blocks it - that is a valid result.

Deadline context: teachers report Monday 14 September 2026. Keep steps small
and verified.

## 2. CPU etiquette

FET is single-threaded. The CP-SAT engine uses 7 of the 8 logical cores while
it runs. Run FET with one thread and do not run more than one FET at a time.
This PC has 7.7 GB of RAM.

## 3. The proven pieces you MUST reuse

| piece | how |
|---|---|
| load the workbook | `import data as D; cfg = D.load_config(); s = D.load_school("data/school_lastyear.xlsx", cfg)` (run from the repo root with `solver/` on `sys.path`) |
| expand rows into sessions | `import solve as S; sessions = S.expand(s)` - each `Sess` has `sid, class_id, subject_id, teacher_id, room_type, length, hour_offset, explicit, group, week` |
| per-hour ids | `S.uid_of(se, t)` for `t in range(se.length)` |
| write the result | `S.save_snapshot(s, sessions, placement, "FET - every rule obeyed")` where `placement = {uid: [day, period]}` with day in `Mon..Sat` and period 1..10. This writes `out/timetable.xml` (aSc, proven import format), `out/view.html`, `out/solution.json` and assigns concrete rooms. **Write to `out/fet/` instead**: copy the three files there right after, or call `emit_asc.write` / `emit_html.write` yourself with a path under `out/fet/`. |
| independent check | `python solver/verify.py data/school_lastyear.xlsx` reads `out/timetable.xml`. Must print ALL GREEN. (Add `--p5` only if period 5 was opened.) |
| score against the hand-made table | `python tools/score_table.py out/timetable.xml` vs `python tools/score_table.py` (last year's hand table) |

The data layer is trusted. The grid: `config.json` - Mon..Sat, 10 periods
08:00-18:00, periods 5-6 (12:00-14:00) closed = lunch, Saturday afternoon
closed. So 44 open slots: Mon-Fri periods 1-4 and 7-10, Saturday 1-4.
Fortnight: `weeks_per_cycle = 2`; a session with `week == "A"` or `"B"` runs
only that week; `week == ""` runs every week.

## 4. The rules FET must hold (all HARD)

Ids refer to `docs/RULES.md`. Semantics below are the settled ones, including
decisions Majd made on 2026-09-01.

1. **H1/H2/H3** no teacher, class-part or room in two places at once, per
   week view (a week-A card and a week-B card may share a slot).
   Class parts: group 0 = whole class clashes with everything of that class;
   group g clashes with group g and with the whole class; groups 1 and 2 may
   run in parallel.
2. **H4/H6** a lesson lands in a room of its `room_type`; never more lessons
   of a type than rooms of that type. Normal lessons may borrow the science
   labs (`D.SPARE_FOR_NORMAL`), never IT / tech / gym / engineering rooms.
   Rooms: 25 normal, 5 it, 3 lab_phys, 2 lab_sci, 2 tech, 6 gym, 1 eng_mech,
   1 eng_elec (last year's file).
3. **H5/H9** every session placed exactly once as one consecutive block on
   one day (a block never straddles lunch); sessions of one row with a
   written pattern (`explicit`) land on DIFFERENT days.
4. **H7** a teacher's `day_off` and `training_day` (Teachers sheet) are fully
   empty. Blank `day_off` = the engine chooses ONE fully free day per teacher
   among the days not adjacent to the training day (**H18**, Sunday wrap:
   Saturday off + Monday training is forbidden too). `(none)` = no day off.
   In FET: pre-assign the chosen day off yourself (balanced across the
   week, H18-legal) and give it as "teacher not available", or use "max days
   per week" and check H18 afterwards.
5. **H8** Unavailable sheet, `hard = yes` rows.
6. **H14** option bands: `s.option_bands` (from the Options sheet). Every
   member class's `OPT:<band>` pseudo-session sits in the SAME periods
   (one activity with several student sets in FET), the option teachers are
   busy then, and the band needs one room per option group
   (`D.option_room_type(s, g)` per group).
7. **H15** `latest_period` on a subject: Sport never after period 9 (17:00).
8. **H17** a teacher never teaches more than 6 hours in one day.
9. **H19** `gap24 = yes` subject (Sport): two sessions of one row never on
   consecutive days is the safe reading.
10. **H20 group halves back to back.** For rows with `groups = 2`, group 1's
    session and group 2's session of the same week sit on the same day in
    ADJACENT periods (G1 then G2 or G2 then G1). Exception: pairs too long
    for one half-day (engineering 4h + 4h) run in PARALLEL with the partner
    subject instead, as the 2023 table shows: mechanical G1 alongside
    electrical G2 in one half-day, swapped on another day, never both halves
    of the same subject in one half-day.
11. **H21/H22** a teacher's half-day (morning = periods 1-4, afternoon =
    7-10) holds 0 hours or at least 2. Teachers with a single hour in the
    week are exempt.
12. **Pupils (circular I.2)** a class part's half-day holds 0 or at least 2
    hours, except that a lone hour of PE or an option is allowed
    (`minmax_exempt = yes` on the subject, or an `OPT:` session).
13. **Locked sheet** pinned placements are immovable.
14. **Period 5 (12:00-13:00)** stays CLOSED by default. Only if Majd asks:
    open it Mon-Thu as a last resort for light subjects (difficulty not
    `hard`), and a class that uses it that day must not have period 7
    (back at 15:00). `cfg.open_period5()` does the config part; verify.py
    has `--p5`.

Comfort, in order of importance (soft in FET; keep them as preferences):
no holes inside a half-day for teachers and classes; no hard subject
(`difficulty = hard`: maths, physics, philosophy) in period 10; sport in the
morning; core rows (`core = yes`) three quarters in the morning; bac classes
(`is_bac = yes`) get one free afternoon Mon-Thu; a 2h/week single-hour
subject not on consecutive days; a double at the top of its half-day.

## 5. FET specifics that matter here

- Use FET **6.x or later** in **Mornings-Afternoons mode** (built for
  Morocco/Algeria): real day = morning + afternoon. Native constraints then
  exist for min hours per morning/afternoon (H21/H22, pupils I.2), max hours
  per real day (H17), max afternoons per week (bac), gaps per real day
  (holes), min half-days between activities.
- **Fortnight (week A/B) is not native.** Recommended: pair each week-A
  session with the week-B session of the same class in the same slot into
  one FET activity carrying both teachers, then split it back into two
  week-masked cards when writing the placement (both get the same
  `[day, period]`; the emitter handles weeks from `se.week`). Say clearly
  in your report that the paired teachers are blocked in the other week's
  slot too.
- Group halves = subgroups of the class in FET (year > group > subgroup).
  A class split two independent ways (halves for labs AND option choice)
  needs the "divide by categories" structure or the cross-product of
  subgroups.
- Back to back (H20) = "activities consecutive" constraint; band copies =
  one activity with several student sets; patterns on different days =
  "min days between activities"; sport before 17:00 = preferred time slots;
  rooms = subject/activity preferred rooms.
- Command line: `fet-cl --inputfile=out/fet/school.fet --outputdir=out/fet
  --timelimitseconds=NNN`. On Windows there is no console output; read
  `out/fet/logs/`. The result XML is under the output dir (activities with
  Day / Hour / Room). Parse that back into `placement`.
- FET's weight percentages are retry probabilities, not an optimiser. Put
  every rule in section 4 at 100 percent. Put comfort at 90-99 percent.

## 6. Order of work

1. `python solver/data.py data/school_lastyear.xlsx` - confirm the data
   loads clean.
2. Write `solver/fet_bridge.py` with `export(s, sessions) -> out/fet/school.fet`
   and `import_result(path) -> placement`. Start with H1-H9 + H17 + H21/H22,
   run FET on last year's data, verify. Then add bands, H20, day-off choice,
   H19, the pupil rule. Verify after every addition.
3. Every result goes through `verify.py`. Never report a table that is not
   ALL GREEN. Never hand-edit `out/timetable.xml`.
4. When last year's data verifies, do `data/school.xlsx` (this year). It is
   incomplete: the Options sheet is empty, Sport is synthetic, 15 curriculum
   rows have no teacher. Report what blocks; do not invent data.

## 7. Privacy

`data/` and `out/` hold real names. They never leave this PC. Do not upload
the workbook, the XML files or teacher names anywhere. The repo's
`.gitignore` already blocks them.

## 8. What "done" looks like

`out/fet/timetable.xml` imported into aSc TimeTables 2013 (6 days, 2 weeks
set in the project first), `verify.py` ALL GREEN, and `score_table.py`
numbers better than last year's hand table (35 teacher hole-hours, 0.5 lone
days, 0.5 lonely half-days, 23.5 pupil hole-hours, 139 last-period lessons).
