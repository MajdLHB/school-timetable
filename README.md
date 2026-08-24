# School Timetable Solver

Generates the timetable for our school automatically, then hands it to
**aSc TimeTables 2013** (`roz.exe`) for editing and printing.

## The idea in one line

Claude does not place the lessons. **A solver places the lessons.** Claude only
writes and maintains the solver, the rules, and the checker.

## Pipeline

```
data/*.csv            <- you fill these in (the only manual work)
      |
      v
  build_model.py      <- turns CSVs into constraints
      |
      v
  solve.py            <- OR-Tools CP-SAT finds a valid timetable (seconds)
      |
      +--> out/report.md      <- which preferences were met / missed, and WHY
      +--> out/timetable.xml  <- aSc TimeTables XML  ->  File > Import > aSc Timetables XML
      |
      v
  verify.py           <- INDEPENDENT check of the finished timetable.
                         Re-reads the rules and the result from scratch.
                         Must print ALL GREEN or we do not ship it.
```

## Why this is trustworthy

1. **Hard rules are mathematically impossible to break.** The solver cannot
   return a solution that violates them, the way a calculator cannot return 5
   for 2+2.
2. **`verify.py` is separate code** from `solve.py`. Two independent programs
   agreeing is the real guarantee. If they disagree, we stop and fix.
3. **Nothing lives in a chat window.** Rules live in `docs/RULES.md`, data lives
   in `data/`, logic lives in the `.py` files. Any future session (or any other
   person) reads the files and continues. The code is the memory.

## Cost

- Building it: a handful of working sessions. One time.
- Running it afterwards: **zero AI tokens**. It runs on this PC in ~30-120s.
  Re-run it any time: a teacher quits in November, edit one CSV line, re-run.

## Where everything is

| I want to... | file |
|---|---|
| know what to do next | **`TASKS.md`** |
| know what data to send | **`docs/WHAT_I_NEED_FROM_YOU.md`** |
| see the rules that are decided | `docs/RULES.md` |
| see what is still undecided | `docs/OPEN_QUESTIONS.md` |
| understand how the machine works | `docs/HOW_IT_WORKS.md` |
| know how to use it day to day | `docs/WORKFLOW.md` |
| know it is not making mistakes | `docs/VERIFICATION.md` |
| read the official circular | `docs/CIRCULAR_51_2018.md` |
| see all ~90 ministry rules, rated | `docs/MINISTRY_RULES.md` |
| find the official hours per stream | `rules/curriculum.json` |
| check nothing personal can leak | `docs/PRIVACY.md` |
| hand this to another AI | `HANDOFF.md` |
| things said but not yet decided | `docs/NOTES.md` |

**You edit one file: `data\school.xlsx`.** Nothing else.

## Status

- [x] **aSc XML bridge PROVEN** on the real app (2026-08-24). See `docs/ASC_XML.md`.
- [x] **Solver works end to end** on a 40-class / 20-room fake school.
      2 minutes -> valid timetable, independent verifier ALL GREEN.
- [ ] Structural questions unanswered - `docs/OPEN_QUESTIONS.md`.
- [ ] No real data loaded. Double-hour blocks and AM/PM cohorts not yet coded.

Try it right now with fake data:

```
python tools/make_demo.py
run.bat
```

New here? Read `HANDOFF.md`.
