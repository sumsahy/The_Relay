"""Load scenarios against the stand-in (no Groq quota used).

Each scenario starts its own stand-in (with that scenario's limits), runs the real pipeline + service
(queue, admission, our rate limiter, retries), simulates people arriving and giving up, and logs one
results.csv row per request (source = stand-in).

Run: python scripts/load_test.py                 # all scenarios
     python scripts/load_test.py steady burst    # some
     python scripts/load_test.py --scale 10      # stand-in capacity = 10x our account (default, see CHANGELOG)
"""
import argparse
import asyncio
import json
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from relay.pipeline import Config, RetryPolicy  # noqa: E402
from relay.results_log import log_result  # noqa: E402
from relay.retrieval import Retriever  # noqa: E402
from relay.service import Service, ServiceConfig  # noqa: E402

# People give up. ASSUMPTION (least certain): patience ~ lognormal, median 45 s, ~10% wait > 2.5 min.
PATIENCE_MEDIAN_S, PATIENCE_SIGMA = 45.0, 0.75


def arrivals(kind: str, cap_per_min: float, duration_s: float) -> list[float]:
    """Arrival times in seconds. Poisson (random gaps) except the burst."""
    rate = {"steady": 0.5, "overload": 2.5, "halved": 0.5, "daily": 0.5, "burst_naive": None, "burst": None}[kind]
    if rate is None:                               # burst: 6x a minute's capacity inside 10 seconds
        n = int(cap_per_min * 6)
        return sorted(random.uniform(0, 10) for _ in range(n))
    per_s, t, out = rate * cap_per_min / 60, 0.0, []
    while True:
        t += random.expovariate(per_s)
        if t > duration_s:
            return out
        out.append(t)


SCENARIOS = {
    #  name          stand-in flags                          our limiter  retries  duration
    "steady":      (["--limit-scale", "{s}"],                    True,   True,  180),
    "burst":       (["--limit-scale", "{s}"],                    True,   True,  10),
    "burst_naive": (["--limit-scale", "{s}"],                    False,  True,  10),   # retry-storm demo
    "overload":    (["--limit-scale", "{s}"],                    True,   True,  180),
    "halved":      (["--limit-scale", "{h}"],                    True,   True,  180),  # limit halved WITHOUT telling our limiter
    "daily":       (["--limit-scale", "{s}", "--daily-requests-left", "60"], True, True, 180),
}


async def run(name: str, scale: float, retriever: Retriever, out_csv: Path, port: int) -> dict:
    flags, use_limiter, retries, duration = SCENARIOS[name]
    flags = [f.format(s=scale, h=scale / 2) for f in flags]
    proc = subprocess.Popen([sys.executable, str(ROOT / "standin" / "server.py"), "--port", str(port), *flags],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}/openai/v1/chat/completions"
    try:
        async with httpx.AsyncClient(limits=httpx.Limits(max_connections=200)) as client:
            for _ in range(50):
                try:
                    if (await client.get(f"http://127.0.0.1:{port}/health")).status_code == 200:
                        break
                except httpx.HTTPError:
                    await asyncio.sleep(0.2)
            pcfg = Config(url=url, retrieval_setting="section-300/k5/hybrid/no-rerank",
                          retry=RetryPolicy() if retries else RetryPolicy(max_retries=0))
            # our limiter knows the ACCOUNT limits we measured (x scale); it is not told about "halved"
            scfg = ServiceConfig(workers=int(4 * max(1, scale / 5)), rpm=30 * scale, tpm=8000 * scale)
            if not use_limiter:
                scfg.rpm = scfg.tpm = 1e9                     # no client-side limiting
                scfg.max_wait_s = 1e9                         # and no admission control
                scfg.workers = 1000                           # everyone sent at once
            svc = Service(retriever, client, pcfg, scfg)
            cap = min(8000 * scale / 5000, 30 * scale / 3)     # questions per minute the limits allow
            times = arrivals(name, cap, duration)
            print(f"\n=== {name}: {len(times)} requests over {duration}s (capacity ~{cap:.0f}/min)")
            t0 = time.perf_counter()

            async def person(i: int, at: float):
                await asyncio.sleep(max(0.0, at - (time.perf_counter() - t0)))
                qs = QUESTIONS[i % len(QUESTIONS)]
                patience = random.lognormvariate(__import__("math").log(PATIENCE_MEDIAN_S), PATIENCE_SIGMA)
                res = await svc.submit(qs, f"{name}-{i:04d}", patience)
                log_result(res, name, url, results_csv=out_csv, detail_jsonl=STANDIN_JSONL)
                return res

            results = await asyncio.gather(*(person(i, at) for i, at in enumerate(times)))
            await svc.close()
            summary = {"scenario": name, "requests": len(results), "duration_s": round(time.perf_counter() - t0, 1),
                       "status": dict(Counter(r.status for r in results)),
                       "outcome": dict(Counter(r.outcome for r in results)),
                       "retries": sum(r.retries for r in results), "peak_queue": svc.peak_queue,
                       "limit_changes_detected": getattr(svc.limiter, "limit_changes", 0)}
            print(json.dumps(summary, indent=1))
            return summary
    finally:
        proc.terminate()


QUESTIONS: list[str] = []
# Stand-in runs go to their own files, so they never collide with real runs being written at the same time.
STANDIN_CSV = ROOT / "results" / "raw" / "results_standin.csv"
STANDIN_JSONL = ROOT / "results" / "raw" / "requests_standin.jsonl"


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("scenarios", nargs="*", default=list(SCENARIOS))
    p.add_argument("--scale", type=float, default=10.0)
    p.add_argument("--out", default=str(STANDIN_CSV), help="merged into results.csv by scripts/build_results.py")
    p.add_argument("--seed", type=int, default=7)
    a = p.parse_args()
    random.seed(a.seed)
    for f in ("quality_questions.json", "retrieval_questions.json"):
        QUESTIONS.extend(q["q"] for q in json.load(open(ROOT / "eval" / f))["questions"] if not q["q"].startswith("EXAMPLE"))
    retriever = Retriever()
    summaries = [await run(name, a.scale, retriever, Path(a.out), 8100 + i) for i, name in enumerate(a.scenarios)]
    out = ROOT / "results" / "raw" / "load_summary.jsonl"
    with open(out, "a") as f:
        for s in summaries:
            f.write(json.dumps({"scale": a.scale, "seed": a.seed, **s}) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
