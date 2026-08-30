"""Note identity: timestamp IDs, title slugs, and the composite note key.

The note key -- ``<title-slug>--<timestamp-id>`` -- is the universal reference
used for filenames, ``[[wikilinks]]``, and frontmatter ``target_id`` values.
Amends FR-5's bare-timestamp filename stem so notes stay legible in Obsidian;
the timestamp ``id`` remains the immutable identity and the slug is frozen at
creation, so a later title edit never moves a file or breaks a link.
"""

from __future__ import annotations

import datetime as _dt
import re
import unicodedata

ID_RE = re.compile(r"^\d{12}$")
KEY_RE = re.compile(r"^(?P<slug>[a-z0-9]+(?:-[a-z0-9]+)*)--(?P<id>\d{12})$")
SEPARATOR = "--"
MAX_SLUG_LEN = 60


def new_id(when: _dt.datetime | None = None) -> str:
    """Return a fresh timestamp ID (``YYYYMMDDHHMM``, UTC)."""
    when = when or _dt.datetime.now(_dt.timezone.utc)
    return when.strftime("%Y%m%d%H%M")


def slugify(title: str, max_len: int = MAX_SLUG_LEN) -> str:
    """Lowercase ASCII slug, truncated on a word boundary.

    Returns ``"untitled"`` when a title has no slug-able characters, so a key
    can always be formed; the timestamp suffix keeps it unique regardless.
    """
    folded = unicodedata.normalize("NFKD", title)
    folded = folded.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", folded).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug:
        return "untitled"
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0].strip("-") or slug[:max_len].strip("-")
    return slug


def make_key(title: str, note_id: str) -> str:
    """Compose the note key from a title and an existing timestamp ID."""
    if not ID_RE.match(note_id):
        raise ValueError(f"invalid note id {note_id!r}: expected 12 digits (YYYYMMDDHHMM)")
    return f"{slugify(title)}{SEPARATOR}{note_id}"


def split_key(key: str) -> tuple[str, str]:
    """Split a note key into ``(slug, id)``; raises on a malformed key."""
    m = KEY_RE.match(key)
    if not m:
        raise ValueError(f"malformed note key {key!r}: expected <title-slug>--<YYYYMMDDHHMM>")
    return m.group("slug"), m.group("id")


def is_key(value: str) -> bool:
    return bool(KEY_RE.match(value))


def is_id(value: str) -> bool:
    return bool(ID_RE.match(value))
