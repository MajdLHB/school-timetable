# How do I know it works?

The honest version of the question is: *on 1,682 lessons, how would I ever
notice a mistake?* You would not. Nobody could. So the answer cannot be
"check it carefully" - it has to be machinery that checks itself.

Five layers, cheapest first. Each catches a different kind of wrong.

---

## Layer 1 - the data is sane  (`check_data.bat`, instant)

Before solving, `solver/data.py` reads the workbook and complains in plain
language:

> `Teacher T014 is given 22 hours but the contract says 18.`
> `Rooms of type 'lab_sci': need 90 hours but only 2 x 40 = 80 available.`
> `Class C07 needs 45 hours but the week only has 40 open periods.`

It never guesses and never picks a side. Most "the timetable is wrong" problems
are really "the data disagreed with itself", and they die here.

## Layer 2 - the rules are mathematically enforced  (during the solve)

Hard rules are equations the solver must satisfy. A timetable that breaks one
is not a bad solution, it is *not a solution*. It cannot be returned, the way a
calculator cannot return 5 for 2+2.

This is why the AI does not place lessons.

## Layer 3 - an independent check of the finished file  (`verify.py`, seconds)

The solver could be given the *wrong* equations. So `verify.py`:

- re-reads `out/timetable.xml` **from disk** - the same bytes aSc will read
- re-derives every hard rule from the source data
- **shares no code with the solver**

Two separately written programs agreeing is the actual guarantee. It prints
ALL GREEN or it refuses.

## Layer 4 - proof the rules are WIRED UP  (`tools/selftest.py`, seconds)

This is the layer people forget, and it is the one that matters most at scale.

A rule can be written in RULES.md, described in a report, believed by everyone
- and **connected to nothing**. Every check would still pass, because there is
nothing to catch. On 1,682 lessons you would never see it.

So each hard rule gets a **pair** of deliberately tiny schools:

| | |
|---|---|
| **BREAK** | a 4-slot school where obeying the rule is impossible. The solver must say INFEASIBLE. |
| **RELAX** | remove only that rule's cause, change nothing else. It must now say FEASIBLE. |

The pair is the point. A BREAK test alone proves nothing - the school might be
impossible for an unrelated reason, and a disconnected rule would still
"pass". Only BREAK-then-RELAX shows the answer hinges on *that* rule.

It also separates **who** caught it:

```
  rule                         must be   caught by            relaxed
  H1  teacher in two places    solver    solver               OPTIMAL     ok
  H7  day off not empty        solver    validator+solver     OPTIMAL     ok
  H10 over contracted hours    validator validator            OPTIMAL     ok
```

`H10` is validator-only **on purpose**: a teacher's weekly total is fixed by
the curriculum, so no placement can change it. It is a property of the data,
not of the arrangement. Adding a CP-SAT constraint would be trivially true -
it would look reassuring and prove nothing. Rules like that are marked
`validator` and the test enforces that distinction.

## Layer 5 - no rule exists only on paper  (`tools/rule_coverage.py`, instant)

Lines up RULES.md against verify.py and selftest.py and lists what is missing:

```
  H5   Every class receives exactly the required hours    yes   yes   yes
  H9   Multi-hour blocks stay consecutive                 NO    NO    NO   <-- GAP
  H14  Optional-subject groups cross class boundaries     NO    NO    NO   <-- GAP
```

A gap here is not a failure - it is the to-do list, kept honest. What it
prevents is *believing* a rule is enforced when it is not.

---

## The run ladder - never jump straight to overnight

```
  30 seconds  ->  verify  ->  does it produce anything valid at all?
  2 minutes   ->  verify  ->  are the numbers moving the right way?
  10 minutes  ->  verify  ->  is the quality actually acceptable?
  overnight   ->  verify  ->  the real run
```

Each rung is verified before the next. Finding a broken rule after 30 seconds
costs 30 seconds. Finding it after an 8-hour run costs a night.

**Never run overnight on rules that have not passed the 10-minute rung.**

## Crash safety

`out/solution.json` is rewritten (atomically) as the search improves, so a
power cut at hour 7 loses at most a few seconds. Resume with:

```
python solver/solve.py --continue
```

Every finished run also drops a timestamped copy in `out/archive/` so a good
result is never silently replaced by a worse one.

## The agreement test - and its limit

Last year's real timetable can be run through our checker. If it flags things
Majd already knows were broken, our checker is reading reality correctly.

**But last year's file is NOT ground truth.** It contains dummy groups, stale
fields, and rules deliberately broken because the job was too hard by hand. It
was never even the final version. Disagreement with it is evidence to
investigate - never proof that we are wrong.

## What none of this can check

**Whether a rule says what Majd meant.**

Machinery can prove a rule is enforced, consistent, and connected. It cannot
know that "no holes" meant teachers rather than pupils, or that "14h -> 16h"
meant sport rather than workload. That is what `docs/RULES.md` is for: every
rule written in plain language, read back, and confirmed **before** it is
coded. A rule nobody confirmed is not a rule - it is a guess with a number
next to it.

See `docs/NOTES.md` for things said in passing that are deliberately NOT rules
yet.
