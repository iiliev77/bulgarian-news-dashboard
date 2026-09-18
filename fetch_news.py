import json, re, html
from datetime import datetime, timezone
from urllib.parse import urljoin
from urllib.request import Request, urlopen

SOURCES = {
    "news": "https://dariknews.bg/novini",
    "sport": "https://dsport.bg/",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.5",
}

def fetch(url):
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=30) as r:
        raw = r.read()
        charset = r.headers.get_content_charset() or "utf-8"
        return raw.decode(charset, errors="replace")

def clean_title(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"\s+", " ", s).strip()

def extract_links(page, base, mode):
    # Capture ordinary article links from the site's HTML.
    pattern = re.compile(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', re.I | re.S)
    found = []
    seen = set()

    for href, body in pattern.findall(page):
        title = clean_title(body)
        if not title or len(title) < 15 or len(title) > 220:
            continue

        url = urljoin(base, html.unescape(href))
        low = url.lower()

        if mode == "news":
            # Darik article URLs are normally /novini/...
            if "dariknews.bg/novini/" not in low:
                continue
            if any(x in low for x in ["/tarsene", "/tag/", "/galeria", "/video"]):
                continue
        else:
            # Dsport article URLs are on dsport.bg and are not navigation pages.
            if "dsport.bg" not in low or low.rstrip("/") == "https://dsport.bg":
                continue
            if any(x in low for x in ["/novini", "/futbol", "/sport", "/search", "/kontakt", "/reklama"]):
                # Keep actual article links even if their path contains a section name.
                if len(low.split("/")) < 4:
                    continue

        key = (title.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        found.append({"title": title, "url": url})

    return found[:12]

def main():
    result = {"updated": datetime.now(timezone.utc).isoformat(), "news": [], "sport": []}
    failures = []

    for mode, url in SOURCES.items():
        try:
            page = fetch(url)
            items = extract_links(page, url, mode)
            if not items:
                raise RuntimeError("No article links found")
            result[mode] = items
        except Exception as e:
            failures.append(f"{mode}: {e}")

    # Do not destroy working data if one source temporarily fails.
    try:
        with open("news.json", "r", encoding="utf-8") as f:
            old = json.load(f)
        for key in ("news", "sport"):
            if not result[key] and old.get(key):
                result[key] = old[key]
    except Exception:
        pass

    if not result["news"] and not result["sport"]:
        raise SystemExit("Both sources failed: " + "; ".join(failures))

    with open("news.json", "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    if failures:
        print("Warnings:", " | ".join(failures))
    print("Updated:", result["updated"])
    print("News:", len(result["news"]), "Sport:", len(result["sport"]))

if __name__ == "__main__":
    main()
