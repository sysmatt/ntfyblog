"""Per-profile listener threads and the daemon's main run loop."""

import signal
import threading

from . import attachments, ntfy_api
from .config import Profile
from .writer import Writer

# After a SubscribeError (bad auth, unreachable host, bad topic) — distinct
# from ntfy_api's own RECONNECT_BACKOFF, which only covers a connection that
# was already established and then dropped mid-stream.
RECONNECT_ERROR_BACKOFF = 5


def build_entry(profile: Profile, msg: dict, data_dir: str, log) -> dict:
    ntfy_id = msg.get("id") or ""
    entry = {
        "id": f"{profile.name}:{ntfy_id}",
        "profile": profile.name,
        "time": msg.get("time"),
        "title": msg.get("title") or None,
        "message": msg.get("message", ""),
        "priority": msg.get("priority"),
        "tags": msg.get("tags") or [],
        "click_url": msg.get("click") or None,
        "attachment": None,
    }

    try:
        att = attachments.save_attachment(profile, msg, data_dir)
        if att:
            entry["attachment"] = att
    except attachments.AttachmentError as e:
        log.error(f"[{profile.name}] attachment download failed: {e}")

    return entry


def _profile_loop(profile: Profile, writer: Writer, log, stop_event: threading.Event) -> None:
    log.verbose(f"[{profile.name}] starting listener on {profile.url} (topic hidden from logs at non-debug levels)")
    log.debug(f"[{profile.name}] topic={profile.topic!r}")

    since = writer.last_seen_ntfy_id(profile.name) or "all"

    while not stop_event.is_set():
        try:
            for msg in ntfy_api.stream_json(profile, profile.topic, since=since):
                if stop_event.is_set():
                    break
                log.info(f"[{profile.name}] {msg.get('title') or ''}: {msg.get('message', '')}".lstrip(": "))
                log.trace(f"[{profile.name}] full message: {msg}")

                entry = build_entry(profile, msg, writer.data_dir, log)
                writer.add_entry(profile, entry)

                if msg.get("id"):
                    since = msg["id"]
        except ntfy_api.SubscribeError as e:
            log.error(f"[{profile.name}] {e} — retrying in {RECONNECT_ERROR_BACKOFF}s")
            stop_event.wait(RECONNECT_ERROR_BACKOFF)
            continue

        # stream_json only returns (without raising) when a caller-supplied
        # timeout elapses — collector never sets one, so reaching here means
        # the generator ended some other way. Back off and resubscribe
        # rather than busy-looping.
        if not stop_event.is_set():
            stop_event.wait(RECONNECT_ERROR_BACKOFF)

    log.verbose(f"[{profile.name}] listener stopped")


def run(profiles: list[Profile], web_config, data_dir: str, log) -> int:
    writer = Writer(data_dir, profiles, log)
    writer.write_config_json(web_config)

    stop_event = threading.Event()

    def _handle_signal(signum, frame):
        log.verbose(f"received signal {signum}, shutting down")
        stop_event.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    threads = [
        threading.Thread(
            target=_profile_loop, args=(profile, writer, log, stop_event),
            name=f"listener-{profile.name}", daemon=True,
        )
        for profile in profiles
    ]
    for t in threads:
        t.start()

    log.info(f"ntfyblog collector running — {len(profiles)} profile(s), data dir {data_dir}")

    try:
        while not stop_event.is_set():
            stop_event.wait(1)
    except KeyboardInterrupt:
        stop_event.set()

    log.verbose("stopped")
    return 0
