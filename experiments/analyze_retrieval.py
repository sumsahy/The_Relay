"""Summarise results/raw/retrieval_grid_per_question.csv into results/retrieval_tables.md.

Every number in the retrieval report comes from this script, so it can be recomputed.
Run: python experiments/analyze_retrieval.py
"""
import csv
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
rows = list(csv.DictReader(open(ROOT / "results/raw/retrieval_grid_per_question.csv")))
CANDIDATES = 20

# re-rank cost per (query, chunk) pair, measured on uncached pairs only
pair_ms = [float(r["rerank_ms_uncached"]) / int(r["rerank_pairs_uncached"])
           for r in rows if int(r["rerank_pairs_uncached"]) > 0]
RR_MS_PER_PAIR = sum(pair_ms) / len(pair_ms)


def key(r):
    return (r["clean"], r["chunking"], r["retriever"], r["rerank"])


groups = defaultdict(list)
for r in rows:
    groups[key(r)].append(r)


def summ(rs, k=5):
    ans = [r for r in rs if r["answerable"] == "True"]
    hits = {kk: sum(int(r[f"hit@{kk}"]) for r in ans) for kk in (3, 5, 8)}
    mrr = sum(1 / int(r["first_rank"]) for r in ans if r["first_rank"]) / len(ans)
    tok = sum(int(r[f"tokens@{k}"]) for r in rs) / len(rs)
    ret_ms = sum(float(r["retrieval_ms"]) for r in rs) / len(rs)
    rr_ms = RR_MS_PER_PAIR * CANDIDATES if rs[0]["rerank"] == "True" else 0.0
    return dict(n=len(ans), **{f"hit@{kk}": hits[kk] for kk in hits}, mrr=mrr,
                tokens5=tok, ms=ret_ms + rr_ms, tok3=sum(int(r["tokens@3"]) for r in rs) / len(rs),
                tok8=sum(int(r["tokens@8"]) for r in rs) / len(rs))


def name(k):
    clean, ch, retr, rr = k
    return f"{'clean' if clean == 'True' else 'raw'} / {ch} / {retr}{' +rerank' if rr == 'True' else ''}"


out = []
p = out.append
p(f"# Retrieval experiment tables (auto-generated)\n")
p(f"Source: `results/raw/retrieval_grid_per_question.csv` ({len(rows)} rows). "
  f"30 answerable + 6 unanswerable questions per config.\n")
p(f"Re-rank cost measured at {RR_MS_PER_PAIR:.0f} ms per (question, chunk) pair on a 2-vCPU sandbox, "
  f"x{CANDIDATES} candidates = {RR_MS_PER_PAIR * CANDIDATES:.0f} ms per question.\n")
p("Tokens are estimated as characters / 4 of the retrieved chunks (context only, not the prompt template).\n")

# 1. full grid
p("## T1. Full grid (hits out of 30 answerable)\n")
p("| Config | hit@3 | hit@5 | hit@8 | MRR | tokens@5 | retrieval ms/question |")
p("|---|---|---|---|---|---|---|")
summaries = {k: summ(v) for k, v in groups.items()}
for k in sorted(summaries, key=lambda k: (-summaries[k]["hit@5"], -summaries[k]["mrr"])):
    s = summaries[k]
    p(f"| {name(k)} | {s['hit@3']} | {s['hit@5']} | {s['hit@8']} | {s['mrr']:.2f} | {s['tokens5']:.0f} | {s['ms']:.0f} |")

# 2. one factor at a time
base = ("False", "w200", "bm25", "False")
p("\n## T2. One change at a time from the baseline (raw / w200 / bm25, no rerank)\n")
p("| Change | Config | hit@3 | hit@5 | hit@8 | MRR | tokens@5 | ms |")
p("|---|---|---|---|---|---|---|---|")
variants = [("baseline", base),
            ("strip headers", ("True", "w200", "bm25", "False")),
            ("chunk 100", ("False", "w100", "bm25", "False")),
            ("chunk 400", ("False", "w400", "bm25", "False")),
            ("section chunks", ("False", "section", "bm25", "False")),
            ("embeddings", ("False", "w200", "dense", "False")),
            ("hybrid", ("False", "w200", "hybrid", "False")),
            ("rerank", ("False", "w200", "bm25", "True"))]
for label, k in variants:
    s = summaries[k]
    p(f"| {label} | {name(k)} | {s['hit@3']} | {s['hit@5']} | {s['hit@8']} | {s['mrr']:.2f} | {s['tokens5']:.0f} | {s['ms']:.0f} |")

