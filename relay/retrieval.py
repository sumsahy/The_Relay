"""Retrieval: section chunks + hybrid search (BM25 + embeddings). Decided 2026-11-13, see CHANGELOG v0.2.

Pipeline at startup:
  PDF pages -> lines -> drop running headers -> detect section headings
  -> split at section boundaries (cap 300 words, 50 overlap) -> index with BM25 and embeddings.

At question time:
  BM25 ranking + embedding ranking -> merged with reciprocal rank fusion -> top k chunks.

Each chunk carries paper + section + page, so citations look like [moshi §3.4.4 p.16].
Embeddings are cached in data/index/ so restarts take seconds, not minutes.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from pypdf import PdfReader
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parent.parent
PAPER_DIR = ROOT / "data" / "papers"
INDEX_DIR = ROOT / "data" / "index"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"

SECTION_CAP, SECTION_OVERLAP = 300, 50

# Startup guard (E15): pypdf 6.17 on Python 3.14 silently lost most of the text of one paper and the
# pipeline kept running on half a library. Refuse to start if any paper extracts far fewer words than
# expected (counts from pypdf 7.0.1: attention 6,123 / moshi 30,429 / dynchunk 21,933).
MIN_WORDS = {"attention": 5500, "moshi": 27000, "dynchunk": 19500}
RRF_K, RRF_DEPTH = 60, 50

# ------------------------------------------------------------------ section detection

_HEADING = re.compile(
    r"^(?:Appendix\s+)?([A-H]|\d{1,2})((?:\.\d{1,2}){0,3})\.?\s+([A-Z][A-Za-z\-][^=±%]{1,90})$"
)


def _heading(line: str, seen_references: bool) -> str | None:
    s = line.strip()
    if s in ("Abstract", "References"):
        return s
    m = _HEADING.match(s)
    if not m:
        return None
    top, sub, title = m.group(1), m.group(2), m.group(3).strip()
    if title.endswith((".", "?")) or ". " in title or len(title.split()) > 12:
        return None
    if sum(c.isalpha() for c in title) / max(1, len(title.replace(" ", ""))) < 0.8:
        return None
    if top.isalpha() and not seen_references:
        return None
    if top.isdigit() and int(top) > 12:
        return None
    return f"{top}{sub} {title}"


def _norm(line: str) -> str:
    return re.sub(r"[\d\s]+", " ", line).strip().lower()


def _repeated_lines(pages: list[list[str]]) -> set[str]:
    """Running headers/footers: lines (digits ignored) on >= 30% of a paper's pages."""
    counts = Counter()
    for lines in pages:
        counts.update({_norm(l) for l in lines if _norm(l)})
    n = len(pages)
    return {k for k, c in counts.items() if n >= 5 and c >= 0.3 * n and len(k) > 3}


# ------------------------------------------------------------------ chunks

@dataclass
class Chunk:
    paper: str
    section: str     # e.g. "3.2.1 Scaled Dot-Product Attention"
    page: int        # page where the chunk starts
    text: str

    @property
    def section_id(self) -> str:
        return self.section.split(" ")[0]

    @property
    def cite(self) -> str:
        return f"[{self.paper} §{self.section_id} p.{self.page}]"


