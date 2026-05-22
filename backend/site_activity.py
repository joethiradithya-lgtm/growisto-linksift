"""
site_activity.py
----------------
Detects whether a website is actively publishing content.

Strategy (in priority order):
  1. sitemap.xml  — look for <lastmod> dates on URLs that look like blog/news
  2. RSS / Atom feed — parse latest pubDate from common feed paths
  3. Fallback scrape — fetch /blog or /news listing page and look for dates

A site is "active" if it published at least one post in the last N months
(default 6). Returns rich metadata for transparency.
"""

from __future__ import annotations

import re
import asyncio
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
import feedparser
from bs4 import BeautifulSoup
from dateutil import parser as dateparser


# ── Config ─────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT = 12.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; LinkSiftBot/1.0; +https://linksift.local) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

BLOG_PATH_HINTS = [
    "/blog", "/news", "/articles", "/posts", "/resources",
    "/insights", "/journal", "/stories", "/press",
]

SITEMAP_CANDIDATES = [
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/sitemap/sitemap.xml",
    "/wp-sitemap.xml",
    "/blog/sitemap.xml",
    "/news-sitemap.xml",
    "/post-sitemap.xml",
]

RSS_CANDIDATES = [
    "/feed", "/rss", "/atom.xml", "/feed.xml", "/rss.xml",
    "/blog/feed", "/blog/rss", "/news/feed", "/feed/",
    "/index.xml", "/blog/index.xml",
]


@dataclass
class ActivityResult:
    domain: str
    is_active: bool
    last_post_date: Optional[str] = None        # ISO string
    days_since_last_post: Optional[int] = None
    method: str = "none"                         # sitemap | rss | scrape | none
    posts_in_window: int = 0                     # count of posts inside window
    window_months: int = 6
    notes: str = ""
    checked_urls: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ── HTTP helpers ───────────────────────────────────────────────────────
async def _fetch(client: httpx.AsyncClient, url: str) -> Optional[httpx.Response]:
    try:
        r = await client.get(url, follow_redirects=True, timeout=DEFAULT_TIMEOUT)
        if r.status_code == 200 and r.content:
            return r
    except (httpx.HTTPError, httpx.TimeoutException):
        return None
    return None


def _normalize_domain(domain: str) -> str:
    d = domain.strip().lower()
    d = re.sub(r"^https?://", "", d)
    d = d.split("/")[0]
    return d


def _base_url(domain: str) -> str:
    return f"https://{_normalize_domain(domain)}"


def _parse_date(raw: str) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = dateparser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError, OverflowError):
        return None


# ── robots.txt sitemap discovery ───────────────────────────────────────
async def _discover_sitemaps_from_robots(
    client: httpx.AsyncClient, base: str
) -> list[str]:
    """Parse robots.txt and return declared Sitemap: URLs, freshest first."""
    r = await _fetch(client, f"{base}/robots.txt")
    if not r:
        return []
    sitemaps = []
    for line in r.text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            url = line.split(":", 1)[1].strip()
            if url:
                sitemaps.append(url)
    # Sort: 48hours/daily/recent sitemaps first (most likely to have fresh dates)
    freshness_priority = ["48hour", "daily", "recent", "news", "post", "article", "blog"]
    def _rank(url: str) -> int:
        u = url.lower()
        for i, kw in enumerate(freshness_priority):
            if kw in u:
                return i
        return len(freshness_priority)
    return sorted(sitemaps, key=_rank)


