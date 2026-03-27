#!/usr/bin/env python3
"""
Morning Briefing Generator
Fetches today's top news, calls Claude to synthesize into a curated reading list.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python3 generate.py
"""

import os
import json
import html as html_module
from datetime import datetime

import feedparser
import anthropic

OUTPUT_HTML = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")
ARCHIVE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "archive")

# ─── RSS Feeds ────────────────────────────────────────────────────────────────

MAIN_FEEDS = {
    "NYT":              "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
    "Washington Post":  "https://feeds.washingtonpost.com/rss/politics",
    "WSJ":              "https://feeds.a.dj.com/rss/RSSWorldNews.xml",
    "Axios":            "https://api.axios.com/feed/",
    "The Atlantic":     "https://www.theatlantic.com/feed/all/",
    "New Yorker":       "https://www.newyorker.com/feed/everything",
    "AP":               "https://feeds.apnews.com/apnews/topnews",
    "Reuters":          "https://feeds.reuters.com/reuters/topNews",
}

RIGHT_FEEDS = {
    "Fox News":           "https://moxie.foxnews.com/google-publisher/latest.xml",
    "WSJ Opinion":        "https://feeds.a.dj.com/rss/RSSOpinion.xml",
    "National Review":    "https://www.nationalreview.com/feed/",
    "Washington Examiner":"https://www.washingtonexaminer.com/section/news/feed/",
    "The Federalist":     "https://thefederalist.com/feed/",
}

LEFT_FEEDS = {
    "The Guardian":  "https://www.theguardian.com/world/rss",
    "Vox":           "https://www.vox.com/rss/index.xml",
    "MSNBC":         "https://www.msnbc.com/feeds/latest",
    "Slate":         "https://feeds.slate.com/slate/all",
    "The Nation":    "https://www.thenation.com/feed/?post_type=article",
}

LOCAL_FEEDS = {
    # Biggest local papers across the country
    "LA Times":         "https://www.latimes.com/local/rss2.0.xml",
    "Chicago Tribune":  "https://www.chicagotribune.com/arcio/rss/",
    "Houston Chronicle":"https://www.houstonchronicle.com/rss/feed/news/",
    "Miami Herald":     "https://www.miamiherald.com/latest-news/?widgetName=rssfeed&widgetContentId=712015&getXmlFeed=true",
    "Boston Globe":     "https://www.bostonglobe.com/topstories/rss.xml",
    "Philadelphia Inquirer": "https://www.inquirer.com/arcio/rss/category/news/?query=&d=7",
    "Dallas Morning News": "https://www.dallasnews.com/arc/outboundfeeds/rss/?outputType=xml",
    "Seattle Times":    "https://www.seattletimes.com/feed/",
    "Denver Post":      "https://www.denverpost.com/feed/",
    "Atlanta Journal-Constitution": "https://www.ajc.com/news/feed/",
}

MAPLEWOOD_QUERY = "https://news.google.com/rss/search?q=Maplewood+NJ&hl=en-US&gl=US&ceid=US:en"
NJ_QUERY = "https://news.google.com/rss/search?q=New+Jersey+news&hl=en-US&gl=US&ceid=US:en"
HIGHER_ED_QUERY = "https://news.google.com/rss/search?q=Trump+universities+higher+education&hl=en-US&gl=US&ceid=US:en"


# ─── Fetch ────────────────────────────────────────────────────────────────────

def fetch_feed(name, url, max_items=6):
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "Mozilla/5.0"}, agent="Mozilla/5.0", handlers=[])
        items = []
        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if title and link:
                items.append({"source": name, "title": title, "url": link})
        return items
    except Exception as e:
        print(f"  [warn] {name}: {e}")
        return []


