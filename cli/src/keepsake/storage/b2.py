"""Backblaze B2 via its S3-compatible API.

Every B2-specific workaround lives in this file. Two matter:

1. Flexible checksums. Since boto3 ~1.36 the AWS SDKs send
   `x-amz-sdk-checksum-algorithm` / `x-amz-checksum-crc32` by default, and B2
   rejects them with "Unsupported header ... received for this API call".
   We force both checksum knobs to "when_required".

   Caveat: s3transfer does not reliably honour `when_required` on the managed
   upload path (boto/s3transfer#327). Verify against a real bucket before
   building on `upload_file`. Small `put_object` writes are unaffected.

2. Region. B2 endpoints look like `s3.us-east-001.backblazeb2.com`, and SigV4
   needs `us-east-001` as the region. We derive it from the hostname rather
   than making the user restate it.
"""

from __future__ import annotations

from typing import Any, BinaryIO, Callable, Iterator
from urllib.parse import urlparse

from keepsake.storage.base import GuardedBucket, Obj, ProgressReader


def region_from_endpoint(endpoint: str) -> str | None:
    """`https://s3.us-east-001.backblazeb2.com` -> `us-east-001`."""
    host = urlparse(endpoint).hostname or ""
    parts = host.split(".")
    if len(parts) >= 3 and parts[0] == "s3":
        return parts[1]
    return None


def make_client(endpoint: str, region: str, key_id: str, app_key: str) -> Any:
    import boto3
    from botocore.config import Config

    common: dict[str, Any] = {
        "retries": {"max_attempts": 5, "mode": "standard"},
        "s3": {"addressing_style": "virtual"},
    }
    try:
        config = Config(
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            **common,
        )
    except TypeError:
        # botocore predates the flexible-checksum knobs, which also means it
        # predates the behaviour that made them necessary.
        config = Config(**common)

    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=key_id,
        aws_secret_access_key=app_key,
        config=config,
    )


class B2Bucket(GuardedBucket):
    def __init__(
        self,
        bucket: str,
        endpoint: str,
        key_id: str,
        app_key: str,
        *,
        region: str | None = None,
        readonly: bool = True,
    ):
        self.name = bucket
        self.endpoint = endpoint
        self.region = region or region_from_endpoint(endpoint) or "us-east-005"
        self.readonly = readonly
        self._client = make_client(endpoint, self.region, key_id, app_key)

    def verify(self) -> None:
        """Confirm the credentials can reach the bucket.

        Never ListBuckets: a B2 application key restricted to a single bucket
        cannot enumerate buckets, and per-bucket restricted keys are the
        recommended setup. HeadBucket is tried first; if the key is scoped
        tightly enough that even that is denied, a one-key listing proves
        reachability just as well.
        """
        from botocore.exceptions import ClientError

        try:
            self._client.head_bucket(Bucket=self.name)
        except ClientError:
            self._client.list_objects_v2(Bucket=self.name, MaxKeys=1)

    def list(self, prefix: str = "") -> Iterator[Obj]:
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.name, Prefix=prefix):
            for item in page.get("Contents", []):
                yield Obj(
                    key=item["Key"],
                    size=item["Size"],
                    last_modified=item.get("LastModified"),
                    etag=(item.get("ETag") or "").strip('"') or None,
                )

    def get(self, key: str) -> bytes:
        from botocore.exceptions import ClientError

        try:
            return self._client.get_object(Bucket=self.name, Key=key)["Body"].read()
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404"):
                raise KeyError(key) from exc
            raise

    def get_range(self, key: str, start: int, end: int) -> bytes:
        """One HTTP Range request. `end` is inclusive.

        B2 serves ranges (`206`, `Accept-Ranges: bytes`), which is what makes
        reading a movie header out of a multi-gigabyte object cheap.
        """
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_object(
                Bucket=self.name, Key=key, Range=f"bytes={start}-{end}"
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchKey", "404"):
                raise KeyError(key) from exc
            if code in ("InvalidRange", "416", "RequestedRangeNotSatisfiable"):
                return b""
            raise
        return resp["Body"].read()

    def head(self, key: str) -> Obj | None:
        from botocore.exceptions import ClientError

        try:
            resp = self._client.head_object(Bucket=self.name, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("NoSuchKey", "404", "NotFound"):
                return None
            raise
        return Obj(
            key=key,
            size=resp["ContentLength"],
            last_modified=resp.get("LastModified"),
            etag=(resp.get("ETag") or "").strip('"') or None,
        )

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
        *,
        allow_media: bool = False,
    ) -> None:
        self._guard(key, allow_media)
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(Bucket=self.name, Key=key, Body=data, **extra)

    def put_media(
        self,
        key: str,
        source: BinaryIO,
        content_type: str | None = None,
        *,
        size: int,
        progress: Callable[[int], None] | None = None,
    ) -> None:
        """Stream a new media file up in a single request.

        Deliberately `put_object` rather than `upload_fileobj`: the managed
        path runs through s3transfer, which is exactly where `when_required`
        checksums are not honoured (see this module's header). One request also
        means one failure mode -- it either lands or it does not.

        `ContentLength` is passed explicitly because a wrapped file object has
        no length botocore can discover.
        """
        self._guard_media_create(key, size)
        extra = {"ContentType": content_type} if content_type else {}
        self._client.put_object(
            Bucket=self.name,
            Key=key,
            Body=ProgressReader(source, progress),
            ContentLength=size,
            **extra,
        )

    def delete(self, key: str, *, allow_media: bool = False) -> None:
        self._guard(key, allow_media)
        self._client.delete_object(Bucket=self.name, Key=key)

    def presigned_url(self, key: str, expires_in: int = 3600) -> str:
        """A time-limited URL a media player can stream directly.

        Videos are far too large to pull through the terminal, and identifying
        `IMG_0002.MOV` requires watching it. Handing this URL to the system
        player streams it without downloading anything.
        """
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.name, "Key": key},
            ExpiresIn=expires_in,
        )

    def lifecycle_keeps_all_versions(self) -> bool | None:
        """True if this bucket retains every file version.

        B2 keeps all versions unless a lifecycle rule says otherwise, so a
        library edited over years accumulates thousands of billable sidecar
        revisions. Returns None when the key lacks permission to check.
        """
        from botocore.exceptions import ClientError

        try:
            resp = self._client.get_bucket_lifecycle_configuration(Bucket=self.name)
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in ("NoSuchLifecycleConfiguration", "404"):
                return True  # no rule at all -> B2 default -> keeps everything
            return None  # AccessDenied or similar; caller reports "unknown"
        for rule in resp.get("Rules", []):
            if rule.get("Status") != "Enabled":
                continue
            if "NoncurrentVersionExpiration" in rule:
                return False
        return True
