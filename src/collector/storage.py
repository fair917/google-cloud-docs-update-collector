from __future__ import annotations

import hashlib
from typing import Iterable

from google.cloud import storage


class GcsClient:
    def __init__(self, bucket: str) -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)
        self.bucket_name = bucket

    def download_to_file(self, key: str, dest: str) -> bool:
        blob = self._bucket.blob(key)
        if not blob.exists():
            return False
        blob.download_to_filename(dest)
        return True

    def upload_from_file(self, key: str, src: str, content_type: str | None = None) -> None:
        blob = self._bucket.blob(key)
        blob.upload_from_filename(src, content_type=content_type)

    def upload_bytes(self, key: str, data: bytes | str, content_type: str) -> str:
        blob = self._bucket.blob(key)
        if isinstance(data, str):
            blob.upload_from_string(data, content_type=content_type)
        else:
            blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self.bucket_name}/{key}"

    def download_bytes(self, key: str) -> bytes | None:
        blob = self._bucket.blob(key)
        if not blob.exists():
            return None
        return blob.download_as_bytes()

    def key_from_gs(self, gs_url: str) -> str:
        prefix = f"gs://{self.bucket_name}/"
        if not gs_url.startswith(prefix):
            raise ValueError(f"object {gs_url} does not belong to bucket {self.bucket_name}")
        return gs_url[len(prefix):]


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def shard(hash_hex: str) -> str:
    return hash_hex[:2]


def snapshot_key(prefix: str, language: str, url: str, revision_id: str) -> str:
    h = url_hash(url)
    return f"{prefix}/{language}/{shard(h)}/{h}/{revision_id}.html"


def diff_key(prefix: str, language: str, url: str, revision_id: str, kind: str) -> str:
    h = url_hash(url)
    ext = "diff.html" if kind == "html" else "diff.txt"
    return f"{prefix}/{language}/{shard(h)}/{h}/{revision_id}.{ext}"


def iter_chunks(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
