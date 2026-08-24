# -*- coding: utf-8 -*-
"""Generate the Curriculum sheet from the Distribution sheet + curriculum.json.

Sources of truth:
  - rules/curriculum.json  : WHAT each stream studies (hours, session patterns)
  - Distribution sheet     : WHO teaches each stream, how many sections each
  - Classes sheet          : the real 41 classes with grade + stream

Documented first-draft policies (every deviation is written to
data/CURRICULUM_REPORT.md so nothing is silent):

  P1  hours = floor(pupil_hours), whole-class (groups=1). Fortnightly halves
      (PISL/CIV 1.5, HIST 3.5...) are DROPPED for now - they return with the
      Week A/B machinery. Flooring never inflates teacher loads, so it can
      never create false H10 contract errors.
  P2  blocks pattern written only when the circular's sessions are plain
      whole-class integers (fortnight entries dropped) and they sum to the
      hours. Anything with groups/alternation gets a blank pattern (free
      single hours) until the group machinery exists.
  P3  The Distribution gives section COUNTS per stream, not class numbers.
      Classes are paired to teachers deterministically: classes in id order,
      Distribution rows in sheet order. This pairing is a FREE CHOICE -
      swap classes between two teachers of the same subject+stream freely.
  P4  SPORT and TASH rows use the exact class lists in the Distribution
      notes column (official for TASH; synthetic test data for SPORT).
  P5  Options (ESP/ALL/ITA, MUS) are POOLED cross-class groups (H14, not
      built) - skipped entirely, listed in the report.
  P6  CS-stream IT splits by the component column: خ = ALGO, تك = ICT plus
      NET (3rd) / DB (4th). Subject rows ALGO/ICT/NET/DB are added to the
      Subjects sheet if missing (room type 'it').
  P7  TECHSCI TECH rows get a BLANK teacher (FLAG-6: the MECH/ELEC teacher
      model is unresolved) - the lessons are placed, the teacher is decided
      later by Majd.
  P8  core=yes on the circular's stream-defining subjects (1st year:
      Arabic/French/Maths). Adjustable.

Refuses to run if the Curriculum sheet already has data.

    python tools/make_curriculum.py
"""
import json
import math
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XLSX = os.path.join(HERE, "data", "school.xlsx")
CURJ = os.path.join(HERE, "rules", "curriculum.json")
REPORT = os.path.join(HERE, "data", "CURRICULUM_REPORT.md")

# Distribution column header -> (grade, stream code used in the Classes sheet)
COLMAP = {
    "1ث ج مشترك": (1, "COMMON"),
    "2آداب": (2, "LETTERS"), "2علوم": (2, "SCIENCES"),
    "2اقتصاد وخدمات": (2, "ECONOMY"), "2تكنلوجية اعلامية": (2, "IT_TECH"),
    "3آداب": (3, "LETTERS"), "3رياضيات": (3, "MATHS"),
    "3علوم تجريبية": (3, "EXPSCI"), "3علوم تقنية": (3, "TECHSCI"),
    "3اقتصاد وتصرف": (3, "ECONOMY"), "3علوم اعلامية": (3, "CS"),
    "4آداب": (4, "LETTERS"), "4رياضيات": (4, "MATHS"),
    "4علوم تجريبية": (4, "EXPSCI"), "4علوم تقنية": (4, "TECHSCI"),
    "4اقتصاد وتصرف": (4, "ECONOMY"), "4علوم اعلامية": (4, "CS"),
}
STREAM_KEY = {"LETTERS": "Y3_Y4_LETTERS", "MATHS": "Y3_Y4_MATH",
              "EXPSCI": "Y3_Y4_EXPSCI", "TECHSCI": "Y3_Y4_TECHSCI",
              "CS": "Y3_Y4_CS", "ECONOMY": "Y3_Y4_ECO"}
