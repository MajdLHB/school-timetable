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
| H1 | A teacher is never in two places in the same period. | SPEC |
| H2 | A class is never in two places in the same period. | SPEC |
| H3 | A room is never used by two lessons in the same period. | SPEC |
| H4 | Never more lessons at once than rooms exist. Measured last year: **45 rooms**, busiest period **47 lessons** - the extra fit because the stadium holds several classes (Stad 1/2/3). The solver counts per room TYPE, so this is automatic. | SPEC |
| H5 | Every class receives exactly the required weekly hours of every subject. | SPEC |
| H6 | A lesson only lands in a room of the right type (lab / IT / gym / normal). | SPEC |
| H7 | Each teacher's **day off** is fully empty. | SPEC |
| H8 | A teacher is never scheduled in a period they declared unavailable. | SPEC |
| H9 | Multi-hour blocks (double hours) stay consecutive and never straddle the lunch break. | SPEC |
| H10 | A teacher never exceeds their contracted weekly hours. | SPEC |

| H16 | **A small class is not split.** The ministry: *لا داعي إلى تقسيم التلاميذ إلى فوجين إذا لم يتجاوز عدد التلاميذ في القسم الواحد 24* - no need to split a class of 24 pupils or fewer. Majd: *"we were few to the point that we were treated as one group the whole class rather than 2 groups"*. **Whether a class splits is a property of the CLASS AND SUBJECT, not of the subject alone** - proved from last year's file, where 4رياضيات1 split for Natural Sciences and Physics but ran Computer Science whole-class. Carried by the `groups` column in the Curriculum sheet; default 1. | SPEC |
| H15 | **Daylight-only subjects.** Sport cannot run after **16:00** - the stadium has no lighting. With 10 periods of one hour from 08:00, 16:00 is the end of **period 8**, so Sport may occupy periods 1-8 and never 9 or 10. Stated by Majd 2026-08-24: "sport time window daylight meaning morning and max 14h to 16h". Generalised: any subject may carry a `latest_period` in the Subjects sheet. | SPEC |
| H14 | **Optional-subject groups cross class boundaries.** Pupils choose one option (Spanish / German / Italian / Tashkilia). Within a single class the pupils do not all pick the same option, and it would waste a teacher to run a class of one or two. So pupils taking the same option are **pooled from several classes** into one group that studies together. While that option lesson runs, every class contributing pupils must be free at the same time - the option lessons of all those classes are locked to the same period. | SPEC |

**H14 is stated by Majd, not inferred.** It also explains what was measured in
last year's file: 23 lessons spanning more than one class, and 224 real group
subdivisions.

Still to confirm before this can be coded:
- Which subjects are options? (Spanish, German, Italian, Tashkilia - any others?)
- Does every pupil take exactly one option, or can they take none / several?
- How many classes typically pool into one option group?
- Do the pooled classes have to be the same grade/level?
- Is this the same thing as "a teacher teaching 3 portions of 3 classes"?

---

## SOFT constraints
Optimised, weighted, and **reported**. The solver maximises satisfaction and
then tells you in `out/report.md` exactly which ones it missed **and why**.

Weight = how much we care. Higher beats lower when they conflict. These numbers
are first guesses - **we will tune them together after seeing the first result.**

| # | Rule | Weight | Status |
|---|------|--------|--------|
| S1 | **No holes.** A teacher's day is one continuous run - no free hour trapped between two taught hours. | 100 | SPEC |
| S2 | **No 1-hour days.** Never make a teacher travel to school to teach a single hour. Minimum 2h if present at all. [CONFIRM: is 2 the right minimum?] | 90 | SPEC |
| S3 | **Hard subjects in the morning.** Maths, Physics, Chemistry etc. placed in early periods. | 70 | SPEC |
| S4 | **No 3 hard subjects in a row** within one continuous session. [CONFIRM: is the limit 2 in a row, or 3?] | 80 | SPEC |
| S5 | **Fair morning/evening balance.** No teacher gets all the evening slots while another gets all mornings. | 60 | SPEC |
| S6 | **Spread subjects across the week.** A class's 4h of Maths sits on 4 different days, not 2 doubles. | 50 | SPEC |
| S7 | **Compact days for classes.** Pupils get no free hour in the middle of their day either. | 85 | SPEC |
| S8 | **Fewest days present.** If a teacher's hours fit in 4 days, do not spread them over 6. | 40 | SPEC |
| S9 | **Room stability.** A class stays in its home room where possible; less moving around. | 30 | SPEC |
| S14 | **Avoid the last period, 17:00-18:00.** *Majd: "try to avoid 17 to 18 as much as possible its late".* Applies to everyone, not only bac. Period 10 becomes a slot of last resort rather than a forbidden one - making it hard would cost too much capacity given classes average 42 hours. | 55 | SPEC |
| S13 | **No Friday evening for bac classes.** *Majd's own words: "me and my other colleague pupils dont want it... so its personal preference as a rule".* **This is a LOCAL preference, not a ministry rule** - the circular requires a free afternoon for bac in the first four days (Mon-Thu) and says nothing about Friday. Recorded as such deliberately, so nobody later mistakes it for policy. | 30 | SPEC |
| S12 | **Daylight subjects prefer the morning.** Majd said "morning and max 14h to 16h" - so 14:00-16:00 is the late acceptable window, not the target. Sport should land in the morning where possible and only use periods 7-8 when it must. | 45 | SPEC |
| S10 | **Last-period fairness.** Nobody is stuck with the final period every single day. | 35 | SPEC |

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
| periods | **10 per day, 08:00-18:00, one hour each, NO lunch break** |
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
- No lunch break exists. `config.json` reflects this.

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

1. **S8 conflicts with the ministry.** Our S8 rewards packing a teacher's hours
   into fewer days. The ministry says the opposite: *"توزيع الحصص على أغلب
   أيّام الأسبوع"* - spread over most days of the week. **Unresolved: whose
   rule wins?** Until Majd decides, S8 stays as written and the conflict stays
   recorded here.
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
