"""Show the last N requests from results/raw/requests.jsonl: claims with verdicts, and any error bodies.
No Groq calls. Run: python scripts/show_last.py [N]
"""
import json
import sys
from pathlib import Path

path = Path(__file__).resolve().parent.parent / "results" / "raw" / "requests.jsonl"
n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for line in path.read_text().splitlines()[-n:]:
    r = json.loads(line)
    print(f"\n=== {r['request_id']} | {r['outcome']} | {r['question'][:90]}")
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
