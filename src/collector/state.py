from __future__ import annotations

import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable, Iterator

if TYPE_CHECKING:
    from .storage import GcsClient

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sitemaps (
    loc TEXT PRIMARY KEY,
    lastmod TEXT,
    last_processed_at TEXT,
    url_count INTEGER
);

CREATE TABLE IF NOT EXISTS pages (
    url TEXT PRIMARY KEY,
    language TEXT NOT NULL,
    sitemap_lastmod TEXT,
    first_seen_at TEXT NOT NULL,
    last_fetched_at TEXT,
    last_content_hash TEXT,
    last_html_gcs_path TEXT,
    last_revision_id TEXT,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    last_error_at TEXT
);

CREATE TABLE IF NOT EXISTS revisions (
    revision_id TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    language TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    sitemap_lastmod TEXT,
    content_hash TEXT NOT NULL,
    title TEXT,
    html_gcs_path TEXT,
    diff_text_gcs_path TEXT,
    diff_html_gcs_path TEXT,
    prev_revision_id TEXT,
    change_type TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS revisions_url_idx ON revisions(url);
CREATE INDEX IF NOT EXISTS revisions_detected_idx ON revisions(detected_at);

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    sitemaps_processed INTEGER NOT NULL DEFAULT 0,
    urls_seen INTEGER NOT NULL DEFAULT 0,
    new_urls INTEGER NOT NULL DEFAULT 0,
    updated_urls INTEGER NOT NULL DEFAULT 0,
    revisions_recorded INTEGER NOT NULL DEFAULT 0,
    errors INTEGER NOT NULL DEFAULT 0,
    notes TEXT
);
"""


@dataclass
class PageRow:
    url: str
    language: str
    sitemap_lastmod: str | None
    last_content_hash: str | None
    last_html_gcs_path: str | None
    last_revision_id: str | None


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat(timespec="seconds")


def new_id() -> str:
    return uuid.uuid4().hex


@contextmanager
def open_state(gcs: "GcsClient", state_object: str) -> Iterator["State"]:
    tmpdir = tempfile.mkdtemp(prefix="gcdocs-state-")
    local_path = os.path.join(tmpdir, "state.sqlite")
    existed = gcs.download_to_file(state_object, local_path)
    conn = sqlite3.connect(local_path)
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.executescript(_SCHEMA)
    conn.commit()
    state = State(conn=conn, local_path=local_path, existed=existed)
    try:
        yield state
        conn.commit()
    finally:
        try:
            # Checkpoint WAL into the main file before close so we upload one
            # self-contained file.
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
            except sqlite3.DatabaseError:
                pass
            conn.close()
        finally:
            try:
                gcs.upload_from_file(state_object, local_path, content_type="application/vnd.sqlite3")
            finally:
                for suffix in ("", "-wal", "-shm", "-journal"):
                    try:
                        os.remove(local_path + suffix)
                    except FileNotFoundError:
                        pass


class State:
    def __init__(self, conn: sqlite3.Connection, local_path: str, existed: bool) -> None:
        self._conn = conn
        self.local_path = local_path
        self.existed_remotely = existed

    # ---- sitemaps ---------------------------------------------------------

    def sitemap_changed(self, loc: str, lastmod: datetime | None) -> bool:
        row = self._conn.execute(
            "SELECT lastmod FROM sitemaps WHERE loc = ?",
            (loc,),
        ).fetchone()
        if row is None:
            return True
        if lastmod is None:
            return True
        stored = row[0]
        if stored is None:
            return True
        return (to_iso(lastmod) or "") > stored

    def record_sitemap_processed(self, loc: str, lastmod: datetime | None, url_count: int) -> None:
        self._conn.execute(
            """
            INSERT INTO sitemaps (loc, lastmod, last_processed_at, url_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(loc) DO UPDATE SET
                lastmod = excluded.lastmod,
                last_processed_at = excluded.last_processed_at,
                url_count = excluded.url_count;
            """,
            (loc, to_iso(lastmod), utcnow_iso(), url_count),
        )

    # ---- pages ------------------------------------------------------------

    def page(self, url: str) -> PageRow | None:
        row = self._conn.execute(
            """
            SELECT url, language, sitemap_lastmod, last_content_hash,
                   last_html_gcs_path, last_revision_id
            FROM pages WHERE url = ?
            """,
            (url,),
        ).fetchone()
        if row is None:
            return None
        return PageRow(
            url=row[0],
            language=row[1],
            sitemap_lastmod=row[2],
            last_content_hash=row[3],
            last_html_gcs_path=row[4],
            last_revision_id=row[5],
        )

    def upsert_page_seen(self, url: str, language: str, sitemap_lastmod: datetime | None) -> None:
        self._conn.execute(
            """
            INSERT INTO pages (url, language, sitemap_lastmod, first_seen_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                sitemap_lastmod = excluded.sitemap_lastmod,
                language = excluded.language;
            """,
            (url, language, to_iso(sitemap_lastmod), utcnow_iso()),
        )

    def update_page_after_fetch(
        self,
        url: str,
        content_hash: str,
        html_gcs_path: str,
        revision_id: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE pages
            SET last_fetched_at = ?,
                last_content_hash = ?,
                last_html_gcs_path = ?,
                last_revision_id = ?,
                error_count = 0,
                last_error = NULL,
                last_error_at = NULL
            WHERE url = ?
            """,
            (utcnow_iso(), content_hash, html_gcs_path, revision_id, url),
        )

    def record_page_error(self, url: str, message: str) -> None:
        self._conn.execute(
            """
            UPDATE pages
            SET error_count = error_count + 1,
                last_error = ?,
                last_error_at = ?
            WHERE url = ?
            """,
            (message[:500], utcnow_iso(), url),
        )

    # ---- revisions --------------------------------------------------------

    def add_revision(
        self,
        revision_id: str,
        url: str,
        language: str,
        sitemap_lastmod: datetime | None,
        content_hash: str,
        title: str,
        html_gcs_path: str,
        diff_text_gcs_path: str | None,
        diff_html_gcs_path: str | None,
        prev_revision_id: str | None,
        change_type: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO revisions (
                revision_id, url, language, detected_at, sitemap_lastmod, content_hash,
                title, html_gcs_path, diff_text_gcs_path, diff_html_gcs_path,
                prev_revision_id, change_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                revision_id, url, language, utcnow_iso(), to_iso(sitemap_lastmod),
                content_hash, title, html_gcs_path, diff_text_gcs_path, diff_html_gcs_path,
                prev_revision_id, change_type,
            ),
        )

    # ---- runs -------------------------------------------------------------

    def start_run(self) -> str:
        run_id = new_id()
        self._conn.execute(
            "INSERT INTO runs (run_id, started_at) VALUES (?, ?);",
            (run_id, utcnow_iso()),
        )
        return run_id

    def finish_run(self, run_id: str, **counters) -> None:
        sets = ["finished_at = ?"]
        params: list = [utcnow_iso()]
        for k, v in counters.items():
            sets.append(f"{k} = ?")
            params.append(v)
        params.append(run_id)
        self._conn.execute(
            f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?",
            params,
        )

    # ---- queries ----------------------------------------------------------

    def candidates_for_fetch(
        self,
        entries: Iterable[tuple[str, str, datetime | None]],
    ) -> tuple[list[tuple[str, str, datetime | None]], list[tuple[str, str, datetime | None]]]:
        """Split (url, language, sitemap_lastmod) entries into (new, updated)."""
        new: list[tuple[str, str, datetime | None]] = []
        updated: list[tuple[str, str, datetime | None]] = []
        for url, lang, lm in entries:
            row = self._conn.execute(
                "SELECT sitemap_lastmod FROM pages WHERE url = ?",
                (url,),
            ).fetchone()
            if row is None:
                new.append((url, lang, lm))
                continue
            stored = row[0]
            incoming = to_iso(lm)
            if incoming is None or stored is None or incoming > stored:
                updated.append((url, lang, lm))
        return new, updated
