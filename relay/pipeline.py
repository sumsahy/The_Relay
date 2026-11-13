"""The Relay pipeline: one question in, one verified cited answer (or an honest refusal) out.

Steps (see PRINCIPLES.md for why):
  1. classify   (code)  which papers does the question name? cross-paper?            P9: free, instant
  2. pre-filter (code)  only under load: refuse clearly off-topic questions           T2: conservative cutoff
  3. retrieve   (tool)  section chunks + hybrid search, k=5, shared across named papers
  4. draft      (LLM)   answer as claims, each with a source passage + exact quote, or "not answerable"
  5. verify A   (code)  is each quote really in the cited passage?                     P1
  6. verify B   (LLM)   does each passage actually support its claim?                  P1
  7. branch/loop        failed claims are dropped; if none survive, redraft once, else refuse
  8. compose            final answer with [paper §section p.N] citations

Progress messages go to `on_progress` at each step (P3).
Every LLM call goes through `_call`, which records timing, tokens and retries.
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Callable

import httpx

from relay.llm import GROQ_URL, CallResult, chat
from relay.retrieval import Chunk, Retriever

# ------------------------------------------------------------------ configuration


@dataclass
class RetryPolicy:
    """PENDING: numbers to be set from the limits probe (Table 1). Principles agreed:
    retry only the failed step, bounded, backoff + jitter, honour retry-after, never retry a daily limit."""
    max_retries: int = 0
    base_s: float = 1.0
    cap_s: float = 20.0
    honour_retry_after: bool = True


@dataclass
class Config:
    model: str = "openai/gpt-oss-20b"
    url: str = GROQ_URL
    k: int = 5
    retrieval_setting: str = "section-300/k5/hybrid/no-rerank"
    under_load: bool = False
    prefilter_cutoff: float = 0.65       # conservative (T2); lowest answerable question scored 0.714
    reasoning_effort: str = "low"        # Claude default, to measure
    draft_max_tokens: int = 900
    verify_max_tokens: int = 400
    call_timeout_s: float = 30.0
    retry: RetryPolicy = field(default_factory=RetryPolicy)


PAPER_NAMES = {
    "attention": ["transformer", "attention is all you need", "vaswani", "attention paper"],
    "moshi": ["moshi", "mimi", "helium", "kyutai"],
    "dynchunk": ["dynamic chunking", "h-net", "hnet", "chunking paper"],
}

# ------------------------------------------------------------------ result record


@dataclass
class Claim:
    text: str
    source: str
    quote: str
    chunk: Chunk | None = None
    code_ok: bool | None = None
    llm_ok: bool | None = None
    reason: str = ""


@dataclass
class RequestResult:
    request_id: str
    question: str
    retrieval_setting: str
    status: str = "ok"                   # ok | rate_limited | timeout | error   (results.csv)
    outcome: str = ""                    # answered | answered_reduced | refused_not_in_papers | refused_unverifiable | refused_prefilter | failed
    answer: str = ""
    refusal_reason: str = ""
    papers: list = field(default_factory=list)
    claims_kept: int = 0
    claims_dropped: int = 0
    redrafted: bool = False
    t_start: float = 0.0                 # wall clock, set when the pipeline starts working on it
    queue_wait_ms: float = 0.0           # filled in by the queue layer
    progress_ms: float | None = None     # first progress message shown
    first_token_ms: float | None = None  # first piece of the verified answer delivered
    total_ms: float = 0.0
    work_ms: float = 0.0                 # time inside LLM calls and tools
    retry_ms: float = 0.0                # time spent waiting to retry
    retries: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    claims: list = field(default_factory=list)  # every claim checked, with verdicts
    steps: list = field(default_factory=list)   # per-step timings
    calls: list = field(default_factory=list)   # per-LLM-call details incl. rate-limit headers


class StepFailed(Exception):
    def __init__(self, status: str, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail

# What the person sees when we can't answer (P7: say why; no made-up time estimates)
USER_MESSAGES = {
    "rate_limit_day": ("Today's model usage limit has been reached, so I can't answer right now. "
                       "Nothing unverified was sent. Please try again later."),
    "rate_limit_minute": "The assistant is busy right now and couldn't finish your answer. Please try again in a minute.",
    "timeout": "The model took too long to respond, so I stopped rather than send an unchecked answer. Please try again.",
    "other": "Something went wrong while preparing a verified answer, so nothing was sent. Please try again.",
}

# ------------------------------------------------------------------ prompts

DRAFT_SYSTEM = """You answer questions about three research papers using ONLY the numbered passages given.
Rules:
- Split your answer into short claims. Each claim must be supported by ONE passage.
- For each claim give the passage id and an exact quote copied word for word from that passage (5 to 30 words).
- Use no outside knowledge. If the passages do not contain the answer, say it is not answerable and say briefly what is missing.
- At most 6 claims.
Reply with JSON only, one of:
{"answerable": true, "claims": [{"text": "...", "source": "S1", "quote": "..."}]}
{"answerable": false, "reason": "..."}"""

VERIFY_SYSTEM = """You check claims against source passages from research papers.
A claim is SUPPORTED only if a careful reader would agree the passage states it or directly implies it.
Numbers, names and comparisons must match exactly. Be strict.
Reply with JSON only: {"verdicts": [{"id": 1, "supported": true, "reason": "..."}]}"""


def _passages(chunks: list[Chunk]) -> str:
    return "\n\n".join(f"[S{i}] ({c.paper} §{c.section}, p.{c.page})\n{c.text}"
                       for i, c in enumerate(chunks, start=1))


def _parse_json(text: str) -> dict | None:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def _letters(s: str) -> str:
    """Compare quotes on letters and digits only: survives PDF spacing artefacts like 'T okenization'."""
    return re.sub(r"[^a-z0-9]", "", s.lower())

# ------------------------------------------------------------------ pipeline


class Pipeline:
    def __init__(self, retriever: Retriever, client: httpx.AsyncClient, config: Config | None = None):
        self.r, self.client, self.cfg = retriever, client, config or Config()

    async def answer(self, question: str, on_progress: Callable[[str], None] | None = None,
                     request_id: str | None = None) -> RequestResult:
        cfg = self.cfg
        res = RequestResult(request_id or uuid.uuid4().hex[:8], question, cfg.retrieval_setting,
                            t_start=time.time())
        t0 = time.perf_counter()
        ms = lambda: (time.perf_counter() - t0) * 1000

        def progress(msg: str):
            if res.progress_ms is None:
                res.progress_ms = ms()
            if on_progress:
                on_progress(msg)

        def step(name: str, t_step: float, **info):
            res.steps.append({"step": name, "ms": round((time.perf_counter() - t_step) * 1000, 1), **info})

        try:
            # 1. classify (code)
            ts = time.perf_counter()
            q = question.lower()
            res.papers = [p for p, names in PAPER_NAMES.items() if any(n in q for n in names)]
            step("classify", ts, papers=res.papers)

            # 2. pre-filter, only under load (decision 2026-11-13, PRINCIPLES T2)
            if cfg.under_load:
                ts = time.perf_counter()
                best = self.r.best_similarity(question)
                step("prefilter", ts, best_similarity=round(best, 3))
                if best < cfg.prefilter_cutoff:
                    res.outcome = "refused_prefilter"
                    res.refusal_reason = "The three papers don't appear to cover this question."
                    return self._finish(res, ms, progress)

            # 3. retrieve (tool)
            progress("Searching the papers...")
            ts = time.perf_counter()
            hits = self.r.search(question, k=cfg.k, papers=res.papers if len(res.papers) > 1 else None)
            chunks = [c for c, _ in hits]
            step("retrieve", ts, cites=[c.cite for c in chunks])
            res.work_ms += res.steps[-1]["ms"]

            # 4-7. draft -> verify -> (drop failed | redraft once | refuse)
            feedback = ""
            for attempt in range(2):
                progress("Drafting an answer..." if attempt == 0 else "Some claims didn't check out, redrafting...")
                draft = await self._draft(res, question, chunks, feedback)
                if draft is None:
                    feedback = "Your previous reply was not valid JSON."
                    continue
                if not draft.get("answerable", False):
                    res.outcome = "refused_not_in_papers"
                    res.refusal_reason = draft.get("reason") or "The papers don't say."
                    return self._finish(res, ms, progress)
                claims = self._claims(draft, chunks)
                progress("Checking citations...")
                self._verify_quotes(res, claims)
                await self._verify_llm(res, [c for c in claims if c.code_ok])
                res.claims += [{"attempt": attempt, "text": c.text, "source": c.source, "quote": c.quote,
                                "cite": c.chunk.cite if c.chunk else None, "code_ok": c.code_ok,
                                "llm_ok": c.llm_ok, "reason": c.reason} for c in claims]
                kept = [c for c in claims if c.code_ok and c.llm_ok]
                failed = [c for c in claims if not (c.code_ok and c.llm_ok)]
                if kept:
                    res.claims_kept, res.claims_dropped = len(kept), len(failed)
                    res.outcome = "answered_reduced" if failed else "answered"
                    res.answer = self._compose(kept, failed)
                    return self._finish(res, ms, progress)
                res.redrafted = attempt == 0
                feedback = "These claims failed verification, do not repeat them: " + \
                    "; ".join(f'"{c.text}" ({c.reason})' for c in failed)
            res.outcome = "refused_unverifiable"
            res.refusal_reason = "I found related passages but couldn't verify an answer against them."
            return self._finish(res, ms, progress)

        except StepFailed as e:
            res.status, res.outcome = e.status, "failed"
            res.refusal_reason = USER_MESSAGES.get(e.detail.split(": ")[-1], USER_MESSAGES["other"])
            res.steps.append({"step": "failed", "detail": e.detail})
            return self._finish(res, ms, progress)

    # -------------------------------------------------------------- steps

    async def _draft(self, res, question, chunks, feedback) -> dict | None:
        user = f"Passages:\n\n{_passages(chunks)}\n\nQuestion: {question}"
        if feedback:
            user += f"\n\nNote: {feedback}"
        r = await self._call(res, "draft", [{"role": "system", "content": DRAFT_SYSTEM},
                                            {"role": "user", "content": user}], self.cfg.draft_max_tokens)
        return _parse_json(r.text)

    def _claims(self, draft: dict, chunks: list[Chunk]) -> list[Claim]:
        out = []
        for c in draft.get("claims", [])[:6]:
            m = re.match(r"S?(\d+)", str(c.get("source", "")).strip())
            idx = int(m.group(1)) - 1 if m else -1
            out.append(Claim(str(c.get("text", "")), str(c.get("source", "")), str(c.get("quote", "")),
                             chunks[idx] if 0 <= idx < len(chunks) else None))
        return out

    def _verify_quotes(self, res, claims: list[Claim]):
        ts = time.perf_counter()
        for c in claims:
            if c.chunk is None:
                c.code_ok, c.reason = False, "cites a passage that doesn't exist"
            elif len(c.quote.split()) < 4:
                c.code_ok, c.reason = False, "quote too short to check"
            elif _letters(c.quote) not in _letters(c.chunk.text):
                c.code_ok, c.reason = False, "quote not found in the cited passage"
            else:
                c.code_ok = True
        res.steps.append({"step": "verify_quotes", "ms": round((time.perf_counter() - ts) * 1000, 2),
                          "passed": sum(bool(c.code_ok) for c in claims), "of": len(claims)})

    async def _verify_llm(self, res, claims: list[Claim]):
        if not claims:
            return
        # P9: send only the passages that are actually cited, not all k
        body = "\n\n".join(f"Claim {i}: {c.text}\nPassage ({c.chunk.cite}):\n{c.chunk.text}"
                           for i, c in enumerate(claims, start=1))
        r = await self._call(res, "verify", [{"role": "system", "content": VERIFY_SYSTEM},
                                             {"role": "user", "content": body}], self.cfg.verify_max_tokens)
        parsed = _parse_json(r.text) or {}
        verdicts = {int(v.get("id", 0)): v for v in parsed.get("verdicts", []) if str(v.get("id", "")).isdigit()}
        for i, c in enumerate(claims, start=1):
            v = verdicts.get(i)
            c.llm_ok = bool(v and v.get("supported") is True)   # missing verdict = not verified (P1)
            if not c.llm_ok:
                c.reason = (v or {}).get("reason", "verifier gave no verdict")

    def _compose(self, kept: list[Claim], failed: list[Claim]) -> str:
        lines = [f"{c.text} {c.chunk.cite}" for c in kept]
        if failed:
            lines.append(f"\n(Reduced answer: {len(failed)} claim(s) removed because they couldn't be verified against the papers.)")
        return "\n".join(lines)

    def _finish(self, res: RequestResult, ms, progress) -> RequestResult:
        if res.outcome.startswith("refused") or res.outcome == "failed":
            res.answer = res.answer or res.refusal_reason
        res.first_token_ms = ms() if res.status == "ok" else None
        res.total_ms = ms()
        if res.progress_ms is None:
            res.progress_ms = res.total_ms
        return res

    # -------------------------------------------------------------- one LLM call, with retries

    async def _call(self, res: RequestResult, step: str, messages, max_tokens) -> CallResult:
        cfg, pol = self.cfg, self.cfg.retry
        extra = {"reasoning_effort": cfg.reasoning_effort, "include_reasoning": False} if "gpt-oss" in cfg.model else {}
        attempt = 0
        while True:
            r = await chat(self.client, cfg.model, messages, max_tokens=max_tokens,
                           timeout_s=cfg.call_timeout_s, extra=extra, url=cfg.url)
            res.work_ms += r.total_ms
            res.tokens_in += r.prompt_tokens or 0
            res.tokens_out += r.completion_tokens or 0
            res.calls.append({"step": step, "attempt": attempt, "ok": r.ok, "status": r.status, "error": r.error,
                              "ttft_ms": r.ttft_ms and round(r.ttft_ms, 1), "total_ms": round(r.total_ms, 1),
                              "prompt_tokens": r.prompt_tokens, "completion_tokens": r.completion_tokens,
                              "headers": r.headers, "error_body": r.error_body[:300]})
            if r.ok:
                return r
            retryable = r.error in ("rate_limit_minute", "timeout") or r.error.startswith(("http_5", "network"))
            if not retryable or attempt >= pol.max_retries:
                status = ("rate_limited" if r.error.startswith("rate_limit")
                          else "timeout" if r.error == "timeout" else "error")
                raise StepFailed(status, f"{step} failed: {r.error}")
            wait = min(pol.cap_s, pol.base_s * 2 ** attempt) * random.uniform(0.5, 1.5)   # backoff + jitter
            if pol.honour_retry_after and r.headers.get("retry-after"):
                wait = max(wait, float(r.headers["retry-after"]))
            t_wait = time.perf_counter()
            await asyncio.sleep(wait)
            res.retry_ms += (time.perf_counter() - t_wait) * 1000
            res.retries += 1
            attempt += 1


def to_dict(res: RequestResult) -> dict:
    return asdict(res)
