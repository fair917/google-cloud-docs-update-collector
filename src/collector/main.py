from __future__ import annotations

import hashlib
import logging
import os
import sys
from datetime import datetime
from functools import partial

from .config import classify_url, load_config
from .differ import html_diff, unified_diff_text
from .extractor import extract_main
from .fetcher import FetchError, fetch_html, make_client
from .sitemap import UrlEntry, fetch_sitemap_index, fetch_sitemap_urls
from .state import State, open_state
from .storage import GcsClient, diff_key, snapshot_key

log = logging.getLogger("gcdocs")


def _configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        stream=sys.stdout,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _format_lm(dt: datetime | None) -> str:
    return dt.isoformat() if dt else "(unknown)"


def run() -> int:
    _configure_logging()
    config = load_config()
    gcs = GcsClient(config.bucket)

    classify = partial(classify_url, languages=config.languages, watch_paths=config.watch_paths)

    new_count = 0
    updated_count = 0
    revisions_recorded = 0
    errors = 0
    urls_seen = 0
    sitemaps_processed = 0

    with open_state(gcs, config.state_object) as state:
        run_id = state.start_run()
        log.info("run started run_id=%s state_existed=%s", run_id, state.existed_remotely)

        with make_client(config.user_agent, config.request_timeout_seconds) as client:
            log.info("fetching sitemap index: %s", config.sitemap_root)
            child_sitemaps = fetch_sitemap_index(client, config.sitemap_root)
            log.info("found %d child sitemaps", len(child_sitemaps))

            all_entries: list[UrlEntry] = []
            for ref in child_sitemaps:
                if not state.sitemap_changed(ref.loc, ref.lastmod):
                    continue
                try:
                    entries = fetch_sitemap_urls(client, ref.loc, classify)
                except Exception as e:
                    log.warning("failed to fetch child sitemap %s: %s", ref.loc, e)
                    errors += 1
                    continue
                state.record_sitemap_processed(ref.loc, ref.lastmod, len(entries))
                sitemaps_processed += 1
                all_entries.extend(entries)
                log.info("sitemap %s yielded %d matching urls", ref.loc, len(entries))

            urls_seen = len(all_entries)
            log.info("total matching urls this run: %d", urls_seen)

            # Mark seen, then classify into fetch candidates.
            tuples: list[tuple[str, str, datetime | None]] = []
            for e in all_entries:
                tuples.append((e.url, e.language, e.lastmod))

            new_items, updated_items = state.candidates_for_fetch(tuples)
            new_count = len(new_items)
            updated_count = len(updated_items)
            log.info("classified: %d new, %d updated", new_count, updated_count)

            # Process updated first so newest revisions land if budget runs out.
            queue = updated_items + new_items
            queue = queue[: config.max_fetch_per_run]
            log.info("fetching %d urls (capped at %d)", len(queue), config.max_fetch_per_run)

            for url, language, sitemap_lastmod in queue:
                try:
                    rev_id = _process_url(
                        state, gcs, client, config,
                        url=url, language=language, sitemap_lastmod=sitemap_lastmod,
                    )
                    if rev_id is not None:
                        revisions_recorded += 1
                except FetchError as e:
                    log.warning("fetch failed url=%s err=%s", url, e)
                    state.upsert_page_seen(url, language, sitemap_lastmod)
                    state.record_page_error(url, str(e))
                    errors += 1
                except Exception as e:
                    log.exception("unexpected error url=%s", url)
                    state.upsert_page_seen(url, language, sitemap_lastmod)
                    state.record_page_error(url, repr(e))
                    errors += 1

        state.finish_run(
            run_id,
            sitemaps_processed=sitemaps_processed,
            urls_seen=urls_seen,
            new_urls=new_count,
            updated_urls=updated_count,
            revisions_recorded=revisions_recorded,
            errors=errors,
        )
        log.info(
            "run finished run_id=%s sitemaps=%d urls_seen=%d new=%d updated=%d revisions=%d errors=%d",
            run_id, sitemaps_processed, urls_seen, new_count, updated_count, revisions_recorded, errors,
        )

    return 0


def _process_url(
    state: State,
    gcs: GcsClient,
    client,
    config,
    *,
    url: str,
    language: str,
    sitemap_lastmod,
) -> str | None:
    prev = state.page(url)
    raw = fetch_html(client, url)
    extracted = extract_main(raw)
    content_hash = _sha256_text(extracted.text)

    state.upsert_page_seen(url, language, sitemap_lastmod)

    if prev and prev.last_content_hash == content_hash:
        # lastmod bumped but rendered content unchanged: refresh metadata only.
        state.update_page_after_fetch(
            url, content_hash,
            prev.last_html_gcs_path or "",
            prev.last_revision_id or "",
        )
        return None

    revision_id = _new_revision_id()
    html_key = snapshot_key(config.snapshot_prefix, language, url, revision_id)
    html_gs = gcs.upload_bytes(html_key, extracted.html, content_type="text/html; charset=utf-8")

    diff_text_gs: str | None = None
    diff_html_gs: str | None = None
    change_type = "new"

    if prev and prev.last_html_gcs_path:
        change_type = "updated"
        prev_html_bytes = gcs.download_bytes(gcs.key_from_gs(prev.last_html_gcs_path))
        prev_text = ""
        if prev_html_bytes is not None:
            prev_text = extract_main(prev_html_bytes.decode("utf-8", errors="replace")).text

        meta = (
            f"url={url} language={language} "
            f"sitemap_lastmod={_format_lm(sitemap_lastmod)} "
            f"prev_revision={prev.last_revision_id}"
        )

        unified = unified_diff_text(
            prev_text, extracted.text,
            fromfile=f"{url}@{prev.last_revision_id}",
            tofile=f"{url}@{revision_id}",
        )
        diff_text_key = diff_key(config.diff_prefix, language, url, revision_id, "text")
        diff_text_gs = gcs.upload_bytes(diff_text_key, unified, content_type="text/plain; charset=utf-8")

        html_diff_body = html_diff(prev_text, extracted.text, title=extracted.title or url, meta=meta)
        diff_html_key = diff_key(config.diff_prefix, language, url, revision_id, "html")
        diff_html_gs = gcs.upload_bytes(diff_html_key, html_diff_body, content_type="text/html; charset=utf-8")

    state.add_revision(
        revision_id=revision_id,
        url=url,
        language=language,
        sitemap_lastmod=sitemap_lastmod,
        content_hash=content_hash,
        title=extracted.title,
        html_gcs_path=html_gs,
        diff_text_gcs_path=diff_text_gs,
        diff_html_gcs_path=diff_html_gs,
        prev_revision_id=prev.last_revision_id if prev else None,
        change_type=change_type,
    )
    state.update_page_after_fetch(url, content_hash, html_gs, revision_id)
    return revision_id


def _new_revision_id() -> str:
    import uuid
    return uuid.uuid4().hex


if __name__ == "__main__":
    sys.exit(run())
