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

## UNRESOLVED - "in hard conditions 14h -> 16h"

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
