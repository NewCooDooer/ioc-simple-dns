"""A small in-memory cache for source results.

The key is (source, clean name). The name has already been cleaned by check_name (trimmed, lowercased, no trailing
dot), so every way of typing one name uses the same entry, and two different names never share one.
The key never contains anything secret: it is only the source's label and the DNS name.

Rules this file enforces:
  * an "error" result is NEVER stored (a timeout, a 429, a 502 ... are not answers);
  * an entry with no time to live is not stored;
  * an expired entry is treated as missing.
"""

import threading
import time

# How long each source's answers are kept, in seconds. The reasons are in design.md, section 11.
# Google DNS is not listed here: its time comes from Google's own Cache-Control header on each reply.
RDAP_OK_SECONDS = 60 * 60  # registration details change rarely
RDAP_NOT_FOUND_SECONDS = 5 * 60  # a name can be registered at any moment
CRTSH_OK_SECONDS = 6 * 60 * 60  # slowest, most limited source; certificate history only grows
CRTSH_NOT_FOUND_SECONDS = 10 * 60  # a new name often gets its first certificate soon

MAX_ENTRIES = 5000  # a safety limit so the dictionary cannot grow without end

# The clock is a variable so that tests can replace it with a fake one and "move time" without waiting.
clock = time.monotonic

# key -> (stored_at, expires_at, result)
_entries = {}
# The Flask development server answers several requests at once, so changes to the dictionary take turns.
_lock = threading.Lock()


def lookup(source, name):
    """Return TWO things, (result, age_seconds), or None if there is no fresh entry.

    The result is the stored dictionary itself, not a copy. That is safe because nothing changes a result after it is built.
    The age travels beside the result (the backend sends it in a header), so the result keeps its original shape.
    """
    now = clock()
    with _lock:
        entry = _entries.get((source, name))
        if entry is None:
            return None
        stored_at, expires_at, result = entry
        if now >= expires_at:
            del _entries[(source, name)]
            return None
    return result, int(now - stored_at)


def store(source, name, result, seconds):
    """Keep a result for `seconds`. Errors and zero-length lifetimes are ignored."""
    if result["status"] == "error" or seconds <= 0:
        return
    now = clock()
    with _lock:
        if len(_entries) >= MAX_ENTRIES:
            _make_room(now)
        _entries[(source, name)] = (now, now + seconds, result)


def _make_room(now):
    """Called while holding the lock. Drop expired entries; if that is not enough, drop the oldest one."""
    for key in [key for key, entry in _entries.items() if now >= entry[1]]:
        del _entries[key]
    if len(_entries) >= MAX_ENTRIES:
        # Oldest *inserted* entry (dictionaries keep insertion order), not the least recently used one.
        # That is good enough at this size; a true LRU would need to reorder entries on every read.
        del _entries[next(iter(_entries))]


def clear_cache():
    with _lock:
        _entries.clear()
