from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Config:
    sitemap_root: str
    bucket: str
    state_object: str
    snapshot_prefix: str
    diff_prefix: str
    languages: tuple[str, ...]
    watch_paths: tuple[str, ...]
    max_fetch_per_run: int
    fetch_concurrency: int
    request_timeout_seconds: int
    user_agent: str


# Known language codes used by cloud.google.com. Used to recognize that a URL
# without a watched-language prefix actually belongs to a different language
# (so we don't classify "/ja/foo" as English).
LANGUAGE_CODES: frozenset[str] = frozenset({
    "ja", "es", "es-419", "pt-br", "zh-cn", "zh-tw", "ko",
    "fr", "de", "it", "id", "ru", "th", "vi", "tr", "pl", "nl",
})


def load_config(path: str | Path | None = None) -> Config:
    path = Path(path or os.environ.get("CONFIG_PATH", "config/config.yaml"))
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # Env overrides: GCDOCS__<KEY>
    for key in list(raw.keys()):
        env_key = f"GCDOCS__{key.upper()}"
        if env_key in os.environ:
            raw[key] = os.environ[env_key]

    # Required at runtime.
    bucket = raw.get("bucket") or os.environ.get("GCDOCS__BUCKET", "")
    if not bucket:
        raise RuntimeError("config 'bucket' is required (set in config.yaml or env GCDOCS__BUCKET)")

    return Config(
        sitemap_root=raw["sitemap_root"],
        bucket=bucket,
        state_object=raw.get("state_object", "state/state.duckdb"),
        snapshot_prefix=raw.get("snapshot_prefix", "snapshots"),
        diff_prefix=raw.get("diff_prefix", "diffs"),
        languages=tuple(raw.get("languages", ["en"])),
        watch_paths=tuple(raw.get("watch_paths", [])),
        max_fetch_per_run=int(raw.get("max_fetch_per_run", 500)),
        fetch_concurrency=int(raw.get("fetch_concurrency", 4)),
        request_timeout_seconds=int(raw.get("request_timeout_seconds", 30)),
        user_agent=raw.get("user_agent", "gcdocs-update-collector/0.1"),
    )


def classify_url(url: str, languages: tuple[str, ...], watch_paths: tuple[str, ...]) -> str | None:
    """Return matched language ('en'/'ja'/...) or None if the URL is out of scope."""
    if not url.startswith("https://cloud.google.com/"):
        return None
    path = url[len("https://cloud.google.com"):]  # keep leading "/"
    first = path.lstrip("/").split("/", 1)[0]

    if first in LANGUAGE_CODES:
        lang = first
        rest = path[len(f"/{lang}"):]
    else:
        lang = "en"
        rest = path

    if lang not in languages:
        return None

    for wp in watch_paths:
        wp = wp.rstrip("/")
        if rest == wp or rest.startswith(wp + "/"):
            return lang
    return None
