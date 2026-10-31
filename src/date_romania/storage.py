"""Raw store: every fetched response or file is kept untouched, addressed by its SHA-256."""

import hashlib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import boto3

from date_romania.config import get_settings


@dataclass(frozen=True)
class StoredObject:
    key: str
    sha256: str
    size_bytes: int


def object_key(source: str, sha256: str) -> str:
    """Spread keys over folders so no single prefix grows to millions of objects."""
    return f"{source}/{sha256[:2]}/{sha256}"


@lru_cache
def _client():
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=s.s3_endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
    )


def put_raw(source: str, content: bytes, content_type: str | None = None) -> StoredObject:
    sha256 = hashlib.sha256(content).hexdigest()
    key = object_key(source, sha256)
    extra = {"ContentType": content_type} if content_type else {}
    _client().put_object(Bucket=get_settings().s3_bucket, Key=key, Body=content, **extra)
    return StoredObject(key=key, sha256=sha256, size_bytes=len(content))


def get_raw(key: str) -> bytes:
    return _client().get_object(Bucket=get_settings().s3_bucket, Key=key)["Body"].read()


def put_raw_file(source: str, path: Path, content_type: str | None = None) -> StoredObject:
    """`put_raw` for a file too large to hold in memory: hashed and sent in parts."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1 << 20):
            digest.update(chunk)
    sha256 = digest.hexdigest()
    key = object_key(source, sha256)
    extra = {"ExtraArgs": {"ContentType": content_type}} if content_type else {}
    _client().upload_file(str(path), get_settings().s3_bucket, key, **extra)
    return StoredObject(key=key, sha256=sha256, size_bytes=path.stat().st_size)


def get_raw_file(key: str, path: Path) -> Path:
    """`get_raw` into a file, for one too large to hold in memory."""
    _client().download_file(get_settings().s3_bucket, key, str(path))
    return path


def storage_ok() -> bool:
    try:
        _client().head_bucket(Bucket=get_settings().s3_bucket)
        return True
    except Exception:
        return False
