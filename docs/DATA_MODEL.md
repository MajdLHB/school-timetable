# Data model

## You edit ONE file: `data/school.xlsx`

Open it in Excel. One sheet per table, coloured headers, dropdown menus,
a HOW TO sheet, and a hint row under every heading. Arabic and French both fine.

**You never edit CSV, and you never edit code.**

CSV is only the internal storage format the program uses underneath - the
tables below document what each column means, but you fill them in Excel.
Or just send me the PDFs and I will fill them for you.

Regenerate a blank workbook: `python tools/make_workbook.py`
(it refuses to overwrite a workbook that already contains data).

---

### `data/teachers.csv`
| column | meaning |
|---|---|
| `id` | short unique code, no spaces (e.g. `T01`) |
| `name` | full name as it should print |
| `short` | 2-4 letters shown in the grid cell |
| `subjects` | subjects they can teach, `;` separated |
| `hours` | contracted hours per week |
| `day_off` | `Mon`/`Tue`/... or blank if none |
| `training_day` | pedagogical training day - kept fully empty, like a day off (H7, circular II.1) |
| `compact` | `yes` = pack this teacher's week into fewer days (the long-journey exception). Blank = ministry default: hours spread across working days (S8, circular II.2) |
| `notes` | free text, for us - not read by the solver |

### `data/classes.csv`
| column | meaning |
|---|---|
| `id` | e.g. `C01` |
| `name` | e.g. `2 Sciences 3` |
| `grade` | level number (1,2,3,4) |
| `stream` | which stream (LETTERS / SCIENCES / MATHS / ...) - drives the curriculum |
| `is_bac` | `yes` for 4th year - drives S13 (no Friday evening) and S17 (free afternoon Mon-Thu, circular I.6) |
| `cohort` | `AM` / `PM` / `ALL` - which session this class attends |
| `home_room` | room id, or blank |
| `size` | number of pupils - H16: no group split at 24 or fewer |

### `data/rooms.csv`
| column | meaning |
|---|---|
| `id` | e.g. `R01` |
| `name` | printed name |
| `type` | `normal` / `lab_phys` / `lab_chem` / `lab_sci` / `it` / `gym` / `tech` |
| `capacity` | max pupils |

### `data/subjects.csv`
| column | meaning |
|---|---|
| `id` | e.g. `MATH` |
| `name` | printed name (Arabic or French) |
| `short` | grid abbreviation |
| `difficulty` | `hard` / `medium` / `easy` - drives rules S3 and S4 |
| `room_type` | required room type, or `normal` |
| `latest_period` | HARD daylight cutoff (H15) - last period allowed. Sport = 8 (ends 16:00). Blank = any |
| `avoid_after` | SOFT late-hour avoidance (S16) - prefer not after this period. Maths = 8 (M-MA3), Physics = 9 (M-PH5). Blank = none |
| `minmax_exempt` | `yes` = exempt from the minimum-2-hours rules (S15) - PE and optional subjects, as circular I.2 says |

### `data/curriculum.csv` - the big one
One row per **class + subject**. This is what must be taught.
| column | meaning |
|---|---|
| `class_id` | from classes.csv |
| `subject_id` | from subjects.csv |
| `hours` | periods per week |
| `teacher_id` | who teaches it (blank = solver may choose from qualified staff) |
| `blocks` | how the hours split, e.g. `1+1+1` (3 singles) or `2+1` (a double + a single) |
| `room_type` | override the subject default, or blank |

### `data/unavailable.csv` - teacher constraints beyond the day off
One row per blocked slot. Leave empty if there are none.
| column | meaning |
|---|---|
| `teacher_id` | |
| `day` | `Mon`..`Sat`, or `*` for every day |
| `period` | period number, or `*` for the whole day |
| `hard` | `yes` = never schedule (H8). `no` = prefer not to (soft) |
| `reason` | free text, printed in the report so you can defend the decision |

---

## On IDs

Use short stable codes, never row numbers. If a teacher leaves, their row goes
away and nothing else shifts. This is what makes "re-run it in November" safe.
