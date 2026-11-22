---
id: sector-screen
title: How the Sector screen builds and ranks a cohort
as_of: 2026-11-20
step: sector
related: review-scoring
tags: Cribado por sectores, empresas pequeñas, small caps, crece rápido, fast grower, tamaño, size, capitalización, market cap, Sector screen, sectores, sectors, cohorte, cohort, ETF, XLK, pares, peers, no estadounidenses, non-US, las tres mejores, best three, podio, podium, ROIC, valoración, calidad, momentum técnico, technical momentum, RSI, MACD, calendario, calendar, resultados, earnings, ex-dividendo, ex-dividend, plazos fiscales, tax deadlines, Fed, BCE, ECB
---
The Sector screen (Cribado por sectores) compares companies inside one of eleven sectors, ranked against each other rather than against the whole market. It is a screen, not advice.

## How a sector cohort is built
Eleven sectors map to SPDR ETFs: XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB, XLRE, XLC.
- The cohort is the ETF's disclosed top 10 holdings (mostly US mega-caps) plus up to 8 non-US names per sector proposed by an AI model.
- Each proposed peer is checked against Yahoo, which must confirm the symbol exists and is filed under that sector. Invented or misfiled symbols are dropped, and funds are dropped. A cohort ends up at roughly 18 names.
- The scan runs nightly with a 5-second pause between sectors. If a sector's scan fails it keeps its previous cohort.
- "Refresh this sector" rescans one sector in the background, shared across users, capped at 4 per account per hour.

## Small companies growing fast
Beside the cohort, each sector lists up to 8 smaller companies growing fast, found by a Yahoo screen every night: market cap between $300 million and $10 billion, revenue up more than 15 % over the last year, revenue above $100 million and a positive EBITDA margin, fastest growth first.
- Five come from the main US exchanges (no OTC), the rest from the main European ones; a European line of a US company and preferred shares are left out.
- They sit in the cohort table marked "Fast grower" but are not scored: the podium, the ranking, the peer medians and the cohort count are the same as without them.
- The table shades their figures by where they would fall in the cohort, without recolouring the cohort's own cells. The quality-against-price map places them too, against the same fixed bars as every other name.
- A name that has grown past $10 billion leaves the list at the next scan. If the screen fails, last night's names are rescanned.
- Size chips filter the table by market cap in dollars: small under $2 billion, mid up to $10 billion, large above. A name whose size is unknown hides when a size is picked. A chip shows only the fast growers.
- It is a screen for names to look at, not a forecast: fast past growth says nothing certain about the next years.

## Valuation and quality ranking
The first podium ranks cohort members on 18 KPIs by percentile within the cohort, so it names the best three of these, not the best anywhere.
- Lower is better (8): trailing P/E, forward P/E, PEG, P/B, EV/EBITDA, EV/sales, net debt/EBITDA, share dilution.
- Higher is better (10): ROE, ROIC, gross margin, operating margin, net margin, FCF yield, cash conversion, revenue CAGR, net income CAGR, FCF CAGR.
- Each company is ranked only on the KPIs its kind of business is judged by, as in Sell or add: banks, insurers and asset managers skip EV/EBITDA, EV/sales, margins, FCF, ROIC, net debt and PEG; REITs and regulated utilities skip FCF, ROIC, gross margin, EV/sales and PEG.
- A multiple at or under zero (EV/EBITDA on a loss, P/B on negative equity) does not count; a loss-making P/E ranks last. PEG is the app's own P/E per sustained sales growth per share, not Yahoo's.
- A KPI counts only when at least 2 names report it, and a company needs at least 5 ranked KPIs to be scored. Its score is the average of its normalised ranks (best 1, worst 0, ties share).
- With fewer than 3 qualifying companies there is no podium.
- It measures neither momentum nor analyst expectations.
- The cohort table defaults to ordering by ROIC, with filters, column choices and a CSV download.

## Technical momentum ranking
"Best three on technical momentum" is a separate podium that ignores valuation entirely. It uses one year of price history pulled for the whole cohort at once.
- Six signals, all higher-is-better: trend (SMA50 against SMA200), RSI(14), MACD histogram, distance from the 1-year high, 63-session return, and volume ratio (20-day against 90-day average volume).
- A ticker needs at least 4 of the 6 signals to be ranked.
- If the price pull fails, only the technical podium is lost.

## The written verdict
Under the podium, "What the screen says" is written by the assistant against tonight's scan and checked figure by figure. Generating it costs one unit of the free allowance; simply opening the page never spends anything. If no model answers, a free computed summary is shown instead. It is stored per sector, scan date and language.

## Buy the whole sector: ETFs and funds
"Buy the whole sector" lists curated vehicles that hold the sector, for a reader who would rather own all of it than pick a podium name.
- UCITS ETFs: a world, a US and a Europe one where they exist (Xtrackers, iShares). Europe's financials ETF holds banks only and is tagged so.
- A mutual fund where one fits, tagged **Traspasable** for Spanish tax residents: a switch between funds carries the gain over untaxed, while leaving an ETF is a taxable sale.
- One row per vehicle, the figures in columns (stacked with their own labels on a phone): TER; purity (the share of its sector split that is this sector; under 60 % it is left out); how much of it is the page's cohort; returns.
- "Its ten largest" is a bar: the ten disclosed lines in weight order, podium names in purple, the page's other companies solid grey, companies the page does not rank hatched, the undisclosed rest left empty. Under it, "Podium:" names the podium companies the fund holds, with their weight.
- The chevron opens the ten lines (share classes summed) with their weights, the sum of the top ten and top three, and the podium names outside its ten largest ("not in its top 10", never 0 %).
- Yahoo discloses only the ten largest lines of a fund, so every overlap is a floor.
- Returns are in the reader's currency, dividends included (adjusted closes): from the book's first day, or from the fund's own first price when it starts later (said so; Morningstar fund prices start in March 2022), and over the last year. A series that cannot be converted shows no figure. A guest sees the year only.
- Profiles are refreshed nightly (`stocks sector-funds`); a fund Yahoo does not answer keeps last night's profile.
- "You in this sector" also says how much of the book sits in the sector through the funds it holds (look-through of each fund's sector split), fund by fund.

## The calendar
The Calendar page (Calendario) puts dated events in one place.
- Earnings dates for stocks you hold or watch (crypto and funds are skipped).
- Tax deadlines of your tax residence, flagged 30 days ahead.
- Ex-dividend dates: declared dates for shares you hold, plus last year's schedule projected over the next 52 weeks and marked projected. Each shows the cash expected after the withholding rate seen in your own statements.
- Repurchase-window days after a loss sale, where your jurisdiction has such a rule.
- Fed and ECB decision days, kept as static data.
