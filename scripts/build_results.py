"""Assemble the final results.csv: real rows (already in results.csv) + stand-in rows + your grades.

- keeps every source=real row in results.csv
- replaces any stand-in rows with the current results/raw/results_standin.csv
- copies answer_grade from results/quality_grading.csv (which you fill in) onto the matching request_id
Safe to rerun. Run: python scripts/build_results.py
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN, STANDIN, GRADES = ROOT / "results.csv", ROOT / "results/raw/results_standin.csv", ROOT / "results/quality_grading.csv"
VALID = {"", "correct", "wrong", "refused_correctly", "refused_wrongly"}

rows = [r for r in csv.DictReader(open(MAIN))] if MAIN.exists() else []
cols = list(rows[0].keys()) if rows else None
real = [r for r in rows if r["source"] == "real"]
standin = list(csv.DictReader(open(STANDIN))) if STANDIN.exists() else []
cols = cols or (list(standin[0].keys()) if standin else None)
grades = {}
if GRADES.exists():
    for g in csv.DictReader(open(GRADES)):
        grade = g["answer_grade"].strip().lower()
        if grade not in VALID:
            raise SystemExit(f"{g['request_id']}: answer_grade '{grade}' must be one of {sorted(VALID - {''})}")
        grades[g["request_id"]] = grade
for r in real:
    if r["request_id"] in grades:
        r["answer_grade"] = grades[r["request_id"]]
with open(MAIN, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=cols)
    w.writeheader(); w.writerows(real + standin)
ungraded = sum(1 for r in real if r["scenario"] == "quality" and not r["answer_grade"])
print(f"results.csv: {len(real)} real + {len(standin)} stand-in rows; {len(grades)} grades applied; "
      f"{ungraded} quality rows still ungraded")
