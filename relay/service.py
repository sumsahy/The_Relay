"""The service around the pipeline: admission control, a queue, workers, and our own rate limiter.

Concepts
- Concurrency (workers): how many requests are being worked on at once.
- Queue: where admitted requests wait for a worker. Bounded by P5: we don't admit anyone we expect to make
  wait more than ~3 minutes; they get an immediate, honest "busy" answer instead.
- Our own rate limiter: mirrors the provider's token buckets (RPM, TPM incl. the prompt + max_tokens
  reservation, E13). Calls wait HERE, before sending, instead of being sent and rejected with a 429.
  That's what stops a burst turning into a retry storm.
- Abandonment: people give up. A request whose person has left is dropped before it spends tokens.
- Budget modes: under load (queue building up) or low daily budget -> pre-filter on (decision 2026-11-13).
  Daily budget gone -> refuse at the door with the P7 message, no queueing, no retrying.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

import httpx

from relay.pipeline import Config, Pipeline, RequestResult, USER_MESSAGES
from relay.retrieval import Retriever


class TokenBucket:
    def __init__(self, capacity: float, per_s: float):
        self.capacity, self.per_s, self.level, self.t = capacity, per_s, capacity, time.monotonic()

    def refill(self):
        now = time.monotonic()
        self.level = min(self.capacity, self.level + (now - self.t) * self.per_s)
        self.t = now


class RateLimiter:
    """Client-side mirror of the provider's per-minute limits. FIFO: whoever asked first sends first."""

    def __init__(self, rpm: float, tpm: float):
        self.req = TokenBucket(rpm, rpm / 60)
        self.tok = TokenBucket(tpm, tpm / 60)
        self.lock = asyncio.Lock()
        self.waiting = 0

    async def acquire(self, tokens: float) -> float:
        """Wait until 1 request + `tokens` fit. Returns ms waited."""
        t0 = time.perf_counter()
        self.waiting += 1
        try:
            async with self.lock:
                while True:
                    self.req.refill(); self.tok.refill()
                    if self.req.level >= 1 and self.tok.level >= tokens:
                        self.req.level -= 1
                        self.tok.level -= tokens
                        return (time.perf_counter() - t0) * 1000
                    need = max((1 - self.req.level) / self.req.per_s, (tokens - self.tok.level) / self.tok.per_s)
                    await asyncio.sleep(min(max(need, 0.01), 2.0))
        finally:
            self.waiting -= 1

    def refund(self, tokens: float):
        self.tok.level = min(self.tok.capacity, self.tok.level + tokens)

    def sync(self, remaining_tokens: float | None, limit_tokens: float | None = None):
        """Trust the provider when it says we have less than we think (other traffic, estimate errors).
        If the provider's limit changed without notice (the brief warns it can), adopt the new limit."""
        if limit_tokens and self.tok.capacity < 1e8 and abs(limit_tokens - self.tok.capacity) > 1:
            self.tok.capacity, self.tok.per_s = limit_tokens, limit_tokens / 60
            self.limit_changes = getattr(self, "limit_changes", 0) + 1
        if remaining_tokens is not None:
            self.tok.refill()
            self.tok.level = min(self.tok.level, remaining_tokens)


@dataclass
class ServiceConfig:
    workers: int = 4
    max_wait_s: float = 180.0              # P5: up to ~3 minutes in the queue is acceptable
    est_tokens_per_request: float = 5000   # E12: ~3.3K-4.9K per question; refined from measurements
    rpm: float = 30
    tpm: float = 8000
    under_load_queue: int = 4              # queue at least this long -> pre-filter on
    low_budget_requests: int = 50          # daily requests left below this -> pre-filter on (P6)


