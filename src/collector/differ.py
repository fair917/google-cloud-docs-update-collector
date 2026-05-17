from __future__ import annotations

import difflib
import html


def unified_diff_text(old: str, new: str, fromfile: str, tofile: str) -> str:
    diff = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=fromfile,
        tofile=tofile,
        n=3,
    )
    return "".join(diff)


_HTML_HEAD = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  body{{font:14px/1.5 ui-sans-serif,system-ui,sans-serif;margin:1rem;color:#111;background:#fafafa}}
  h1{{font-size:16px;margin:0 0 .25rem 0}}
  .meta{{color:#555;margin-bottom:1rem}}
  table.diff{{font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;border-collapse:collapse;width:100%;background:#fff}}
  .diff_header{{background:#eaeaea}}
  td.diff_header{{text-align:right;padding:0 .5em;color:#888}}
  .diff_next{{background:#f0f0f0}}
  .diff_add{{background:#e6ffed}}
  .diff_chg{{background:#fff5b1}}
  .diff_sub{{background:#ffeef0}}
</style>
</head><body>
<h1>{title}</h1>
<div class="meta">{meta}</div>
"""

_HTML_TAIL = "</body></html>"


def html_diff(old_text: str, new_text: str, title: str, meta: str) -> str:
    table = difflib.HtmlDiff(wrapcolumn=100).make_table(
        old_text.splitlines(),
        new_text.splitlines(),
        fromdesc="previous",
        todesc="current",
        context=True,
        numlines=3,
    )
    return _HTML_HEAD.format(title=html.escape(title), meta=html.escape(meta)) + table + _HTML_TAIL
