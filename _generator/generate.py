#!/usr/bin/env python3
"""
Autonomous SEO/GEO article generator for realvalueportfolio.com.

Picks the next unpublished title from blog/content-plan.md, writes a full
article via the Claude API (matching the existing template exactly), wires it
into blog.html + sitemap.xml, and marks the plan. Publishes RVP_COUNT per run.

Runs headless from GitHub Actions; commit + push is handled by the workflow.
"""
import datetime
import html as _html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOG = ROOT / "blog"
PLAN = BLOG / "content-plan.md"
BLOG_INDEX = ROOT / "blog.html"
SITEMAP = ROOT / "sitemap.xml"
GOLD = BLOG / "fd-vs-mutual-fund.html"  # the template every article must match

MODEL = os.environ.get("RVP_MODEL", "claude-opus-5")
COUNT = int(os.environ.get("RVP_COUNT", "2"))
TODAY = datetime.date.today().isoformat()

_client = None


def get_client():
    """Lazy client so this module imports without an API key (backfill uses it)."""
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


# ── Social share cards (og:image) ───────────────────────────────────────────
# Every article gets a branded 1200x630 card with its own title baked in, so a
# link pasted into WhatsApp / LinkedIn / X renders a proper preview instead of
# bare text. Rendered with headless Chrome (set CHROME_BIN in CI).
OG_DIR = BLOG / "og"

OG_TEMPLATE = """<!doctype html><html lang="en"><head><meta charset="utf-8"/>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Hanken+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{background:#0a0a0d}
  .card{width:1200px;height:630px;background:#0a0a0d;color:#f4f1ea;position:relative;overflow:hidden;font-family:"Hanken Grotesk",sans-serif;padding:72px 76px;display:flex;flex-direction:column}
  .dim{position:absolute;right:-160px;top:-160px;width:460px;height:460px;border-radius:50%;border:1px solid rgba(189,182,255,.16)}
  .dim2{position:absolute;right:-60px;bottom:-220px;width:380px;height:380px;border-radius:50%;border:1px solid rgba(189,182,255,.10)}
  .rule{position:absolute;left:0;top:0;width:8px;height:100%;background:#bdb6ff}
  .top{display:flex;align-items:center;justify-content:space-between}
  .brand{font-family:"Instrument Serif",serif;font-size:34px;letter-spacing:.5px}
  .brand b{color:#bdb6ff;font-weight:400;font-style:italic}
  .eyebrow{font-size:17px;letter-spacing:.28em;text-transform:uppercase;color:#bdb6ff;font-weight:600;text-align:right;max-width:520px}
  .title{font-family:"Instrument Serif",serif;font-weight:400;font-size:{{SIZE}}px;line-height:1.05;letter-spacing:-.5px;margin-top:auto;max-width:1048px}
  .title .a{color:#bdb6ff;font-style:italic}
  .foot{margin-top:34px;padding-top:26px;border-top:1px solid rgba(244,241,234,.14);display:flex;align-items:center;justify-content:space-between}
  .foot .site{color:#bdb6ff;font-size:24px;font-weight:600}
  .foot .who{color:#8e8b99;font-size:20px;font-weight:400}
</style></head>
<body>
  <div class="card">
    <div class="rule"></div><div class="dim"></div><div class="dim2"></div>
    <div class="top"><div class="brand">Real <b>Value</b></div><div class="eyebrow">{{CATEGORY}}</div></div>
    <div class="title">{{TITLE}}</div>
    <div class="foot"><div class="site">realvalueportfolio.com</div><div class="who">Bhrugu Thakkar · AMFI ARN 24454</div></div>
  </div>
</body></html>"""


def _title_size(title):
    """Deterministic font size (px) so 2-3 lines always fit the card nicely."""
    n = len(title)
    if n <= 40:
        return 84
    if n <= 58:
        return 74
    if n <= 78:
        return 64
    if n <= 104:
        return 54
    return 48


def _accentize(title):
    """Escape the title and tint numeric / ₹ / % tokens lilac for a little pop."""
    parts = _html.escape(title).split(" ")
    out = [f'<span class="a">{p}</span>' if re.search(r"[₹%]|\d", p) else p for p in parts]
    return " ".join(out)


