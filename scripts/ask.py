"""Ask the pipeline one question, on real Groq. Shows progress, the answer, and where the time went.

Costs 2 to 4 Groq calls (~3-6K tokens). Every run is logged to results.csv + results/raw/requests.jsonl.
Run: python scripts/ask.py "What latency does Moshi achieve?"
     python scripts/ask.py "..." --under-load      # turns on the pre-filter
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relay.pipeline import Config, Pipeline  # noqa: E402
from relay.results_log import log_result  # noqa: E402
from relay.retrieval import Retriever  # noqa: E402


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("question")
    p.add_argument("--under-load", action="store_true")
    p.add_argument("--model", default="openai/gpt-oss-20b")
    p.add_argument("--scenario", default="manual")
    a = p.parse_args()

    cfg = Config(model=a.model, under_load=a.under_load)
    retriever = Retriever()
    t0 = time.perf_counter()
    async with httpx.AsyncClient() as client:
        res = await Pipeline(retriever, client, cfg).answer(
            a.question, on_progress=lambda m: print(f"  [{(time.perf_counter() - t0) * 1000:6.0f} ms] {m}"))
    log_result(res, a.scenario, cfg.url)

    print(f"\n{res.answer}\n")
    print(f"status={res.status} outcome={res.outcome} papers={res.papers or '-'} "
          f"kept={res.claims_kept} dropped={res.claims_dropped} redrafted={res.redrafted}")
    print(f"first progress {res.progress_ms:.0f} ms | answer ready {res.first_token_ms or 0:.0f} ms | "
          f"total {res.total_ms:.0f} ms | in LLM/tools {res.work_ms:.0f} ms | retrying {res.retry_ms:.0f} ms")
    print(f"tokens in={res.tokens_in} out={res.tokens_out} | retries={res.retries}")
    for s in res.steps:
        print(f"  step {s['step']:<14} " + (f"{s['ms']:>8} ms" if "ms" in s else s.get("detail", "")))
    for c in res.calls:
        h = c["headers"]
        print(f"  call {c['step']:<7} ok={c['ok']} ttft={c['ttft_ms']} total={c['total_ms']} "
              f"in={c['prompt_tokens']} out={c['completion_tokens']} "
              f"remaining tokens/min={h.get('x-ratelimit-remaining-tokens')} req/day={h.get('x-ratelimit-remaining-requests')}"
              + (f" error={c['error']}" if c["error"] else ""))


if __name__ == "__main__":
    asyncio.run(main())
