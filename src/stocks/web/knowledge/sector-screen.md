---
id: sector-screen
title: How the Sector screen builds and ranks a cohort
as_of: 2026-10-11
step: sector
related: review-scoring
tags: Cribado por sectores, Sector screen, sectores, sectors, cohorte, cohort, ETF, XLK, pares, peers, no estadounidenses, non-US, las tres mejores, best three, podio, podium, ROIC, valoración, calidad, momentum técnico, technical momentum, RSI, MACD, calendario, calendar, resultados, earnings, ex-dividendo, ex-dividend, plazos fiscales, tax deadlines, Fed, BCE, ECB
---
The Sector screen (Cribado por sectores) compares companies inside one of eleven sectors, ranked against each other rather than against the whole market. It is a screen, not advice.

## How a sector cohort is built
Eleven sectors map to SPDR ETFs: XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB, XLRE, XLC.
- The cohort is the ETF's disclosed top 10 holdings (mostly US mega-caps) plus up to 8 non-US names per sector proposed by an AI model.
- Each proposed peer is checked against Yahoo, which must confirm the symbol exists and is filed under that sector. Invented or misfiled symbols are dropped, and funds are dropped. A cohort ends up at roughly 18 names.
- The scan runs nightly with a 5-second pause between sectors. If a sector's scan fails it keeps its previous cohort.
- "Refresh this sector" rescans one sector in the background, shared across users, capped at 4 per account per hour.

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

## The calendar
The Calendar page (Calendario) puts dated events in one place.
- Earnings dates for stocks you hold or watch (crypto and funds are skipped).
- Tax deadlines of your tax residence, flagged 30 days ahead.
- Ex-dividend dates: declared dates for shares you hold, plus last year's schedule projected over the next 52 weeks and marked projected. Each shows the cash expected after the withholding rate seen in your own statements.
- Repurchase-window days after a loss sale, where your jurisdiction has such a rule.
- Fed and ECB decision days, kept as static data.
