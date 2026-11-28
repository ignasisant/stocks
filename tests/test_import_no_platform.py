"""Importing with no platform chosen: the reader reads whatever it is given.

The importer page no longer asks which broker a file comes from. What that
leans on, tested here with files shaped like the ones real users bring:

* a dedicated parser's file is read as that broker with no platform named;
* a file no parser owns is read by its columns, and the preview says which
  column became which field, so the reader can check it before confirming;
* a file that is not a statement at all (a shipping list has a date, a name,
  a count and a price too) is refused, not booked as purchases;
* the preview says which tickers a commit opens positions in.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_api_import import (  # noqa: F401 — fixtures
    account,
    client,
    offline,
    signed_in,
    token,
    upload,
)

SAMPLE = Path(__file__).parents[1] / "src/stocks/web/assets/sample-statement-revolut.csv"

LISTING = """When,What,Did,Units,Each,Money
2025-03-03,American Tower,Bought,3,91.00,USD
2025-03-03,Nvidia,Bought,2,114.00,USD
2025-03-04,Microsoft,Sold,1,389.00,USD
"""

SHIPPING = """order-id,business-name,buyer-name,sku,quantity-to-ship,product-price,order-price,flag,ship-date
B2B-0001,Acme Retail SL,Laura Martinez,SKU12345,10,19.99,349.80,yes,2026-11-16
B2B-0001,Acme Retail SL,Laura Martinez,SKU67890,6,25.00,349.80,yes,2026-11-16
B2B-0002,Bolt SL,Pedro Gil,SKU11111,2,5.00,10.00,no,2026-11-17
"""


def send(client, filename: str, text: str, **extra):
    body = {"filename": filename, "content": upload(text), **extra}
    return client.post("/v1/import/preview", json=body)


def test_a_revolut_export_is_read_with_no_platform_named(client, account, signed_in):
    text = SAMPLE.read_text()
    payload = send(signed_in, SAMPLE.name, text).json()
    assert payload["platform"] == "revolut"
    assert payload["importable"]
    assert payload["columns"] == []  # a parser's read has no mapping to check


def test_a_listing_of_trades_is_read_by_its_columns_and_says_which(
    client, account, signed_in
):
    payload = send(signed_in, "mine.csv", LISTING).json()
    assert payload["platform"] == "llm"
    assert {r["ticker"]: r["price"] for r in payload["importable"]}["NVIDIA"] == 114.0
    read = {c["field"]: c["column"] for c in payload["columns"]}
    assert read["date"] == "When"
    assert read["price"] == "Each"
    assert read["action"] == "Did"


def test_a_shipping_list_is_not_booked_as_purchases(client, account, signed_in):
    response = send(signed_in, "orders.csv", SHIPPING)
    assert response.status_code == 422, response.text


def test_the_preview_names_the_positions_a_commit_would_open(
    client, account, signed_in
):
    payload = send(signed_in, "mine.csv", LISTING).json()
    assert payload["new_positions"] == ["NVIDIA"]  # the other names are rejected rows



def test_the_page_can_log_its_actions_and_nothing_else(client, account, signed_in):
    ok = signed_in.post("/v1/import/event", json={"action": "override", "detail": "revolut>degiro"})
    assert ok.status_code == 204
    bad = signed_in.post("/v1/import/event", json={"action": "anything"})
    assert bad.status_code == 422
    free = signed_in.post("/v1/import/event", json={"action": "paste", "detail": "<script>"})
    assert free.status_code == 422


def test_the_preview_log_names_the_columns_it_read_and_no_values(
    client, account, signed_in, monkeypatch
):
    from stocks import obs

    seen: list[tuple[str, dict]] = []
    monkeypatch.setattr(obs, "event", lambda name, **f: seen.append((name, f)))
    send(signed_in, "mine.csv", LISTING)
    fields = [f for name, f in seen if name == "import.preview"]
    assert fields, seen
    mapped = fields[-1]["mapped"]
    assert "price:Each" in mapped and "date:When" in mapped
    assert "114" not in mapped
    assert "asks_broker" in fields[-1]
