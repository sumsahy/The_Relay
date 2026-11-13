"""Groq client: one chat call, streamed, with everything we need to measure it.

Concepts in this file
- Streaming (SSE): Groq sends the answer as a series of small "data: {...}" lines as tokens are
  generated, instead of one big response at the end. That's what lets us measure TTFT.
- TTFT (time to first token): request sent -> first piece of answer text arrives.
  Total time: request sent -> stream finished. TTFT is what the user *feels*; total is what the
  system *spends*.
- Rate-limit headers: every Groq response says how much quota is left (requests per day,
  tokens per minute) and when it resets. On a 429 it also sends `retry-after`.
  We record them on every call: that's the raw data for Table 1 and for the retry policy.

This module makes exactly ONE attempt per call. Retries are a policy decision and live elsewhere.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field

import httpx

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# The stand-in model service exposes the same endpoint shape, so the pipeline only changes the URL.
STANDIN_URL = os.getenv("STANDIN_URL", "http://127.0.0.1:8100/openai/v1/chat/completions")

RATE_HEADERS = (
    "retry-after",
    "x-ratelimit-limit-requests", "x-ratelimit-remaining-requests", "x-ratelimit-reset-requests",
    "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "x-ratelimit-reset-tokens",
)


@dataclass
class CallResult:
    ok: bool
    text: str = ""
    status: int | None = None          # HTTP status, None if we never got a response
    error: str = ""                    # short machine-readable reason: rate_limit, timeout, http_500, ...
    error_body: str = ""               # first 500 chars of the provider's error message
    t_start: float = 0.0               # wall clock (time.time) when the request was sent
    ttft_ms: float | None = None       # time to first content token
    total_ms: float = 0.0
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    headers: dict = field(default_factory=dict)


def _api_key() -> str:
    key = os.getenv("GROQ_API_KEY")
    if not key:
        try:
            from dotenv import load_dotenv
            load_dotenv()
            key = os.getenv("GROQ_API_KEY")
        except ImportError:
            pass
    if not key:
        raise RuntimeError("GROQ_API_KEY not set (Codespaces secret or .env)")
    return key


async def chat(client: httpx.AsyncClient, model: str, messages: list[dict],
               max_tokens: int = 512, temperature: float = 0.0, timeout_s: float = 30.0,
               extra: dict | None = None, url: str = GROQ_URL) -> CallResult:
    """One streamed chat completion. Never raises for provider errors: returns ok=False instead."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "stream": True, **(extra or {})}
    res = CallResult(ok=False, t_start=time.time())
    t0 = time.perf_counter()
    parts: list[str] = []
    try:
        async with client.stream("POST", url, json=body, timeout=timeout_s,
                                 headers={"Authorization": f"Bearer {_api_key()}"}) as r:
            res.status = r.status_code
            res.headers = {h: r.headers[h] for h in RATE_HEADERS if h in r.headers}
            if r.status_code != 200:
                res.error_body = (await r.aread()).decode(errors="replace")[:500]
                if r.status_code == 429:
                    body_l = res.error_body.lower()
                    # Groq's message names the limit, e.g. "tokens per minute (TPM)" or "requests per day (RPD)"
                    res.error = "rate_limit_day" if ("per day" in body_l or "(rpd)" in body_l or "(tpd)" in body_l) else "rate_limit_minute"
                else:
                    res.error = f"http_{r.status_code}"
                return res
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                event = json.loads(data)
                for choice in event.get("choices", []):
                    piece = (choice.get("delta") or {}).get("content")
                    if piece:
                        if res.ttft_ms is None:
                            res.ttft_ms = (time.perf_counter() - t0) * 1000
                        parts.append(piece)
                usage = event.get("usage") or (event.get("x_groq") or {}).get("usage")
                if usage:
                    res.prompt_tokens = usage.get("prompt_tokens")
                    res.completion_tokens = usage.get("completion_tokens")
        res.ok, res.text = True, "".join(parts)
    except httpx.TimeoutException:
        res.error = "timeout"
    except httpx.HTTPError as e:
        res.error = f"network:{type(e).__name__}"
    finally:
        res.total_ms = (time.perf_counter() - t0) * 1000
    return res
