---
id: tax-engine
title: How the app's tax engine works (all countries)
as_of: 2026-10-11
tags: tax engine, motor fiscal, jurisdictions, jurisdicciones, tax residence, residencia fiscal, FIFO, LIFO, average cost, coste medio, S104, wash sale, superficial loss, regla de los dos meses, repurchase window, plusvalías, capital gains, harvest, tax-loss harvesting, compensar pérdidas, withholding, retención, doble imposición, deadlines, plazos, Realized & tax
---
The Realized & tax tab of Portfolio turns your ledger into a realized gain or loss per sale and an estimated tax bill under the rules of one country. It is a planning aid, not tax advice.

## Which countries are modelled
The app models twelve tax residences: Spain, United States, Germany, United Kingdom, France, Italy, Ireland, Portugal, Canada, Australia, United Arab Emirates and Switzerland. The UAE and Switzerland are modelled to say that a private investor's capital gains are not taxed there (0%, and losses are not deductible or carried forward). Other countries are not modelled. If your residence is not on the list, the tab still applies one of the modelled countries' rules (Spain's by default) and shows a warning saying the figures are borrowed law, almost certainly not what you owe.

## How your tax residence is chosen
You set it in Profile, under "Where you file". A residence you pick there always wins. If you leave it on "Auto (browser region)", the app uses the region of your browser's language (for example en-US means the United States) when that country is modelled. If the browser names a country that is not modelled, the app falls back to Spain and warns you. If the browser gives no region at all, it uses Spain without a warning. Profile also shows extra inputs only where the country's rates need them: filing status, other taxable income, a US NIIT switch, German church tax rate, or a Canadian provincial rate. Spain asks for none.

## Share-matching methods by country
Which shares a sale is deemed to have sold changes the gain, so the app replays your ledger under each country's rule.
- FIFO (oldest shares first): Spain, United States (broker default when no lots are identified), Germany, Ireland, Portugal, Australia, and also UAE and Switzerland as a bookkeeping convention.
- LIFO (newest shares first): Italy.
- Average cost (one averaged holding per security, recomputed on each purchase): France and Canada.
- UK Section 104: same-day purchases first, then purchases in the 30 days after the sale, then the pooled average cost.
A cost basis under average or S104 is never one lot's own purchase price.

## Currency and commissions
The ledger is replayed in the jurisdiction's own currency, not your reporting currency: EUR for Spain, Germany, France, Italy, Ireland and Portugal; USD, GBP, CAD, AUD, AED and CHF for the others. Each purchase and sale is converted at the rate of its own trade date. Purchase commissions are added to the cost of the shares and sale commissions are subtracted from the proceeds, so fees reduce your taxable gain automatically.

## Repurchase windows (wash sale rules)
Several countries deny or defer a loss if you buy the same security back close to the sale. The app applies these windows by ticker (same ticker counts as the same security):
- Spain: two months before or after the sale.
- United States: 30 days before or after.
- Canada: 30 days before or after (superficial loss).
- Ireland: 28 days after the sale only.
- UK: no separate rule; the 30-day matching in the S104 replay does the job.
- Germany, France, Italy, Portugal, Australia, UAE, Switzerland: no repurchase rule is applied.
In every case the loss is deferred, not lost: it comes back when the replacement shares are sold. A buy-back of fewer shares than you sold defers only that proportion of the loss.

## Dividends, withholding and the Spanish credit
The Dividends tab lists dividends from your ledger. For each dividend, the ledger holds the gross amount and the tax withheld at source; the net is the difference. The columns Withheld, Creditable and Reclaimable apply the Spanish double-taxation rule: foreign withholding is creditable up to 15% of the gross dividend, and any excess is shown as reclaimable from the source country. This 15% cap is built in for the Spanish treatment and is not switched per country. Some statements (Revolut's CSV, for instance) do not report withholding, so it shows 0 there.

## Tax-loss harvesting and the buy-back date
When you ask the assistant how to offset gains, or when the Home briefing flags it, the app lists open positions that are more than 150 currency units under their cost. For each candidate it replays the ledger as if you sold the whole holding today and reports the change in this year's estimated tax, plus all candidates sold together and any net loss left to carry forward. Where the country has a repurchase window, it also gives the first day you can buy the security back without the loss being deferred: two months, 30 days or 28 days after the sale, plus one day. The Home briefing also reminds you when such a window is about to end. On the earnings calendar (and the Home calendar card), every day from a loss sale up to that first free day is shaded amber, and the free day itself carries an amber outlined chip; countries with no repurchase rule show neither.

## Reporting flags and the tax calendar
Some countries require informative declarations of assets held abroad. The app shows a flag when the value of your book crosses the country's threshold, such as Modelo 720 in Spain, FBAR and Form 8938 in the US, or T1135 in Canada. A flag means the threshold is crossed, not that you must file: that depends on where the assets are actually custodied, which the ledger cannot see.
The earnings calendar also lists each country's statutory filing dates (Spain's renta and Modelo 720, the US 1040, UK Self Assessment, and so on), with a reminder in the 30 days before. Dates that fall on a weekend are moved to Monday in the countries where the law does so; public holidays are not modelled.

## Rates and rules by country: Americas and Europe
- United States: federal only. Lots held more than a year are long-term (0/15/20%), the rest short-term at ordinary rates, plus NIIT if enabled in Profile. No state tax, no AMT. Net losses deduct $3,000 a year from ordinary income ($1,500 filing separately), carry forward indefinitely and keep their short/long character.
- Canada: half of the net capital gain is taxable at your marginal rate (federal brackets plus the provincial rate set in Profile). Cost is the adjusted cost base, one average per security. A superficial loss (repurchase within 30 days) is added to the ACB of the replacement shares. No AMT or provincial surtaxes.
- Germany: Abgeltungsteuer 25% plus 5.5% solidarity surcharge on that tax (26.375% total), plus church tax at the Profile rate. Share losses only offset share gains; fund and other losses offset any capital income; the two loss pools carry forward separately and indefinitely. 30% of an equity fund's result is exempt. The Günstigerprüfung against the progressive scale is not applied.
- United Kingdom: CGT 18% inside the remaining basic-rate band and 24% above it (rates from 30 October 2024), after the £3,000 Annual Exempt Amount. Losses come off before the allowance, so a loss year can waste it. Tax year 6 April to 5 April. Brought-forward losses only reduce later gains down to the allowance, which the app does not apply for you.
- France: PFU flat 30% (12.8% income tax plus 17.2% social charges), no allowance. Losses (moins-values) carry forward 10 years against gains of the same nature only.
- Italy: imposta sostitutiva 26% on the year's saldo, LIFO matching (art. 67 TUIR); losses carry forward four years then expire. Quadro RW applies to foreign securities at any value (the 15,000 EUR exemption is for bank accounts) and IVAFE is 0.2% of the value a year.
- Ireland: CGT 33% after the 1,270 EUR personal exemption; a loss on shares reacquired within four weeks is restricted until those are sold; share losses carry forward indefinitely. Irish and EU funds are exit tax 41%, no exemption, losses not allowable. US-domiciled ETFs are CGT; the app cannot tell domiciles apart.
- Portugal: IRS 28% on the year's saldo, FIFO, no allowance. Gains on holdings under 365 days are aggregated with other income once it reaches the top bracket (48% marginal, solidarity surcharge excluded). Losses carry forward five years only if you opt for englobamento.

## Rates and rules by country: Australia, UAE and Switzerland
- Australia: net capital gain is ordinary income at your marginal rate plus 2% Medicare levy. Assets held over 12 months get a 50% discount; losses come off gross gains first, applied to non-discounted gains first to keep more discount. Income year 1 July to 30 June. No levy surcharge or tax offsets.
- UAE: no personal income tax or capital gains tax for an individual, at any size or holding period; the tab is a record, not a bill. Figures are in AED through the fixed 3.6725 peg to the dollar. The planning aid assumes personal holding and UAE residence all year; a previous residence may still tax the year you left, and a licensed entity is a different filer.
- Switzerland: art. 16 para. 3 DBG leaves a private investor's capital gains out of taxable income at federal, cantonal and communal level. The exemption holds while you stay inside circular KS 36: positions held 6 months or more, turnover under 5x the portfolio, gains under half your net income, no borrowed money, no speculative derivatives. Not in the figures: the cantonal wealth tax (year-end value, 31 December, listed in the Wertschriftenverzeichnis), dividends as ordinary income and the 35% Verrechnungssteuer. Verify with a Treuhänder.
- Spain: see tax-spain. IRPF savings base 19-28%, FIFO (art. 37 LIRPF); broker allocation on the Portfolio page is informational, tax figures stay FIFO across all brokers.
- If your browser region is not modelled, the Realized & tax tab shows another country's rules applied to your book as a stand-in, which is almost certainly not what you owe; pick your residence in Profile if it is modelled.
