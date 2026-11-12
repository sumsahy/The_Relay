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


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, arxiv_id in PAPERS.items():
        dest = OUT / f"{name}.pdf"
        if dest.exists():
            print(f"skip {name} (already downloaded)")
            continue
        url = f"https://arxiv.org/pdf/{arxiv_id}"
        print(f"fetching {name} from {url}")
        r = httpx.get(url, follow_redirects=True, timeout=60)
        r.raise_for_status()
        dest.write_bytes(r.content)
        print(f"  saved {dest.name} ({len(r.content) // 1024} KB)")


if __name__ == "__main__":
    main()
