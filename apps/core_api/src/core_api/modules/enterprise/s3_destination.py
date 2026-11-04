"""Path-style S3 with DNS pinning, TLS hostname verification and bounded reads."""
from hashlib import sha256
import ipaddress
import re
import socket
from tempfile import SpooledTemporaryFile
from time import monotonic
from urllib.parse import quote, urlparse

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials
from fastapi import HTTPException
import httpx

from core_api.infrastructure.settings import settings


class PrehashedS3Auth(SigV4Auth):
    def _normalize_url_path(self, path):
        # S3 signs the exact encoded object path without double escaping or
        # normalizing it. The payload hash is already known and verified.
        return path


def endpoint_host(endpoint):
    parsed = urlparse(endpoint)
    try:
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(422, "Invalid storage endpoint") from exc
    if (parsed.scheme != "https" or not parsed.hostname or port not in {None, 443}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment):
        raise HTTPException(422, "Storage endpoint must be an HTTPS origin on port 443")
    host = parsed.hostname.lower()
    allowed = {value.strip().lower() for value in settings.ENTERPRISE_S3_ALLOWED_HOSTS.split(",") if value.strip()}
    official = (host == "s3.amazonaws.com" or re.fullmatch(r"s3[.-][a-z0-9-]+\.amazonaws\.com", host)
        or re.fullmatch(r"[0-9a-f]{32}(?:\.eu)?\.r2\.cloudflarestorage\.com", host))
    if not official and host not in allowed:
        raise HTTPException(422, "Storage endpoint requires an operator-approved hostname")
    return host


def pinned_address(host):
    try:
        addresses = {entry[4][0] for entry in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise HTTPException(502, "Storage DNS resolution failed") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise HTTPException(422, "Storage endpoint must resolve only to public addresses")
    return sorted(addresses)[0]


class S3Destination:
    def __init__(self, configuration):
        self.configuration = configuration
        self.host = endpoint_host(configuration["endpoint"])

    def signed_request(self, method, key, *, digest=None, size=None, content_type=None):
        config = self.configuration
        path = f"/{config['bucket']}/{quote(key, safe='/-_.~')}"
        canonical = f"https://{self.host}{path}"
        headers = {"Host": self.host, "Accept-Encoding": "identity",
                   "X-Amz-Content-SHA256": digest or sha256(b"").hexdigest()}
        if size is not None:
            headers["Content-Length"] = str(size)
        if content_type:
            headers["Content-Type"] = content_type
        if method == "PUT":
            headers["If-None-Match"] = "*"
        request = AWSRequest(method=method, url=canonical, headers=headers)
        credentials = Credentials(config["access_key_id"], config["secret_access_key"], config.get("session_token"))
        PrehashedS3Auth(credentials, "s3", config["region"]).add_auth(request)
        ip = pinned_address(self.host)
        host = f"[{ip}]" if ":" in ip else ip
        return f"https://{host}{path}", dict(request.headers.items()), {"sni_hostname": self.host}

    def read_verified(self, key, digest, size):
        deadline = monotonic() + 60
        url, headers, extensions = self.signed_request("GET", key)
        output = SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        try:
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                with client.stream("GET", url, headers=headers, extensions=extensions) as result:
                    if result.status_code == 404:
                        raise FileNotFoundError(key)
                    if result.status_code != 200 or result.headers.get("content-encoding", "identity") != "identity":
                        raise HTTPException(502, "Storage read was rejected")
                    checksum, count = sha256(), 0
                    for chunk in result.iter_raw():
                        if monotonic() > deadline:
                            raise HTTPException(504, "Storage transfer exceeded its time budget")
                        count += len(chunk)
                        if count > size:
                            raise HTTPException(409, "External object size mismatch")
                        checksum.update(chunk)
                        output.write(chunk)
                    if count != size or checksum.hexdigest() != digest:
                        raise HTTPException(409, "External object integrity mismatch")
            output.seek(0)
            return output
        except httpx.HTTPError as exc:
            output.close()
            raise HTTPException(502, "Storage service unavailable") from exc
        except Exception:
            output.close()
            raise

    def ensure_object(self, key, digest, size, content_type, source):
        try:
            with self.read_verified(key, digest, size):
                return
        except FileNotFoundError:
            pass
        url, headers, extensions = self.signed_request("PUT", key, digest=digest, size=size, content_type=content_type)
        deadline = monotonic() + 60

        def chunks(stream):
            while chunk := stream.read(256 * 1024):
                if monotonic() > deadline:
                    raise HTTPException(504, "Storage transfer exceeded its time budget")
                yield chunk
        try:
            with source() as stream, httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                with client.stream("PUT", url, headers=headers, extensions=extensions, content=chunks(stream)) as result:
                    if result.status_code not in {200, 201, 204, 412}:
                        raise HTTPException(502, "Storage write was rejected")
            with self.read_verified(key, digest, size):
                pass
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Storage service unavailable") from exc

    def delete_probe(self, key):
        if "/probes/" not in key:
            raise ValueError("Only generated probe objects may be removed externally")
        url, headers, extensions = self.signed_request("DELETE", key)
        try:
            with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
                with client.stream("DELETE", url, headers=headers, extensions=extensions) as result:
                    if result.status_code not in {200, 204}:
                        raise HTTPException(502, "Storage probe cleanup failed")
        except httpx.HTTPError as exc:
            raise HTTPException(502, "Storage service unavailable") from exc