OPTION_SUBJECTS = {"ESP", "ALL", "ITA", "MUS", "LANG3"}
# P8: the circular's stream-defining subjects (III.2)
CORE = {
    (1, "COMMON"): {"ARAB", "FREN", "MATH"},
    (3, "MATHS"): {"MATH"}, (4, "MATHS"): {"MATH"},
    (3, "EXPSCI"): {"SVT", "PHYS"}, (4, "EXPSCI"): {"SVT", "PHYS"},
    (3, "TECHSCI"): {"TECH"}, (4, "TECHSCI"): {"TECH"},
    (3, "CS"): {"ALGO", "ICT"}, (4, "CS"): {"ALGO", "ICT"},
    (3, "ECONOMY"): {"ECO", "GEST"}, (4, "ECONOMY"): {"ECO", "GEST"},
    (3, "LETTERS"): {"ARAB", "PHIL"}, (4, "LETTERS"): {"ARAB", "PHIL"},
}


def node_for(streams, grade, stream):
    """The curriculum.json subject table for one (grade, stream)."""
    if grade == 1:
        return streams["Y1_COMMON"]["subjects"]
    if grade == 2:
        return streams["Y2"]["by_stream"][stream]["subjects"]
    return streams[STREAM_KEY[stream]]["Y%d" % grade]


def hours_and_blocks(node):
    """P1 + P2. Returns (hours, blocks_string, flags)."""
    flags = []
    ph = node.get("pupil_hours")
    if ph is None:
        return 0, "", ["no pupil_hours in curriculum.json"]
    hours = int(math.floor(ph))
    if hours != ph:
        flags.append("pupil_hours %.2f floored to %d (fortnightly part "
                     "dropped until Week A/B exists)" % (ph, hours))
    sessions = node.get("sessions", [])
    wholes, clean = [], True
    for se in sessions:
        if list(se.keys()) == ["whole"]:
            wholes.append(int(se["whole"]))
        elif list(se.keys()) == ["fortnight_whole"]:
            continue                       # dropped by P1
        else:
            clean = False
    blocks = ""
    if clean and node.get("_no_groups") and wholes and sum(wholes) == hours:
        blocks = "+".join(str(w) for w in sorted(wholes, reverse=True))
    elif not node.get("_no_groups"):
        flags.append("has group/alternating sessions - placed whole-class, "
                     "no block pattern, until the group machinery exists")
    return hours, blocks, flags


def class_names_in(text, name_to_id):
    """Find real class names inside a free-text note."""
    found = []
    for name, cid in name_to_id.items():
        if name and name in (text or ""):
            found.append((name, cid))
    return [cid for _n, cid in sorted(found)]