# 3. by question type
types = ["exact", "paraphrase", "header_trap", "transcript", "cross_paper"]
p("\n## T3. hit@5 by question type (clean text unless noted)\n")
counts = {t: sum(1 for r in groups[base] if r["qtype"] == t) for t in types}
p("| Config | " + " | ".join(f"{t} (n={counts[t]})" for t in types) + " |")
p("|---|" + "---|" * len(types))
for k in [base, ("True", "w200", "bm25", "False"), ("True", "w200", "dense", "False"),
          ("True", "w200", "hybrid", "False"), ("True", "w200", "bm25", "True"),
          ("True", "w200", "hybrid", "True"), ("True", "section", "hybrid", "True")]:
    cells = [str(sum(int(r["hit@5"]) for r in groups[k] if r["qtype"] == t)) for t in types]
    p(f"| {name(k)} | " + " | ".join(cells) + " |")

# 4. paired wins / losses
p("\n## T4. Paired comparison at hit@5: questions gained / lost vs. a reference\n")
p("| Reference -> Variant | gained | lost | net | which |")
p("|---|---|---|---|---|")
pairs = [(base, ("True", "w200", "bm25", "False")),
         (("True", "w200", "bm25", "False"), ("True", "w200", "dense", "False")),
         (("True", "w200", "bm25", "False"), ("True", "w200", "hybrid", "False")),
         (("True", "w200", "hybrid", "False"), ("True", "w200", "hybrid", "True")),
         (("True", "w200", "bm25", "False"), ("True", "w200", "bm25", "True")),
         (("True", "w200", "hybrid", "True"), ("True", "section", "hybrid", "True")),
         (("True", "w200", "hybrid", "True"), ("True", "w100", "hybrid", "True")),
         (("True", "w200", "hybrid", "True"), ("True", "w400", "hybrid", "True"))]
for a, b in pairs:
    ra = {r["qid"]: r for r in groups[a] if r["answerable"] == "True"}
    rb = {r["qid"]: r for r in groups[b] if r["answerable"] == "True"}
    gained = [q for q in ra if ra[q]["hit@5"] == "0" and rb[q]["hit@5"] == "1"]
    lost = [q for q in ra if ra[q]["hit@5"] == "1" and rb[q]["hit@5"] == "0"]
    p(f"| {name(a)} -> {name(b)} | {len(gained)} | {len(lost)} | {len(gained) - len(lost):+d} | "
      f"+{','.join(gained) or '-'} / -{','.join(lost) or '-'} |")

# 5. unanswerable separation
p("\n## T5. Can the top-1 retrieval score flag unanswerable questions? (clean / w200)\n")
p("AUC = probability a random answerable question scores higher than a random unanswerable one "
  "(0.5 = useless, 1.0 = perfect). 'Best threshold' = accuracy of the best single cut over all 36.\n")
p("| Retriever | AUC | best threshold accuracy | lowest answerable score | highest unanswerable score (which) |")
p("|---|---|---|---|---|")
for retr in ("bm25", "dense", "hybrid"):
    for rr in ("False", "True"):
        rs = groups[("True", "w200", retr, rr)]
        a = [float(r["top1_score"]) for r in rs if r["answerable"] == "True"]
        u = [(float(r["top1_score"]), r["qid"]) for r in rs if r["answerable"] == "False"]
        auc = sum((x > y) + 0.5 * (x == y) for x in a for y, _ in u) / (len(a) * len(u))
        best = 0
        for t in sorted(set(a + [y for y, _ in u])):
            acc = (sum(x >= t for x in a) + sum(y < t for y, _ in u)) / (len(a) + len(u))
            best = max(best, acc)
        hu = max(u)
        p(f"| {retr}{' +rerank' if rr == 'True' else ''} | {auc:.2f} | {best:.0%} | {min(a):.3f} | {hu[0]:.3f} ({hu[1]}) |")

# 6. k tradeoff for shortlisted configs
p("\n## T6. k tradeoff (clean text)\n")
p("| Config | hit@3 / tokens | hit@5 / tokens | hit@8 / tokens |")
p("|---|---|---|---|")
for k in [("True", "w200", "bm25", "False"), ("True", "w200", "hybrid", "False"),
          ("True", "w200", "hybrid", "True"), ("True", "w100", "hybrid", "True"),
          ("True", "w400", "hybrid", "False"), ("True", "section", "hybrid", "True")]:
    s = summaries[k]
    p(f"| {name(k)} | {s['hit@3']} / {s['tok3']:.0f} | {s['hit@5']} / {s['tokens5']:.0f} | {s['hit@8']} / {s['tok8']:.0f} |")

# 7. questions nobody gets
p("\n## T7. Per-question hit@5 across all 48 configs\n")
p("| Question | type | configs that hit@5 (of 48) |")
p("|---|---|---|")
by_q = defaultdict(list)
for r in rows:
    if r["answerable"] == "True":
        by_q[(r["qid"], r["qtype"])].append(int(r["hit@5"]))
for (qid, t), v in sorted(by_q.items(), key=lambda x: sum(x[1])):
    p(f"| {qid} | {t} | {sum(v)} |")

(ROOT / "results/retrieval_tables.md").write_text("\n".join(out) + "\n")
print("\n".join(out))