def fetch_feed_with_timeout(name, url, max_items=6, timeout=8):
    """Fetch a feed with a hard timeout to avoid hangs."""
    import signal

    def _handler(signum, frame):
        raise TimeoutError(f"Timeout fetching {name}")

    signal.signal(signal.SIGALRM, _handler)
    signal.alarm(timeout)
    try:
        result = fetch_feed(name, url, max_items)
        signal.alarm(0)
        return result
    except TimeoutError:
        print(f"  [timeout] {name} — skipping")
        signal.alarm(0)
        return []
    except Exception as e:
        signal.alarm(0)
        print(f"  [warn] {name}: {e}")
        return []


def fetch_all():
    print("Fetching feeds...")
    all_articles = {}

    print("  Main sources...")
    all_articles["main"] = []
    for name, url in MAIN_FEEDS.items():
        items = fetch_feed_with_timeout(name, url)
        all_articles["main"].extend(items)
        print(f"    {name}: {len(items)} items")

    print("  Right-leaning sources...")
    all_articles["right"] = []
    for name, url in RIGHT_FEEDS.items():
        items = fetch_feed_with_timeout(name, url)
        all_articles["right"].extend(items)
        print(f"    {name}: {len(items)} items")

    print("  Left-leaning sources...")
    all_articles["left"] = []
    for name, url in LEFT_FEEDS.items():
        items = fetch_feed_with_timeout(name, url)
        all_articles["left"].extend(items)
        print(f"    {name}: {len(items)} items")

    print("  Local sources...")
    all_articles["local"] = []
    for name, url in LOCAL_FEEDS.items():
        items = fetch_feed_with_timeout(name, url, max_items=3)
        all_articles["local"].extend(items)
        print(f"    {name}: {len(items)} items")

    print("  Higher education / Trump vs. universities...")
    higher_ed = fetch_feed_with_timeout("Google News", HIGHER_ED_QUERY, max_items=8)
    all_articles["higher_ed"] = higher_ed
    print(f"    Higher ed: {len(higher_ed)} items")

    return all_articles


# ─── Synthesize with Claude ───────────────────────────────────────────────────

SYSTEM_PROMPT = """You are the editor of a premium daily briefing called "Daily Briefing for Natalie."
Natalie Kitroeff is a senior journalist at The New York Times. She is well-informed, politically sophisticated, and time-poor.
Your job is to produce a tightly curated, deeply synthesized morning reading list — not a list of links, but a real editorial product.

The output must be a JSON object. All HTML fields can contain inline <a href="..."> links.
Write with authority and precision. Be specific — name names, cite numbers, quote when useful. Never be vague."""

