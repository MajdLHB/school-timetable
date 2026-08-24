# The Rules

**This file is the single source of truth.** Every rule the solver enforces is
written here first, in plain language, before any code exists. If a rule is not
in this file, the solver does not know about it.

Read this file and correct it. Anything marked **[CONFIRM]** is my assumption,
not your rule - tell me if it is wrong.

Status legend: `SPEC` = written only | `CODED` = in solver | `VERIFIED` = checker proves it

---

## HARD constraints
Never violated. The solver is mathematically incapable of returning a timetable
that breaks any of these. If they cannot all be satisfied at once, the solver
reports **INFEASIBLE** and we find out which rule is impossible - it never
silently bends one.

| # | Rule | Status |
|---|------|--------|
| H1 | A teacher is never in two places in the same period. | VERIFIED |
| H2 | A class is never in two places in the same period. | VERIFIED |
| H3 | A room is never used by two lessons in the same period. | VERIFIED |
| H4 | Never more lessons at once than rooms exist. Measured last year: **45 rooms**, busiest period **47 lessons** - the extra fit because the stadium holds several classes (Stad 1/2/3). The solver counts per room TYPE, so this is automatic. | VERIFIED |
| H5 | Every class receives exactly the required weekly hours of every subject. | VERIFIED |
| H6 | A lesson only lands in a room of the right type (lab / IT / gym / normal). | VERIFIED |
| H7 | Each teacher's **day off** is fully empty - and so is their **training day** (`training_day` column; circular II.1: respect the pedagogical training days). *Relaxable in rescue mode - see below.* | VERIFIED |
| H8 | A teacher is never scheduled in a period they declared unavailable. Never relaxed. | VERIFIED |
| H9 | Multi-hour blocks (double hours) stay consecutive and never straddle the lunch break. | SPEC |
| H10 | A teacher never exceeds their contracted weekly hours. | VERIFIED |
| H17 | **A teacher never teaches more than 6 hours in one day.** Circular 51/2018 II.2, stated again by the inspectorate text (M-T2). *Relaxable in rescue mode.* | VERIFIED |

| H18 | **The day off must not create two consecutive free days with the training day.** Source: the inspector's written note on the approved Arabic distribution sheet (21/08/2026): *"لا يسند للأستاذ يوما عطلة متتاليان باعتبار يوم التكوين (لا يمكن إسناد يوم الأربعاء و/أو يوم الجمعة)"* - do not give a teacher two consecutive rest days counting the training day; concretely, when the training day is Thursday, neither Wednesday nor Friday may be the day off. **Majd (2026-08-24): the inspector notes are to be followed, and this one applies to ALL teachers**, not only Arabic. General form: `day_off` must never be adjacent to `training_day`. Enforced as a data-check (like H10: it is a property of the data, no placement can change it), re-checked by verify.py, proven by selftest. Adjacency is between Mon-Sat weekdays; whether Saturday-Sunday-Monday also counts as consecutive is Q26. | VERIFIED |
| H16 | **A small class is not split.** The ministry: *لا داعي إلى تقسيم التلاميذ إلى فوجين إذا لم يتجاوز عدد التلاميذ في القسم الواحد 24* - no need to split a class of 24 pupils or fewer. Majd: *"we were few to the point that we were treated as one group the whole class rather than 2 groups"*. **Whether a class splits is a property of the CLASS AND SUBJECT, not of the subject alone** - proved from last year's file, where 4رياضيات1 split for Natural Sciences and Physics but ran Computer Science whole-class. Carried by the `groups` column in the Curriculum sheet; default 1. Enforced today as a data-check warning when a small class is set to split; full group placement awaits the group machinery. | CODED (data check) |
| H15 | **Daylight-only subjects.** Sport cannot run after **16:00** - the stadium has no lighting. With 10 periods of one hour from 08:00, 16:00 is the end of **period 8**, so Sport may occupy periods 1-8 and never 9 or 10. Stated by Majd 2026-08-24: "sport time window daylight meaning morning and max 14h to 16h". Generalised: any subject may carry a `latest_period` in the Subjects sheet. | VERIFIED |
| H14 | **Optional-subject groups cross class boundaries.** Pupils choose one option (Spanish / German / Italian / Tashkilia). Within a single class the pupils do not all pick the same option, and it would waste a teacher to run a class of one or two. So pupils taking the same option are **pooled from several classes** into one group that studies together. While that option lesson runs, every class contributing pupils must be free at the same time - the option lessons of all those classes are locked to the same period. | SPEC |

**H14 is stated by Majd, not inferred.** It also explains what was measured in
last year's file: 23 lessons spanning more than one class, and 224 real group
subdivisions.

