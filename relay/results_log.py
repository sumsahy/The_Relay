"""Write one row per request to results.csv (exact columns from the brief) and full detail to a JSONL file.

results.csv            what reviewers recompute the tables from. Columns fixed by the brief.
results/raw/requests.jsonl  everything else: per-step timings, every LLM call with headers, claims, the answer.
answer_grade is left empty here and filled in by hand (or a grading script) afterwards.
"""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from relay.llm import GROQ_URL
from relay.pipeline import RequestResult, to_dict

ROOT = Path(__file__).resolve().parent.parent
RESULTS_CSV = ROOT / "results.csv"
DETAIL_JSONL = ROOT / "results" / "raw" / "requests.jsonl"

COLUMNS = ["request_id", "scenario", "source", "start_time", "first_token_ms", "total_ms", "status",
           "retries", "tokens_in", "tokens_out", "retrieval_setting", "answer_grade"]


def log_result(res: RequestResult, scenario: str, url: str, answer_grade: str = "") -> None:
    source = "real" if url == GROQ_URL else "stand-in"
    row = {
        "request_id": res.request_id,
        "scenario": scenario,
        "source": source,
        "start_time": datetime.fromtimestamp(res.t_start - res.queue_wait_ms / 1000, timezone.utc).isoformat(),
        # time is measured from arrival, so queue waiting is included
        "first_token_ms": "" if res.first_token_ms is None else round(res.first_token_ms + res.queue_wait_ms),
        "total_ms": round(res.total_ms + res.queue_wait_ms),
        "status": res.status,
        "retries": res.retries,
        "tokens_in": res.tokens_in,
        "tokens_out": res.tokens_out,
        "retrieval_setting": res.retrieval_setting,
        "answer_grade": answer_grade,
    }
    new = not RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row)
    DETAIL_JSONL.parent.mkdir(parents=True, exist_ok=True)
    with open(DETAIL_JSONL, "a") as f:
        detail = to_dict(res)
        for c in detail.get("claims", []):
            c.pop("chunk", None)
        f.write(json.dumps({"scenario": scenario, "source": source, **detail}, default=str) + "\n")