def build_chunks(paper_dir: Path = PAPER_DIR, chunking: str = "section") -> list[Chunk]:
    """chunking: "section" (production) or "w200" (200-word page-bound windows, the naive baseline for Table 3)."""
    chunks: list[Chunk] = []
    pdfs = sorted(paper_dir.glob("*.pdf"))
    if not pdfs:
        raise FileNotFoundError(f"No PDFs in {paper_dir}. Run: python scripts/fetch_papers.py")
    for pdf in pdfs:
        pages = [(p.extract_text() or "").split("\n") for p in PdfReader(pdf).pages]
        n_words = sum(len(l.split()) for lines in pages for l in lines)
        if n_words < MIN_WORDS.get(pdf.stem, 0):
            raise RuntimeError(f"{pdf.name}: extracted only {n_words} words (expected >= {MIN_WORDS[pdf.stem]}). "
                               f"PDF text extraction is broken (pypdf version? corrupted download?). Refusing to "
                               f"build an index from a partial library.")
        drop = _repeated_lines(pages)
        words: list[tuple[str, int, str]] = []          # (word, page, section)
        section, seen_refs = "front matter", False
        for page_no, lines in enumerate(pages, start=1):
            for line in lines:
                if _norm(line) in drop or re.fullmatch(r"\s*\d+\s*", line):
                    continue
                h = _heading(line, seen_refs)
                if h:
                    section, seen_refs = h, seen_refs or h == "References"
                words += [(w, page_no, section) for w in line.split()]
        if chunking == "w200":
            by_page: dict[int, list] = {}
            for w in words:
                by_page.setdefault(w[1], []).append(w)
            for page_no, ws in by_page.items():
                for s0 in range(0, len(ws), 160):
                    piece = ws[s0:s0 + 200]
                    if len(piece) < 20 and s0 > 0:
                        break
                    chunks.append(Chunk(pdf.stem, piece[0][2], page_no, " ".join(w for w, _, _ in piece)))
            continue
        # group consecutive words by section, then cap long sections into windows
        start = 0
        while start < len(words):
            end = start
            while end < len(words) and words[end][2] == words[start][2]:
                end += 1
            group = words[start:end]
            for s in range(0, len(group), SECTION_CAP - SECTION_OVERLAP):
                piece = group[s:s + SECTION_CAP]
                if len(piece) < 20 and s > 0:
                    break
                chunks.append(Chunk(pdf.stem, piece[0][2], piece[0][1], " ".join(w for w, _, _ in piece)))
            start = end
    return chunks


# ------------------------------------------------------------------ search

def _tok(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class Retriever:
    def __init__(self, chunks: list[Chunk] | None = None, chunking: str = "section", method: str = "hybrid"):
        from fastembed import TextEmbedding

        self.method = method
        self.chunks = chunks or build_chunks(chunking=chunking)
        self.bm25 = BM25Okapi([_tok(c.text) for c in self.chunks])
        self.embedder = TextEmbedding(EMBED_MODEL)
        self.vecs = self._load_or_embed()

    def _load_or_embed(self) -> np.ndarray:
        digest = hashlib.sha1("".join(c.text for c in self.chunks).encode()).hexdigest()[:12]
        path = INDEX_DIR / f"embeddings_{digest}.npy"
        if path.exists():
            return np.load(path)
        t0 = time.perf_counter()
        print(f"Embedding {len(self.chunks)} chunks (one-off, cached afterwards)...")
        vecs = np.array(list(self.embedder.passage_embed([c.text for c in self.chunks], batch_size=16)))
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        np.save(path, vecs)
        print(f"  done in {time.perf_counter() - t0:.0f}s -> {path.name}")
        return vecs

    def _dense_scores(self, query: str) -> np.ndarray:
        q = np.array(list(self.embedder.query_embed([query])))[0]
        return self.vecs @ (q / np.linalg.norm(q))

    def search(self, query: str, k: int = 5, papers: list[str] | None = None) -> list[tuple[Chunk, float]]:
        """Hybrid search. Returns top-k (chunk, fused score).

        papers: restrict to these papers. With 2+ papers, k is shared out so every named paper
        gets at least k // len(papers) chunks (fixes "one paper hogs the results", X1).
        """
        bm25 = self.bm25.get_scores(_tok(query))
        dense = self._dense_scores(query) if self.method == "hybrid" else None
        allowed = None if not papers else {i for i, c in enumerate(self.chunks) if c.paper in papers}
        fused: dict[int, float] = {}
        for scores in ([bm25, dense] if dense is not None else [bm25]):
            order = [int(i) for i in np.argsort(-scores) if allowed is None or int(i) in allowed]
            for rank, i in enumerate(order[:RRF_DEPTH], start=1):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + rank)
        ranked = sorted(fused.items(), key=lambda x: -x[1])
        if papers and len(papers) > 1:
            per = max(1, k // len(papers))
            picked = []
            for p in papers:
                picked += [x for x in ranked if self.chunks[x[0]].paper == p][:per]
            rest = [x for x in ranked if x not in picked]
            picked += rest[:k - len(picked)]
            top = sorted(picked, key=lambda x: -x[1])[:k]
        else:
            top = ranked[:k]
        return [(self.chunks[i], s) for i, s in top]

    def best_similarity(self, query: str) -> float:
        """Embedding similarity of the closest chunk. Used by the under-load pre-filter."""
        return float(self._dense_scores(query).max())
