"""Table 3: run Sumukh's questions through each retrieval setting on REAL Groq, slowly, within the limits.

- Paced: before each question, waits until the per-minute token bucket has room (from Groq's own headers).
- Resumable: skips (setting, question) pairs already done, so it can be stopped and restarted any time.
- Stops cleanly on the daily limit. Rerun later and it continues where it stopped.
- Writes results.csv rows (scenario "quality") and a grading sheet: results/quality_grading.csv.

Run: python scripts/run_quality.py              # all settings
     python scripts/run_quality.py --dry-run    # show the plan and token estimate, no calls
"""
import argparse
import asyncio
import csv
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from relay.pipeline import Config, Pipeline  # noqa: E402
from relay.results_log import DETAIL_JSONL, log_result  # noqa: E402
from relay.retrieval import Retriever  # noqa: E402

# Table 3 settings (piece size, pieces fetched, re-rank). Claude default, see CHANGELOG v0.4.
SETTINGS = {
    "w200/k5/bm25/no-rerank": dict(chunking="w200", method="bm25", k=5),       # naive baseline
    "section-300/k5/hybrid/no-rerank": dict(chunking="section", method="hybrid", k=5),  # chosen
    "section-300/k3/hybrid/no-rerank": dict(chunking="section", method="hybrid", k=3),  # cheaper
}
NEED_TOKENS = 4500          # wait until the per-minute bucket has about this much room
REFILL_PER_S = 8000 / 60    # E12: 8K TPM refills continuously
GRADING = ROOT / "results" / "quality_grading.csv"


def done_pairs() -> set:
    if not DETAIL_JSONL.exists():
        return set()
    out = set()
    for line in DETAIL_JSONL.read_text().splitlines():
        r = json.loads(line)
        if r.get("scenario") == "quality" and r.get("status") == "ok":
            out.add(r["request_id"])
    return out


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args()
    qs = [q for q in json.load(open(ROOT / "eval" / "quality_questions.json"))["questions"]
          if not q["q"].startswith("EXAMPLE")]
    if not qs:
        sys.exit("Add your questions to eval/quality_questions.json first (the EXAMPLE ones are skipped).")
    done = done_pairs()
    todo = [(s, q) for s in SETTINGS for q in qs if f"{s.split('/')[0]}-{s.split('/')[1]}-{q['id']}" not in done]
    print(f"{len(qs)} questions x {len(SETTINGS)} settings = {len(qs) * len(SETTINGS)} runs; "
          f"{len(todo)} to do; estimated ~{len(todo) * 4.5:.0f}K tokens (daily limit 200K)")
    if a.dry_run:
        return
    retrievers: dict = {}
    room, last = 8000.0, time.time()
    async with httpx.AsyncClient() as client:
        for i, (setting, q) in enumerate(todo, 1):
            # pacing: our own estimate of the token bucket, corrected by Groq's headers after each call
            room = min(8000.0, room + (time.time() - last) * REFILL_PER_S)
            if room < NEED_TOKENS:
                wait = (NEED_TOKENS - room) / REFILL_PER_S
                print(f"  pacing: waiting {wait:.0f}s for per-minute tokens")
                await asyncio.sleep(wait)
            sp = SETTINGS[setting]
            if setting not in retrievers:
                retrievers[setting] = Retriever(chunking=sp["chunking"], method=sp["method"])
            cfg = Config(k=sp["k"], retrieval_setting=setting)
            rid = f"{setting.split('/')[0]}-{setting.split('/')[1]}-{q['id']}"
            res = await Pipeline(retrievers[setting], client, cfg).answer(q["q"], request_id=rid)
            log_result(res, "quality", cfg.url)
            last = time.time()
            remaining = [c["headers"].get("x-ratelimit-remaining-tokens") for c in res.calls if c["headers"]]
            room = float(remaining[-1]) if remaining and remaining[-1] else 0.0
            new = not GRADING.exists()
            with open(GRADING, "a", newline="") as f:
                w = csv.writer(f)
                if new:
                    w.writerow(["request_id", "setting", "qid", "question", "answerable", "expected",
                                "outcome", "answer", "answer_grade"])
                w.writerow([rid, setting, q["id"], q["q"], q["answerable"], q["expected"],
                            res.outcome, res.answer, ""])
            print(f"[{i}/{len(todo)}] {rid}: {res.status}/{res.outcome} {res.total_ms:.0f} ms "
                  f"tokens {res.tokens_in}+{res.tokens_out} retries {res.retries}")
            if res.status == "rate_limited" and any(c["error"] == "rate_limit_day" for c in res.calls):
                print("Daily limit reached. Stopping. Rerun later: it resumes where it stopped.")
                return
    print("All done. Grade the answers in results/quality_grading.csv (answer_grade column).")


if __name__ == "__main__":
    asyncio.run(main())
