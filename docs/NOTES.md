# Notes - things mentioned, NOT decided

Nothing in this file is a rule. Nothing here gets coded.

These are things Majd said in passing while talking about something else. They
were briefly written into `RULES.md` as numbered rules, which was wrong - it
made undecided remarks look settled. They live here until stated deliberately,
and only then do they get a rule number.

**Promotion path:** note here -> Majd states it as a rule -> numbered in
RULES.md -> coded -> checked in verify.py -> deliberate-failure test in
tools/selftest.py. A rule that has not finished that path is not enforced.

---

## RESOLVED 2026-08-24 - "14h -> 16h" meant SPORT

Majd: *"it sport time window daylight meaning morning and max 14h to 16h"*.
Coded as H15 (hard, never past 16:00) + S12 (soft, prefer morning). Note the
ministry text uses the identical window for Islamic Thought - see MINISTRY_RULES.md.

## REMINDER LIST - teachers who need a COMPACT timetable

Majd, on the S8 vs ministry conflict:

> *"we should follow ministry bc its bidagogic but it feels wrong when someone
> uses transport to come here and u do that to him so there exceptions with
> compact scheduels put them on reminder list so i say them to u later"*

**Decision: the ministry rule wins by default** - each teacher's hours spread
across most working days (circular 51/2018, II.2). **But some teachers get an
exception** and keep a compact timetable, because they travel a long way and
spreading their hours over five days means five journeys.

This needs a per-teacher flag, not a global rule. Plan: a `compact` column in
the Teachers sheet. Blank = ministry default (spread). `yes` = pack into fewer
days.

**Majd will supply the list of names later.** Until then the column exists and
is empty, and everyone gets the ministry default.

## OLD - superseded, kept for the record

The original ambiguity of "14h -> 16h"

Said in the same breath as sport and stadium lighting. **Two readings, and I
will not guess between them:**

- **(a) Sport hours.** Sport can run until 16:00 but no later, because the
  stadium has no lighting. "14h -> 16h" = the 14:00-16:00 window.
- **(b) Teacher workload.** In a difficult year a teacher's load rises from
  ~15h to 14-16h rather than being capped at 15.

These lead to completely different constraints. **Which is it?**

## Mentioned, needs a proper statement

- **Sport and daylight.** No lighting at the stadium. Implies a latest period
  for Sport - unknown which.
- **The stadium holds several classes at once.** aSc models it as Stad 1/2/3.
  Our room-type system already expresses this (N rooms of type `gym`), so this
  may need no new rule at all - but that is an assumption, not a decision.
- **"3-hour" lab sessions are really 1.5h x 2 alternating groups.** aSc could
  not express 1.5h, so it was written as 3h. Measured support: 224 real group
  subdivisions and 145 alternating-week cards in last year's file. Almost
  certainly real, still not a stated rule.
- **"A teacher teaching 3 portions of 3 classes"** - described as the starting
  point of the timetable and the hardest part by hand. 23 multi-class lessons
  exist in last year's file. **What does this mean exactly?** One teacher
  taking a group from each of three different classes in the same period?
- **Rules deliberately broken last year** because it was too hard by hand.
  Which ones? These are the most valuable rules in the project - they are
  exactly what the solver can give back.

## Standing reminder

Last year's export is **not ground truth**. It contains dummy groups, unused
entries, stale fields, and known rule violations, and was never the final
version. It is evidence about *structure* and a subject for the agreement test
(`tools/agreement_test.py`) - never a source of correct answers.
