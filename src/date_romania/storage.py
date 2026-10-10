"""Raw store: every fetched response or file is kept untouched, addressed by its SHA-256."""

import hashlib
from dataclasses import dataclass
from functools import lru_cache

import boto3
from botocore.exceptions import ClientError

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


def storage_ok() -> bool:
    try:
        _client().head_bucket(Bucket=get_settings().s3_bucket)
        return True
    except (ClientError, Exception):
        return False
