"""Per-profile retention: independent count/age caps, either one purges."""

import time

from .config import Profile


def purge(entries: list[dict], profile: Profile, *, now: float | None = None) -> tuple[list[dict], list[dict]]:
    """
    Split `entries` (all belonging to a single profile, any order) into
    (kept, purged). An entry is purged the moment it violates EITHER cap:
    ranked past profile.keep_entries by recency, or older than
    profile.keep_age_hours. A cap that's None (unset) never purges on its
    own. `kept` is returned newest-first.
    """
    now = now if now is not None else time.time()
    ordered = sorted(entries, key=lambda e: e.get("time", 0), reverse=True)

    kept = []
    purged = []
    for i, entry in enumerate(ordered):
        too_many = profile.keep_entries is not None and i >= profile.keep_entries
        too_old = (
            profile.keep_age_hours is not None
            and (now - entry.get("time", 0)) > profile.keep_age_hours * 3600
        )
        if too_many or too_old:
            purged.append(entry)
        else:
            kept.append(entry)

    return kept, purged