Still to confirm before H14 can be coded:
- Which subjects are options? (Spanish, German, Italian, Tashkilia - any others?)
- Does every pupil take exactly one option, or can they take none / several?
- How many classes typically pool into one option group?
- Do the pooled classes have to be the same grade/level?
- Is this the same thing as "a teacher teaching 3 portions of 3 classes"?

## RESCUE MODE - livable exceptions, stated by Majd 2026-08-24

Majd: *"u can tell the model if it get suck to make some livable realistic
exception that teachers and pupils can live with but in extreme condition...
or it gives after work report of what is done whats done but not by rules"*.

So: the solver first tries the strict rules. **Only if NO legal timetable
exists at all**, it retries with the two *livable* hard rules allowed to break
at enormous cost (10,000 per broken hour - far above any soft trade-off):

- **H7** - a teacher teaching on their day off / training day
- **H17** - a teacher's day running past 6 hours

**Never relaxed, ever:** clashes (H1-H3), room rules (H4/H6), hours (H5),
declared unavailability (H8), daylight (H15), the lunch break, closed period
5, and pinned lessons. Every exception taken is listed in `out/report.md`
("RULE EXCEPTIONS"), written to `out/exceptions.json`, and `verify.py` reports
the timetable as "GREEN WITH DECLARED EXCEPTIONS" - done, but not by rules,
exactly as asked. A later strict success deletes the exceptions file.

---

## SOFT constraints
Optimised, weighted, and **reported**. The solver maximises satisfaction and
then tells you in `out/report.md` exactly which ones it missed **and why**.

Weight = how much we care. Higher beats lower when they conflict. These numbers
are first guesses - **we will tune them together after seeing the first result.**

| # | Rule | Weight | Status |
|---|------|--------|--------|
| S1 | **No holes.** A teacher's day is one continuous run - no free hour trapped between two taught hours. | 100 | CODED |
| S2 | **No 1-hour days.** Never make a teacher travel to school to teach a single hour. Minimum 2h if present at all. *Answered by the PDFs: the minimum is 2 - circular I.2/II.2 ("minimum 2 hours in any morning or evening", for pupils AND teachers), and the inspectorate text repeats it twice. 2 is ministry policy, not a guess.* | 90 | CODED |
| S3 | **Hard subjects in the morning.** Maths, Physics, Chemistry etc. placed in early periods. | 70 | CODED |
| S4 | **No 3 hard subjects in a row** within one continuous session. *The ministry is stricter: inspectorate pupil-rule 8 says avoid **two or more consecutive** subjects of the same nature (literary/scientific/social) or stream-defining subjects (= M-P6). So the ministry's limit is "not even 2 of the same nature in a row" - our "hard subjects" framing is looser. Adopting M-P6 properly needs a `nature` column on Subjects.* | 80 | SPEC |
| S5 | **Fair morning/evening balance** (circular II.4: alternation). Each teacher's morning and evening hours may differ by at most 2 before a penalty grows - nobody teaches only mornings or only evenings. | 60 | CODED |
| S6 | **Spread subjects across the week.** A class's 4h of Maths sits on 4 different days, not 2 doubles. | 50 | CODED |
| S7 | **Compact days for classes.** Pupils get no free hour in the middle of their day either. | 85 | CODED |
| S8 | **Ministry spread** (REWRITTEN 2026-08-24, was "fewest days present"). Circular II.2: a teacher's hours are balanced across working days. Default: every taught hour beyond 4 on one day is penalised (H17 caps it at 6 outright). **Exception:** `compact=yes` in the Teachers sheet keeps the old packed week - for teachers with long journeys, the list Majd will supply. The old behaviour was the ministry conflict recorded below; the ministry now wins by default, exactly as Majd decided. | 40 | CODED |
| S9 | **Room stability.** A class stays in its home room where possible; less moving around. | 30 | SPEC |
| S14 | **Avoid the last period, 17:00-18:00.** *Majd: "try to avoid 17 to 18 as much as possible its late".* Applies to everyone, not only bac. Period 10 becomes a slot of last resort rather than a forbidden one - making it hard would cost too much capacity given classes average 42 hours. *Independently backed by the ministry: the inspectorate text tells Physics to avoid "from five to six" (M-PH5, corrected reading) - the same 17:00-18:00 hour.* | 55 | CODED |
| S13 | **No Friday evening for bac classes.** *Majd's own words: "me and my other colleague pupils dont want it... so its personal preference as a rule".* **This is a LOCAL preference, not a ministry rule** - the circular requires a free afternoon for bac in the first four days (Mon-Thu) and says nothing about Friday. Recorded as such deliberately, so nobody later mistakes it for policy. Uses `is_bac=yes` in the Classes sheet. | 30 | CODED |
| S12 | **Daylight subjects prefer the morning.** Majd said "morning and max 14h to 16h" - so 14:00-16:00 is the late acceptable window, not the target. Sport should land in the morning where possible and only use periods 7-8 when it must. | 45 | CODED |
| S10 | **Last-period fairness.** Nobody is stuck with the final period every single day. | 35 | SPEC |
| S15 | **A class never comes in for a single lone hour** in a morning or evening session (circular I.2 - the minimum-2 rule applies to pupils too). PE and optional subjects are exempt, as the circular itself says (`minmax_exempt=yes` in the Subjects sheet - Sport carries it). | 85 | CODED |
| S16 | **Subject-specific late-hour avoidance** - soft cousin of H15, via the `avoid_after` column in the Subjects sheet. Ministry: **Maths after 16:00** is avoided (M-MA3: "avoid the evening; if impossible, before 16:00"), **Physics avoids 17:00-18:00** (M-PH5). Maths=8, Physics=9. | 50 | CODED |
| S17 | **Bac classes get at least one free afternoon Mon-Thu** (circular I.6: ينبغي منح تلاميذ البكالوريا أمسية راحة). One evening of the first four days entirely free per bac class; penalty if none is. | 70 | CODED |

