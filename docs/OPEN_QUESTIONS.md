# Open questions - blocking work

## Test 1 - PROVE THE BRIDGE (do this first, ~10 minutes, no data needed)

Before we build anything, we prove aSc will accept a generated timetable.
I will write a tiny XML file: 4 teachers, 2 classes, 3 subjects, 2 rooms, and a
few **already-placed** cards. You:

1. Open `roz.exe`
2. New / blank document
3. `File > Import > aSc Timetables XML`, pick the file
4. Tell me what happens

**Pass** = the lessons appear, already sitting in the grid.
**Fail** = we switch to the Excel/clipboard import route instead (still works,
slightly more manual). Either way we find out in 10 minutes, not 10 sessions.

## Structure questions

1. **Periods per day** - how many, and where is the morning/evening split?
   (e.g. 4 morning + 4 evening?) What are the real clock times?
2. **Days** - Monday to Saturday? Is Saturday a half day?
3. **Cohorts** - 40 classes vs 20 rooms means at most 20 classes can be in a
   room at once. So: does cohort A come in the morning and cohort B in the
   evening? Or does every class come every day with free periods? **This is the
   single most important question** - it decides the whole shape of the model.
4. **Rooms** - of the 20, how many are specialised (labs, IT, gym) and which
   subjects are locked to them?
5. **Hard subjects** - which exactly count as "hard" for rule S3/S4?
6. **Break** - is there a lunch break that a double hour must not cross?

## Data you offered to give me

Give it in whatever form is easiest - PDF, photo of a paper list, Excel, or just
typed out class by class. I will convert it into the CSVs. Do it **in batches**,
one thing at a time:

- [ ] Batch 1: teacher list (name, subject, contracted hours, day off)
- [ ] Batch 2: class list (name, level/grade, cohort)
- [ ] Batch 3: room list (name, type, capacity)
- [ ] Batch 4: curriculum - for each class, each subject, hours per week, room type
- [ ] Batch 5: who teaches what - teacher assigned to each class+subject
- [ ] Batch 6: individual teacher preferences and unavailabilities

Batch 4 and 5 are the big ones. Everything else is quick.
