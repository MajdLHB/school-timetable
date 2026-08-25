# Example data

`school_example.xlsx` is a **small fictional school** showing how to fill
the data workbook. Every name in it is invented.

This project is a **constraint-solver timetable generator built primarily
for Tunisian secondary schools**: it enforces the ministry rules (circular
51/2018 and the inspectorate texts) as hard mathematical constraints,
optimises teacher and pupil comfort as weighted soft rules, and exports the
finished timetable as XML that imports into **aSc TimeTables 2013**
(days/groups/weeks/options formats all proven against the real program).

Try it:

```bash
python solver/data.py  examples/school_example.xlsx   # plain-language check
python solver/solve.py examples/school_example.xlsx   # solve it
python solver/verify.py examples/school_example.xlsx  # independent re-check
```

The `READ ME` sheet inside the file explains every demonstrated feature:
session block patterns, half-class groups, week A/B and alternating-group
fortnights, pooled option bands, flexible days off, pinned lessons, and the
editable rule-weights sheet (including `HARD` promotion).

To start your own school from a blank workbook:

```bash
python tools/make_workbook.py
```

Real school data belongs in `data/`, which never enters git - see
`docs/PRIVACY.md`.
