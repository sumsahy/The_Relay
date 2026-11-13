"""Show requests from results/raw/requests.jsonl: claims with verdicts, timings, and any error bodies.
No Groq calls. Run: python scripts/show_last.py [N]            last N requests
                    python scripts/show_last.py Q10 Q05        requests whose id contains these
"""
import json
import sys
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "results" / "raw" / "requests.jsonl"
args = sys.argv[1:] or ["3"]
lines = path.read_text().splitlines()
if args[0].isdigit():
    picked = lines[-int(args[0]):]
else:
    picked = [l for l in lines if any(a in json.loads(l)["request_id"] for a in args)]
for line in picked:
    r = json.loads(line)
    print(f"\n=== {r['request_id']} | {r['outcome']} | {r['question'][:90]}")
    print(f"  total {r['total_ms']:.0f} ms = work {r['work_ms']:.0f} + retry wait {r['retry_ms']:.0f} "
          f"+ limiter wait {r.get('limiter_wait_ms', 0):.0f} | answer ready at {r['first_token_ms'] or 0:.0f} ms")
    for c in r.get("calls", []):
        print(f"  call {c['step']:<7} attempt {c['attempt']} ok={c['ok']} ttft={c['ttft_ms']} total={c['total_ms']} "
              f"in={c['prompt_tokens']} out={c['completion_tokens']}" + (f" ERROR {c['error']}" if c['error'] else ""))
    for c in r.get("claims", []):
        mark = "KEPT" if c["code_ok"] and c["llm_ok"] else "DROPPED"
        print(f"  [{mark}] attempt {c['attempt']} {c['cite']}: {c['text']}")
        print(f"      quote: \"{c['quote']}\"")
        if mark == "DROPPED":
            print(f"      why: quote check={c['code_ok']} support check={c['llm_ok']} -> {c['reason']}")
    for call in r.get("calls", []):
        if not call["ok"]:
            print(f"  FAILED CALL {call['step']}: status={call['status']} error={call['error']}")
            print(f"      headers: {call['headers']}")
            print(f"      body: {call['error_body']}")
