# How it works

## What happens when you double-click `run.bat`

```
   data/school.xlsx
        |
   [1] solver/data.py      reads it, checks it makes sense
        |                  ("Teacher T014 is given 22 hours, contract is 18")
        |                  stops here if anything is wrong. Nothing is guessed.
        |
   [2] solver/solve.py     turns every lesson-hour into a yes/no question:
        |                  "does class C07's 3rd Maths hour go in Tuesday period 4?"
        |                  580 lessons x 40 periods = 23,200 such questions.
        |                  CP-SAT answers all of them at once, obeying every
        |                  hard rule, while making the soft penalties as small
        |                  as it can. It prints each improvement as it goes.
        |
        +--> out/timetable.xml    aSc format, already placed
        +--> out/report.md        what it achieved and what it could not
        |
   [3] solver/verify.py    re-opens out/timetable.xml FROM DISK - the same
                           bytes aSc will read - and re-checks every hard rule
                           from scratch. Shares no code with the solver.
                           Prints ALL GREEN, or refuses.
```

Then you import `out/timetable.xml` into aSc and work in aSc as you always have.

## Why the solver cannot make the mistakes you are afraid of

The rules are not advice the program tries to follow. They are **equations it
must satisfy**. "Teacher T012 is in at most one place during Tuesday period 3"
is written as an equation over yes/no variables. A solution that breaks it is
not a bad solution - it is *not a solution*, and the solver cannot return one,
in the same way a calculator cannot return 5 for 2+2.

That is the whole reason we are not asking an AI to place lessons.

## Why there is a separate checker

Because the solver could have the *wrong equations*. If I encoded a rule badly,
the solver would faithfully satisfy the wrong thing.

So `verify.py` is written separately, reads the finished file rather than the
solver's memory, and re-derives every check from the source data. If the two
disagree, something is wrong and you are told - instead of finding out in
October when a teacher shows up to a double-booked room.

## What the penalty number means

Each soft rule has a weight in `config.json`:

```json
"teacher_gap": 100,   "one_hour_day": 90,   "class_gap": 85,
"hard_subject_evening": 70,   "same_subject_twice_a_day": 50,
"extra_day_present": 40
```

The score is the weighted sum of everything it failed to achieve. **Lower is
better; 0 is perfect.** The numbers are meaningless on their own - they only
matter *relative to each other*. Doubling `teacher_gap` tells the solver
"I care about holes twice as much as before, sacrifice something else."

That is how you steer it without touching code.

## The three answers the solver can give

| answer | meaning | what to do |
|---|---|---|
| **OPTIMAL** | Best possible timetable, proven. | Use it. |
| **FEASIBLE** | Valid timetable; time ran out before proving it is the best. | Fine to use. Raise `time_limit_seconds` for better quality. |
| **INFEASIBLE** | **No timetable exists** obeying all your hard rules. | Not a bug. Something you asked for is impossible. Loosen a rule. |

INFEASIBLE is the most valuable answer it can give you. By hand you would spend
three weeks discovering the same thing.

## Measured performance - real numbers, not estimates

Run on this PC, on a fake school the size of yours
(40 classes, 20 rooms, 37 teachers, 580 lesson-hours, 40 periods/week):

| time limit | result | quality |
|---|---|---|
| 2 minutes | FEASIBLE, all hard rules green | 59% of teachers with a clean week, 9 one-hour days |

It was still improving when the clock stopped, so longer limits give better
timetables. Set `time_limit_seconds` to whatever you are willing to wait -
the run happens once, and you can leave it going over lunch.

**The important part: 100% of hard rules held at 2 minutes.** Extra time buys
comfort, never correctness.

## Where the numbers came from

Nothing above is a guess. `docs/ASC_XML.md` records what was tested against the
real aSc. The performance table is from an actual run. If a number in these
docs was estimated rather than measured, it says so.