def _find_chrome():
    candidates = [
        os.environ.get("CHROME_BIN"),
        "google-chrome-stable", "google-chrome", "chromium", "chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for c in candidates:
        if not c:
            continue
        if os.path.sep in c and os.path.exists(c):
            return c
        found = shutil.which(c)
        if found:
            return found
    raise RuntimeError("no Chrome/Chromium binary found (set CHROME_BIN)")


def render_og_card(slug, title, category):
    """Render blog/og/<slug>.png. Returns the repo-relative path."""
    OG_DIR.mkdir(parents=True, exist_ok=True)
    eyebrow = (category or "Real Value").strip().upper()[:42]
    doc = (OG_TEMPLATE
           .replace("{{CATEGORY}}", _html.escape(eyebrow))
           .replace("{{SIZE}}", str(_title_size(title)))
           .replace("{{TITLE}}", _accentize(title)))
    tmp = OG_DIR / f"_tmp_{slug}.html"
    tmp.write_text(doc, encoding="utf-8")
    out = OG_DIR / f"{slug}.png"
    try:
        subprocess.run(
            [_find_chrome(), "--headless=new", "--no-sandbox", "--disable-gpu",
             "--hide-scrollbars", "--force-device-scale-factor=2",
             "--window-size=1200,630", "--virtual-time-budget=6000",
             f"--screenshot={out}", tmp.as_uri()],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    finally:
        tmp.unlink(missing_ok=True)
    if not out.exists():
        raise RuntimeError(f"card render produced no file for {slug}")
    return f"blog/og/{slug}.png"


def extract_h1(html):
    m = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None


def strip_og_meta(html):
    """Remove any share-card meta (so a copied template URL can't leak through)."""
    html = re.sub(r'\s*<meta property="og:image(?::width|:height)?"[^>]*>', "", html)
    html = re.sub(r'\s*<meta name="twitter:(?:card|image)"[^>]*>', "", html)
    return html


def inject_og_meta(html, slug):
    """Set og:image + twitter card meta on an article <head> (authoritative)."""
    html = strip_og_meta(html)
    # Apex host (no www): www 301-redirects, and scrapers (WhatsApp/FB) won't
    # follow a redirect on og:image — must be a direct 200.
    url = f"https://realvalueportfolio.com/blog/og/{slug}.png"
    block = (
        f'<meta property="og:image" content="{url}"/>\n'
        f'<meta property="og:image:width" content="1200"/>\n'
        f'<meta property="og:image:height" content="630"/>\n'
        f'<meta name="twitter:card" content="summary_large_image"/>\n'
        f'<meta name="twitter:image" content="{url}"/>\n'
    )
    m = re.search(r'<meta property="og:url"[^>]*>\s*', html)
    if m:
        return html[:m.end()] + block + html[m.end():]
    return html.replace("</head>", block + "</head>", 1)


# The exact AMFI market-risk disclaimer — compliance-mandatory on every article.
DISC = (
    '<div class="disc">Mutual fund investments are subject to market risks. '
    "Read all scheme related documents carefully. Educational content, not "
    "personalised advice. Real Value — AMFI Registered Mutual Fund Distributor, "
    "ARN 24454.</div>"
)


def guarantee_disc(html):
    """Ensure the disclaimer is present (the model drops it intermittently)."""
    if 'class="disc"' in html:
        return html
    if '<script src="share.js"></script>' in html:
        return html.replace(
            '<script src="share.js"></script>', DISC + '\n<script src="share.js"></script>', 1
        )
    return html.replace("</body>", DISC + "\n</body>", 1)


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
    gold = strip_og_meta(GOLD.read_text(encoding="utf-8"))
    # Raw json_schema → use messages.create + json.loads(content text). (parse()
    # populates parsed_output only when given output_format=<type>, not a schema.)
    msg = get_client().messages.create(
        model=MODEL,
        max_tokens=16000,
        # Deterministic template-clone task: adaptive thinking can burn the whole
        # token budget before emitting the JSON. Disable it (Sonnet 5 allows).
        thinking={"type": "disabled"},
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
    text = next((b.text for b in msg.content if getattr(b, "type", None) == "text"), None)
    if not text:
        raise RuntimeError(
            f"no text output for: {title} (stop_reason={getattr(msg, 'stop_reason', '?')})"
        )
    art = json.loads(text)
    art["html"] = guarantee_disc(art["html"])
    return art


def missing_tokens(html):
    need = ['class="answer"', "FAQPage", "ARN 24454", "article.css", 'class="disc"']
    return [t for t in need if t not in html]


def wire_in(art):
    slug = art["slug"].strip().strip("/").replace(".html", "")
    html = art["html"]

    # Branded share card + og:image meta (never block a publish if it fails).
    display_title = extract_h1(html) or art.get("card_title") or slug
    try:
        render_og_card(slug, display_title, art.get("category", "Real Value"))
        html = inject_og_meta(html, slug)
    except Exception as e:  # noqa: BLE001
        print(f"og card failed for {slug}: {e}", file=sys.stderr)

    (BLOG / f"{slug}.html").write_text(html, encoding="utf-8")

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
            if already_have(slug):
                print(f"skip (dup): {title}", file=sys.stderr)
                mark_published(title)
                continue
            miss = missing_tokens(art["html"])
            if miss:
                print(f"skip (invalid, missing {miss}): {title}", file=sys.stderr)
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
