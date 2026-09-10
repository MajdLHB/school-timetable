# -*- coding: utf-8 -*-
"""Overnight batch for the FET bridge: run several comfort configurations
on one workbook, a few at a time (one FET process per core), long time
limits, fresh seeds, and collect the best of each into a summary.

    python tools/fet_batch.py data/school_official.xlsx out/fet/official_batch [--parallel 4] [--time 1800]

Each configuration writes to <outdir>/<name>/ (its own best/ folder); the
summary <outdir>/summary.txt lists every ALL GREEN result with its felt
numbers, sorted by the bridge's discomfort index. Safe to stop at any time:
finished configurations keep their files.
"""
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BRIDGE = os.path.join(HERE, "solver", "fet_bridge.py")

# name -> extra arguments (all get --no-pair-days --no-fortnight-zero --last-cap 0)
CONFIGS = [
    ("gaps2_bac", ["--teacher-gaps", "2", "--pupil-gaps", "-1", "--pupil-day-cap", "0",
                   "--no-max-half-days", "--no-soft"]),
    ("gaps2_only", ["--teacher-gaps", "2", "--pupil-gaps", "-1", "--pupil-day-cap", "0",
                    "--no-max-half-days", "--no-soft", "--no-bac-afternoon"]),
    ("gaps1_bac", ["--teacher-gaps", "1", "--pupil-gaps", "-1", "--pupil-day-cap", "0",
                   "--no-max-half-days", "--no-soft"]),
    ("gaps2_bac_ministry", ["--teacher-gaps", "2", "--pupil-gaps", "-1", "--pupil-day-cap", "ministry",
                            "--no-max-half-days", "--no-soft"]),
    ("gaps1_bac_soft", ["--teacher-gaps", "1", "--pupil-gaps", "-1", "--pupil-day-cap", "0",
                        "--no-max-half-days"]),
    ("gaps2_bac_trips", ["--teacher-gaps", "2", "--pupil-gaps", "-1", "--pupil-day-cap", "0",
                         "--no-soft"]),
    ("gaps1_bac_ministry", ["--teacher-gaps", "1", "--pupil-gaps", "-1", "--pupil-day-cap", "ministry",
                            "--no-max-half-days", "--no-soft"]),
    ("gaps2_bac_ministry_soft", ["--teacher-gaps", "2", "--pupil-gaps", "-1", "--pupil-day-cap", "ministry",
                                 "--no-max-half-days"]),
    ("gaps1_bac_pupilgaps2", ["--teacher-gaps", "1", "--pupil-gaps", "2", "--pupil-day-cap", "0",
                              "--no-max-half-days", "--no-soft"]),
    ("gaps1_bac_rounds", ["--teacher-gaps", "1", "--pupil-gaps", "-1", "--pupil-day-cap", "0",
                          "--no-max-half-days", "--no-soft", "--rounds", "3"]),
]


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "data", "school_official.xlsx")
    outdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(HERE, "out", "fet", "official_batch")
    parallel = int(sys.argv[sys.argv.index("--parallel") + 1]) if "--parallel" in sys.argv else 4
    tlimit = sys.argv[sys.argv.index("--time") + 1] if "--time" in sys.argv else "1800"
    attempts = sys.argv[sys.argv.index("--attempts") + 1] if "--attempts" in sys.argv else "2"
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(outdir, "batch.log"), "a", encoding="utf-8")

    def say(msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()
    queue = list(CONFIGS)
    running = []
    say("batch start: %d configurations, %d in parallel, %s s each, %s attempts" % (
        len(queue), parallel, tlimit, attempts))
    while queue or running:
        while queue and len(running) < parallel:
            name, extra = queue.pop(0)
            d = os.path.join(outdir, name)
            os.makedirs(d, exist_ok=True)
            cmd = [sys.executable, BRIDGE, xlsx, "--outdir", d, "--time", tlimit, "--attempts", attempts,
                   "--no-pair-days", "--no-fortnight-zero", "--last-cap", "0"] + extra
            f = open(os.path.join(d, "run.log"), "w", encoding="utf-8")
            p = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=HERE)
            running.append((name, p, f, time.time()))
            say("started %s" % name)
        time.sleep(30)
        for item in list(running):
            name, p, f, t0 = item
            if p.poll() is not None:
                f.close()
                running.remove(item)
                score = os.path.join(outdir, name, "best", "score.json")
                if os.path.exists(score):
                    with open(score, encoding="utf-8") as fh:
                        sc = json.load(fh)
                    say("done %s in %.0f s: ALL GREEN, discomfort %.1f, teacher holes %.1f, pupil holes "
                        "%.1f, last %s, trips %.2f" % (name, time.time() - t0, sc.get("discomfort", 0),
                                                     sc["teacher_holes"], sc["pupil_holes"],
                                                     sc.get("last_period"), sc.get("felt", {}).get("trips", 0)))
                else:
                    say("done %s in %.0f s: no ALL GREEN table" % (name, time.time() - t0))
                write_summary(outdir)
    say("batch finished")


def write_summary(outdir):
    rows = []
    for name in sorted(os.listdir(outdir)):
        score = os.path.join(outdir, name, "best", "score.json")
        if os.path.exists(score):
            with open(score, encoding="utf-8") as fh:
                sc = json.load(fh)
            rows.append((sc.get("discomfort", 9999), name, sc))
    rows.sort()
    with open(os.path.join(outdir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("ALL GREEN tables, best first (discomfort = teacher holes + pupil holes + 0.25 last "
                "+ 20 trips + 0.2 eight-hour days)\n\n")
        for disc, name, sc in rows:
            felt = sc.get("felt", {})
            f.write("%-28s discomfort %6.1f | teacher holes %5.1f | pupil holes %5.1f | last %4s | "
                    "trips %.2f | 8h days %3s | %s\n" % (name, disc, sc["teacher_holes"], sc["pupil_holes"],
                                                        sc.get("last_period"), felt.get("trips", 0),
                                                        felt.get("heavy", "?"), sc.get("when", "")))
        if not rows:
            f.write("(none yet)\n")


if __name__ == "__main__":
    main()
