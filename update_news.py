#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Обновява news.json с най-новите новини от:
- DarikNews.bg — новини
- Gong.bg — спорт

За всяка статия:
- намира заглавие и линк от началната/последните новини страница;
- отваря самата статия;
- извлича снимката на конкретната статия, приоритетно от og:image;
- записва image URL в news.json.

Предназначено за GitHub Actions.
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
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "bg-BG,bg;q=0.9,en;q=0.8",
}

SOURCES = [
    {
        "name": "DarikNews",
        "section": "news",
        "url": "https://dariknews.bg/novini",
        "domain": "dariknews.bg",
        "max_articles": 20,
    },
    {
        "name": "Gong",
        "section": "sport",
        "url": "https://gong.bg/",
        "domain": "gong.bg",
        "max_articles": 20,
    },
]

session = requests.Session()
session.headers.update(HEADERS)


def clean_text(value):
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def absolute_url(base, value):
    if not value:
        return ""
    return urljoin(base, value.strip())


def valid_article_url(url, domain):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False

        host = (parsed.netloc or "").lower()
        return host == domain or host.endswith("." + domain)
    except Exception:
        return False


def get_html(url):
    response = session.get(url, timeout=20)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or response.encoding
    return response.text


def meta_content(soup, *, prop=None, name=None):
    tag = None

    if prop:
        tag = soup.find("meta", attrs={"property": prop})

    if not tag and name:
        tag = soup.find("meta", attrs={"name": name})

    if tag:
        return clean_text(tag.get("content", ""))

    return ""


def extract_article_image(article_url):
    """
    Извлича снимката от самата статия.
    Приоритет:
      1. og:image
      2. twitter:image
      3. JSON-LD image
      4. първата подходяща img в main/article
    """
    try:
        html = get_html(article_url)
        soup = BeautifulSoup(html, "html.parser")

        # 1) Open Graph — обикновено е основната снимка на статията.
        image = meta_content(soup, prop="og:image")
        if image:
            return absolute_url(article_url, image)

        # 2) Twitter card.
        image = meta_content(soup, name="twitter:image")
        if image:
            return absolute_url(article_url, image)

        # 3) JSON-LD.
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            try:
                data = json.loads(script.string or script.get_text())
            except Exception:
                continue

            objects = data if isinstance(data, list) else [data]

            for obj in objects:
                if not isinstance(obj, dict):
                    continue

                image_data = obj.get("image")

                if isinstance(image_data, str):
                    image = image_data
                elif isinstance(image_data, dict):
                    image = image_data.get("url", "")
                elif isinstance(image_data, list) and image_data:
                    image = image_data[0]
                else:
                    image = ""

                if image:
                    return absolute_url(article_url, image)

        # 4) Резервен вариант — снимка от основното съдържание.
        containers = [
            soup.find("article"),
            soup.find("main"),
            soup.find("div", attrs={"itemprop": "articleBody"}),
        ]

        for container in containers:
            if not container:
                continue

            for img in container.find_all("img"):
                candidates = [
                    img.get("src"),
                    img.get("data-src"),
                    img.get("data-lazy-src"),
                    img.get("data-original"),
                ]

                for candidate in candidates:
                    candidate = absolute_url(article_url, candidate)
                    if candidate and candidate.startswith(("http://", "https://")):
                        return candidate

    except Exception as exc:
        print(f"[image] Неуспешно извличане на {article_url}: {exc}")

    return


def title_from_link(link):
    text = clean_text(link.get_text(" ", strip=True))
    if text:
        return text

    return clean_text(
        link.get("aria-label")
        or link.get("title")
        or link.get("data-title")
        or ""
    )


def extract_article_links(source):
    html = get_html(source["url"])
    soup = BeautifulSoup(html, "html.parser")

    domain = source["domain"]
    candidates = []
    seen_urls = set()

    # Търсим всички линкове към същия домейн.
    for link in soup.find_all("a", href=True):
        href = absolute_url(source["url"], link.get("href"))
        title = title_from_link(link)

        if not href or not title:
            continue

        if not valid_article_url(href, domain):
            continue

        # Премахваме fragment/query, за да няма дубликати.
        parsed = urlparse(href)
        normalized = parsed._replace(query="", fragment="").geturl()

        if normalized in seen_urls:
            continue

        # Игнорирай очевидни навигационни/служебни страници.
        path = parsed.path.lower()

        blocked_parts = (
            "/search",
            "/forum",
            "/livescore",
            "/streaming",
            "/video",
            "/tag/",
            "/tags/",
            "/login",
            "/register",
        )

        if any(part in path for part in blocked_parts):
            continue
# Darik: приемаме само реални статии,

# а не категории, избори, начални страници и др.

if source["domain"] == "dariknews.bg":

    if not re.search(r"-\d{6,}$", path):

        continue
        # Заглавието трябва да е разумна дължина.
        if len(title) < 15 or len(title) > 300:
            continue

        seen_urls.add(normalized)
        candidates.append((title, normalized))

        if len(candidates) >= source["max_articles"] * 3:
            break

    return candidates


def build_source_articles(source):
    articles = []

    try:
        candidates = extract_article_links(source)
        print(f"[{source['name']}] намерени линкове: {len(candidates)}")

        for title, url in candidates:
            image = extract_article_image(url)

            article = {
                "title": title,
                "url": url,
                "source": source["name"],
                "section": source["section"],
                "image": image,
            }

            articles.append(article)

            print(
                f"[{source['name']}] {title[:70]} | "
                f"image={'OK' if image else 'NO'}"
            )

            if len(articles) >= source["max_articles"]:
                break

    except Exception as exc:
        print(f"[{source['name']}] ГРЕШКА: {exc}")

    return articles


def deduplicate(articles):
    result = []
    seen = set()

    for article in articles:
        key = article.get("url", "").strip()

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(article)

    return result


def main():
    all_articles = []

    for source in SOURCES:
        all_articles.extend(build_source_articles(source))

    all_articles = deduplicate(all_articles)

    # Запазваме стабилен и лесен за index.html формат.
    payload = {
        "updated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
        "articles": all_articles,
    }

    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Готово: {OUTPUT} — {len(all_articles)} статии.")


if __name__ == "__main__":
    main()
