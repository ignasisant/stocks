---
id: tax-spain
title: Spanish tax (IRPF) as the app computes it
as_of: 2026-10-11
step: tax
related: tax-engine, cost-basis-and-currency
tags: IRPF, base del ahorro, tramos, savings base, brackets, regla de los dos meses, two-month rule, norma antiaplicación, art. 33.5.f, compensar pérdidas, pérdidas diferidas, carry forward, Modelo 720, Modelo 721, Hacienda, campaña de la renta, FIFO, retención dividendos, doble imposición, plusvalías
---
For a Spanish tax resident, the Realized & tax tab in Portfolio computes the IRPF savings base (base del ahorro) on your securities sales, in euros. It is a planning aid, not tax advice.

## Savings base brackets
The app taxes the net result of each year's sales with that year's marginal brackets. From 2025:
- first 6,000 EUR: 19%
- 6,000 to 50,000 EUR: 21%
- 50,000 to 200,000 EUR: 23%
- 200,000 to 300,000 EUR: 27%
- above 300,000 EUR: 30%
Earlier years use their own scale: 28% above 300,000 EUR in 2023 and 2024; 26% above 200,000 EUR in 2021 and 2022; 23% above 50,000 EUR before that.
The estimate ignores your other income and regional specifics. The tax year is the calendar year. Spain's savings base has no filing status or other inputs, so Profile asks for none.

## How gains are calculated
Sales are matched FIFO: the oldest shares you bought are sold first (art. 37 LIRPF). All amounts are in euros, each purchase and sale converted at the ECB rate of its own date. Purchase commissions are added to the cost and sale commissions are subtracted from the proceeds. The tax year's net result is the realized gains minus the deductible losses, minus any previously deferred losses that become deductible this year. The Realized & tax tab also has a monthly view, but that is only a breakdown of when results were booked; IRPF nets the whole year.

## Two-month rule (regla de los dos meses)
Under art. 33.5.f, a loss on a sale is not deductible in the year if you bought the same security (same ticker in the app) in the two months before or after the sale. The app checks purchases from two calendar months before to two calendar months after the sale date, counting only shares bought after the lot you sold. Only as many shares as were bought back are affected: selling 100 at a loss and buying 10 back defers a tenth of the loss. The tab shows the amount as "deferred (2-month rule)".
The loss is deferred, not lost. When the replacement shares are later sold, the deferred loss becomes deductible in that sale's year and appears as "recovered from earlier deferrals".

## Listed versus unlisted securities
The app implements only the two-month window of the repurchase rule. It does not distinguish listed from unlisted securities and has no one-year window: every security is checked against the two-month window, by ticker. If you sold unlisted shares at a loss, check the applicable window with an adviser.

## Loss offsetting and carry-forward
Within a year, losses are netted against gains in the savings base. If the year's net result is negative, the Tax tab shows the amount as a carry-forward loss, which the help text describes as usable against gains in the next 4 years. The app shows this figure and a note, but does not automatically apply a loss from one year against the gains of the next. The 25% cap on offsetting capital losses against dividend and interest income (the cross-offset between the two savings-base buckets) is not implemented: the app nets the sales of securities only.

## Dividends and foreign withholding
Dividends belong to the savings base in Spanish law, and the renta calendar note says gains, losses and dividends go there. However, the tab's estimated tax is computed from realized sales only; dividends are not added to the base the brackets are applied to. The Dividends tab shows, per year, the gross dividend, the tax withheld at source, the creditable part (the lower of the withholding and 15% of the gross, the usual treaty cap) and the reclaimable part: withholding above 15%, to be claimed from the source country. Where your statement does not report withholding, it shows 0.

## Modelo 720, Modelo 721 and deadlines
Portfolio shows a Modelo 720 flag when the value of your whole book is 50,000 EUR or more. The app cannot see where your broker holds the securities, so this is only a flag: Modelo 720 may apply if you hold them through a non-Spanish broker. A Spanish broker reports for you. The flag measures the total book value in euros, not just foreign assets.
The earnings calendar lists these Spanish dates, with a reminder in the 30 days before, moved to the next Monday if they fall on a weekend:
- Modelo 720 and Modelo 721 (crypto held with foreign custodians): 31 March.
- Renta (IRPF campaign close): 30 June.
- Renta second instalment, if you split the payment: 5 November.
The 720 and 721 notes mention the 50,000 EUR threshold on 31 December of the previous year.

## Verify with an adviser
The brackets, the 4-year carry-forward, the two-month window and the 50,000 EUR Modelo 720 line are the engine's current parameters, labelled 2023-2025 for the brackets. Tax law changes and the app is a planning aid, not tax advice. It does not model regional rules, other income, the 25% cross-offset, a longer window for unlisted securities, or dividends in the estimated bill. Verify your figures with an asesor fiscal or gestor before filing.
