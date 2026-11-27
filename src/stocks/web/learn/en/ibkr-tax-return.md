---
id: ibkr-tax-return
path: tax-es
title: Declaring Interactive Brokers on your Spanish tax return
minutes: 5
as_of: 2026-11-27
terms: tax_return, fx_conversion, withholding_tax, form_720, fifo
app: import
slug: declare-interactive-brokers-spanish-tax
description: Which report to ask Interactive Brokers for, how to convert each trade to euros, where to see dividend withholding, and when form 720 applies. With an example.
---
Interactive Brokers (IBKR) gives you more data than almost any other broker, but not in the format the Spanish return needs. These are the steps.

## What to download
In Client Portal, under Performance & Reports, generate an **Activity Statement** for the whole period, or a **Flex Query** with trades, dividends and withholdings, as CSV. Ask from your first purchase: **FIFO** needs the price of every purchase to know which shares you sold.

IBKR is not a Spanish broker and does not report to the Spanish tax agency for you: **you declare**.

## What the report does not do for you
- **Several currencies.** You will trade in dollars, euros or pounds depending on the market. Each purchase and sale is converted to euros at **that date's exchange rate**, not the year-end one. IBKR also shows a result in the account's base currency: that is not the figure you declare.
- **Dividends and withholding apart.** The report splits the gross dividend from the tax withheld at source. The return takes the **gross**, and what was withheld abroad is recovered through the **double-taxation deduction**, up to the limit each country's treaty sets.
- **The cost method.** The report summarises results by its own rules. In Spain shares are sold by **FIFO**, and the **two-month rule** can block losses the report counts as good.
- **Fees.** They add to the cost of a purchase and subtract from the value of a sale.

## An example
You buy 10 shares at $150 ($1,500) with the euro at 1.10: they cost **€1,363.64**. You sell at $165 ($1,650) with the euro at 1.20: you receive **€1,375.00**. The gain you declare is **€11.36**, not the 10 % you see in dollars.

## Form 720
Your securities are held outside Spain. If their value, added to your other foreign accounts and assets, is over **€50,000** on 31 December, file **form 720** by 31 March.

## The typical mistake
Copying the realised result in base currency from the report, or the total of net dividends. Neither is the figure the tax agency asks for.

MyBrainStock imports the IBKR report and does these calculations: FIFO, euros at each date's rate, the two-month rule, and the gross of each dividend with its withholding. It helps you prepare the return; it is not tax advice, so if your case is complex, ask an adviser.
