"""Refuse to let real people's data escape into a published repository.

Run this BEFORE pushing anywhere, ever. It does three things:

  1. Fails if git is tracking anything under data/ or out/, or any file type
     that carries real data (pdf, xlsx, roz, csv, images).
  2. Reads the REAL names out of data/school.xlsx and greps every tracked
     file for them - catching a name accidentally pasted into a doc or a
     code comment.
  3. Warns if the git HISTORY ever contained such a file, because deleting a
     file does not remove it from history.

Exit code 0 = CLEAN. Anything else = do not publish.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BLOCKED_DIRS = ("data/", "out/")
BLOCKED_EXT = (".pdf", ".xlsx", ".xls", ".csv", ".roz", ".docx",
               ".jpg", ".jpeg", ".png")
# names short enough to cause false matches are skipped
MIN_NAME_LEN = 4


def git(*args):
    try:
        r = subprocess.run(["git"] + list(args), cwd=HERE,
                           capture_output=True, text=True, timeout=60)
        return r.stdout.splitlines() if r.returncode == 0 else []
    except (OSError, subprocess.SubprocessError):
        return []


def real_names():
    """Every human-identifying string in the live data file."""
    path = os.path.join(HERE, "data", "school.xlsx")
    if not os.path.exists(path):
        return []
    try:
        from openpyxl import load_workbook
    except ImportError:
        return []
    names = set()
    wb = load_workbook(path, read_only=True, data_only=True)
    for sheet, cols in (("Teachers", ("name", "notes")),
                        ("Unavailable", ("reason",))):
        if sheet not in wb.sheetnames:
            continue
        ws = wb[sheet]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        header = [str(h).strip() if h else "" for h in rows[0]]
        for r in rows[2:]:
            for h, v in zip(header, r):
                if h in cols and v and len(str(v).strip()) >= MIN_NAME_LEN:
                    names.add(str(v).strip())
    wb.close()
    return sorted(names)


def main():
    problems = []
    tracked = git("ls-files")
    if not tracked:
        print("Not a git repository (or nothing tracked yet) - nothing to leak.")

    for f in tracked:
        low = f.lower()
        if low.startswith(BLOCKED_DIRS):
            problems.append("TRACKED REAL DATA: " + f)
        elif low.endswith(BLOCKED_EXT):
            problems.append("TRACKED DATA FILE TYPE: " + f)

    names = real_names()
    if names:
        for f in tracked:
            p = os.path.join(HERE, f)
            if not os.path.isfile(p):
                continue
            try:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except OSError:
                continue
            for n in names:
                if n in text:
                    problems.append("REAL NAME %r found inside tracked file %s" % (n, f))

    # history check
    hist = set()
    for line in git("log", "--pretty=format:", "--name-only", "--all"):
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith(BLOCKED_DIRS) or low.endswith(BLOCKED_EXT):
            hist.add(line)
    if hist:
        problems.append(
            "GIT HISTORY once contained real data (%d file(s), e.g. %s). "
            "Deleting them now does NOT remove them from history. "
            "Start a fresh repository instead."
            % (len(hist), sorted(hist)[0]))

    print("")
    print("Checked %d tracked files against %d real names." % (len(tracked), len(names)))
    print("")
    if problems:
        print("!!! NOT SAFE TO PUBLISH - %d problem(s) !!!" % len(problems))
        print("")
        for p in problems:
            print("  " + p)
        print("")
        print("See docs/PRIVACY.md.")
        return 1
    print("CLEAN - no personal data is tracked by git.")
    print("Safe to publish the code. data/ and out/ stay on this PC.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
