"""Quota detection and wait utilities for Claude Code CLI on acct2's account (5-hour window, no weekly limit).

Extracted from changes/0.3_math_sliding_window/compose/scripts/common.py, which handles usage-limit parsing,
reset-time detection and backoff for multi-account orchestration. Stripped to the essentials for a single-account
auto-agent loop.
"""
import re, time
from datetime import datetime, timedelta

# --- Regexes for detecting limit and overload messages in CLI output ---

LIMIT_RX = re.compile(
    r"usage limit|limit reached|hit your [^\n]{0,80}?limit|session limit|out of (extra )?usage"
    r"|rate.?limit|resets? (at |in |on )?\d|exceeded your|\b429\b|quota_pause", re.I)

AUTH_RX = re.compile(
    r"invalid (?:oauth )?token|token (?:has )?expired|unauthori[sz]ed|authentication (?:error|failed)"
    r"|api_error_status\s*[=:]\s*401|\bHTTP\s*401\b", re.I)

OVERLOAD_RX = re.compile(
    r"overloaded|\b529\b|\b50[0234]\b|internal server error|api error|connection (error|reset)", re.I)

# Epoch timestamp embedded in CLI error messages: "...resets at 1730000000|1730000000..."
EPOCH_RX = re.compile(r"\|(\d{10})\b")

# Clock-style reset time: "resets at 7:00 am (America/New_York)"
CLOCK_RX = re.compile(r"resets?\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?", re.I)

# Date-style reset time: "resets Nov 7, 7am (America/Indiana/Indianapolis)"
DATE_RX = re.compile(
    r"resets?\s+(?:on\s+)?([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(?:at\s+)?"
    r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?(?:\s*\(([^)]+)\))?", re.I)

MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun",
                                       "jul", "aug", "sep", "oct", "nov", "dec"), 1)}

# Default polling interval when no reset time can be parsed
LIMIT_POLL_S = 900
RESET_BUFFER_S = 5


def _hour24(hour, ampm):
    ampm = (ampm or "").lower()
    if ampm == "pm" and hour < 12:
        return hour + 12
    if ampm == "am" and hour == 12:
        return 0
    return hour


def _zone(tz):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz) if tz else None
    except Exception:
        return None


def classify_failure(text):
    """Classify authentication, quota, and transient failures separately."""
    if AUTH_RX.search(text):
        return "auth"
    if LIMIT_RX.search(text):
        return "limit"
    if OVERLOAD_RX.search(text):
        return "overload"
    return "other"


def reset_wait_s(text):
    """Seconds until the usage limit resets (plus a short buffer), or None if unparseable."""
    # Try epoch timestamp first
    m = EPOCH_RX.search(text)
    if m and int(m.group(1)) > time.time():
        return int(m.group(1)) - time.time() + RESET_BUFFER_S

    # Try date-style: "resets Nov 7, 7am (...)"
    m = DATE_RX.search(text)
    if m and m.group(1)[:3].lower() in MONTHS:
        month, day = MONTHS[m.group(1)[:3].lower()], int(m.group(2))
        hour = _hour24(int(m.group(3)), m.group(5))
        minute = int(m.group(4) or 0)
        zone = _zone(m.group(6))
        cur = datetime.now(zone) if zone else datetime.now()
        try:
            target = cur.replace(month=month, day=day, hour=hour, minute=minute, second=0, microsecond=0)
            if target < cur - timedelta(days=1):
                target = target.replace(year=cur.year + 1)
        except ValueError:
            target = None
        if target is not None:
            wait = (target - cur).total_seconds() + RESET_BUFFER_S
            if 0 < wait < 9 * 24 * 3600:
                return wait

    # Try clock-style: "resets at 7:00 am (...)"
    m = CLOCK_RX.search(text)
    if m:
        hour = _hour24(int(m.group(1)), m.group(3))
        minute = int(m.group(2) or 0)
        zone = _zone(m.group(4))
        cur = datetime.now(zone) if zone else datetime.now()
        if 0 <= hour < 24 and 0 <= minute < 60:
            target = cur.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target <= cur:
                if cur - target < timedelta(minutes=15):
                    return 60  # reset time just passed; retry soon rather than wait a day
                target += timedelta(days=1)
            wait = (target - cur).total_seconds() + RESET_BUFFER_S
            if wait < 8 * 24 * 3600:
                return wait

    return None


def limit_wait_s(text):
    """Seconds to wait for quota reset; falls back to LIMIT_POLL_S if no reset time can be parsed."""
    w = reset_wait_s(text)
    return LIMIT_POLL_S if w is None else w


def fmt_s(s):
    """Human-readable duration."""
    s = int(max(0, s))
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}min"
    return f"{s // 60}min"