---

## MEASURED from last year's real export (2026-08-24)

Not asked, measured. `python tools/analyze_reference.py` reproduces all of it.

| fact | value |
|---|---|
| teachers | **101** |
| classes | **41** |
| **classrooms** | **45** (not 20 - see below) |
| subjects | 24 |
| groups | 265 (41 whole-class + **224 real subdivisions**) |
| lessons / placed cards | 881 / **1682** |
| week | **Mon-Sat**, day mask **6 chars** on all 1682 cards |
| periods | **10 per day, 08:00-18:00, one hour each.** The grid defines no break, but usage shows one: **period 6 (13:00-14:00) has 0 cards, period 5 (12:00-13:00) only 40** vs ~220 for normal periods. The lunch break is real and visible in the data. |
| Saturday | half day (176 lessons vs ~300 on other days) |
| class load | min 32, median 43, max 53, **avg 42.2 h/week** |
| teacher load | min 8, median 17, max 23, **avg 16.7 h/week** |
| busiest period | **47 lessons at once** vs 45 rooms |
| alternating weeks | **145 of 1682 cards** are Week A or Week B only |
| co-teaching | **none** - 0 lessons with 2 teachers |
| multi-class lessons | 23 |

**The "20 physical classes" figure was wrong.** The real file defines 45
classrooms and uses all 45. That is why the room arithmetic looked impossible:
45 rooms x 6 days x 10 periods = 2700 room-slots for 1682 cards = 62% full.
Comfortable, not impossible.

The busiest period needs 47 rooms for 45 - because the stadium holds several
classes at once (Stad 1/2/3), exactly as described.

## Known about last year's timetable
- It is **not identical to this year**: dummy class-groups that were never used,
  groups added for nothing, fields never updated.
- **Some rules were deliberately broken** because it was too hard by hand.
- Treat it as a *reference for structure*, never as a source of truth.
- **The lunch break is real** (corrected 2026-08-24). Circular 51/2018 I.3
  requires a 2-hour separation between morning and evening; `config.json`
  closes periods 5-6 (12:00-14:00) daily. An earlier claim here that "no lunch
  break exists" was a misreading of Majd's remarks about a *generated*
  timetable. Note: last year 40 cards did sit in period 5 (12:00-13:00) -
  possibly the 5-hour mornings circular I.5 allows Mon-Thu. Whether period 5
  should stay hard-closed or be a rare 5th morning hour is an open question
  (see `docs/OPEN_QUESTIONS.md` Q25).

## Rules I suspect exist but you have not said yet

Tell me yes or no on each - each one is cheap to add now and expensive later.

- [ ] Are there teachers who work **part-time / specific days only**?
- [ ] Do any teachers teach at **another school** and need fixed free half-days?
- [ ] Are there subjects taught by **two teachers together** (co-teaching)?
- [ ] Are classes ever **split into groups** (e.g. half the class to the lab, half elsewhere)?
- [ ] Is there a **fixed all-school slot** (assembly, sport, prayer, break)?
- [ ] Do **exams / devoirs de contrôle** need reserved slots?
- [ ] Any teacher who must **not** be scheduled at the same time as another
      (shared spouse transport, same person covering two roles)?
- [ ] Any **seniority** rules - senior staff get first pick of the good slots?

---

## Ministry recommendations

