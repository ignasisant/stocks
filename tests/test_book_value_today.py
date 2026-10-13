import pandas as pd

from stocks.api import loaders


def test_the_priced_table_wins_when_everything_priced(monkeypatch):
    table = pd.DataFrame({"cost": [1.0, 2.0], "value": [100.4, 46.6]})
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    hist = pd.DataFrame({"value": [140.0, 147.5]})
    assert loaders.book_value_today("db", 1.0, "EUR", hist) == 147.0


def test_the_path_stands_when_a_name_is_unpriced(monkeypatch):
    table = pd.DataFrame({"cost": [1.0, 2.0], "value": [100.0, float("nan")]})
    monkeypatch.setattr(loaders, "positions_table", lambda *a, **k: table)
    hist = pd.DataFrame({"value": [140.0, 147.5]})
    assert loaders.book_value_today("db", 1.0, "EUR", hist) == 147.5
