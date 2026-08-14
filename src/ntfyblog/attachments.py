"""
Received-attachment download and safe local storage.

attachment.name comes from the message sender — untrusted. The stored
filename is built from the ntfy message id (already globally unique, and
it's the same id the entry itself is keyed by) plus a sanitized extension
taken from the sender-provided name — unlike ntfyer's collision-retry
dance, there's nothing to collide with here: a message id can never repeat,
so the id alone is a stable, predictable, one-to-one filename.
"""

import os

from . import ntfy_api
from .config import Profile

MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024  # 100 MiB

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".avif"}
VIDEO_EXTS = {".mp4", ".webm", ".mov", ".m4v", ".ogv"}


class AttachmentError(Exception):
    pass


def sanitize_filename(name: str) -> str:
    name = os.path.basename((name or "").strip())
    if not name or name in (".", ".."):
        return "attachment"
    return name


def classify(mime: str | None, ext: str) -> str:
    """Returns "image", "video", or "file" — ntfy's attachment.type is the
    sender-reported MIME type, cross-checked against the extension since
    senders don't always set it."""
    mime = (mime or "").lower()
    ext = ext.lower()
    if mime.startswith("image/") or ext in IMAGE_EXTS:
        return "image"
    if mime.startswith("video/") or ext in VIDEO_EXTS:
        return "video"
    return "file"


def save_attachment(profile: Profile, msg: dict, data_dir: str) -> dict | None:
    """
    Download msg's attachment (if any) into
    data_dir/attachments/<profile.name>/<message id><ext>.

    Returns {"file": <path relative to data_dir, forward-slashed>,
    "name": <original sender-provided filename>, "type": "image"|"video"|"file"},
    or None if the message has no attachment. Raises AttachmentError on
    failure (network, HTTP, size limit, filesystem). data_dir is created if
    missing; the caller doesn't need to pre-create it.
    """
    attachment = msg.get("attachment")
    if not attachment or not attachment.get("url"):
        return None

    msg_id = msg.get("id")
    if not msg_id:
        raise AttachmentError("message has an attachment but no id — cannot derive a stable filename")

    orig_name = sanitize_filename(attachment.get("name") or "attachment")
    _, ext = os.path.splitext(orig_name)
    attachment_type = classify(attachment.get("type"), ext)

    rel_path = f"attachments/{profile.name}/{msg_id}{ext}"
    dest_dir = os.path.join(data_dir, "attachments", profile.name)
    dest_path = os.path.join(data_dir, *rel_path.split("/"))

    os.makedirs(dest_dir, exist_ok=True)

    if os.path.exists(dest_path):
        # Already downloaded — e.g. this message was redelivered after a
        # reconnect. Reuse the existing file rather than re-fetching it.
        return {"file": rel_path, "name": orig_name, "type": attachment_type}

    tmp_path = f"{dest_path}.part"
    try:
        with open(tmp_path, "wb") as f:
            ntfy_api.download_attachment(profile, attachment["url"], f, max_bytes=MAX_ATTACHMENT_BYTES)
        os.replace(tmp_path, dest_path)
    except ntfy_api.DownloadError as e:
        _cleanup(tmp_path)
        raise AttachmentError(str(e)) from e
    except OSError as e:
        _cleanup(tmp_path)
        raise AttachmentError(f"could not write {dest_path!r}: {e}") from e
    except BaseException:
        _cleanup(tmp_path)
        raise

    return {"file": rel_path, "name": orig_name, "type": attachment_type}


def delete_attachment(data_dir: str, rel_path: str) -> None:
    """Best-effort delete of a previously saved attachment, given the
    relative path stored in an entry's attachment.file — used by retention
    purge so a file never outlives the JSON entry that was the only
    sanctioned way to reach it."""
    abs_path = os.path.join(data_dir, *rel_path.split("/"))
    try:
        os.unlink(abs_path)
    except OSError:
        pass


def _cleanup(path: str) -> None:
    if os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass
