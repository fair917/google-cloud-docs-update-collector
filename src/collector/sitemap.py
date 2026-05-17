from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from lxml import etree

NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


@dataclass(frozen=True)
class SitemapRef:
    loc: str
    lastmod: datetime | None


@dataclass(frozen=True)
class UrlEntry:
    url: str
    lastmod: datetime | None
    language: str


def _parse_lastmod(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        # Python 3.11+ handles trailing 'Z' and offsets.
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fetch_sitemap_index(client: httpx.Client, url: str) -> list[SitemapRef]:
    resp = client.get(url)
    resp.raise_for_status()
    root = etree.fromstring(resp.content)
    refs: list[SitemapRef] = []
    for sm in root.findall("sm:sitemap", NS):
        loc_el = sm.find("sm:loc", NS)
        lm_el = sm.find("sm:lastmod", NS)
        if loc_el is None or not loc_el.text:
            continue
        refs.append(SitemapRef(loc=loc_el.text.strip(), lastmod=_parse_lastmod(lm_el.text if lm_el is not None else None)))
    return refs


def fetch_sitemap_urls(
    client: httpx.Client,
    loc: str,
    classify,  # callable(url) -> language or None
) -> list[UrlEntry]:
    resp = client.get(loc)
    resp.raise_for_status()
    root = etree.fromstring(resp.content)
    entries: list[UrlEntry] = []
    for u in root.findall("sm:url", NS):
        loc_el = u.find("sm:loc", NS)
        lm_el = u.find("sm:lastmod", NS)
        if loc_el is None or not loc_el.text:
            continue
        url = loc_el.text.strip()
        lang = classify(url)
        if lang is None:
            continue
        entries.append(
            UrlEntry(
                url=url,
                lastmod=_parse_lastmod(lm_el.text if lm_el is not None else None),
                language=lang,
            )
        )
    return entries
