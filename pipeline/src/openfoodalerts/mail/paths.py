"""Notification detail page paths: `/{locale}/n/{source}/{key…}` (spec §9).

The Python twin of web/lib/notification-path.ts; both test suites use the same examples.

- openFDA and RASFF keys (`H-0015-2027`, `2026.9489`) are one path segment.
- NVWA keys are URL paths (`/actueel/nieuws/2026/10/24/…`); they are spread over the
  remaining segments without their leading slash.

Each segment is percent-encoded exactly like JavaScript's encodeURIComponent.
"""

from urllib.parse import quote

_PATH_KEYED = frozenset({"nvwa"})
# encodeURIComponent leaves these unreserved characters alone.
_SAFE = "-_.!~*'()"


def key_segments(source: str, key: str) -> list[str]:
    return key.lstrip("/").split("/") if source in _PATH_KEYED else [key]


def notification_path(locale: str, source: str, key: str) -> str:
    segments = "/".join(quote(s, safe=_SAFE) for s in key_segments(source, key))
    return f"/{locale}/n/{source}/{segments}"