# ── 1) Sitemap check ───────────────────────────────────────────────────
async def _check_sitemap(
    client: httpx.AsyncClient, base: str, window_start: datetime, checked: list[str]
) -> Optional[tuple[datetime, int]]:
    """
    Returns (latest_post_date, count_in_window) or None.
    Tries robots.txt-declared sitemaps first, then falls back to common paths.
    """
    latest: Optional[datetime] = None
    in_window = 0

    async def parse_sitemap(url: str, depth: int = 0) -> None:
        nonlocal latest, in_window
        if depth > 1 or in_window >= 3:
            return
        checked.append(url)
        r = await _fetch(client, url)
        if not r:
            return

        try:
            soup = BeautifulSoup(r.text, "lxml-xml")
        except Exception:
            soup = BeautifulSoup(r.text, "xml")

        # Detect Google News sitemaps — they only contain article URLs so
        # skip the blog-path filter; accept any URL with a date.
        is_news_sitemap = (
            "news" in url.lower()
            or "48hour" in url.lower()
            or bool(soup.find("news:news"))
        )

        # Nested sitemap index — recurse into content-flavoured child sitemaps
        for sm in soup.find_all("sitemap"):
            loc = sm.find("loc")
            if not loc or not loc.text:
                continue
            child_url = loc.text.strip()
            if any(h in child_url.lower() for h in ["blog", "post", "news", "article", "48hour", "daily"]):
                await parse_sitemap(child_url, depth + 1)

        # Page-level URLs — stop once we've confirmed 3 recent posts
        for url_el in soup.find_all("url"):
            if in_window >= 3:
                break
            loc = url_el.find("loc")
            if not loc or not loc.text:
                continue
            page_url = loc.text.strip().lower()

            # For regular sitemaps filter by known content paths;
            # for news sitemaps every entry is an article so skip the filter.
            if not is_news_sitemap and not any(h in page_url for h in BLOG_PATH_HINTS):
                continue

            # Try <lastmod>, then <news:publication_date> as fallback
            lastmod = url_el.find("lastmod")
            if not lastmod or not lastmod.text:
                lastmod = url_el.find("publication_date")
            if not lastmod or not lastmod.text:
                continue

            dt = _parse_date(lastmod.text)
            if not dt:
                continue
            if latest is None or dt > latest:
                latest = dt
            if dt >= window_start:
                in_window += 1

    # 1a. Try sitemaps declared in robots.txt (correct path for many large sites)
    robots_sitemaps = await _discover_sitemaps_from_robots(client, base)
    for url in robots_sitemaps:
        await parse_sitemap(url)
        if latest is not None:
            break

    # 1b. Fall back to well-known paths if robots.txt had nothing useful
    if latest is None:
        for path in SITEMAP_CANDIDATES:
            await parse_sitemap(urljoin(base, path))
            if latest is not None:
                break

    if latest is None:
        return None
    return latest, in_window


# ── 2) RSS/Atom feed check ─────────────────────────────────────────────
async def _check_rss(
    client: httpx.AsyncClient, base: str, window_start: datetime, checked: list[str]
) -> Optional[tuple[datetime, int]]:
    for path in RSS_CANDIDATES:
        url = urljoin(base, path)
        checked.append(url)
        r = await _fetch(client, url)
        if not r:
            continue
        # feedparser is sync — run in thread to avoid blocking
        feed = await asyncio.to_thread(feedparser.parse, r.content)
        if not feed.entries:
            continue
        latest: Optional[datetime] = None
        in_window = 0
        for entry in feed.entries[:3]:
            raw = entry.get("published") or entry.get("updated") or ""
            dt = _parse_date(raw)
            if not dt:
                continue
            if latest is None or dt > latest:
                latest = dt
            if dt >= window_start:
                in_window += 1
        if latest:
            return latest, in_window
    return None


# ── 3) Fallback scrape ─────────────────────────────────────────────────
DATE_REGEXES = [
    re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"),
    re.compile(
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+(20\d{2})\b",
        re.I,
    ),
    re.compile(r"\b\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+(20\d{2})\b", re.I),
]


