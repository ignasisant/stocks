---
id: value-at-risk
path: returns
title: Value at risk (VaR): a "normal" bad day
minutes: 3
as_of: 2026-10-25
terms: var, confidence_level
app: portfolio?tab=risk
---
How much can I lose on a bad day? Value at risk (VaR) answers with a single number, as long as you remember what that number does not cover.

## The idea
The **1-day historical VaR at 95 %** is calculated from real daily returns in the past. They are sorted from worst to best, and you find the point that leaves the worst 5 % of days below it.

It reads like this: **"19 days out of 20 you do not lose more than X"**. And the 20th day can be worse.

The **confidence level** (here 95 %) is the share of days the VaR covers. At 99 % the figure would be larger, because it covers more bad days. It is "historical" because it assumes no formula: it uses what actually happened.

It needs enough history to be reliable: with only a few days the figure is shaky.

## An example
Your portfolio is worth €20,000 and its 1-day VaR at 95 % is 2 %.

- VaR in euros: 20,000 × 2 % = **€400**.
- Reading: on 19 days out of 20 you should not lose more than €400.
- A year has about 250 trading days. 5 % of that is about 12 or 13 days on which the loss **does** exceed €400.

Those days exist, and the VaR does not say how much they lose.

## What VaR does not tell you
- **It is not the worst case.** It is the threshold of the worst 5 %, not the floor. The bad day can be double or triple.
- **It ignores the tails.** Crises (March 2020, for example) concentrate extreme losses that a calm history does not show.
- **It is a snapshot of the past.** If the portfolio or the market changes, the number changes.
- **It covers a single day.** It does not say how much you can lose in a month.

## The common mistake
Reading "95 %" as "safe". It measures an ordinary bad day, not a crisis. Use it to calibrate your portfolio's daily pulse, and pair it with the maximum drawdown to see what can really hurt.
