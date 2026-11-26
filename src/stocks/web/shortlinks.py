"""Short addresses for a bio: `mybrainstock.com/ig` instead of a query string.

A profile page prints the link it was given, and a link carrying
`?utm_source=instagram&utm_medium=bio` reads as clutter there. The short path
answers with a redirect to the landing carrying that same campaign, so the
bio shows the clean address and `stocks logs funnel` still groups by network.

One path per network, named by what people already call it. The target is the
landing at `/`, not a page of the app: a campaign link is a first visit
(`attribution.PASSIVE_KEYS`) and must see the pitch.

The redirect is temporary (302): a bio link is edited, and a browser or a
crawler that cached a 301 would keep sending people to the old place.
"""

from __future__ import annotations

from urllib.parse import urlencode

#: short path -> the `utm_source` it stands for. Keep the tokens equal to the
#: table in `docs/BRAND.md`.
SOURCES = {
    "ig": "instagram",
    "tiktok": "tiktok",
    "x": "x",
    "li": "linkedin",
    "yt": "youtube",
    "threads": "threads",
    "bsky": "bluesky",
    "reddit": "reddit",
}

MEDIUM = "bio"

PATHS = tuple(f"/{slug}" for slug in SOURCES)


def target(slug: str) -> str | None:
    """Where `/<slug>` goes, or None when it is not a short link."""
    source = SOURCES.get(slug.strip("/").lower())
    if source is None:
        return None
    return "/?" + urlencode({"utm_source": source, "utm_medium": MEDIUM})
