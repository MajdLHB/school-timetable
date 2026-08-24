# How you actually use it - the loop

The fear: *"it runs, it finishes, and then I am stuck with something I hate and
must fix by hand."*

That is not how this works. **It is a loop, not a single shot.**

```
   edit school.xlsx  ->  run.bat  ->  read report.md  ->  don't like something?
        ^                                                        |
        +-------- pin what you like in the Locked sheet ---------+
                        (each turn of this loop is ~1 minute)
```

## The Locked sheet - this is your steering wheel

After a run you look at the result. Say classes 1A and 1B look perfect, but you
hate what happened to 2C on Tuesday.

You do **not** fix 2C by hand. You:

1. Pin the parts you like into the **Locked** sheet (or tell the program
   "lock everything for classes 1A and 1B").
2. Change whatever you want - a rule weight, a teacher's day off, anything.
3. Re-run.

The solver now treats your locked lessons as **immovable facts** and rebuilds
everything else around them. It cannot break what you pinned. Every run keeps
your good decisions and re-thinks only the rest.

Do this five times and you have converged on a timetable that is genuinely
yours, without ever dragging a card.

## Why ~1 minute per turn matters

A one-minute turnaround **is** real-time control. You get 20 attempts in an
afternoon. By hand, one attempt costs you a week, which is exactly why the
current timetable can never be improved - you only ever get one shot at it.

## The manual escape hatch never closes

aSc still works the way it always did. Import the result, and if you want to
drag one card with the mouse, drag it. aSc will warn you about conflicts as it
always has. Nothing about this project takes that away from you.

The difference is that you start from a good timetable instead of a blank grid.

## Stopping early

The solver is **anytime**: it finds a valid timetable quickly, then keeps
improving it. It prints each improvement as it goes:

```
   12s   first valid timetable      penalty 4210
   31s   improved                   penalty 1880
   58s   improved                   penalty  940
  2m10   improved                   penalty  902
  5m00   time limit - best kept     penalty  902
```

You set the time limit in `config.txt`. Press Ctrl+C any time and it keeps the
best result found so far. You are never waiting on it.

## What the report tells you

`out/report.md` is written in plain language, for example:

> **S1 no holes - 94% satisfied.** 6 teachers have one gap each.
> - Mr Ahmed, Tuesday, period 3. Reason: he is the only Chemistry teacher
>   and the chemistry lab is occupied by 3B in periods 2 and 4.
>   To remove this gap: free the lab in period 3, or give Chemistry a
>   second qualified teacher.

So when a teacher complains, you have the reason and the fix - not a shrug.

---

# Data that keeps changing

Real schools are not a snapshot. Teachers leave in October, new ones arrive in
November, and the PDFs you have now will contradict each other. That is normal
and the design already handles it.

## Contradictions

`check_data.bat` exists exactly for this. It never guesses and never silently
picks a side. It says things like:

- `Teacher T014 is given 22 hours but the contract says 18.`
- `Curriculum row C07 / PHYS - teacher 'T099' is not in the Teachers sheet.`
- `Rooms of type 'lab_sci': need 90 hours but only 2 x 40 = 80 available.`

You fix the sheet, run it again. It changes nothing on its own - it only tells
you what disagrees with what.

## Partial data is fine

You do not need the full school to start. Load 5 classes and 8 teachers and run
it. It will produce a timetable for those 5 classes. Add more and re-run.
Nothing about the tool requires completeness.

## A teacher leaves in November

1. Delete their row in the Teachers sheet.
2. Put the replacement in, and change the `teacher_id` in the Curriculum rows.
3. **Pin everything you want to keep** into the Locked sheet.
4. Re-run.

The solver rebuilds only what it must and leaves the rest of the school
untouched. This is the part that is impossible by hand - today one teacher
leaving means re-doing the whole timetable.

## Version history

The project is a git repository, so every version of the rules and the code is
kept and you can go back to any of them.

**Your data is deliberately NOT in it** - see `docs/PRIVACY.md`. To keep old
timetables, copy `out/timetable.xml` to something like
`out/archive/2026-09-15-before-Ahmed-left.xml`. Keep those on this PC only.
