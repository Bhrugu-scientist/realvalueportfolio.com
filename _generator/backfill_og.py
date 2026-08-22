#!/usr/bin/env python3
"""
One-off backfill: give every existing blog article a branded share card
(blog/og/<slug>.png) and og:image meta, so links already in circulation
start rendering a proper preview. Safe to re-run (idempotent).

No API key needed — reuses the render/inject helpers from generate.py.
Requires a Chrome/Chromium binary (set CHROME_BIN, or have Google Chrome
installed locally).
"""
import re
import sys
from pathlib import Path

from generate import BLOG, BLOG_INDEX, extract_h1, inject_og_meta, render_og_card

# Files in blog/ that are not articles.
SKIP = {"blog.html"}


def category_map():
    """slug -> category label, parsed from the blog index (cat carries forward)."""
    text = BLOG_INDEX.read_text(encoding="utf-8")
    out, current = {}, "Real Value · Insights"
    for line in text.splitlines():
        m = re.search(r'class="cat">(.*?)</div>', line)
        if m:
            current = m.group(1).strip()
            continue
        m = re.search(r'class="post" href="/blog/(.+?)\.html"', line)
        if m:
            out[m.group(1)] = current
    return out


def main():
    cats = category_map()
    done = 0
    for path in sorted(BLOG.glob("*.html")):
        if path.name in SKIP:
            continue
        slug = path.stem
        html = path.read_text(encoding="utf-8")
        title = extract_h1(html) or slug.replace("-", " ").title()
        category = cats.get(slug, "Real Value · Insights")
        try:
            render_og_card(slug, title, category)
            new_html = inject_og_meta(html, slug)
            if new_html != html:
                path.write_text(new_html, encoding="utf-8")
            done += 1
            print(f"card: {slug}  [{category}]  “{title}”")
        except Exception as e:  # noqa: BLE001
            print(f"FAILED {slug}: {e}", file=sys.stderr)
    print(f"\ndone: {done} card(s)")


if __name__ == "__main__":
    main()
