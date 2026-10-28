---
id: fifo
path: tax-es
title: FIFO: which shares count as sold
minutes: 4
as_of: 2026-10-25
terms: fifo, cost_basis, lot
app: portfolio?tab=tax
---
You bought the same stock several times at different prices. When you sell only part of it, which of those purchases are you selling? The answer decides how much tax you pay.

## The idea
Each purchase is a **lot**: a number of shares with their own price. If you buy 10 shares today and 10 next month, you hold two lots.

In Spain, for homogeneous securities (those of the same company), the law requires **FIFO** (*first in, first out*): the oldest shares are treated as sold first. You cannot pick the most convenient lot.

The **cost basis** (coste de adquisición) is what each lot cost you **including purchase commissions**. When you sell, the selling commission is subtracted from what you receive. So commissions reduce your taxable gain.

## An example
- Purchase 1: 10 shares at €100 + €5 commission = **€1,005** cost.
- Purchase 2: 10 shares at €120 + €5 commission = **€1,205** cost.
- Sale: 15 shares at €130 = €1,950, minus €6 commission = **€1,944** net.

Under FIFO, the sale uses all of lot 1 (10 shares) and 5 from lot 2:

- Lot 1 cost: €1,005
- Cost of 5 shares from lot 2: €1,205 × 5 / 10 = €602.50
- Total cost: €1,607.50

Gain: 1,944 − 1,607.50 = **€336.50**.

You are left with 5 shares at a cost of €602.50 (€120.50 each). When you sell them, you start from that cost, not from an average price.

## The common mistake
Calculating with the **average price**. Here it would be 2,210 / 20 = €110.50 per share, a cost of €1,657.50 for 15 shares and a gain of €286.50. It looks more convenient, but in Spain it is not valid for securities: the tax office requires FIFO.

Another slip: using only the share price and forgetting commissions. And if you trade through several brokers, FIFO applies across all your shares of that company together, not broker by broker.
