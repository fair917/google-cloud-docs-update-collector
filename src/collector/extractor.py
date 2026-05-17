from __future__ import annotations

import re
from dataclasses import dataclass

from bs4 import BeautifulSoup

# Selectors to drop before computing diff. Order matters less than coverage.
_DROP_SELECTORS = [
    "header",
    "footer",
    "nav",
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "form",
    "devsite-header",
    "devsite-footer",
    "devsite-book-nav",
    "devsite-cookie-notification-bar",
    "devsite-feedback",
    "devsite-toc",
    "devsite-thumb-rating",
    "devsite-mathjax",
    ".devsite-header",
    ".devsite-footer",
    ".devsite-book-nav",
    ".devsite-banner",
    ".devsite-feedback",
    ".devsite-page-nav-jump-links",
    ".devsite-article-meta",
    ".devsite-page-rating",
    ".devsite-content-footer",
    ".devsite-content-data",
    ".devsite-floating-action-buttons",
]

# Preferred main-content selectors (first match wins).
_MAIN_SELECTORS = [
    "article.devsite-article",
    "article",
    "main devsite-content",
    "main",
    "div.devsite-article-body",
    "#gc-wrapper",
]

_TITLE_SELECTORS = [
    "h1.devsite-page-title",
    "h1",
    "title",
]

_WS_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Extracted:
    title: str
    text: str
    html: str  # cleaned HTML of the main region


def extract_main(raw_html: str) -> Extracted:
    soup = BeautifulSoup(raw_html, "lxml")

    for sel in _DROP_SELECTORS:
        for el in soup.select(sel):
            el.decompose()

    # Drop common attributes that change per build (tracking ids, hashes) so
    # they don't show up as diff noise.
    for el in soup.find_all(True):
        for attr in ("data-track-metadata-eventdetail", "data-track-metadata-position",
                     "data-tracking-id", "nonce", "integrity"):
            if attr in el.attrs:
                del el.attrs[attr]

    title = ""
    for sel in _TITLE_SELECTORS:
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            title = el.get_text(strip=True)
            break

    main = None
    for sel in _MAIN_SELECTORS:
        el = soup.select_one(sel)
        if el is not None:
            main = el
            break
    if main is None:
        main = soup.body or soup

    text = main.get_text("\n", strip=True)
    text = _WS_RE.sub(" ", text)
    text = _BLANK_RE.sub("\n\n", text).strip() + "\n"

    return Extracted(title=title, text=text, html=str(main))
