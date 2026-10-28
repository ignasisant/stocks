---
id: order-types
path: start
title: Order types: market, limit and stop
minutes: 4
as_of: 2026-10-25
terms: market_order, limit_order, stop_order, bid_ask_spread, liquidity
app: ticker
---
When you buy or sell you choose not only what and how much, but also how. The order type decides the price you may end up trading at.

## The idea
Every security has two prices at once: the **bid** (what someone will pay now) and the **ask** (what someone is asking now). The difference is the **spread**. For heavily traded stocks it is cents; for thinly traded ones, large.

**Liquidity** is how easily you can buy or sell without moving the price. With high volume the spread is narrow. With low volume it is wide.

Three basic orders:

- **Market**: buy or sell now, at the best price available. It almost surely executes, but the price is not guaranteed.
- **Limit**: you set a maximum price to buy or a minimum to sell. You control the price, but it may not execute.
- **Stop** (stop-loss): an order that activates when the price touches a level. Used to limit losses. Once triggered it usually becomes a market order.

## An example
A stock trades with bid €9.98 and ask €10.02.

- The spread is €10.02 − €9.98 = **€0.04**, 0.4 % of €10.00.
- If you buy at market you pay €10.02. If you sell at market right after, you get €9.98. That 0.4 % is a cost of getting in and out.

Now a thinly traded stock with an ask of €10.02 but only 100 shares available at that price. You want 1,000. A market order would keep buying at higher prices until filled. A **limit at €10.05** buys only up to that price: you end up with fewer shares, but never pay more than planned.

## The common mistake
Using market orders on illiquid stocks or outside trading hours. The price you see is not the price you get.

With stops, a frequent error is placing them too close: normal movement triggers them and you sell too early. And if the price jumps (a *gap*), a stop can execute well below the level you set.
