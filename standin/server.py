"""Stand-in model service: a fake Groq we control, for loads the free tier can't take.

Same endpoint and stream format as Groq (POST /openai/v1/chat/completions, SSE), so the pipeline only
changes the URL. It can:
  - be slow      latency drawn from distributions fitted to our real Groq calls (standin/calibration.json)
  - fail         a small share of 500s, and some calls that hang until the client times out
  - refuse       429s from the same limits as our account (RPM, TPM with prompt+max_tokens reservation,
                 RPD refilling 1 per 86.4 s, TPD), with Groq's headers and error-message format
  - slow down    every call gets slower as more calls are in flight at once
  - stream       content arrives a few tokens at a time, after hidden "thinking" time

Answers are canned but valid: drafts quote the first passage, verifies say "supported" (with a small reject
rate), so the pipeline runs end to end. Answer QUALITY is not simulated (see "where it differs").

Run:  python standin/server.py                       # account limits
      python standin/server.py --limit-scale 0.5     # per-minute limits halved
      python standin/server.py --daily-tokens-left 20000   # daily budget nearly gone
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
import random
import re
import time
from pathlib import Path

from aiohttp import web

CAL_PATH = Path(__file__).resolve().parent / "calibration.json"

# Defaults from E10-E12 (real gpt-oss-20b calls). calibrate.py overwrites calibration.json from raw data.
DEFAULT_CAL = {
    "source": "defaults from E10-E12 (3 real pipeline runs + 1 hello call); rerun standin/calibrate.py",
    "ttft_median_ms": 520.0, "ttft_sigma": 0.25,       # lognormal around the median
    "prefill_ms_per_1k_prompt_tokens": 40.0,
    "output_tokens_per_s": 900.0,                      # visible streaming speed after the first token
    "completion_tokens": {"draft": 170, "verify": 120, "other": 40},
    "slowdown_per_inflight": 0.03,                     # +3% latency per concurrent call
    "p_500": 0.01, "p_hang": 0.005, "p_slow_tail": 0.02, "slow_tail_factor": 6.0,
}

LIMITS = {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200_000}


class Bucket:
    """Continuously refilling budget (E12/E13: Groq's limits refill gradually, not per fixed window)."""

    def __init__(self, capacity: float, refill_per_s: float, start: float | None = None):
        self.capacity, self.rate = capacity, refill_per_s
        self.level = capacity if start is None else start
        self.t = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        self.level = min(self.capacity, self.level + (now - self.t) * self.rate)
        self.t = now

    def available(self) -> float:
        self._refill()
        return self.level

    def take(self, n: float):
        self._refill()
        self.level -= n

    def seconds_until(self, n: float) -> float:
        self._refill()
        return max(0.0, (n - self.level) / self.rate) if self.rate > 0 else math.inf


def fmt_reset(s: float) -> str:
    return f"{int(s // 60)}m{s % 60:.1f}s" if s >= 60 else f"{s:.3f}s"


class StandIn:
    def __init__(self, cal: dict, limit_scale: float, daily_tokens_left: float | None, daily_requests_left: float | None):
        self.cal = cal
        rpm, tpm = LIMITS["rpm"] * limit_scale, LIMITS["tpm"] * limit_scale
        self.rpm = Bucket(rpm, rpm / 60)
        self.tpm = Bucket(tpm, tpm / 60)
        self.rpd = Bucket(LIMITS["rpd"], LIMITS["rpd"] / 86400, daily_requests_left)
        self.tpd = Bucket(LIMITS["tpd"], LIMITS["tpd"] / 86400, daily_tokens_left)
        self.inflight = 0
        self.log = []

    def headers(self) -> dict:
        return {
            "x-ratelimit-limit-requests": str(int(self.rpd.capacity)),
            "x-ratelimit-remaining-requests": str(int(self.rpd.available())),
            "x-ratelimit-reset-requests": fmt_reset(self.rpd.seconds_until(self.rpd.capacity)),
            "x-ratelimit-limit-tokens": str(int(self.tpm.capacity)),
            "x-ratelimit-remaining-tokens": str(int(self.tpm.available())),
            "x-ratelimit-reset-tokens": fmt_reset(self.tpm.seconds_until(self.tpm.capacity)),
        }

    def check_limits(self, model: str, requested: int) -> web.Response | None:
        """Same order and message shape as Groq's 429s."""
        checks = [
            ("requests per day (RPD)", self.rpd, 1),
            ("tokens per day (TPD)", self.tpd, requested),
            ("requests per minute (RPM)", self.rpm, 1),
            ("tokens per minute (TPM)", self.tpm, requested),
        ]
        for name, bucket, need in checks:
            if bucket.available() < need:
                wait = bucket.seconds_until(need)
                used = int(bucket.capacity - bucket.available())
                msg = (f"Rate limit reached for model `{model}` in organization `org_standin` service tier "
                       f"`on_demand` on {name}: Limit {int(bucket.capacity)}, Used {used}, Requested {need}. "
                       f"Please try again in {wait:.4f}s.")
                h = self.headers()
                h["retry-after"] = str(max(1, math.ceil(wait)))
                return web.json_response({"error": {"message": msg, "type": "tokens", "code": "rate_limit_exceeded"}},
                                         status=429, headers=h)
        return None

    async def handle(self, request: web.Request) -> web.StreamResponse:
        body = await request.json()
        model = body.get("model", "standin")
        messages = body.get("messages", [])
        max_tokens = int(body.get("max_tokens", 512))
        text_in = " ".join(m.get("content", "") for m in messages)
        prompt_tokens = max(1, len(text_in) // 4)
        kind = "verify" if "check claims" in text_in else "draft" if "Passages:" in text_in else "other"

        refused = self.check_limits(model, prompt_tokens + max_tokens)
        if refused is not None:
            self.log.append({"t": time.time(), "kind": kind, "status": 429})
            return refused
        # reserve like Groq (E13): prompt + max_tokens now, refund the unused output at the end
        for b in (self.rpm, self.rpd):
            b.take(1)
        for b in (self.tpm, self.tpd):
            b.take(prompt_tokens + max_tokens)

        cal = self.cal
        if random.random() < cal["p_500"]:
            await asyncio.sleep(random.uniform(0.05, 0.3))
            return web.json_response({"error": {"message": "Internal Server Error (stand-in)"}}, status=500,
                                     headers=self.headers())

        self.inflight += 1
        try:
            if random.random() < cal["p_hang"]:
                await asyncio.sleep(120)          # "succeeds slowly instead of failing": client should time out
            load = 1 + cal["slowdown_per_inflight"] * (self.inflight - 1)
            ttft = random.lognormvariate(math.log(cal["ttft_median_ms"]), cal["ttft_sigma"])
            ttft += cal["prefill_ms_per_1k_prompt_tokens"] * prompt_tokens / 1000
            if random.random() < cal["p_slow_tail"]:
                ttft *= cal["slow_tail_factor"]
            ttft *= load

            out_tokens = min(max_tokens, max(5, int(random.gauss(cal["completion_tokens"][kind],
                                                                 cal["completion_tokens"][kind] * 0.3))))
            content = self.answer(kind, text_in)
            resp = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream", **self.headers()})
            await resp.prepare(request)
            await asyncio.sleep(ttft / 1000)
            pieces = [content[i:i + 16] for i in range(0, len(content), 16)]
            per_piece = (out_tokens / cal["output_tokens_per_s"]) / max(1, len(pieces)) * load
            for p in pieces:
                await resp.write(f"data: {json.dumps({'choices': [{'delta': {'content': p}}]})}\n\n".encode())
                await asyncio.sleep(per_piece)
            finish = {"choices": [{"delta": {}, "finish_reason": "stop"}],
                      "x_groq": {"usage": {"prompt_tokens": prompt_tokens, "completion_tokens": out_tokens}}}
            await resp.write(f"data: {json.dumps(finish)}\n\ndata: [DONE]\n\n".encode())
            for b in (self.tpm, self.tpd):
                b.take(-(max_tokens - out_tokens))      # refund unused reservation
            self.log.append({"t": time.time(), "kind": kind, "status": 200, "ttft_ms": ttft,
                             "inflight": self.inflight})
            return resp
        finally:
            self.inflight -= 1

    @staticmethod
    def answer(kind: str, text_in: str) -> str:
        if kind == "verify":
            n = len(re.findall(r"^Claim \d+:", text_in, flags=re.M)) or 1
            return json.dumps({"verdicts": [{"id": i, "supported": random.random() > 0.05, "reason": "stand-in"}
                                            for i in range(1, n + 1)]})
        if kind == "draft":
            m = re.search(r"\[S1\][^\n]*\n(.+)", text_in)
            words = (m.group(1).split() if m else [])[:14]
            if len(words) < 6:
                return json.dumps({"answerable": False, "reason": "stand-in: no usable passage"})
            quote = " ".join(words)
            return json.dumps({"answerable": True, "claims": [{"text": quote, "source": "S1", "quote": quote}]})
        return "ok"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8100)
    p.add_argument("--limit-scale", type=float, default=1.0, help="0.5 = per-minute limits halved")
    p.add_argument("--daily-tokens-left", type=float, default=None)
    p.add_argument("--daily-requests-left", type=float, default=None)
    a = p.parse_args()
    cal = {**DEFAULT_CAL, **(json.loads(CAL_PATH.read_text()) if CAL_PATH.exists() else {})}
    s = StandIn(cal, a.limit_scale, a.daily_tokens_left, a.daily_requests_left)
    app = web.Application()
    app.router.add_post("/openai/v1/chat/completions", s.handle)
    app.router.add_get("/health", lambda r: web.json_response({"ok": True, "inflight": s.inflight}))
    print(f"stand-in on :{a.port} | calibration: {cal['source']} | limit scale {a.limit_scale}")
    web.run_app(app, port=a.port, print=None)


if __name__ == "__main__":
    main()
