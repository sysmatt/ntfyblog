"""
Owns entries.json/config.json and every attachment file — the single
writer all profile threads funnel through. All reads/writes of the shared
in-memory state are lock-guarded; every on-disk write is atomic
(write to .tmp, then os.replace()).
"""

import json
import os
import threading
from datetime import datetime, timezone

from . import attachments, retention
from .config import Profile, WebConfig


class Writer:
    def __init__(self, data_dir: str, profiles: list[Profile], log):
        self.data_dir = data_dir
        self.profiles = {p.name: p for p in profiles}
        self.log = log
        self._lock = threading.Lock()
        self._entries_by_profile: dict[str, list[dict]] = {name: [] for name in self.profiles}

        os.makedirs(self.data_dir, exist_ok=True)
        os.makedirs(os.path.join(self.data_dir, "attachments"), exist_ok=True)

        self._load_existing()
        # Reconcile against *current* retention settings on every start —
        # if keep_entries/keep_hours/keep_days were tightened since the last
        # run, apply that now rather than waiting for the next new message.
        with self._lock:
            for name in self.profiles:
                self._purge_locked(name)
            self._write_entries_locked()

    def _entries_path(self) -> str:
        return os.path.join(self.data_dir, "entries.json")

    def _config_path(self) -> str:
        return os.path.join(self.data_dir, "config.json")

    def _load_existing(self) -> None:
        path = self._entries_path()
        if not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            self.log.warning(f"could not read existing {path}: {e} — starting with an empty feed")
            return

        dropped = 0
        for entry in data.get("entries", []):
            profile_name = entry.get("profile")
            if profile_name in self._entries_by_profile:
                self._entries_by_profile[profile_name].append(entry)
            else:
                dropped += 1
        if dropped:
            self.log.verbose(f"dropped {dropped} entr{'y' if dropped == 1 else 'ies'} for profile(s) no longer in config")

    def last_seen_ntfy_id(self, profile_name: str) -> str | None:
        """The raw ntfy message id (not the profile-prefixed entry id) of the
        newest entry we already have for this profile — used to seed
        stream_json's `since=` so a restart resumes instead of replaying
        everything or missing the gap."""
        entries = self._entries_by_profile.get(profile_name) or []
        if not entries:
            return None
        newest = max(entries, key=lambda e: e.get("time", 0))
        prefix = f"{profile_name}:"
        entry_id = newest.get("id", "")
        return entry_id[len(prefix):] if entry_id.startswith(prefix) else None

    def add_entry(self, profile: Profile, entry: dict) -> None:
        with self._lock:
            self._entries_by_profile.setdefault(profile.name, []).append(entry)
            self._purge_locked(profile.name)
            self._write_entries_locked()

    def _purge_locked(self, profile_name: str) -> None:
        profile = self.profiles[profile_name]
        entries = self._entries_by_profile.get(profile_name, [])
        kept, purged = retention.purge(entries, profile)
        self._entries_by_profile[profile_name] = kept

        for old in purged:
            att = old.get("attachment")
            if att and att.get("file"):
                attachments.delete_attachment(self.data_dir, att["file"])

        if purged:
            self.log.verbose(
                f"purged {len(purged)} stale entr{'y' if len(purged) == 1 else 'ies'} for profile '{profile_name}'"
            )

    def _write_entries_locked(self) -> None:
        merged = []
        for entries in self._entries_by_profile.values():
            merged.extend(entries)
        merged.sort(key=lambda e: e.get("time", 0), reverse=True)

        payload = {"generated_at": _iso_now(), "entries": merged}
        _atomic_write_json(self._entries_path(), payload)

    def write_config_json(self, web_config: WebConfig) -> None:
        _atomic_write_json(self._config_path(), web_config.to_public_dict())


def _atomic_write_json(path: str, data) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp_path, path)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
