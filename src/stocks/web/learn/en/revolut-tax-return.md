---
id: revolut-tax-return
path: tax-es
title: Declaring Revolut shares on your Spanish tax return
minutes: 5
as_of: 2026-10-31
terms: tax_return, fx_conversion, withholding_tax, form_720
app: import
slug: revolut-spain-tax-return
description: What to download from Revolut, how to convert each trade to euros, why dividends arrive net, and when Form 720 applies. For Spanish tax residents.
---
Revolut lets you buy shares in two taps, but the tax return is on you. These are the steps to get your trades into your Spanish return without missing anything.

## What to download
In the Revolut app, in the investing section, find the documents and download the **trading account statement** as a CSV. Ask for the full period, from your first purchase, not just last year: to know which shares you sold, **FIFO** needs the price of every purchase, even years back.

Revolut is not a Spanish broker, so do not assume the tax office has your trades: **check your tax data** and the draft return. Anything missing, you add yourself.

## What the statement does not do for you
- **It is in dollars.** Every purchase and every sale is converted to euros at the **exchange rate of its own date**, not the 31 December rate. The statement carries the rate Revolut applied; the usual reference is the one the ECB publishes.
- **Dividends arrive net.** The statement amount already has US withholding taken off (15% if you signed the W-8BEN when you opened the account). The return takes the **gross** amount, and what was withheld abroad comes back through the **double taxation deduction**.
- **Splits do not carry the ratio.** The statement records the shares you received, not the ratio. Correct the price of your earlier purchases or FIFO will get the cost wrong.

## An example
You buy 10 shares at $150 ($1,500) with the euro at $1.10: they cost you **€1,363.64**. You sell them at $165 ($1,650) with the euro at $1.20: you receive **€1,375.00**.

In dollars you made 10%. In euros, the gain you declare is only **€11.36**, because the dollar got cheaper while you held the shares. With the wrong rate you would declare far more than you made.

## Form 720
Your shares are held outside Spain. If their value exceeds **€50,000** on 31 December, file **Form 720** by 31 March. If you also hold crypto at Revolut above that threshold, look at Form 721.

## The typical mistake
Copying the dollar profit the app shows, or the total dividends received. Both figures are wrong for the tax office: the first is not in euros and the second is net.

TopStocks imports the Revolut CSV and does these calculations: FIFO, euros at each date's rate, the two-month rule, and each dividend's gross with its withholding. It is a help for preparing your return, not tax advice: if your case is complex, ask an adviser.
