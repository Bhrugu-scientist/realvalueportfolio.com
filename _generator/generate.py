#!/usr/bin/env python3
"""
Autonomous SEO/GEO article generator for realvalueportfolio.com.

Picks the next unpublished title from blog/content-plan.md, writes a full
article via the Claude API (matching the existing template exactly), wires it
into blog.html + sitemap.xml, and marks the plan. Publishes RVP_COUNT per run.

Runs headless from GitHub Actions; commit + push is handled by the workflow.
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path

import anthropic

ROOT = Path(__file__).resolve().parent.parent
BLOG = ROOT / "blog"
PLAN = BLOG / "content-plan.md"
BLOG_INDEX = ROOT / "blog.html"
SITEMAP = ROOT / "sitemap.xml"
GOLD = BLOG / "fd-vs-mutual-fund.html"  # the template every article must match

MODEL = os.environ.get("RVP_MODEL", "claude-opus-5")
COUNT = int(os.environ.get("RVP_COUNT", "2"))
TODAY = datetime.date.today().isoformat()

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

ARTICLE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "slug": {"type": "string"},
        "category": {"type": "string"},
        "card_title": {"type": "string"},
        "card_blurb": {"type": "string"},
        "html": {"type": "string"},
    },
    "required": ["slug", "category", "card_title", "card_blurb", "html"],
}


def next_titles(n):
    """Return up to n unpublished '- [ ] Title' entries from the plan."""
    lines = PLAN.read_text(encoding="utf-8").splitlines()
    out = []
    for line in lines:
        m = re.match(r"^- \[ \] (.+)$", line.strip())
        if m:
            out.append(m.group(1).strip())
            if len(out) >= n:
                break
    return out


def mark_published(title):
    text = PLAN.read_text(encoding="utf-8")
    text = text.replace(f"- [ ] {title}", f"- [x] {title}", 1)
    PLAN.write_text(text, encoding="utf-8")


def already_have(slug):
    return (BLOG / f"{slug}.html").exists()


SYSTEM = f"""You write SEO- and GEO-optimised educational articles for Real Value
Portfolio Management & Marketing — an AMFI-registered mutual fund distributor in
Bharuch, Gujarat (ARN 24454, NJ Wealth partner, founder Bhrugu Thakkar).

Your output must clone the attached GOLD template EXACTLY in structure: same
<head> (meta description + keywords, canonical, OG tags, THREE JSON-LD blocks —
Article, FAQPage with 3 Q&As, BreadcrumbList), same body shape (breadcrumb nav,
h1, meta line "By Bhrugu Thakkar · Real Value (ARN 24454) · {datetime.date.today().strftime('%B %Y')} · N min read",
an .answer "Short answer:" box, h2 sections with tables/lists, a .cta block, the
.share block, #rv-comments div, the .disc disclaimer), and the same trailing
<script> tags (article.css, share.js, comments.js) and DM Sans font link.

Hard rules:
- datePublished and dateModified = {TODAY}.
- canonical/OG url = https://www.realvalueportfolio.com/blog/<slug>.html
- Educational only. NEVER recommend specific fund names/AMCs as "buy this" — give
  frameworks and the numbers to check. General principles are fine.
- Always keep the exact .disc disclaimer text (market-risk + ARN 24454).
- Indian context, INR, plain clear English. Genuinely useful, non-thin content
  (~700-1000 words). Link to 1-2 sibling articles by relative /blog/ path if natural.
- Return valid, complete, self-contained HTML — no markdown, no code fences.

Return JSON: slug (kebab-case, from the title), category (a 2-4 word section
label like "Understanding Returns"), card_title (the blog-index headline, lower
sentence case), card_blurb (one-line teaser), html (the full article file)."""


def generate(title):
    gold = GOLD.read_text(encoding="utf-8")
    msg = client.messages.parse(
        model=MODEL,
        max_tokens=12000,
        system=SYSTEM,
        messages=[
            {
                "role": "user",
                "content": (
                    f"GOLD TEMPLATE (clone this structure exactly):\n\n{gold}\n\n"
                    f"---\n\nWrite the article for this title: \"{title}\""
                ),
            }
        ],
        output_config={"format": {"type": "json_schema", "schema": ARTICLE_SCHEMA}},
    )
    art = msg.parsed_output
    if not art:
        raise RuntimeError(f"no parsed output for: {title}")
    return art


def valid(html):
    need = ['class="answer"', "FAQPage", "ARN 24454", "article.css", 'class="disc"']
    return all(tok in html for tok in need)


def wire_in(art):
    slug = art["slug"].strip().strip("/").replace(".html", "")
    (BLOG / f"{slug}.html").write_text(art["html"], encoding="utf-8")

    # Blog index card — prepend above the first category block (freshest on top)
    idx = BLOG_INDEX.read_text(encoding="utf-8")
    card = (
        f'  <div class="cat">{art["category"]}</div>\n'
        f'  <a class="post" href="/blog/{slug}.html">\n'
        f'    <h3>{art["card_title"]}</h3>\n'
        f'    <p>{art["card_blurb"]}</p>\n'
        f'  </a>\n\n'
    )
    anchor = '  <div class="cat">'
    if anchor in idx:
        idx = idx.replace(anchor, card + anchor, 1)
        BLOG_INDEX.write_text(idx, encoding="utf-8")

    # Sitemap entry
    sm = SITEMAP.read_text(encoding="utf-8")
    entry = (
        "  <url>\n"
        f"    <loc>https://www.realvalueportfolio.com/blog/{slug}.html</loc>\n"
        "    <changefreq>monthly</changefreq>\n"
        "    <priority>0.8</priority>\n"
        "  </url>\n"
    )
    if f"/blog/{slug}.html" not in sm:
        sm = sm.replace("</urlset>", entry + "</urlset>", 1)
        SITEMAP.write_text(sm, encoding="utf-8")
    return slug


def main():
    published = 0
    for title in next_titles(COUNT * 3):  # headroom for skips
        if published >= COUNT:
            break
        try:
            art = generate(title)
            slug = art["slug"].strip().strip("/").replace(".html", "")
            if already_have(slug) or not valid(art["html"]):
                print(f"skip (dup/invalid): {title}", file=sys.stderr)
                mark_published(title)  # don't retry a bad title forever
                continue
            wire_in(art)
            mark_published(title)
            published += 1
            print(f"published: {slug}  ({title})")
        except Exception as e:  # noqa: BLE001 — keep the run alive
            print(f"error on '{title}': {e}", file=sys.stderr)
    print(f"done: {published} article(s)")
    if published == 0:
        sys.exit(1)  # nothing shipped → let the workflow surface it


if __name__ == "__main__":
    main()
