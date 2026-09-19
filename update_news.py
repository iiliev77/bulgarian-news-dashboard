#!/usr/bin/env python3

# -*- coding: utf-8 -*-

import json
import re
from datetime import datetime, timezone
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


def meta_content(soup, prop=None, name=None):
    tag = None
    if prop:
        tag = soup.find("meta", attrs={"property": prop})
    if not tag and name:
        tag = soup.find("meta", attrs={"name": name})
    if tag:
        return clean_text(tag.get("content", ""))
    return ""


def is_bad_image_url(url):
    """Reject branding/tracking images instead of article photos."""
    if not url:
        return True

    value = url.strip().lower()

    if not value.startswith(("http://", "https://")):
        return True

    bad_parts = (
        "dbrand.php",
        "/branding/",
        "/brand/",
        "logo",
        "favicon",
        "sprite",
        "placeholder",
        "default-image",
        "avatar",
        "tracking",
        "pixel",
        "spacer",
    )

    return any(part in value for part in bad_parts)


def normalize_image_candidate(article_url, value):
    if not value:
        return ""

    value = str(value).strip()

    # srcset: use the last/largest candidate.
    if "," in value:
        parts = [part.strip() for part in value.split(",") if part.strip()]
        if parts:
            value = parts[-1].split()[0]

    # URL followed by a srcset descriptor.
    if " " in value:
        value = value.split()[0]

    value = absolute_url(article_url, value)

    if is_bad_image_url(value):
        return ""

    return value


def extract_jsonld_images(data):
    """Extract image fields recursively from JSON-LD."""
    found = []

    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() == "image":
                if isinstance(value, str):
                    found.append(value)
                elif isinstance(value, dict):
                    found.extend(extract_jsonld_images(value))
                elif isinstance(value, list):
                    for item in value:
                        if isinstance(item, str):
                            found.append(item)
                        elif isinstance(item, (dict, list)):
                            found.extend(extract_jsonld_images(item))
            elif isinstance(value, (dict, list)):
                found.extend(extract_jsonld_images(value))

    elif isinstance(data, list):
        for item in data:
            if isinstance(item, (dict, list)):
                found.extend(extract_jsonld_images(item))

    return found


def extract_article_image(article_url):
    try:
        html = get_html(article_url)
        soup = BeautifulSoup(html, "html.parser")

        # 1. Open Graph / Twitter.
        # Bad branding URLs are rejected and the next source is tried.
        meta_candidates = [
            meta_content(soup, prop="og:image"),
            meta_content(soup, prop="og:image:url"),
            meta_content(soup, prop="og:image:secure_url"),
            meta_content(soup, name="twitter:image"),
            meta_content(soup, name="twitter:image:src"),
        ]

        for candidate in meta_candidates:
            image = normalize_image_candidate(article_url, candidate)
            if image:
                return image

        # 2. JSON-LD Article / NewsArticle / ImageObject.
        for script in soup.find_all(
            "script",
            attrs={"type": "application/ld+json"}
        ):
            try:
                data = json.loads(
                    script.string or script.get_text()
                )
            except Exception:
                continue

            for candidate in extract_jsonld_images(data):
                image = normalize_image_candidate(
                    article_url,
                    candidate
                )
                if image:
                    return image

        # 3. rel=image_src.
        for link in soup.find_all(
            "link",
            attrs={"rel": lambda value: value and "image_src" in value}
        ):
            image = normalize_image_candidate(
                article_url,
                link.get("href", "")
            )
            if image:
                return image

        # 4. Images inside the article/main content.
        containers = [
            soup.find("article"),
            soup.find("main"),
            soup.find(
                "div",
                attrs={"itemprop": "articleBody"}
            ),
        ]

        image_candidates = []

        for container in containers:
            if not container:
                continue

            for img in container.find_all("img"):
                raw_candidates = [
                    img.get("src"),
                    img.get("data-src"),
                    img.get("data-lazy-src"),
                    img.get("data-original"),
                    img.get("data-image"),
                    img.get("srcset"),
                    img.get("data-srcset"),
                ]

                for raw in raw_candidates:
                    image = normalize_image_candidate(
                        article_url,
                        raw
                    )
                    if not image:
                        continue

                    score = 0
                    attrs = " ".join(
                        str(img.get(attr, "")).lower()
                        for attr in ("class", "alt", "title", "id")
                    )

                    if any(
                        word in attrs
                        for word in (
                            "article",
                            "content",
                            "hero",
                            "main-image",
                            "lead",
                            "gallery",
                        )
                    ):
                        score += 10

                    if any(
                        word in attrs
                        for word in (
                            "logo",
                            "avatar",
                            "icon",
                            "banner",
                        )
                    ):
                        score -= 20

                    image_candidates.append((score, image))

        if image_candidates:
            image_candidates.sort(
                key=lambda item: item[0],
                reverse=True
            )
            return image_candidates[0][1]

    except Exception as exc:
        print(
            f"[image] ÐÐµÑÑÐ¿ÐµÑÐ½Ð¾ Ð¸Ð·Ð²Ð»Ð¸ÑÐ°Ð½Ðµ Ð½Ð° "
            f"{article_url}: {exc}"
        )

    return ""


