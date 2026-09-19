#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Обновява news.json с най-новите новини от:
- DarikNews.bg – последни новини
- Gong.bg – спортни новини

Скриптът е предназначен за GitHub Actions.
"""

import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


OUTPUT = Path("news.json")
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0 Safari/537.36"
    ),
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}

SOURCES = [
    {
        "name": "DarikNews",
        "section": "news",
        "url": "https://dariknews.bg/novini",
        "domain": "dariknews.bg",
    },
    {
        "name": "Gong",
        "section": "sport",
        "url": "https://gong.bg/",
        "domain": "gong.bg",
    },
]


def clean_text(value):
    return re.sub(r"\s+", " ", value or "").strip()


def absolute_url(base, value):
    if not value:
        return ""
    return urljoin(base, value)


def valid_article_url(url, domain):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        host = parsed.netloc.lower().split(":")[0]
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def image_from_node(node, base_url):
    # Look first inside the article/card, then in nearby parent containers.
    candidates = [node]
    parent = node.parent
    if parent:
        candidates.append(parent)
    if parent and parent.parent:
        candidates.append(parent.parent)

    for item in candidates:
        img = item.find("img")
        if not img:
            continue

        for attr in ("src", "data-src", "data-lazy-src", "data-original"):
            value = img.get(attr)
            if value:
                return absolute_url(base_url, value)

        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            value = srcset.split(",")[0].strip().split(" ")[0]
            if value:
                return absolute_url(base_url, value)

    return ""


def extract_articles(html, source):
    soup = BeautifulSoup(html, "html.parser")
    domain = source["domain"]
    base_url = source["url"]
    found = []
    seen = set()

    # Most news sites expose articles as <article>. This is the preferred path.
    nodes = soup.find_all("article")

    # If the site does not use article tags consistently, inspect links as fallback.
    if not nodes:
        nodes = soup.find_all("a", href=True)

    for node in nodes:
        if node.name == "a":
            link = node
        else:
            link = node.find("a", href=True)

        if not link:
            continue

        href = absolute_url(base_url, link.get("href"))
        if not valid_article_url(href, domain):
            continue

        # Avoid category/navigation URLs and obvious non-article pages.
        path = urlparse(href).path.lower()
        if source["name"] == "DarikNews":
            if "/novini/" not in path:
                continue
        else:
            # Gong article URLs generally contain more than the bare homepage path.
            if path in ("", "/"):
                continue
            if not any(part in path for part in ("/news/", "/football/", "/basketball/",
                                                  "/volleyball/", "/tennis/", "/esports/",
                                                  "/motor/", "/combat/", "/other/")):
                # Keep likely article URLs as a fallback.
                if path.count("/") < 2:
                    continue

        title = ""
        # Prefer heading text inside the card.
        for tag in ("h1", "h2", "h3", "h4", "h5"):
            heading = node.find(tag)
            if heading:
                title = clean_text(heading.get_text(" ", strip=True))
                if title:
                    break

        if not title:
            title = clean_text(link.get_text(" ", strip=True))

        # Some cards contain buttons/live labels. Reject unusable text.
        if len(title) < 12 or len(title) > 300:
            continue

        # Remove common UI-only titles.
        bad = {
            "виж още",
            "последни",
            "начало",
            "новини",
            "спорт",
            "live livestream",
        }
        if title.lower() in bad:
            continue

        if href in seen:
            continue
        seen.add(href)

        image = image_from_node(node, base_url)

        found.append(
            {
                "title": title,
                "url": href,
                "image": image,
                "source": source["name"],
                "section": source["section"],
            }
        )

        if len(found) >= 20:
            break

    return found


def fetch_source(source):
    response = requests.get(
        source["url"],
        headers=HEADERS,
        timeout=25,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return extract_articles(response.text, source)


def main():
    all_news = []
    errors = []

    for source in SOURCES:
        try:
            articles = fetch_source(source)
            print(f"{source['name']}: намерени {len(articles)} новини")
            all_news.extend(articles)
        except Exception as exc:
            message = f"{source['name']}: {exc}"
            print(f"ERROR: {message}")
            errors.append(message)

    # Keep the output usable even if one source temporarily fails.
    if not all_news:
        raise RuntimeError("Не е намерена нито една новина от източниците.")

    # Remove duplicates by URL while preserving source order.
    unique = []
    seen_urls = set()
    for item in all_news:
        if item["url"] not in seen_urls:
            seen_urls.add(item["url"])
            unique.append(item)

    data = {
        "updated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "news": [x for x in unique if x["section"] == "news"][:15],
        "sport": [x for x in unique if x["section"] == "sport"][:15],
        "errors": errors,
    }

    OUTPUT.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(
        f"Готово: {len(data['news'])} новини + "
        f"{len(data['sport'])} спортни новини → {OUTPUT}"
    )


if __name__ == "__main__":
    main()