The Tunisian General Inspectorate publishes binding pedagogical
recommendations for building teacher timetables, per subject. Majd supplied
them 2026-08-24. They are catalogued and rated in **`docs/MINISTRY_RULES.md`**
- about 90 items - and none are coded yet.

Two findings from that catalogue that affect the rules below:

1. **S8 vs the ministry - RESOLVED 2026-08-24.** Our old S8 rewarded packing a
   teacher's hours into fewer days. The ministry says the opposite: *"توزيع
   الحصص على أغلب أيّام الأسبوع"* - spread over most days. **Majd decided the
   ministry wins by default**, with a per-teacher `compact=yes` exception for
   those with long journeys (names to come). S8 is rewritten and coded that
   way above.
2. Several ministry items are about **who teaches which classes**, not about
   when lessons happen. Our solver does not decide that - it reads `teacher_id`
   as input. Those are tagged [A] in the catalogue.

## Change log

Every change to a rule gets a line here, so no rule is ever silently lost.

| Date | Change |
|------|--------|
| 2026-08-24 | File created from the first conversation. All rules `SPEC`, nothing coded. |
| 2026-08-24 | Ministry recommendations catalogued and rated in `docs/MINISTRY_RULES.md`. Nothing coded from them yet. Recorded a direct conflict between our S8 and ministry rule M-T5. |
| 2026-08-24 | H15 (daylight cutoff for Sport) and S12 (prefer morning) stated by Majd, coded, verified, and covered by a BREAK/RELAX test. |
| 2026-08-24 | **Retracted H11, H12, H13, S11.** They were written up as numbered rules from remarks made in passing. Nothing had been decided. Moved to `docs/NOTES.md` as open questions. Nothing gets a rule number until it is stated deliberately and confirmed. |
| 2026-08-24 | **PDF verification pass** (Majd: "pdfs are source of truth"). All 21 pages of `rules/rules.pdf` read as images and checked against the catalogue; two errors fixed there (M-PH5 time window, M-PHI3/M-PHI8 swapped). In this file: removed the stale "no lunch break" claims (break confirmed by circular I.3, config, and last year's data - period 6 empty, period 5 nearly so); answered S2's [CONFIRM] (minimum is 2, ministry policy); annotated S4 with the ministry's stricter same-nature rule; added the ministry backing to S14. New Q25 raised on period 5. |
| 2026-08-24 | **Q25 answered by Majd: period 5 stays closed.** "it shouldnt be open even if rare follow rules" - last year's 40 uses were hand-made exceptions under time pressure, not policy. |
| 2026-08-24 | **Ministry rules coded.** New **H17** (max 6 teaching hours/day, circular II.2) - hard, verified, selftested. **H7 extended** to the training day (II.1; `training_day` column). **S8 rewritten** to the ministry spread with the `compact=yes` exception, as Majd decided. **S5 built** (II.4 alternation). New **S15** (class never a lone hour, I.2, PE/optional exempt via `minmax_exempt`), **S16** (`avoid_after`: Maths 16:00 M-MA3, Physics 17-18 M-PH5), **S17** (bac free afternoon Mon-Thu, I.6), **S13/S14 coded** (`is_bac` column). Statuses above updated to match reality: everything marked CODED/VERIFIED is running and tested; selftest 11/11, demo 580 lessons ALL GREEN. |
| 2026-08-24 | **H18 added** from the inspector's note on the approved Arabic distribution sheet; Majd instructed that inspector notes are binding and this one applies to all teachers. The 2026/27 pedagogical distribution (who teaches which stream, and each teacher's required hours) was extracted from the sheets in `data/reference/currect distirbution - can be changed/`, cross-verified against `rules/curriculum.json` hours and the 41-class structure, and written to `data/school.xlsx` (Teachers hours, Classes, Subjects, new Distribution sheet). Full verification log and open flags: `data/DISTRIBUTION_REPORT.md`. |
| 2026-08-24 | **H18 coded and proven** (inspector's rule, all teachers, as Majd instructed): day_off never adjacent to training_day. Data-check + verify.py + selftest. Q26 raised: does the rule wrap around Sunday? |
| 2026-08-24 | **RESCUE MODE built, stated by Majd** ("livable realistic exception... in extreme condition... after work report of what is done but not by rules"). Strict first, always; only if NO legal timetable exists, H7/H17 may break at cost 10,000/hour; every exception is listed in the report, `out/exceptions.json`, and verify.py's "GREEN WITH DECLARED EXCEPTIONS". Clashes, rooms, hours, H8, H15, the lunch break and locks are never relaxed. Proven end-to-end on a deliberately impossible school (one declared exception, minimal). |