def main():
    from openpyxl import load_workbook

    streams = json.load(open(CURJ, encoding="utf-8"))["streams"]
    wb = load_workbook(XLSX)
    cur_ws = wb["Curriculum"]
    if cur_ws.max_row > 2:
        sys.exit("REFUSING: the Curriculum sheet already has data. Clear it "
                 "first if you want a regeneration.")

    # ---- classes by (grade, stream) --------------------------------------
    classes = []            # (id, name, grade, stream)
    rows = list(wb["Classes"].iter_rows(values_only=True))
    header = [str(h or "").strip() for h in rows[0]]
    for r in rows[2:]:
        rec = dict(zip(header, r))
        if not rec.get("id"):
            continue
        classes.append((str(rec["id"]), str(rec.get("name") or ""),
                        int(float(rec.get("grade") or 0)),
                        str(rec.get("stream") or "").strip()))
    by_gs = {}
    name_to_id = {}
    for cid, name, grade, stream in classes:
        by_gs.setdefault((grade, stream), []).append(cid)
        name_to_id[name] = cid
    for k in by_gs:
        by_gs[k].sort()

    # ---- distribution rows ------------------------------------------------
    drows = list(wb["Distribution"].iter_rows(values_only=True))
    dheader = [str(h or "").strip() for h in drows[0]]
    dist = []
    for r in drows[2:]:
        rec = dict(zip(dheader, r))
        if rec.get("subject"):
            dist.append(rec)

    # ---- existing subject ids; add the CS components if missing (P6) ------
    subj_ws = wb["Subjects"]
    subj_ids = {str(r[0]).strip() for r in
                list(subj_ws.iter_rows(values_only=True))[2:] if r and r[0]}
    CS_SUBJ = {"ALGO": "خوارزميات وبرمجة", "ICT": "تكنولوجيات المعلومات",
               "NET": "الشبكات والأنظمة", "DB": "قواعد البيانات"}
    added_subjects = []
    for sid, name_ar in CS_SUBJ.items():
        if sid not in subj_ids:
            subj_ws.append([sid, name_ar, sid, "", "it"])
            subj_ids.add(sid)
            added_subjects.append(sid)

    report = ["# Curriculum generation report",
              "",
              "Generated by tools/make_curriculum.py. The policies P1-P8 are",
              "documented at the top of that file. EVERYTHING unusual is",
              "listed below - if a row is not listed, it came straight from",
              "the circular and the official distribution.",
              ""]
    R = report.append

    out_rows = []          # (class_id, subject_id, hours, teacher, blocks, core)
    flags_hours = set()
    unassigned = []        # (class, subject) with no teacher
    skipped = []           # option rows skipped

    # ---- P3: assign sections to classes, per subject ----------------------
    # assign[(class, subject)] = teacher_id
    assign = {}
    over = []
    # cursor per (grade, stream, subject) walking the sorted class list
    cursor = {}
    for rec in dist:
        subj = str(rec["subject"]).strip()
        tid = str(rec.get("teacher_id") or "").strip()
        comp = str(rec.get("component") or "").strip()
        notes = str(rec.get("notes") or "")
        if subj in OPTION_SUBJECTS:
            skipped.append((subj, tid, rec.get("hours_assigned")))
            continue
        if subj in ("SPORT", "TASH"):
            # P4: exact class lists live in the notes column
            for cid in class_names_in(notes, name_to_id):
                key = "TASH" if subj == "TASH" else "SPORT"
                assign[cid, key] = tid
            continue
        if subj in ("MECH", "ELEC"):
            continue       # P7 - reported below via TECH rows
        for col, (grade, stream) in COLMAP.items():
            n = rec.get(col)
            if not n:
                continue
            n = int(float(n))
            pool = by_gs.get((grade, stream), [])
            # CS-stream IT rows split into components
            targets = [subj]
            if subj == "IT" and stream == "CS":
                if comp == "خ":
                    targets = ["ALGO"]
                elif comp == "تك":
                    targets = ["ICT", "NET"] if grade == 3 else ["ICT", "DB"]
            for t_subj in targets:
                cur = cursor.get((grade, stream, t_subj), 0)
                take = pool[cur:cur + n]
                if len(take) < n:
                    over.append("%s %s: %s wants %d sections of %s but only %d "
                                "classes remain unassigned" %
                                (subj, tid, col, n, stream, len(take)))
                for cid in take:
                    assign[cid, t_subj] = tid
                cursor[(grade, stream, t_subj)] = cur + len(take)

    # ---- build the curriculum rows from curriculum.json -------------------
    guessed_it = []
    for cid, cname, grade, stream in sorted(classes):
        try:
            table = node_for(streams, grade, stream)
        except KeyError:
            R("- **%s (%s)**: no curriculum table for grade %d stream %s - "
              "NO ROWS generated. Fix the stream code." % (cid, cname, grade, stream))
            continue
        subs = dict(table)
        # f7: 2علوم/2آداب IT exists on the official sheets (~2h) but not in
        # curriculum.json. If a teacher was assigned, emit a GUESSED row.
        if (cid, "IT") in assign and "IT" not in subs:
            subs["IT"] = {"pupil_hours": 2.0, "sessions": [{"group": 4}]}
            guessed_it.append(cid)
        for sid, node in subs.items():
            if sid.startswith("_"):
                continue
            if sid in OPTION_SUBJECTS:
                continue
            hours, blocks, hf = hours_and_blocks(node)
            if hours <= 0:
                continue
            for f in hf:
                flags_hours.add("%s: %s" % (sid, f))
            tid = assign.get((cid, sid), "")
            if not tid and sid == "TECH" and stream == "TECHSCI":
                pass       # P7, reported once below
            elif not tid and sid not in ("SPORT", "TASH"):
                unassigned.append((cid, sid))
            core = "yes" if sid in CORE.get((grade, stream), set()) else ""
            out_rows.append((cid, sid, hours, tid, blocks, core))
        # TASH: only for classes named on the official art sheet
        if (cid, "TASH") in assign:
            out_rows.append((cid, "TASH", 2, assign[cid, "TASH"], "2", ""))

    # ---- write ------------------------------------------------------------
    for cid, sid, hours, tid, blocks, core in out_rows:
        # Columns: class_id, subject_id, hours, teacher_id, blocks, groups,
        # room_type, core
        cur_ws.append([cid, sid, hours, tid, blocks, 1, "", core])
    wb.save(XLSX)

    # ---- report -----------------------------------------------------------
    R("## Numbers")
    R("")
    R("- %d curriculum rows written for %d classes" % (len(out_rows), len(classes)))
    R("- %d rows have a teacher; %d are BLANK (listed below)"
      % (sum(1 for r in out_rows if r[3]), sum(1 for r in out_rows if not r[3])))
    if added_subjects:
        R("- Subjects added for the CS stream (P6): " + ", ".join(added_subjects))
    R("")
    R("## P1 - hours floored / group subjects placed whole-class")
    R("")
    for f in sorted(flags_hours):
        R("- " + f)
    R("")
    R("## P3 - the class pairing is a FREE choice")
    R("")
    R("Classes were paired to teachers in id order, Distribution rows in")
    R("sheet order. The official sheets only fix the COUNTS per stream.")
    R("Swap classes between two teachers of the same subject freely.")
    if over:
        R("")
        R("**Count mismatches:**")
        for o in over:
            R("- " + o)
    R("")
    R("## Rows with a BLANK teacher")
    R("")
    R("These lessons ARE placed in the timetable, but nobody teaches them")
    R("yet - the solver applies no teacher rules to them. Decide and fill.")
    R("")
    tech_blank = sorted(set(c for c, s in unassigned if s == "TECH"))
    if tech_blank:
        R("- **TECH for %s** - FLAG-6: the MECH/ELEC teacher model is "
          "unresolved (each engineering teacher has both classes of one "
          "year at 16h). Majd decides." % ", ".join(tech_blank))
    for cid, sid in sorted(u for u in unassigned if u[1] != "TECH"):
        R("- %s / %s" % (cid, sid))
    R("")
    R("## P5 - options skipped (pooled groups, H14 not built)")
    R("")
    for subj, tid, h in skipped:
        R("- %s (teacher %s, %s h on the official sheet)" % (subj, tid, h))
    if guessed_it:
        R("")
        R("## GUESSED rows")
        R("")
        R("- IT 2h for %s - on the official sheets but not in the circular "
          "guide (curriculum.json). Confirm the hours." % ", ".join(guessed_it))
    R("")
    R("## Known carried-over guesses")
    R("")
    R("- ENGL أسماء بن طاهر: one 3ع-إعلا section moved to 3ع-تج in the "
      "Distribution (documented guess) - the pairing here inherits it.")
    R("- SPORT class lists are synthetic test data (FLAG-8).")

    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(report))
    print("Wrote %d curriculum rows." % len(out_rows))
    print("Report: %s" % REPORT)


if __name__ == "__main__":
    main()
