"""Ticker search as a domain question: which tier answers, and in what order.

The ranking used to live inside the Streamlit top bar, where it could only be
tested through a page run. It is `stocks.search` now because a second front end
asks the same question, and these tests are what stops the two from drifting:
every tier is fed by a callable, so nothing here touches the network.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stocks import search


@dataclass
class Holding:
    ticker: str
    name: str = ""
    favorite: bool = False
    tags: list[str] = field(default_factory=list)


WATCHLIST = [
    Holding("AAPL", "Apple Inc.", favorite=True, tags=["Tech"]),
    Holding("MSFT", "Microsoft Corp", tags=["Tech"]),
    Holding("SAN.MC", "Banco Santander", tags=["Banca"]),
]

NOTHING: list = []


def tiers(q, catalog=None, *, crypto=None, funds=None, sec=None, world=None):
    return search.tiers(
        q,
        catalog if catalog is not None else search.account_catalog(WATCHLIST),
        crypto=crypto or (lambda _q: []),
        funds=funds or (lambda _q: []),
        sec=sec or (lambda _q: []),
        world=world or (lambda _q: []),
    )


# ------------------------------------------------------------- the own list


def test_the_own_list_matches_symbol_name_or_tag():
    """All three fields, because all three are how someone refers to a holding."""
    assert [t for t, _, _ in tiers("AAPL")[0]] == ["AAPL"]
    assert [t for t, _, _ in tiers("microsoft")[0]] == ["MSFT"]
    assert [t for t, _, _ in tiers("tech")[0]] == ["AAPL", "MSFT"]


def test_favorites_lead_their_own_list():
    """A starred name is the one its owner meant; it cannot sort below the rest."""
    catalog = search.account_catalog([Holding("ZZZZ", "Zed", tags=["Tech"]), *WATCHLIST])
    assert [t for t, _, _ in tiers("tech", catalog)[0]][0] == "AAPL"


def test_a_typo_still_finds_the_holding():
    """Fuzzy is a fallback, not a tier: it runs only when exact found nothing."""
    assert [t for t, _, _ in tiers("aple")[0]] == ["AAPL"]


def test_fuzzy_never_dilutes_an_exact_hit():
    """"MSFT" must answer MSFT alone, not MSFT plus everything near it."""
    assert [t for t, _, _ in tiers("MSFT")[0]] == ["MSFT"]


def test_a_starred_row_is_marked_starred_and_a_held_one_held():
    """The mark is a name, not a glyph — each front end draws its own."""
    catalog = search.account_catalog(WATCHLIST, held=["ORCL"], title=lambda t: "Oracle")
    marks = {t: m for t, _, m in tiers("a", catalog)[0]}
    assert marks["AAPL"] == search.FAVORITE
    assert marks["ORCL"] == search.HELD
    assert marks["SAN.MC"] == ""


def test_a_held_but_unlisted_symbol_is_searchable_by_company_name():
    """Without the SEC title, an imported ORCL position is unreachable by name —
    and the `not in labels` dedup drops the SEC row for it too."""
    catalog = search.account_catalog(WATCHLIST, held=["ORCL"], title=lambda t: "Oracle")
    assert [t for t, _, _ in tiers("oracle", catalog)[0]] == ["ORCL"]


# ----------------------------------------------------------------- the tiers


def test_every_tier_is_deduped_against_the_ones_above_it():
    """A symbol already on the list must not come back as a SEC or world row."""
    watch, coins, funds, sec, world, _ = tiers(
        "AAPL",
        crypto=lambda _q: [("AAPL", "not really")],
        funds=lambda _q: [("AAPL", "nor this")],
        sec=lambda _q: [("AAPL", "Apple Inc")],
        world=lambda _q: [("AAPL", "Apple", "NMS")],
    )
    assert [t for t, _, _ in watch] == ["AAPL"]
    assert (coins, funds, sec, world) == ([], [], [], [])


def test_worldwide_runs_even_when_the_local_tiers_answered():
    """Their fuzzy fallbacks always produce something, so "nothing local" is not
    a usable trigger — it is what buried MIPS.ST under four wrong US tickers."""
    _, _, _, sec, world, _ = tiers(
        "MIPS",
        sec=lambda _q: [("VIPS", "Vipshop"), ("CMPS", "Compass")],
        world=lambda _q: [("MIPS.ST", "Mips AB", "Stockholm")],
    )
    assert [t for t, _, _ in world] == ["MIPS.ST"]
    assert [t for t, _ in sec] == ["VIPS", "CMPS"]


def test_an_unknown_but_plausible_symbol_gets_the_analyze_escape_hatch():
    assert tiers("ZZQQ")[5] == "ZZQQ"


def test_a_sentence_is_not_a_symbol():
    """The fallback is a symbol shape, or every failed name search offers one."""
    assert tiers("a whole sentence")[5] is None


def test_an_empty_query_answers_nothing_at_all():
    assert tiers("   ") == ([], [], [], [], [], None)


def test_a_symbol_any_tier_knows_gets_no_analyze_row():
    assert tiers("MIPS.ST", world=lambda _q: [("MIPS.ST", "Mips AB", "STO")])[5] is None


# ------------------------------------------------------ which group leads


def test_a_nailed_sec_hit_keeps_the_top_slot():
    assert search.world_first("SANDISC", [("SNDK", "Sandisk Corp")]) is False


def test_near_misses_hand_the_lead_to_the_worldwide_group():
    assert search.world_first("MIPS", [("VIPS", "Vipshop Holdings")]) is True


def test_the_query_buried_in_a_longer_name_proves_nothing():
    """"hermes" scores .92 against "Federated Hermes" — matching from the start
    is what keeps Hermès itself above an asset manager."""
    assert search.world_first("HERMES", [("FHI", "Federated Hermes, Inc.")]) is True


# ----------------------------------------------------------- the flat order


def test_the_flat_list_draws_the_tiers_in_the_dropdown_order():
    rows = search.ranked(
        "A",
        search.account_catalog(WATCHLIST),
        crypto=lambda _q: [("BTC-USD", "Bitcoin")],
        funds=lambda _q: [("IWDA.AS", "iShares World")],
        sec=lambda _q: [("AMZN", "Amazon.com Inc")],
        world=lambda _q: [("AIR.PA", "Airbus", "Paris")],
    )
    kinds = [row.kind for row in rows]
    assert kinds[: kinds.index(search.CRYPTO)] == [search.WATCH] * kinds.count(
        search.WATCH
    )
    assert kinds.index(search.CRYPTO) < kinds.index(search.FUND)
    assert kinds.index(search.FUND) < min(
        kinds.index(search.SEC), kinds.index(search.WORLD)
    )


def test_the_swap_between_sec_and_world_survives_flattening():
    """`ranked` is the draw order, so it has to apply `world_first` itself."""
    ordered = search.ranked(
        "MIPS",
        search.account_catalog([]),
        crypto=lambda _q: [],
        funds=lambda _q: [],
        sec=lambda _q: [("VIPS", "Vipshop Holdings")],
        world=lambda _q: [("MIPS.ST", "Mips AB", "Stockholm")],
    )
    assert [row.ticker for row in ordered][:2] == ["MIPS.ST", "VIPS"]


def test_the_analyze_row_is_last_and_carries_no_name():
    rows = search.ranked(
        "ZZQQ",
        search.account_catalog([]),
        crypto=lambda _q: [],
        funds=lambda _q: [],
        sec=lambda _q: [],
        world=lambda _q: [],
    )
    assert rows[-1].kind == search.ANALYZE
    assert (rows[-1].ticker, rows[-1].name) == ("ZZQQ", "")


def test_the_worldwide_row_carries_its_venue():
    """The exchange is what disambiguates the tier — several rows are the same
    brand on different venues, and it is the hint that the symbol is foreign."""
    rows = search.ranked(
        "MIPS",
        search.account_catalog([]),
        crypto=lambda _q: [],
        funds=lambda _q: [],
        sec=lambda _q: [],
        world=lambda _q: [("MIPS.ST", "Mips AB", "Stockholm")],
    )
    assert rows[0].exchange == "Stockholm"
