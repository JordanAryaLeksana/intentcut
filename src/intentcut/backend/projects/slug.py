"""Readable, stable project slugs. Internal UUIDs remain canonical."""

import re
import unicodedata
from collections.abc import Iterator

SLUG_MAX_LENGTH = 60
_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def is_valid_slug(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 80
        and _SLUG_PATTERN.fullmatch(value) is not None
    )


def slugify_name(name: str) -> str:
    """One deterministic base slug for a display name (no uniqueness)."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    slug = slug[:SLUG_MAX_LENGTH].strip("-")
    return slug or "project"


def slug_candidates(name: str) -> Iterator[str]:
    """Base slug, then -2, -3, ... with the suffix inside the length cap."""
    base = slugify_name(name)
    yield base
    number = 2
    while True:
        suffix = f"-{number}"
        yield f"{base[: SLUG_MAX_LENGTH - len(suffix)].strip('-')}{suffix}"
        number += 1