USER_PROMPT_TEMPLATE = """Today is {date}. Here are the raw headlines fetched from RSS feeds.
Synthesize them into a curated daily briefing.

MAIN SOURCES (NYT, WaPo, WSJ, Axios, Atlantic, New Yorker, AP, Reuters):
{main}

RIGHT-LEANING SOURCES (Fox, WSJ Opinion, National Review, Examiner, Federalist):
{right}

LEFT-LEANING SOURCES (Guardian, Vox, MSNBC, Slate, The Nation):
{left}

LOCAL SOURCES (LA Times, Chicago Tribune, Houston Chronicle, Miami Herald, Boston Globe, etc.):
{local}

HIGHER EDUCATION / TRUMP VS. UNIVERSITIES (use these to enrich the right and left summaries):
{higher_ed}

Return a JSON object with exactly these fields:

{{
  "top_stories": [
    {{
      "category": "Category name — e.g. Politics, International, Economy, Justice, Climate, Technology, Culture. Use whatever categories fit today's news. Aim for 3-5 categories total.",
      "stories": [
        {{
          "title": "Punchy, specific headline — rewrite it to be clear and direct",
          "url": "url from source",
          "source": "source name",
          "description": "2-3 sentence description. Be specific: names, numbers, context, why it matters."
        }}
      ]
    }}
  ],  // 3-5 category buckets, 2-3 stories each, covering the most important news of the day

  "right_summary": "HTML synthesis of what right-wing media is focused on today. Format as a series of bullet points (<ul><li>...</li></ul>), one per major topic or argument. Each bullet should be 2-4 sentences. Use <strong> to bold the most important names, numbers, and claims. Include inline <a href='...'> links to the specific articles, opinion pieces, or tweets being discussed — link directly to the source making the argument, not just a homepage. Be specific: name the commentators, quote them, explain the arguments. If any bullets touch on higher education, universities, or Trump vs. colleges/academia, include them and bold the key claims.",

  "left_summary": "HTML synthesis of what left-wing/progressive media is focused on today. Same format — bullet points (<ul><li>...</li></ul>), one per major topic. Use <strong> to bold key names, numbers, and claims. Include inline <a href='...'> links to specific articles, opinion pieces, or tweets being discussed. Be specific: name writers and outlets, quote them, explain the arguments. If any bullets touch on higher education, universities, or Trump vs. colleges/academia, include them and bold the key claims.",

  "must_reads": [
    {{
      "title": "Article title",
      "url": "url",
      "source": "source name"
    }}
  ],  // 5-8 longer-form pieces worth reading — prioritize Atlantic, New Yorker, longform WaPo/NYT

  "local_stories": [
    {{
      "title": "Headline",
      "url": "url",
      "source": "source",
      "description": "1-2 sentences."
    }}
  ],  // 4-6 most important local stories from across the country

  "also_noted": [
    {{
      "title": "Punchy headline",
      "url": "url",
      "source": "source"
    }}
  ]  // 4-6 additional items worth knowing, didn't make top stories
}}"""


def format_articles(articles):
    lines = []
    for a in articles:
        lines.append(f"- [{a['source']}] {a['title']} | {a['url']}")
    return "\n".join(lines) if lines else "(none fetched)"


def synthesize(all_articles):
    print("\nSynthesizing with Claude...")
    client = anthropic.Anthropic()

    date_str = datetime.now().strftime("%A, %B %d, %Y")
    prompt = USER_PROMPT_TEMPLATE.format(
        date=date_str,
        main=format_articles(all_articles["main"]),
        right=format_articles(all_articles["right"]),
        left=format_articles(all_articles["left"]),
        local=format_articles(all_articles["local"]),
        higher_ed=format_articles(all_articles.get("higher_ed", [])),
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = response.content[0].text.strip()
    # Strip markdown fences if present
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1]
        raw = raw.rsplit("```", 1)[0]

    data = json.loads(raw)
    print("  Claude synthesis complete.")
    return data


# ─── Render HTML ──────────────────────────────────────────────────────────────

COLORS = {
    "sage":       "#6b7f6b",
    "steel":      "#5c7a8a",
    "terra":      "#8a6f5e",
    "clay":       "#9a7b6b",
    "umber":      "#7a6b5a",
    "indigo":     "#6b6a7a",
    "dusty_rose": "#8a6b7a",
    "warm_green": "#7a8b6b",
}

def dot_section(label, color, content_html):
    return f"""
<section>
    <div class="section-header">
        <div class="section-dot" style="background: {color};"></div>
        <h2>{label}</h2>
        <div class="section-line"></div>
    </div>
    {content_html}
</section>"""

def story_list(stories, show_desc=True):
    items = []
    for s in stories:
        title_esc = html_module.escape(s["title"])
        url_esc = html_module.escape(s.get("url", "#"))
        source_esc = html_module.escape(s.get("source", ""))
        desc = s.get("description", "")
        desc_html = f'<span class="desc">{html_module.escape(desc)}</span>' if desc and show_desc else ""
        items.append(f"""        <li>
            <a href="{url_esc}" target="_blank">{title_esc}</a><span class="source">{source_esc}</span>
            {desc_html}
        </li>""")
    return f'<ul class="link-list">\n' + "\n".join(items) + "\n    </ul>"

