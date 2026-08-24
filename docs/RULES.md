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
| H4 | At most **20** lessons run in any single period (we have 20 rooms). | SPEC |
| H5 | Every class receives exactly the required weekly hours of every subject. | SPEC |
| H6 | A lesson only lands in a room of the right type (lab / IT / gym / normal). | SPEC |
| H7 | Each teacher's **day off** is fully empty. | SPEC |
| H8 | A teacher is never scheduled in a period they declared unavailable. | SPEC |
| H9 | Multi-hour blocks (double hours) stay consecutive and never straddle the lunch break. | SPEC |
| H10 | A teacher never exceeds their contracted weekly hours. | SPEC |

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
| S10 | **Last-period fairness.** Nobody is stuck with the final period every single day. | 35 | SPEC |

---

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

## Change log

Every change to a rule gets a line here, so no rule is ever silently lost.

| Date | Change |
|------|--------|
| 2026-08-24 | File created from the first conversation. All rules `SPEC`, nothing coded. |
