"""HTX API v2 signature helpers."""

from __future__ import annotations

import base64
import datetime
import hashlib
import hmac
from urllib.parse import urlencode, urlparse


def utc_timestamp() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def sign_params(
    *,
    method: str,
    base_url: str,
    path: str,
    params: dict,
    api_key: str,
    secret_key: str,
) -> dict:
    signed = dict(params or {})
    signed["AccessKeyId"] = api_key
    signed["SignatureMethod"] = "HmacSHA256"
    signed["SignatureVersion"] = "2"
    signed["Timestamp"] = utc_timestamp()
    encoded = urlencode(sorted((str(k), str(v)) for k, v in signed.items()))
    host = urlparse(base_url).netloc
    payload = "\n".join([method.upper(), host, path, encoded])
    digest = hmac.new(secret_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    signed["Signature"] = base64.b64encode(digest).decode("utf-8")
    return signed
