"""Table 1 probe: find the real per-minute request limit, requests in flight, and recovery time.

Uses tiny requests (max_tokens 20) so the per-minute TOKEN limit isn't hit first:
~45 requests and ~4-5K tokens in total. Run it BEFORE run_quality.py, not at the same time.

  Test 1  in flight: 10 requests at once. Do all succeed? Does latency rise with concurrency?
  Test 2  per-minute requests: send requests back to back until Groq returns a 429 (expected ~30 in a minute).
  Test 3  recovery: after the 429, one request every 2 s until one succeeds. How long did it take?

Raw: results/raw/probe_limits.jsonl. Run: python scripts/probe_limits.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from relay.llm import chat  # noqa: E402

MODEL = "openai/gpt-oss-20b"
OUT = ROOT / "results" / "raw" / "probe_limits.jsonl"
MSG = [{"role": "user", "content": "Reply with one word: ok"}]
EXTRA = {"reasoning_effort": "low", "include_reasoning": False}


async def one(client, test, i, t0):
    r = await chat(client, MODEL, MSG, max_tokens=20, extra=EXTRA)
    row = {"test": test, "i": i, "t_rel_s": round(r.t_start - t0, 3), "ok": r.ok, "status": r.status,
           "error": r.error, "ttft_ms": r.ttft_ms and round(r.ttft_ms, 1), "total_ms": round(r.total_ms, 1),
           "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
           "headers": r.headers, "error_body": r.error_body[:400]}
    with open(OUT, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row


async def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=50)) as client:
        t0 = time.time()
        print("Test 1: 10 requests at the same time")
        rows = await asyncio.gather(*(one(client, "in_flight_10", i, t0) for i in range(10)))
        oks = [r for r in rows if r["ok"]]
        lat = sorted(r["total_ms"] for r in oks)
        print(f"  {len(oks)}/10 ok; total ms min {lat[0] if lat else '-'} / max {lat[-1] if lat else '-'}; "
              f"errors: {[r['error'] for r in rows if not r['ok']]}")

        print("Test 2: back-to-back requests until a 429 (max 40)")
        hit = None
        t_start2 = time.time()
        for i in range(40):
            r = await one(client, "rpm", i, t0)
            if not r["ok"]:
                hit = r
                print(f"  429 after {i} more requests ({10 + i} in total), {time.time() - t_start2:.1f}s into test 2")
                print(f"  error: {r['error']}  retry-after: {r['headers'].get('retry-after')}")
                print(f"  body: {r['error_body'][:250]}")
                break
        if not hit:
            print("  no 429 within 40 requests")
            return

        print("Test 3: recovery, one request every 2 s")
        t_hit = time.time()
        for i in range(60):
            await asyncio.sleep(2)
            r = await one(client, "recovery", i, t0)
            if r["ok"]:
                print(f"  recovered after {time.time() - t_hit:.1f}s ({i + 1} attempts)")
                break
        else:
            print("  not recovered within 2 minutes")
    print(f"Raw rows: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
