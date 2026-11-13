"""Fit the stand-in's latency model to REAL Groq measurements and write standin/calibration.json.

Sources (both raw, both from real Groq):
  results/raw/requests.jsonl    every LLM call of every real pipeline run (Table 3, manual runs)
  results/raw/probe_limits.jsonl  the Table 1 probe (concurrency effect)
Run: python standin/calibrate.py
"""
import json
import math
import statistics as st
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
calls = []
for line in (ROOT / "results/raw/requests.jsonl").read_text().splitlines():
    r = json.loads(line)
    if r.get("source") == "real":
        calls += [c for c in r["calls"] if c["ok"] and c["ttft_ms"]]
if len(calls) < 5:
    raise SystemExit(f"only {len(calls)} real calls with timings; run some real requests first")

ttft = [c["ttft_ms"] for c in calls]
logs = [math.log(t) for t in ttft]
# prefill: how much longer TTFT gets per 1K prompt tokens (least squares)
xs = [c["prompt_tokens"] / 1000 for c in calls if c["prompt_tokens"]]
ys = [c["ttft_ms"] for c in calls if c["prompt_tokens"]]
mx, my = st.mean(xs), st.mean(ys)
slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / max(1e-9, sum((x - mx) ** 2 for x in xs))
slope = max(0.0, slope)
speeds = [c["completion_tokens"] / ((c["total_ms"] - c["ttft_ms"]) / 1000)
          for c in calls if c["completion_tokens"] and c["total_ms"] - c["ttft_ms"] > 5]
comp = {k: round(st.median([c["completion_tokens"] for c in calls if c["step"] == k and c["completion_tokens"]] or [60]))
        for k in ("draft", "verify")}
base_ttft = [t - slope * x for t, x in zip(ys, xs)]
q = sorted(ttft)
p95 = q[int(0.95 * (len(q) - 1))]
med = st.median(ttft)

# concurrency effect from the probe: 10 at once vs. later sequential requests
slow = 0.03
probe = ROOT / "results/raw/probe_limits.jsonl"
if probe.exists():
    rows = [json.loads(l) for l in probe.read_text().splitlines()]
    par = [r["total_ms"] for r in rows if r["test"] == "in_flight_10" and r["ok"]]
    seq = [r["total_ms"] for r in rows if r["test"] == "rpm" and r["ok"]]
    if par and seq:
        slow = max(0.0, (st.median(par) / st.median(seq) - 1) / 9)

cal = {
    "source": f"standin/calibrate.py from {len(calls)} real Groq calls" + (" + probe" if probe.exists() else ""),
    "ttft_median_ms": round(st.median(base_ttft), 1),
    "ttft_sigma": round(st.pstdev(logs), 3),
    "prefill_ms_per_1k_prompt_tokens": round(slope, 1),
    "output_tokens_per_s": round(st.median(speeds), 1) if speeds else 900.0,
    "completion_tokens": {"draft": comp["draft"], "verify": comp["verify"], "other": 20},
    "slowdown_per_inflight": round(slow, 4),
    "observed": {"real_ttft_p50_ms": round(med, 1), "real_ttft_p95_ms": round(p95, 1), "n_calls": len(calls)},
}
(ROOT / "standin/calibration.json").write_text(json.dumps(cal, indent=2))
print(json.dumps(cal, indent=2))
