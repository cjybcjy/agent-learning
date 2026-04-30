from __future__ import annotations

from sentinel.collectors.base import RawMention


MIN_ACCOUNT_AGE_DAYS = 30
MIN_FOLLOWERS = 10


def filter_spam(mentions: list[RawMention]) -> list[RawMention]:
    """Apply anti-spam rules: account age, follower count, and per-symbol dedup."""
    seen: set[tuple[str, str]] = set()  # (account_key, symbol)
    clean: list[RawMention] = []
    for m in mentions:
        # Account age filter
        if m.account_age_days < MIN_ACCOUNT_AGE_DAYS:
            continue
        # Follower threshold
        if m.account_followers < MIN_FOLLOWERS:
            continue
        # Dedup: same source_url counts only once per symbol
        dedup_key = (m.source_url, m.symbol)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        clean.append(m)
    return clean
