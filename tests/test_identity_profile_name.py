"""A non-US listing gets Yahoo's name from the profile memo (GLB-10)."""

from stocks import identity
from stocks.data import profiles


def test_company_name_falls_back_to_profile_name(tmp_path, monkeypatch):
    monkeypatch.setattr(profiles, "PROFILE_CACHE", tmp_path / "profiles.json")
    profiles.clear()
    profiles.remember(
        "ASML.AS",
        {"quoteType": "EQUITY", "sector": "Technology", "longName": "ASML Holding N.V."},
    )
    watchlist = tmp_path / "watchlist.yaml"
    watchlist.write_text("[]\n")
    assert identity.company_name("ASML.AS", watchlist) == "ASML Holding N.V."
    assert identity.company_name("ZZZZ.AS", watchlist) is None
    profiles.clear()