def _extract_dates_from_html(html: str) -> list[datetime]:
    dates: list[datetime] = []
    soup = BeautifulSoup(html, "html.parser")

    # Look at structured date elements first
    for tag in soup.find_all(["time", "meta", "span", "div", "p"], limit=300):
        # <time datetime="...">
        if tag.name == "time" and tag.get("datetime"):
            dt = _parse_date(tag["datetime"])
            if dt:
                dates.append(dt)
                continue
        # <meta property="article:published_time" content="...">
        if tag.name == "meta":
            prop = (tag.get("property") or tag.get("name") or "").lower()
            if "published" in prop or "date" in prop or "modified" in prop:
                content = tag.get("content")
                if content:
                    dt = _parse_date(content)
                    if dt:
                        dates.append(dt)
            continue
        # Class hints
        cls = " ".join(tag.get("class", [])).lower()
        if any(k in cls for k in ["date", "time", "published", "posted", "meta"]):
            text = tag.get_text(" ", strip=True)[:120]
            for rx in DATE_REGEXES:
                m = rx.search(text)
                if m:
                    dt = _parse_date(m.group(0))
                    if dt:
                        dates.append(dt)
                    break

    # If still nothing, regex-sweep the body text (limited)
    if not dates:
        text = soup.get_text(" ", strip=True)[:30000]
        for rx in DATE_REGEXES:
            for m in rx.finditer(text):
                dt = _parse_date(m.group(0))
                if dt:
                    dates.append(dt)

    # Sanity filter — drop wildly future dates and pre-2000
    now = datetime.now(timezone.utc) + timedelta(days=2)
    dates = [d for d in dates if d <= now and d.year >= 2000]
    return dates


async def _check_scrape(
    client: httpx.AsyncClient, base: str, window_start: datetime, checked: list[str]
) -> Optional[tuple[datetime, int]]:
    for path in BLOG_PATH_HINTS:
        url = urljoin(base, path)
        checked.append(url)
        r = await _fetch(client, url)
        if not r:
            continue
        # Only treat HTML responses
        ctype = r.headers.get("content-type", "").lower()
        if "html" not in ctype:
            continue
        dates = _extract_dates_from_html(r.text)
        if not dates:
            continue
        latest = max(dates)
        in_window = sum(1 for d in dates if d >= window_start)
        return latest, in_window
    return None


# ── Orchestrator ───────────────────────────────────────────────────────
async def check_site_activity(
    domain: str,
    window_months: int = 6,
    client: Optional[httpx.AsyncClient] = None,
) -> ActivityResult:
    """
    Check if `domain` is publishing content. Tries sitemap → RSS → scrape.
    """
    domain = _normalize_domain(domain)
    base = _base_url(domain)
    window_start = datetime.now(timezone.utc) - timedelta(days=window_months * 30)
    checked: list[str] = []

    own_client = client is None
    if own_client:
        client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=DEFAULT_TIMEOUT,
            limits=httpx.Limits(max_connections=5),
        )

    try:
        for method, fn in [
            ("sitemap", _check_sitemap),
            ("rss", _check_rss),
            ("scrape", _check_scrape),
        ]:
            result = await fn(client, base, window_start, checked)
            if result is None:
                continue
            latest, in_window = result
            days_since = (datetime.now(timezone.utc) - latest).days
            is_active = latest >= window_start
            return ActivityResult(
                domain=domain,
                is_active=is_active,
                last_post_date=latest.date().isoformat(),
                days_since_last_post=days_since,
                method=method,
                posts_in_window=in_window,
                window_months=window_months,
                notes=(
                    f"Last post {latest.date().isoformat()} "
                    f"({'active' if latest >= window_start else 'inactive — last post outside window'}, "
                    f"via {method})."
                ),
                checked_urls=checked[:8],
            )

        return ActivityResult(
            domain=domain,
            is_active=False,
            method="none",
            window_months=window_months,
            notes="No sitemap, RSS feed, or datable blog page found. "
                  "Site appears inactive or has no content section.",
            checked_urls=checked[:8],
        )
    finally:
        if own_client:
            await client.aclose()
