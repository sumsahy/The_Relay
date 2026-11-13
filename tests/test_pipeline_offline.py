"""Offline pipeline test: a scripted fake model, no Groq calls. Run: python tests/test_pipeline_offline.py"""
import asyncio, json, sys
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import os; os.environ.setdefault("GROQ_API_KEY", "offline-test")
from relay.pipeline import Config, Pipeline, RetryPolicy
from relay.retrieval import Chunk, Retriever

CH = [Chunk("moshi", "1 Introduction", 2, "Moshi is the first real-time full-duplex spoken large language model, with a theoretical latency of 160ms, 200ms in practice."),
      Chunk("attention", "3.2.1 Scaled Dot-Product Attention", 4, "We suspect that for large values of dk, the dot products grow large in magnitude, pushing the softmax function into regions where it has extremely small gradients.")]

CH.append(Chunk("dynchunk", "2.2 Dynamic Chunking (DC)", 5, "The routing module predicts boundaries between adjacent elements through a similarity score, and the main network operates on the compressed chunks."))

class FakeRetriever:
    chunks = CH
    def search(self, q, k=5, papers=None):
        return [(c, 1.0) for c in CH if papers is None or c.paper in papers][:k]
    def best_similarity(self, q): return 0.5 if "gpt-4" in q.lower() else 0.8

def sse(text, finish="stop"):
    return "".join(f"data: {json.dumps({'choices':[{'delta':{'content':text[i:i+20]}}]})}\n\n" for i in range(0,len(text),20)) + \
        f'data: {{"choices":[{{"delta":{{}},"finish_reason":"{finish}"}}]}}\n\n' + \
        'data: {"choices":[],"x_groq":{"usage":{"prompt_tokens":100,"completion_tokens":50}}}\n\ndata: [DONE]\n\n'

def make_handler(script):
    calls = iter(script)
    def h(req):
        kind, payload = next(calls)
        if kind == 429:
            return httpx.Response(429, headers={"retry-after": "0.1"}, text=payload)
        if kind == "cut":
            return httpx.Response(200, text=sse('{"answerable": true, "claims": [{"text": "Mosh', finish="length"))
        return httpx.Response(200, text=sse(json.dumps(payload)))
    return h

GOOD = {"answerable": True, "claims": [{"text": "Moshi has a theoretical latency of 160 ms.", "source": "S1", "quote": "with a theoretical latency of 160ms, 200ms in practice"}]}
TWO = {"answerable": True, "claims": [GOOD["claims"][0], {"text": "Moshi runs on a phone.", "source": "S1", "quote": "Moshi runs efficiently on mobile phones"}]}
OK1 = {"verdicts": [{"id": 1, "supported": True, "reason": "stated"}]}
CASES = {
  "answered":            ("latency?", [(200, GOOD), (200, OK1)], {}),
  "reduced (bad quote)": ("latency?", [(200, TWO), (200, OK1)], {}),
  "not in papers":       ("price?", [(200, {"answerable": False, "reason": "No pricing info."})], {}),
  "llm rejects -> redraft -> refuse": ("latency?", [(200, GOOD), (200, {"verdicts":[{"id":1,"supported":False,"reason":"wrong"}]}), (200, GOOD), (200, {"verdicts":[{"id":1,"supported":False,"reason":"wrong"}]})], {}),
  "prefilter under load": ("How many parameters does GPT-4 have?", [], {"under_load": True}),
  "429, retries off":    ("latency?", [(429, '{"error":{"message":"Rate limit reached ... tokens per minute (TPM)"}}')], {"retry": RetryPolicy(max_retries=0)}),
  "429 x2 then ok (default policy)": ("latency?", [(429, '{"error":{"message":"tokens per minute (TPM)"}}'), (429, '{"error":{"message":"tokens per minute (TPM)"}}'), (200, GOOD), (200, OK1)], {"retry": RetryPolicy(jitter_s=0.01)}),
  "429, 1 retry -> ok":  ("latency?", [(429, '{"error":{"message":"tokens per minute (TPM)"}}'), (200, GOOD), (200, OK1)], {"retry": RetryPolicy(max_retries=1, base_s=0.05)}),
  "cross-paper, 2nd retrieval finds it": ("Compare the Transformer and dynamic chunking", [
        (200, {"answerable": True, "claims": [{"text": "Self-attention gradients shrink for large dk.", "source": "S1", "quote": "pushing the softmax function into regions where it has extremely small gradients"}]}),
        (200, OK1),
        (200, {"answerable": True, "claims": [{"text": "A routing module predicts chunk boundaries from similarity.", "source": "S1", "quote": "The routing module predicts boundaries between adjacent elements"}]}),
        (200, OK1)], {}),
  "cross-paper, 2nd retrieval finds nothing": ("Compare the Transformer and dynamic chunking", [
        (200, {"answerable": True, "claims": [{"text": "Self-attention gradients shrink for large dk.", "source": "S1", "quote": "pushing the softmax function into regions where it has extremely small gradients"}]}),
        (200, OK1),
        (200, {"answerable": False, "reason": "not discussed"})], {}),
  "draft cut off at 500 -> retried at 1000": ("latency?", [("cut", None), (200, GOOD), (200, OK1)], {}),
  "429 retry-after too long for 30 s cap": ("latency?", [(429, '{"error":{"message":"tokens per minute (TPM)"}}')], {"retry": RetryPolicy(max_retries=2, max_total_wait_s=0.05)}),
  "daily limit, never retried": ("latency?", [(429, '{"error":{"message":"Rate limit reached for requests per day (RPD)"}}')], {"retry": RetryPolicy(max_retries=3, base_s=0.05)}),
}

async def main():
    for name, (q, script, kw) in CASES.items():
        async with httpx.AsyncClient(transport=httpx.MockTransport(make_handler(script))) as c:
            r = await Pipeline(FakeRetriever(), c, Config(**kw)).answer(q)
        print(f"{name:<34} status={r.status:<12} outcome={r.outcome:<22} retries={r.retries} calls={len(r.calls)} tokens={r.tokens_in}/{r.tokens_out}")
        if name in ("reduced (bad quote)",) or name.startswith("cross"): print("   answer:", r.answer.replace(chr(10), ' | '), "| 2nd:", r.second_retrieval)
        if name.startswith("draft cut"): print("   hit_max_tokens:", r.hit_max_tokens, "budgets:", [c.get("hit_max_tokens", False) for c in r.calls])
asyncio.run(main())
