# What I need from you

Everything goes into **`data\school.xlsx`**. One sheet per batch below.

**Send it in batches. Do not wait until everything is ready.** Five classes and
eight teachers is enough for a first real run, and a real run teaches us more
than another week of collecting.

Every field says **why** it exists. If a field has no purpose you recognise,
say so and I will remove it — an unused column is just a chance to make a
mistake.

**Nothing here leaves your computer.** `data\` is blocked from git. See
`docs/PRIVACY.md`.

---

# BATCH 1 — Classes  (sheet: Classes)

The 41 class names are already recovered from last year's file, so this is
mostly checking, not typing.

| column | what | why it matters |
|---|---|---|
| `id` | short code, e.g. `C01` | must never change once set — that is what makes re-running safe |
| `name` | as it should print, e.g. `4رياضيات1` | goes on the printed timetable |
| `grade` | **1, 2, 3 or 4** | almost every ministry rule is per level |
| `stream` | Letters / Sciences / Maths / Economics / Computer Science / Experimental / Technical | decides which curriculum table applies |
| `size` | **number of pupils** | **H16**: a class of 24 or fewer is not split into groups. Without this I cannot tell whether a lab session splits |
| `home_room` | room id, or blank | reduces pupils walking between rooms |
| `is_bac` | yes for 4th year | bac has its own ministry rules: a free afternoon, PE as one 2-hour block, exemption from morning/evening spreading |

**One thing to fix while you are there:** `3أداب1` is spelled with أ while
`2آداب1` and `4آداب1` use آ. Harmless in aSc, but it breaks any name matching.

---

# BATCH 2 — Rooms  (sheet: Rooms)

45 rooms. This is the batch where the *building* matters.

| column | what | why it matters |
|---|---|---|
| `id` | `R01`… | stable code |
| `name` | as it prints | |
| `type` | normal / lab_phys / lab_chem / lab_sci / it / gym / tech / music / arts | the ministry insists specialised rooms are used **for their subject and nothing else** |
| `capacity` | max pupils | a room smaller than a class can only take a half-group |
| **`zone`** | **which part of the building** | see below |
| `computers` | for IT labs only | ministry rule: pupils in a lab must not exceed **twice** the number of computers |
| `notes` | free text | e.g. "shared with the primary school on Tuesdays" |

## About `zone` — this is the part you offered and it does matter

Write a short label for where the room physically is. Anything consistent:

```
A-rez      building A, ground floor
A-1        building A, first floor
B-rez      building B, ground floor
stade      the stadium
```

**Why:** if a class has Physics in `A-1` and then Sport in `stade`, the walk
eats into both lessons. Right now the solver has no idea the stadium is far
away, so it will happily put a lesson right after PE. With `zone` filled in it
can avoid that.

You do **not** need exact distances. Just tell me which rooms are near each
other. If two zones are far apart, add a row to the **Zones** sheet:

| from | to | walk_minutes |
|---|---|---|
| A-rez | stade | 8 |
| A-1 | B-rez | 4 |

Leave the Zones sheet empty and everything is treated as close together — which
is what the solver assumes today.

## The stadium specifically

- Is `Stad 1 / 2 / 3` really three separate spaces, or one field split by
  convention? *(It changes whether three classes can genuinely be there at once.)*
- How long to walk there and back?
- What happens to PE when it rains — does the lesson move indoors, or is it lost?

---

# BATCH 3 — Teachers  (sheet: Teachers)

The 93 names are already imported from the ministry list. **Their national ID
numbers were deliberately not copied** — a timetable does not need them.

Still empty, because the ministry list does not contain them and **I will not
invent them**:

| column | what | why it matters |
|---|---|---|
| `hours` | contracted hours per week | without it I cannot tell overload from a full load |
| `day_off` | the free day, or blank | a hard rule — that day stays completely empty |
| `training_day` | pedagogical training day (يوم التكوين) | the circular says it must be free **and** must not count when balancing the week |
| `compact` | **yes** for the exception list | see below |
| `notes` | free text | |

## The `compact` column — the exception you asked for

Default is the ministry rule: hours **spread across most days of the week**.

You said some teachers travel a long way, and spreading them over five days
means five journeys. Those teachers get `compact = yes` and are packed into
fewer, longer days instead.

**You said you would send that list.** Write the names here whenever you like —
the column already exists and is empty, so everyone currently gets the ministry
default.

## Also needed, and not in the ministry list

- **Trainees (المتربّصون)** — 1st and 2nd year trainees must be free on
  **Saturday**. Who are they?
- **Teachers working at a second school** — which ones, and when are they
  elsewhere? Those hours go in the **Unavailable** sheet as hard blocks.
- **The two vacancies** in the ministry list — arriving, or staying empty?

---

# BATCH 4 — Who teaches what  (sheet: Curriculum)

The big one. One row per **class + subject**.

| column | what | why it matters |
|---|---|---|
| `class_id` | from Classes | |
| `subject_id` | from Subjects | |
| `hours` | per week | I can pre-fill this from `rules/curriculum.json` once Batch 1 exists |
| `teacher_id` | who teaches it | blank means the solver may choose |
| `blocks` | how the hours split, e.g. `2+1+1` | from the ministry tables |
| **`groups`** | **1 = whole class, 2 = split** | see below |
| `room_type` | override, or blank | |

## About `groups`

Last year, `4رياضيات1` split into two groups for Natural Sciences and Physics —
but ran **Computer Science whole-class**. That is what you meant by *"we were
few, so we were treated as one group"*.

So this is **per class and subject**, not per subject. Default is **1** — I will
never assume a split.

The ministry: a class of **24 pupils or fewer is not split**. Once `size` is
filled in, the checker warns if a small class is set to split.

---

# BATCH 5 — Exceptions  (sheet: Unavailable)

Only where they exist. One row per blocked slot.

| column | what |
|---|---|
| `teacher_id` | |
| `day` | or `*` for every day |
| `period` | or `*` for the whole day |
| `hard` | **yes** = never schedule. **no** = prefer not to |
| `reason` | free text |

## About `reason` — please read this one

This is the most sensitive field in the whole project. It exists so the report
can explain *why* a decision was made, and so you can defend it to staff.

**Write only what the timetable needs.** "Not available Tuesday morning" is
enough. A medical condition, a family situation, a personal difficulty — the
solver does not need any of it, and data you never write down can never leak.

---

# BATCH 6 — Options  (rule H14)

Your optional subjects, confirmed by both the circular and last year's file:
**third foreign language** (Spanish / German / Italian), **Music**, **Plastic
Arts (تشكيلية)**.

I still need:

- Does every pupil take exactly one option, or can they take none?
- How many classes typically pool into one option group?
- Must pooled classes be the same level and stream?
- **Is this the same thing as "a teacher teaching 3 portions of 3 classes"?**

---

# The fastest useful order

1. **Batch 1** (Classes) — unlocks the curriculum, which I can then pre-fill
2. **Batch 2** (Rooms) — the second real constraint after teachers
3. **Batch 3** (Teachers: hours and days off)
4. **Batch 4** (Curriculum) — the big one, and mostly automatic after 1
5. Batches 5 and 6 whenever

Send Batch 1 for **five classes** and I will run the whole pipeline on them the
same day. A small real run finds more problems than a large imagined one.
