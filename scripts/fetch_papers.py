"""Download the three papers at the exact versions the brief requires.

Run: python scripts/fetch_papers.py
"""
from pathlib import Path

import httpx

PAPERS = {
    "attention": "1706.03762v7",   # Attention Is All You Need
    "moshi": "2410.00037v1",       # Moshi
    "dynchunk": "2507.07955v2",    # Dynamic Chunking (H-Net)
}

OUT = Path(__file__).resolve().parent.parent / "data" / "papers"
# md5 of the files every experiment in this repo used (E15: a replaced moshi.pdf silently broke a run)
MD5 = {"attention": "18e1b007a1dab45b30cc861ba2dfda25", "moshi": "c18d8ed0cc989509089af289c4010b14",
       "dynchunk": "274fd334546d71272bab79c7613f5ac2"}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, arxiv_id in PAPERS.items():
        dest = OUT / f"{name}.pdf"
        if dest.exists():
            import hashlib
            md5 = hashlib.md5(dest.read_bytes()).hexdigest()
            print(f"skip {name} (already downloaded) md5 {'OK' if md5 == MD5[name] else 'MISMATCH ' + md5}")
            continue
        url = f"https://arxiv.org/pdf/{arxiv_id}"
        print(f"fetching {name} from {url}")
        r = httpx.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        print(f"  saved {dest.name} ({len(r.content) // 1024} KB)")


if __name__ == "__main__":
    main()
