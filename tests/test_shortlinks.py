"""A bio link is a short path that lands on the pitch with its campaign."""

from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest

from stocks import navigation
from stocks.web import attribution, shortlinks
from tests.test_attribution import BROWSER_HEADERS, CHROME, client, events  # noqa: F401


def test_no_short_path_shadows_a_page_of_the_app():
    taken = {f"/{slug}" for slug in navigation.SHELL_PATHS}
    assert not taken & set(shortlinks.PATHS)


@pytest.mark.parametrize("slug", sorted(shortlinks.SOURCES))
def test_each_path_redirects_to_the_landing_with_its_campaign(client, slug):  # noqa: F811
    response = client.get(
        f"/{slug}",
        follow_redirects=False,
        headers={"user-agent": CHROME, **BROWSER_HEADERS},
    )
    assert response.status_code == 302
    assert response.headers["cache-control"] == "no-store"
    parts = urlsplit(response.headers["location"])
    assert parts.path == "/"
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert attribution.source(query) == shortlinks.SOURCES[slug]
    assert attribution.medium(query) == shortlinks.MEDIUM


def test_the_campaign_reaches_the_funnel_as_a_landing_view(client, events):  # noqa: F811
    response = client.get(
        "/ig", follow_redirects=True, headers={"user-agent": CHROME, **BROWSER_HEADERS}
    )
    assert response.status_code == 200
    name, fields = next(e for e in events if e[0] == "landing.view")
    assert fields["src"] == "instagram"
    assert fields["medium"] == "bio"


def test_an_unknown_short_path_is_still_a_404(client):  # noqa: F811
    assert client.get("/nope", follow_redirects=False).status_code == 404


def test_the_targets_match_the_brand_table():
    from pathlib import Path

    brand = (Path(__file__).parent.parent / "docs" / "BRAND.md").read_text()
    for source in shortlinks.SOURCES.values():
        assert f"utm_source={source}&utm_medium={shortlinks.MEDIUM}" in brand
