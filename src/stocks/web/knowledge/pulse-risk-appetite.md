---
id: pulse-risk-appetite
title: How the Market pulse page reads risk appetite
as_of: 2026-10-11
step: pulse
related: returns-and-risk
tags: Pulso de mercado, Pulso, Market pulse, apetito de riesgo, risk appetite, Tensión, Cautela, Neutral, Apetito, Euforia, stress, caution, euphoria, amplitud, breadth, volatilidad, VIX, crédito, credit spread, correlación bolsa-bonos, stock bond correlation, régimen de tipos, rates regime, bear steepening, bull flattening, beta, tu cartera contra este régimen, rotación, sectores, inflación
---
The Market pulse page (Pulso de mercado) condenses market conditions into one 0-100 Risk appetite score, then shows what sits behind it and how your own book would react. It is a relative reading of the last year, not an absolute one, and not advice.

## The risk appetite score and its bands
The score on the Market pulse page is the average of its live inputs, each already converted to 0-100. Each input is turned into a percentile rank over its own trailing 252 sessions (at least 60 periods needed), inverted where a high reading means fear. So 80 means "more risk-on than most of the past year", not an absolute level.
- Under 20: Stress (Tensión). 20-40: Caution (Cautela). 40-60: Neutral. 60-80: Appetite (Apetito). 80 and over: Euphoria (Euforia).
- The page also shows how many consecutive sessions the score has stayed in its band.
- Sources: Yahoo Finance, FRED (published about a day late) and Eurostat.

## The eight inputs
Each of these feeds the score equally.
- Trend (Tendencia): S&P 500 distance from its 125-session average.
- Breadth (Amplitud): RSP/SPY (equal-weight against cap-weight), 20-session change.
- Volatility (Volatilidad): VIX level, inverted.
- Vol term structure (Estructura de plazos): VIX3M divided by VIX. Below 1 is backwardation, meaning hedging costs more now than later.
- Credit (Crédito): the FRED high-yield option-adjusted spread, inverted. If FRED is unavailable it falls back to the HYG/IEF ratio.
- Stocks vs bonds (Bolsa frente a bonos): SPY 20-day return minus TLT 20-day return.
- Junk demand (Apetito por bono basura): HYG/LQD, 20-session change.
- Emerging markets (Mercados emergentes): EEM/SPY, 20-session change. The only non-US read.

## Month-ago pin, missing inputs and freshness
On the score gauge the white pin is today and the grey ghost pin is a month ago. In the "Why: the eight inputs" panel each bar is today's score for that input and its tick is where it stood 21 sessions earlier.
- A lagging input is carried forward at most 5 sessions, then dropped.
- A score is quoted only when at least 4 inputs are live. Otherwise the pin parks mid-scale and shows n/a.
- The page says "quoted on N of 8 inputs" and names the missing ones. The history line is the daily average of the live inputs, and the as-of date is the last day that had enough inputs.

## Breadth and stock/bond correlation
- Indices in uptrend: how many of 13 indices (S&P 500, Nasdaq Composite, Dow, Russell 2000, Euro Stoxx 50, DAX, IBEX 35, CAC 40, FTSE 100, Nikkei 225, Hang Seng, MSCI ACWI, emerging markets) trade above their own 200-session average.
- Sectors in uptrend: how many of the 11 SPDR sector ETFs sit above their 100-session average.
- A name without enough history is left out of both counts.
- Stock/bond correlation: 60-session rolling correlation of SPY and TLT daily returns, shown with its value a quarter (63 sessions) earlier. Positive means stocks and bonds are falling together, so bonds are not cushioning equities.

## Rates regime
The Rates regime card places the market in one of four quadrants from two 63-session (quarter) changes: the US 10-year yield (FRED DGS10) and the 2s10s slope (T10Y2Y). Yield up is bear, down is bull. Slope up is steepening, down is flattening.
- Bear steepening: the long end is selling off faster, often growth or supply worries.
- Bear flattening: inflation or a central bank running late.
- Bull steepening: cuts are being priced.
- Bull flattening: a growth scare, with demand for duration.
A Chicago Fed financial conditions index (NFCI) note shows its 3-month change; below zero means looser than average.

## Your book against this regime
Signed in with holdings, the page measures how your current weights would have behaved against market factors over roughly the last 12 months. Signed out or with an empty book it shows no invented numbers.
- Betas: equity beta against the S&P 500, plus betas to TLT (duration), HYG (credit) and EEM (emerging markets). Each shows a rolling 60-session value and its 3-month drift.
- Stance on equity beta: above 1.05 amplifies the market, below 0.95 cushions it, otherwise tracks it closely.
- Basket correlation with long bonds, now and 3 months ago.
- USD share of your value, and the FX drag: last month's USD move against your base currency as a contribution to value. US names in a EUR book are an unhedged short-EUR position.
- Rotation capture: your sector-weighted excess return against SPY over 21 sessions.
- Sector tilt: your sector weights minus SPY's; a sector you do not hold counts as 0.

## Detail tables: indices, volatility, rates, inflation
Below the story the page lists detail tables. Each row shows the level, changes over a week (5 sessions), month (21), quarter (63) and year (252), a 90-session sparkline and a trend state. Each table loads independently, so one can fail without the others.
- Indices, ordered by your country weights, with "% of your book trades here".
- Volatility gauges: VIX, VXN, VVIX, MOVE, OVX, GVZ, SKEW, with percentile in their own year and a month ago. A gauge more than 7 days behind is flagged stale.
- Rates and credit: US 10y, 10y real, curves 2s10s and 3m10y, HY and IG spreads, 5y breakeven, Fed funds, ECB deposit, NFCI. Changes in basis points; curves and policy rates are uncoloured.
- Inflation by country: euro area, Spain, Germany, France, Italy, Netherlands, Portugal (Eurostat HICP) and the US (CPI from FRED), headline and core, with momentum against 6 months ago (annual rate now minus six months ago, in points; not an annualised 3-month rate, because Eurostat HICP is not seasonally adjusted).

## Rotation, factor and cross-asset tables
- Rotation: 11 sector ETFs, excess over SPY, your weight and tilt.
- Factor pairs: IVW/IVE (growth vs value), IWM/SPY, RSP/SPY, SPY/ACWX, XLY/XLP, XLK/SPY.
- Cross-asset: DXY, EUR/USD, gold, silver, WTI, copper, Bitcoin, Ethereum.

## Trend state
- Trend state compares the level with its 100-session average and the slope of its 20-session average: up, turning down, turning up or down. Under 100 sessions of history it is unknown.
