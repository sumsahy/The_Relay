"""First real Groq call: checks the key works and shows what a response looks like.

Costs 1 request and ~50 tokens of your daily quota.
Run: python scripts/hello_groq.py [model]
"""
import asyncio
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from relay.llm import chat  # noqa: E402

MODEL = sys.argv[1] if len(sys.argv) > 1 else "openai/gpt-oss-20b"


async def main() -> None:
    async with httpx.AsyncClient() as client:
        r = await chat(client, MODEL, [{"role": "user", "content": "Reply with exactly: hello relay"}],
                       max_tokens=200)
    print(f"model:   {MODEL}")
    print(f"ok:      {r.ok}  status={r.status}  error={r.error or '-'}")
    print(f"text:    {r.text!r}")
    ttft = f"{r.ttft_ms:.0f} ms" if r.ttft_ms is not None else "-"
    print(f"TTFT:    {ttft}   total: {r.total_ms:.0f} ms")
    print(f"tokens:  prompt={r.prompt_tokens} completion={r.completion_tokens}")
    print("rate-limit headers:")
    print(json.dumps(r.headers, indent=2))
    if r.error_body:
        print("error body:", r.error_body)


if __name__ == "__main__":
    asyncio.run(main())
