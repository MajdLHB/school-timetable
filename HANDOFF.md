# HANDOFF - read this first

**If you are an AI assistant who has just been given this project: read this
file completely, then `docs/RULES.md`, then `docs/ASC_XML.md`. That is enough to
continue. Do not ask the user to re-explain anything written here.**

---

## Who and what

The user is a school administrator in Tunisia who builds the timetable for a
secondary school by hand every year, using **aSc TimeTables 2013** (`roz.exe`).

- **~100+ teachers**
- **~40 classes**
- **only 20 physical rooms**
- morning and evening sessions

Doing it by hand takes enormous effort and still produces poor results: teachers
with a single 1-hour day, holes in the middle of a teacher's day, hard subjects
stacked in the evening. Staff are unhappy, pupils suffer.

## The core decision - do not change this without a real reason

**The AI does not place lessons. A constraint solver places lessons.**

An LLM asked to place ~1200 lessons will silently break a rule it respected 500
placements earlier. So instead:

- **AI** writes and maintains the rules, the solver code, and the checker.
- **OR-Tools CP-SAT** (Python, local, free) does the actual placement.
- **`verify.py`** - independent code from the solver - re-checks the finished
  result from scratch. If solver and checker disagree, stop and fix.

Hard constraints are then mathematically impossible to violate.
This was explained to the user and they accepted it. Do not quietly revert to
"let me just write the timetable for you."

## Where things live - the code is the memory, not the chat

```
README.md              overview and pipeline
HANDOFF.md             this file
docs/RULES.md          *** THE SOURCE OF TRUTH *** every rule, plain language
docs/ASC_XML.md        aSc integration - format VERIFIED against the real app
docs/DATA_MODEL.md     the six CSV schemas
docs/OPEN_QUESTIONS.md what is still blocking
data/*.csv             the user's real data (templates for now)
test/*.xml             aSc import probes (Test 1 - already passed)
out/                   generated timetable.xml + report.md
```

Any rule not written in `docs/RULES.md` does not exist. When the user states a
new rule in chat, **write it into RULES.md immediately** and add a change-log
line. That is the whole mechanism that survives context loss.

## Settled facts - do not re-investigate these

1. `.roz` is proprietary binary from 2005. **Never write `.roz` directly.**
2. The bridge is XML: `File > Import > aSc Timetables XML`.
3. **Test 1 passed on 2026-08-24.** The working format is explicit `<lessons>`
   with our ids + `<cards>` referencing `lessonid`, with `days` as a **bitmask
   string** (`10000` = Monday). The flat `day="1" period="1"` card form does
   **not** place cards - it only adds unplaced lessons. Full detail and the exact
   two-dialog import procedure are in `docs/ASC_XML.md`.
4. Python 3.13 is installed. OR-Tools was installed on 2026-08-24.
5. Arabic print designs already exist in the aSc `designs/` folder and keep
   working - aSc does the printing, we only feed it data.

## The structural constraint that shapes everything

**40 classes, 20 rooms.** At most 20 classes can be in a room in any single
period. This - not teacher preferences - is the binding constraint and the real
source of the ugly timetables. The morning/evening cohort structure is how the
school absorbs it. Get this right before modelling anything else.

## Working style the user asked for

- Honesty over reassurance. They explicitly said they do not want tokens and
  time wasted, and they fear AI mistakes. Tell them plainly when something fails.
- Small verified steps. Prove each piece works before building on it.
- The user is not a programmer. They edit CSVs and click in aSc. They never
  touch Python. Keep it that way.
- English is not their first language. Write plainly, short sentences.

## Status - 2026-08-24

**The tool exists and works end to end**, proven on a fake school the size of
the real one (40 classes, 20 rooms, 37 teachers, 580 lesson-hours):

- [x] aSc XML bridge proven against the real `roz.exe` (Test 1)
- [x] `solver/data.py` - load + plain-language validation
- [x] `solver/solve.py` - CP-SAT model, H1-H8/H10 hard, S1/S2/S3/S6/S7/S8 soft
- [x] `solver/emit_asc.py` - writes the proven aSc XML form
- [x] `solver/verify.py` - independent checker, reads the XML off disk
- [x] `run.bat`, `check_data.bat` - what the user actually double-clicks
- [x] `tools/make_workbook.py` (blank input), `tools/make_demo.py` (fake school)
- [x] `tools/check_privacy.py` + `.gitignore` - data/ and out/ never committed
- [x] Demo runs, both verifier ALL GREEN:
      2 min  -> penalty 21575, 59% of teachers with a clean week, 9 one-hour days
      10 min -> penalty 11730, 95% clean weeks, 2 one-hour days, 4 pupil gaps
      Still improving at 10 min. Time buys comfort, never correctness.

### Not done
- [ ] **Structural questions unanswered** - `docs/OPEN_QUESTIONS.md`.
      Cohort structure (AM/PM), days per week and periods per day are guesses
      in `config.json` right now.
- [ ] No real data loaded. User has PDFs to convert.
- [ ] Most soft rules are untuned; weights are first guesses.
- [ ] Blocks (`2+1` double hours) are parsed but NOT yet enforced - every
      lesson is currently placed as a single hour. This is the biggest known
      gap. Rule H9 in RULES.md is still SPEC, not CODED.
- [ ] Cohort AM/PM is read from the Classes sheet but not yet constrained.
- [ ] The `<periods>` block in the emitted XML is the one element never tested
      against real aSc. If import misbehaves, drop it (see emit_asc.py).

## Next action

1. Get the structural answers, fix `config.json` to match the real school.
2. Ingest the PDFs into `data/school.xlsx` in batches.
3. Implement H9 (double-hour blocks) and the AM/PM cohort constraint.
4. Tune weights with the user against real output.