class Service:
    def __init__(self, retriever: Retriever, client: httpx.AsyncClient, pcfg: Config, scfg: ServiceConfig):
        self.pcfg, self.scfg = pcfg, scfg
        self.limiter = RateLimiter(scfg.rpm, scfg.tpm)
        self.pipeline = Pipeline(retriever, client, pcfg, limiter=self.limiter)
        self.queue: asyncio.Queue = asyncio.Queue()
        self.tokens_seen: deque = deque(maxlen=20)       # tokens per finished request, for admission estimates
        self.daily_exhausted = False
        self.daily_requests_left: float | None = None
        self.peak_queue = 0
        self.workers = [asyncio.create_task(self._worker()) for _ in range(scfg.workers)]

    # ---------------------------------------------------------------- admission

    def capacity_per_s(self) -> float:
        per_req = (sum(self.tokens_seen) / len(self.tokens_seen)) if self.tokens_seen else self.scfg.est_tokens_per_request
        return min(self.scfg.tpm / per_req, self.scfg.rpm / 3) / 60       # ~3 calls per request

    def expected_wait_s(self) -> float:
        return (self.queue.qsize() + 1) / self.capacity_per_s()

    async def submit(self, question: str, request_id: str, patience_s: float) -> RequestResult:
        """Called per arriving person. Returns when answered, refused at the door, or the person gave up."""
        arrived = time.perf_counter()
        if self.daily_exhausted:
            return self._door(request_id, question, "rate_limited", "refused_daily_budget", USER_MESSAGES["rate_limit_day"])
        if self.expected_wait_s() > self.scfg.max_wait_s:
            return self._door(request_id, question, "rate_limited", "refused_busy",
                              "The assistant is at capacity right now, so I'm not queueing your question. "
                              "Please try again in a few minutes.")
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        item = {"q": question, "id": request_id, "arrived": arrived, "fut": fut, "abandoned": False, "task": None,
                "res": RequestResult(request_id, question, self.pcfg.retrieval_setting)}
        await self.queue.put(item)
        self.peak_queue = max(self.peak_queue, self.queue.qsize())
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=patience_s)
        except asyncio.TimeoutError:
            item["abandoned"] = True
            res = item["res"]
            started = item["task"] is not None
            if started:
                item["task"].cancel()          # stop spending tokens on someone who left
            gave_up_after = (time.perf_counter() - arrived) * 1000
            res.status, res.outcome = "timeout", "given_up_working" if started else "given_up_queued"
            if not started:
                res.t_start = time.time() - gave_up_after / 1000
                res.queue_wait_ms = gave_up_after
                res.total_ms = 0.0
            else:
                res.total_ms = gave_up_after - res.queue_wait_ms
            res.first_token_ms = None
            return res

    def _door(self, rid, q, status, outcome, msg) -> RequestResult:
        res = RequestResult(rid, q, self.pcfg.retrieval_setting, status=status, outcome=outcome,
                            answer=msg, refusal_reason=msg, t_start=time.time())
        res.progress_ms = res.first_token_ms = None if status != "ok" else 0.0
        return res

    # ---------------------------------------------------------------- workers

    async def _worker(self):
        while True:
            item = await self.queue.get()
            try:
                if item["abandoned"]:
                    continue                    # person already left: spend nothing
                waited = (time.perf_counter() - item["arrived"]) * 1000
                under_load = (self.queue.qsize() >= self.scfg.under_load_queue or
                              (self.daily_requests_left is not None and
                               self.daily_requests_left < self.scfg.low_budget_requests))
                if self.daily_exhausted:
                    res = self._door(item["id"], item["q"], "rate_limited", "refused_daily_budget",
                                     USER_MESSAGES["rate_limit_day"])
                else:
                    item["res"].queue_wait_ms = waited
                    task = asyncio.create_task(self.pipeline.answer(item["q"], request_id=item["id"],
                                                                    under_load=under_load, res=item["res"]))
                    item["task"] = task
                    try:
                        res = await task
                    except asyncio.CancelledError:
                        continue
                res.queue_wait_ms = waited
                self._learn(res)
                if not item["fut"].done():
                    item["fut"].set_result(res)
            finally:
                self.queue.task_done()

    def _learn(self, res: RequestResult):
        if res.status == "ok" and res.tokens_in:
            self.tokens_seen.append(res.tokens_in + res.tokens_out)
        for c in res.calls:
            if c.get("error") == "rate_limit_day":
                self.daily_exhausted = True
            h = c.get("headers") or {}
            if h.get("x-ratelimit-remaining-requests"):
                self.daily_requests_left = float(h["x-ratelimit-remaining-requests"])

    async def close(self):
        for w in self.workers:
            w.cancel()
