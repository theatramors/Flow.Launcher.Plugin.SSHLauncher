# -*- coding: utf-8 -*-
"""Tiny fuzzy matcher.

Flow Launcher does *not* filter the results a plugin returns, so the plugin
does its own filtering.  Scores are deliberately simple and predictable:
exact alias > alias prefix > alias substring > subsequence, then the weaker
secondary fields (description, user@host, host).
"""

from __future__ import annotations

WEIGHTS = (
    ("alias", 1.0),
    ("description", 0.55),
    ("target", 0.5),
    ("host", 0.45),
)

MIN_SCORE = 1.0


def _subsequence_score(needle, text):
    if not needle or not text:
        return 0.0
    if needle == text:
        return 100.0
    if text.startswith(needle):
        return 92.0 - min(len(text) - len(needle), 12) * 0.5
    index = text.find(needle)
    if index >= 0:
        return 80.0 - min(index, 24)

    position = 0
    gaps = 0
    last = -1
    for char in needle:
        found = text.find(char, position)
        if found < 0:
            return 0.0
        if last >= 0:
            gaps += found - last - 1
        last = found
        position = found + 1
    score = 55.0 - gaps * 4.0 - last * 0.6
    return score if score > 5.0 else 5.0


def score_destination(needle, dest):
    if not needle:
        return 0.0
    needle = needle.lower()
    targets = {
        "alias": dest.get("alias", "").lower(),
        "description": (dest.get("description") or "").lower(),
        "host": (dest.get("host") or "").lower(),
        "target": target_of(dest).lower(),
    }
    best = 0.0
    for field, weight in WEIGHTS:
        text = targets.get(field) or ""
        if not text:
            continue
        score = _subsequence_score(needle, text) * weight
        if score > best:
            best = score
    if target_of(dest).lower() == needle and dest.get("alias", "").lower() != needle:
        best = max(best, 70.0)
    return best


def score_text(needle, text):
    if not needle:
        return 0.0
    return _subsequence_score(needle.lower(), (text or "").lower())


def target_of(dest):
    user = dest.get("user")
    host = dest.get("host") or ""
    return "%s@%s" % (user, host) if user else host
