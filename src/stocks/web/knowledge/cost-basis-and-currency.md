---
id: cost-basis-and-currency
title: Cost basis, currency conversion and missing prices
as_of: 2026-10-11
step: positions
related: tax-engine, importing, returns-and-risk
tags: coste, precio medio, base de coste, FIFO, lotes, cost basis, lots, divisa, moneda de referencia, reporting currency, tipo de cambio, FX, BCE, ECB, sin precio, unpriced, held at cost, pérdidas y ganancias, P/L, unrealised, plusvalía latente, peso, weight, demo, datos de demostración
---
How the Portfolio page values what you hold: the cost of each position, the currency everything is shown in, and what happens when a live price is missing.

## Cost basis and FIFO lots
The cost of a position on the Portfolio page is built from your ledger replayed in date order, in lots. As a general definition, a lot is one purchase; cost basis is what you paid for the shares you still hold. Each buy opens a lot whose cost is price times quantity plus the buy commission. When you sell, the app matches the sale against the oldest lots first (FIFO, first in first out), so the cost of the shares sold is what those oldest lots cost, and what remains keeps the cost of the newer lots. Sale proceeds are net of the sell commission. A stock split multiplies the shares in each open lot without changing the total cost. A return of capital lowers the cost of the shares it was paid on. Moving shares between your brokers is not a sale and changes no cost. The "Gained on sales" figure uses this FIFO matching.

## FIFO on the Portfolio page vs the tax report
The Portfolio page always values positions and its "Gained on sales" with FIFO, in your reporting currency. The Realized & tax tab is a separate calculation: it replays the same trades under the share-matching rule and currency of your tax jurisdiction, which can differ (for example last-in first-out, average cost or the UK's same-day, 30-day and pooled rules, and the jurisdiction's own currency). The two results are therefore not interchangeable unless your reporting currency, jurisdiction and matching rule coincide, such as a euro-reporting account taxed under FIFO.

## Reporting currency
The reporting currency is the currency in which TopStocks shows all your money: values, costs, gains, returns and weights. You choose it in Profile under "Reporting currency". The options are EUR (the default), USD, GBP, CHF, SEK, NOK, DKK, PLN, CZK, CAD and AUD. The app computes in that currency from the start: every trade is converted at its own date's rate when the ledger is replayed, rather than converting a final total at the end. Changing the reporting currency therefore recomputes the cost and gains, not just the labels.

## How foreign currencies are converted
When a trade is in a currency other than your reporting currency, TopStocks converts its amount (including the commission) at the European Central Bank (ECB) reference rate for the trade's date, served by the frankfurter service. Weekends and holidays use the previous published business day's rate. So the cost of a US stock bought in dollars is fixed in your reporting currency at the rate of the purchase day and does not change afterwards. The current value of a position is its latest price converted at the latest daily rate. Cost uses the trade-date rate and value uses today's rate, so the gain on a foreign position includes the currency move as well as the price move. UK prices quoted in pence are scaled to pounds first.

## Positions with no live price
A position is unpriced when no usable price could be found for it, for example because the price provider is throttling requests, does not know the symbol or a broker code has no alias yet. On the Portfolio page, the totals "what you paid" and "value today", and the unsold gain percentage, are taken only over the positions that have a price, on both sides, so an intact book is never shown with a false loss. The page says how many positions were left out ("Positions with no live price: n of total"). An unpriced position shows no value or gain of its own. The daily value history behind the charts and the return figures instead carries an unpriced position at its cost: no invented loss and no mark-to-market, and the names are listed in a note under the return charts.

## Weights when some prices are missing
The Weight column in the Positions tab is each position's share of the book's market value. When some positions have no price, the app does not drop them from the denominator, which would hand their share to the names that did price: they stay in the total at their cost. Their own weight shows empty, so the column may sum to less than 100%. The risk analysis on the Allocation & risk tab works differently: it builds the current-basket weights only from positions it could price in your reporting currency, and renormalises them. A name with no price or no exchange rate is left out of that analysis.

## Demo book
If your ledger is empty, the Portfolio page offers "Use demo transactions", which fills every tab with a demo book: seven well-known US stocks (AAPL, MSFT, NVDA, GOOGL, META, TSLA, NOW) with real prices and made-up trades, including a few sales, dividends and a custody fee. Demo rows are marked as demo and a banner says they are not yours. You can remove them with "Remove demo data". Your first real import (from the Import page or the chat) deletes them automatically, so invented lots never mix into your real cost basis. The demo can only be added to an empty ledger.