def divider():
    return """
<div class="divider"><div class="divider-dot"></div><div class="divider-dot"></div><div class="divider-dot"></div></div>"""

def render_html(data):
    date_str = datetime.now().strftime("%A, %B %d, %Y")

    sections = []

    # Right summary
    sections.append(dot_section(
        "What the Right Is Saying", COLORS["umber"],
        f'<div class="synthesis">{data["right_summary"]}</div>'
    ))

    # Left summary
    sections.append(dot_section(
        "What the Left Is Saying", COLORS["dusty_rose"],
        f'<div class="synthesis">{data["left_summary"]}</div>'
    ))

    sections.append(divider())

    # Top stories — categorized
    color_cycle = [COLORS["sage"], COLORS["steel"], COLORS["terra"], COLORS["clay"], COLORS["indigo"]]
    for i, bucket in enumerate(data["top_stories"]):
        color = color_cycle[i % len(color_cycle)]
        sections.append(dot_section(
            bucket["category"], color,
            story_list(bucket["stories"], show_desc=True)
        ))

    # Must reads
    sections.append(dot_section(
        "Must Reads", COLORS["steel"],
        story_list(data["must_reads"], show_desc=False)
    ))

    sections.append(divider())

    # Local
    if data.get("local_stories"):
        sections.append(dot_section(
            "Local — Across the Country", COLORS["terra"],
            story_list(data["local_stories"], show_desc=True)
        ))

    sections.append(divider())

    # Also noted
    if data.get("also_noted"):
        sections.append(dot_section(
            "Also Noted", COLORS["indigo"],
            story_list(data["also_noted"], show_desc=False)
        ))

    html_out = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Daily Briefing — {date_str}</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif&family=Inter:wght@300;400;500;600&family=Newsreader:ital,opsz,wght@0,6..72,300;0,6..72,400;0,6..72,500;1,6..72,300;1,6..72,400&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            background: #f7f5f0;
            color: #2c2a25;
            line-height: 1.75;
            max-width: 640px;
            margin: 0 auto;
            padding: 3rem 2rem 4rem;
            -webkit-font-smoothing: antialiased;
        }}
        header {{
            text-align: center;
            padding-bottom: 2rem;
            margin-bottom: 2.5rem;
            position: relative;
        }}
        header::after {{
            content: "";
            display: block;
            width: 50px;
            height: 2px;
            background: #b5b0a6;
            margin: 0 auto;
            position: absolute;
            bottom: 0;
            left: 50%;
            transform: translateX(-50%);
        }}
        .masthead {{
            font-family: 'Instrument Serif', Georgia, serif;
            font-size: 2.8rem;
            font-weight: 400;
            letter-spacing: -0.02em;
            color: #2c2a25;
            line-height: 1.1;
        }}
        .for-line {{
            font-family: 'Newsreader', serif;
            font-style: italic;
            font-size: 0.9rem;
            color: #b5b0a6;
            margin-top: 0.35rem;
        }}
        .date {{
            font-family: 'Inter', sans-serif;
            font-size: 0.68rem;
            font-weight: 400;
            color: #8a857c;
            text-transform: uppercase;
            letter-spacing: 0.18em;
            margin-top: 0.4rem;
        }}
        section {{ margin-bottom: 2.2rem; }}
        .section-header {{
            display: flex;
            align-items: center;
            gap: 0.7rem;
            margin-bottom: 1rem;
        }}
        .section-dot {{
            width: 7px;
            height: 7px;
            border-radius: 50%;
            flex-shrink: 0;
        }}
        h2 {{
            font-family: 'Inter', sans-serif;
            font-size: 0.65rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.14em;
            color: #8a857c;
        }}
        .section-line {{
            flex: 1;
            height: 1px;
            background: #e4e0d8;
        }}
        .link-list {{ list-style: none; padding: 0; }}
        .link-list li {{
            padding: 0.55rem 0;
            border-bottom: 1px solid rgba(228,224,216,0.5);
        }}
        .link-list li:last-child {{ border-bottom: none; }}
        .link-list a {{
            font-family: 'Inter', sans-serif;
            color: #2c2a25;
            text-decoration: none;
            font-weight: 500;
            font-size: 0.95rem;
            line-height: 1.4;
        }}
        .link-list a:hover {{ color: #555; }}
        .link-list .source {{
            font-family: 'Inter', sans-serif;
            font-size: 0.6rem;
            font-weight: 500;
            color: #b5b0a6;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            margin-left: 0.4rem;
        }}
        .link-list .desc {{
            display: block;
            font-size: 0.85rem;
            font-weight: 400;
            color: #4a4640;
            margin-top: 0.2rem;
            line-height: 1.6;
        }}
        .synthesis {{
            background: #fffef9;
            border-radius: 10px;
            padding: 1.3rem 1.4rem;
            font-family: 'Inter', sans-serif;
            font-size: 0.9rem;
            line-height: 1.8;
            color: #2c2a25;
            border: 1px solid #e4e0d8;
        }}
        .synthesis p {{ margin-bottom: 0.9rem; }}
        .synthesis p:last-child {{ margin-bottom: 0; }}
        .synthesis ul {{
            list-style: none;
            padding: 0;
            margin: 0;
        }}
        .synthesis ul li {{
            padding: 0.75rem 0 0.75rem 1.1rem;
            border-bottom: 1px solid rgba(228,224,216,0.6);
            position: relative;
            line-height: 1.7;
        }}
        .synthesis ul li:last-child {{ border-bottom: none; padding-bottom: 0; }}
        .synthesis ul li::before {{
            content: "—";
            position: absolute;
            left: 0;
            color: #b5b0a6;
            font-weight: 300;
        }}
        .synthesis strong {{ font-weight: 600; color: #1a1816; }}
        .synthesis a {{
            color: #2c2a25;
            text-decoration: underline;
            text-decoration-color: rgba(0,0,0,0.25);
            text-underline-offset: 2px;
        }}
        .synthesis a:hover {{ text-decoration-color: #2c2a25; }}
        .divider {{
            display: flex;
            align-items: center;
            justify-content: center;
            margin: 1.8rem 0;
            gap: 0.5rem;
        }}
        .divider-dot {{
            width: 3px;
            height: 3px;
            border-radius: 50%;
            background: #b5b0a6;
        }}
        footer {{
            margin-top: 2.5rem;
            text-align: center;
            font-family: 'Inter', sans-serif;
            font-size: 0.6rem;
            color: #b5b0a6;
            letter-spacing: 0.04em;
            line-height: 1.8;
        }}
        @media (max-width: 600px) {{
            body {{ padding: 1.5rem 1rem 3rem; }}
            .masthead {{ font-size: 2.2rem; }}
        }}
    </style>
</head>
<body>

<header>
    <div class="masthead">Daily Briefing</div>
    <div class="for-line">for Natalie</div>
    <div class="date">{date_str}</div>
</header>

<main>
{''.join(sections)}
</main>

<footer>
    <p>Compiled for Natalie Kitroeff</p>
    <p>NYT &middot; WSJ &middot; Washington Post &middot; Axios &middot; The Atlantic &middot; New Yorker &middot; AP &middot; Reuters &middot; Fox &middot; Guardian &middot; Vox &middot; and more</p>
</footer>

</body>
</html>"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"\nNewsletter written to {OUTPUT_HTML}")

    # Archive a dated copy
    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(ARCHIVE_DIR, datetime.now().strftime("%Y-%m-%d") + ".html")
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html_out)
    print(f"Archived to {archive_path}")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    all_articles = fetch_all()
    data = synthesize(all_articles)
    render_html(data)
    print("Done! Open with: open index.html")


if __name__ == "__main__":
    main()
