"""ntfy subscribe/download HTTP layer. No publish support — ntfyblog only ever reads."""

import json
import time
from urllib.parse import urlparse

import requests

from .config import Profile

DEFAULT_TIMEOUT = (10, 30)  # connect, read — seconds
DOWNLOAD_CHUNK_SIZE = 65536

# ntfy sends a keepalive line roughly every 30-45s on the JSON stream; this
# needs comfortable margin above that so a normal quiet period between
# messages never trips a spurious read timeout.
STREAM_CONNECT_TIMEOUT = 10
STREAM_READ_TIMEOUT = 90
RECONNECT_BACKOFF = 2


class SubscribeError(Exception):
    pass


class DownloadError(Exception):
    pass


def _auth(profile: Profile) -> tuple[dict, tuple | None]:
    if profile.auth_type == "token":
        return {"Authorization": f"Bearer {profile.token}"}, None
    if profile.auth_type == "basic":
        return {}, (profile.username, profile.password)
    return {}, None


def _same_origin(server_url: str, other_url: str) -> bool:
    return urlparse(server_url).netloc == urlparse(other_url).netloc


def stream_json(profile: Profile, topic: str, *, timeout: float | None = None, since: str | None = None):
    """
    Yield decoded JSON dicts for each 'message' event on profile.url/topic/json.
    'open'/'keepalive' events are consumed silently.

    `since` seeds ntfy's replay of cached messages on the *first* connection
    of this call — pass a message id to resume after it, "all" to replay
    everything the server still has cached, or None to skip replay and only
    see messages from here on. After the first message is seen, every
    reconnect (dropped connection) automatically re-seeds `since` from the
    last message id actually yielded, so a mid-stream drop can never
    re-deliver or skip messages regardless of what the caller originally
    passed.

    A dropped connection (successfully connected, then lost mid-stream)
    reconnects automatically. A failure on the connection attempt itself
    (bad auth, unreachable host, bad topic) raises SubscribeError — the
    caller is expected to retry at a higher level with its own backoff if
    this is meant to run indefinitely as a service. If `timeout` is given,
    stops yielding (returns) once that many seconds have passed since the
    call started, whether or not anything arrived.
    """
    if not topic:
        raise SubscribeError("topic is required")

    base_url = f"{profile.url.rstrip('/')}/{topic}/json"
    auth_headers, basic_auth = _auth(profile)
    deadline = time.monotonic() + timeout if timeout else None
    current_since = since

    while True:
        if deadline and time.monotonic() >= deadline:
            return

        if deadline:
            read_timeout = min(STREAM_READ_TIMEOUT, max(deadline - time.monotonic(), 1))
        else:
            read_timeout = STREAM_READ_TIMEOUT

        url = f"{base_url}?since={current_since}" if current_since else base_url

        try:
            resp = requests.get(
                url, headers=auth_headers, auth=basic_auth, stream=True,
                timeout=(STREAM_CONNECT_TIMEOUT, read_timeout),
            )
            resp.raise_for_status()
        except requests.HTTPError as e:
            raise SubscribeError(f"server returned {e.response.status_code} for {url}") from e
        except requests.RequestException as e:
            raise SubscribeError(f"could not connect to {url}: {e}") from e

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if deadline and time.monotonic() >= deadline:
                    return
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if data.get("event") == "message":
                    if data.get("id"):
                        current_since = data["id"]
                    yield data
        except requests.RequestException:
            pass  # dropped mid-stream — fall through and reconnect
        finally:
            resp.close()

        if deadline and time.monotonic() >= deadline:
            return
        time.sleep(min(RECONNECT_BACKOFF, max(deadline - time.monotonic(), 0)) if deadline else RECONNECT_BACKOFF)


def download_attachment(profile: Profile, url: str, fileobj, *, max_bytes: int) -> int:
    """
    Stream url's bytes into fileobj. profile's auth is only attached when url
    is on the same host as profile.url — an attachment can point anywhere,
    and credentials must never leak to a host that isn't actually your ntfy
    server. Raises DownloadError on any network/HTTP failure or if more than
    max_bytes arrive. Returns the number of bytes written; does not
    delete/touch fileobj on failure — that's the caller's responsibility.
    """
    headers = {}
    basic_auth = None
    if _same_origin(profile.url, url):
        auth_headers, basic_auth = _auth(profile)
        headers.update(auth_headers)

    try:
        resp = requests.get(url, headers=headers, auth=basic_auth, stream=True, timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as e:
        raise DownloadError(f"could not download {url}: {e}") from e

    written = 0
    try:
        for chunk in resp.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            written += len(chunk)
            if written > max_bytes:
                raise DownloadError(f"attachment exceeds {max_bytes}-byte limit while downloading {url}")
            fileobj.write(chunk)
    except requests.RequestException as e:
        raise DownloadError(f"download of {url} failed: {e}") from e
    finally:
        resp.close()

    return written