def title_from_link(link):
    text = clean_text(
        link.get_text(" ", strip=True)
    )

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
    soup = BeautifulSoup(
        html,
        "html.parser"
    )

    domain = source["domain"]
    candidates = []
    seen_urls = set()

    for link in soup.find_all(
        "a",
        href=True
    ):
        href = absolute_url(
            source["url"],
            link.get("href")
        )
        title = title_from_link(link)

        if not href or not title:
            continue

        if not valid_article_url(
            href,
            domain
        ):
            continue

        parsed = urlparse(href)
        normalized = parsed._replace(
            query="",
            fragment=""
        ).geturl()

        if normalized in seen_urls:
            continue

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

        if any(
            part in path
            for part in blocked_parts
        ):
            continue

        if domain == "dariknews.bg":
            if not re.search(
                r"-\d{6,}$",
                path
            ):
                continue

        if len(title) < 15 or len(title) > 300:
            continue

        seen_urls.add(normalized)
        candidates.append(
            (
                title,
                normalized
            )
        )

        if len(candidates) >= (
            source["max_articles"] * 3
        ):
            break

    return candidates


def build_source_articles(source):
    articles = []

    try:
        candidates = extract_article_links(
            source
        )

        print(
            f"[{source['name']}] "
            f"Ð½Ð°Ð¼ÐµÑÐµÐ½Ð¸ Ð»Ð¸Ð½ÐºÐ¾Ð²Ðµ: "
            f"{len(candidates)}"
        )

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
                f"[{source['name']}] "
                f"{title[:70]} | "
                f"image="
                f"{'OK' if image else 'NO'}"
            )

            if len(articles) >= source[
                "max_articles"
            ]:
                break

    except Exception as exc:
        print(
            f"[{source['name']}] "
            f"ÐÐ ÐÐ¨ÐÐ: {exc}"
        )

    return articles


def deduplicate(articles):
    result = []
    seen = set()

    for article in articles:
        key = article.get(
            "url",
            ""
        ).strip()

        if not key or key in seen:
            continue

        seen.add(key)
        result.append(article)

    return result


def main():
    all_articles = []

    for source in SOURCES:
        all_articles.extend(
            build_source_articles(
                source
            )
        )

    all_articles = deduplicate(
        all_articles
    )

    payload = {
        "updated": datetime.now(
            timezone.utc
        ).isoformat(),
        "articles": all_articles,
    }

    OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8",
    )

    print(
        f"ÐÐ¾ÑÐ¾Ð²Ð¾: {OUTPUT} â "
        f"{len(all_articles)} ÑÑÐ°ÑÐ¸Ð¸."
    )


if __name__ == "__main__":
    main()
