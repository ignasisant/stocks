---
id: review-scoring
title: How the Sell or add page scores holdings
as_of: 2026-10-14
step: review
related: sector-screen, tax-engine
tags: Vender o reforzar, no hacer nada, mantener la cartera, stay put, dinero nuevo, new money, decisión ajustada, close call, coste fiscal de vender, fondo de comercio, goodwill, trampa de valor, value trap, margen en máximos, ciclo, margen de seguridad, deuda, PEG, P/E por crecimiento, barato para su crecimiento, Sell or add, review, calidad, quality score, precio, valoración, price score, cheapness, vender, sell, recortar, trim, mantener, hold, reforzar, add, comprar, buy, vigilar, watch, descartar, pass, apuesta, bet, sin valorar, unrated, FCF yield, rentabilidad por flujo de caja libre, concentración, peso, riesgo, país, moneda, divisa, fondos indexados, liquidez, impuesto, ventana de recompra, mapa calidad precio, target weight, bancos, banks, aseguradoras, REIT, SOCIMI, utilities, dividendo, dividend yield, payout, ROE, P/B, valor en libros
---
The Sell or add page (Vender o reforzar) gives every holding two 0-100 scores, one for the business and one for its price, and turns them plus the position's size into a verdict. It is a screen over your own records and public fundamentals, not advice.

## Quality and price scores for a mature business
On the Sell or add page, a mature company gets a Quality score and a Price score, both 0-100. Each is the plain average of its inputs, and a score needs at least two inputs, otherwise the name is Unrated rather than guessed.
- Quality averages ROIC (0% scores 0, 40% scores 100; the better of ROIC and ROIC on capital net of acquired goodwill, so a company that grew by buying others is not sunk by the price it paid), operating margin (0% to 40%), free-cash-flow yield (-2% to 4%, used only as "does it make cash") and the moat score as it is. If sales still grow 20% or more a year, the rule of 40 (growth plus FCF margin, 0% to 60%) joins as a fifth input.
- Price averages forward P/E (8 scores 100, 40 scores 0, a forecast loss scores 0), FCF yield (0% to 10%) and EV/EBITDA (8 scores 100, 50 scores 0). Higher Price means cheaper.
- Without analyst estimates (common for European small caps) the last twelve months' P/E stands in for the forward one, and the row says "trailing P/E". When the feed gives fewer than two price readings, price to book (1x scores 100, 4x scores 0) joins and the row says "priced on book".
- A dividend yield of 3.5% or more joins Price (1% scores 0, 6% scores 100, so it only joins where it reads cheap). Under 3.5% it is left out, so a 2% payer is not priced dearer than a company that reinvests or buys back instead. A yield of 4% or more is named on the row; it never decides a verdict alone.
- The forward P/E counts as the better of itself and its growth-adjusted reading: P/E per point of sustained sales growth per share (a PEG on the app's own growth, net of share dilution so a company issuing shares gets less credit and one buying back gets more, capped at 40%, never the feed's PEG; shown as "P/E per growth"), where 0.5x scores 100 and 2.5x scores 0 (1x scores 75). A slow grower is not marked down; a fast one gets credit. At 1x or under the row says "cheap for its growth".
- 60 or more on Quality is good; under 45 is weak. 50 or more on Price is cheap; under 30 is expensive.
- The moat score (0-100, wide at 70+, narrow 45-70, none under 45) weighs persistent ROIC 35%, steady operating margins 25%, cash conversion 20%, durable growth 15% and no dilution 5%; it is a screen, not a verdict.
- Growth is the sustained pace: the lower of the last quarter against a year earlier and the multi-year rate.

## Warning flags that block Add and Buy
On the Sell or add page, good scores are not enough when the numbers behind them may not hold. Any of these flags keeps a name at Hold or Watch, and the row names it. They only ever stop an Add or Buy, never cause one.
- Margin at a peak: operating margin at least 1.5 times (and 5 points above) its median over the filed years, at a company whose sales fell in one of those years and that now grows under 20%. Likely the top of a cycle, not a new normal, so its P/E is read on the median margin instead: today's sales at a normal year's margin.
- Sales falling: sales below a year ago and over the years. Cheap may just mean shrinking: the value trap.
- Margin sliding: operating margin down 5 points or more since the first filed year, and by a quarter of its median. Pricing power fading.
- Earnings expected to fall: the analysts' next-year earnings 10% or more under the last twelve months' (forward P/E above the trailing one). The low P/E is on a profit already shrinking, so it is cheaper than it will be.
- Heavy debt: net debt 3 times EBITDA or more; 5 times for utilities and telecoms, 8 times for REITs, never for banks and insurers.
- Stretched payout: dividends above 90% of earnings (not for REITs, which must pay out) or above the free cash flow summed over the filed years when earnings payout is also over 75% or dividends run over 1.5 times that cash flow (not for banks, insurers or regulated utilities, whose capex is funded with debt). A dividend earnings cover comfortably is not flagged for a cash flow cut by one-offs. The dividend may be cut.
- Heavy dilution: share count growing 5% a year or more. Each share owns a shrinking slice of what the business earns. Not for REITs, which must pay out their earnings and grow on new shares.
- Earnings not backed by cash: accruals (net income less operating cash flow) over 10% of assets, or operating cash flow under 70% of the profit summed over the filed years. Not for banks, insurers, REITs or utilities. Bookkeeping profits tend to come back down.
- Goodwill heavy: goodwill over half the assets or larger than the equity, and a return under 8% on all the capital with that goodwill left in. The acquisitions are not earning their price; a write-down comes off the book. Not for banks and insurers.
- Thin trading: under 1 million dollars traded a day over the last three months. Getting in and out costs a spread and moves the price.
- Cheap on one reading: the Price score clears 50 but only one of its inputs scores 50 or more on its own. Nothing else confirms the price, so there is no margin of safety. Two cheap inputs beside a dear one are enough.

## Banks, insurers, REITs and utilities
Sell or add reads some industries through their own lens, because cash flow, EBITDA and ROIC mean something else there. The row names the lens first.
- Financial lens (banks, insurers, asset managers): Quality averages return on equity (4% to 18%), earnings growth (-5% to 15% a year) and share count change (buybacks score up). Price averages P/E (6 scores 100, 16 scores 0), price to tangible book (book less goodwill and intangibles; whole book when the filings lack it, 0.7x to 2.5x), that price over the justified one, (ROTCE − 3%) / (10% − 3%) with a 10% cost of capital and 3% growth (0.6x to 1.6x; a return under 3% reads as dear), and the dividend. Cash-flow, margin, moat and debt flags do not apply. ROE of 15% or more and under 8% are named.
- REIT lens (listed real estate): Quality averages ROE (0% to 10%), sales growth (-5% to 10%), share issuance (0% to 10% a year) and operating margin (20% to 60%). Price averages price to book (0.7x to 2x), P/E as a stand-in for P/FFO (12x to 45x), EV/EBITDA (12x to 28x) and the dividend whatever its size. Debt up to 8 times EBITDA is normal.
- Utility lens (regulated electric, gas and water networks, and diversified utilities): Quality averages return on equity (4% to 14%, the return a regulator allows), earnings growth (-5% to 8% a year), share issuance and net debt over EBITDA (3x scores 100, 7x scores 0). Price averages P/E (10x to 25x), EV/EBITDA (7x to 16x) and the dividend whatever its size. ROIC, free cash flow, the moat and the cash runway do not apply: their capex is funded with debt on purpose. Debt of 5 times EBITDA or more is still named and blocks an add. Renewables developers and merchant power producers keep the standard lens.
- No lens but the standard one has a growth stage or an early-stage bet: a bank with negative cash flow is not burning money.
- Card lenders and payment networks (credit services) and brokers (capital markets, where Yahoo also files bitcoin miners) keep the standard lens; when their FCF is customer money the "cash not its own" rule applies.

## Growth stage and early-stage bets
The Sell or add page judges a company on a different yardstick when profits are not the right ruler.
- Growth stage: operating margin under 10% and sales growing 25% or more a year, or 15% or more when growth plus free cash flow before share-based pay over sales (a cash rule of 40) reaches 30%: the thin margin is spent on growth, as at a software house paying staff in shares. Quality is the rule of 40, gross margin (20% to 80%) and the moat score. Price is EV/sales per point of growth (0.1x a point is cheap, 0.6x dear), FCF yield (-5% to 5%) and forward P/E only once positive.
- Early stage: no sales to speak of (none, or market cap over 40 times sales) with cash going out, or an operating loss bigger than all its sales. It gets no scores and the verdict Bet: a position sized to be lost, with the cash runway as the one hard number (under 1.5 years is short, 3 or more is long).
- A held Bet above 3% of the book is marked Trim down to 3%.
- Drug makers carry a patent-cliff or trial-risk warning, because filings do not price expiry dates or trial outcomes.

## How free cash flow is treated and the FCF yield backed rule
Sell or add uses free cash flow net of share-based pay (the "Owner FCF yield"), since the data feed adds that pay back as if it were free. When share-based pay is half or more of FCF, or a tenth of sales, the row says "paid in shares". When insiders (managers, founders, a family) hold 10% or more of the shares, the row says so; it is not scored.
- Cash not its own: if that FCF is more than twice EBITDA (a lender's book, a payments float, subscriptions paid ahead), it is left out of the scores and the row says so.
- Broken-data rule: an FCF yield above 25% is normally treated as a currency mix-up at the source, as is an enterprise value at or below zero. Those inputs are dropped, the row says "source data looks broken", and the name cannot be Add or Buy.
- Backed exception: a yield above 25% is accepted as a real price when the forward P/E backs it, meaning the yield is no more than twice the earnings yield (2 divided by the P/E) and never above 50%. A market-abandoned name at five times earnings can genuinely yield 30%.

## Verdicts for holdings and how they are sized
For a stock you hold, the Sell or add page applies these rules in order, using the position's weight (share of the priced book; unpriced positions count at cost).
- Sell (target 0%): Quality and Price both under 35 for a new sale (a sale the page already proposed stands while both stay under 40), or Quality under 60 on a crumb: a position under 0.5% of the book, or under 0.5 divided by the number of companies in a book of more than 100 (0.25% with 200). At most five crumbs are sold in one pass, the weakest first; the rest show Hold, still marked small.
- Trim for concentration: one company above the book's line, whatever its quality. The line is 1.5 divided by the number of companies held, never under 15% nor over 35% (15% from ten names up, 37.5% would be 35% with four). The trim goes to an even share (1 divided by the number of companies, at least 10%); a good business at a good price is cut only halfway between that and the line.
- Fewer than three companies: no concentration trim at all, since one or two names cannot be spread; the page says so and points to the Buy candidates.
- Tax-staged trim: when a concentration trim would cost 10% or more of what the sale raises in tax, only half the cut is proposed now ("cut in two years for tax"); the rest waits for another tax year. Sales for quality (Sell, or Trim of a weak business) are never staged.
- Trim by half: Quality under 45 and the position weighs 6% or more, or carries 10% or more of the book's volatility (its share of risk).
- Add to the add line: Quality 65+ and Price 55+ for a new add (one the page already proposed holds while it clears 60 and 50), data not broken, no warning flag and the position at least a crumb under the line (closer than that is Hold, so a name hovering at it does not flip daily). The line is 5% up to 40 companies, then twice an even share (2 divided by the number of companies: 4% with 50, 2% with 100), never under 1%. A growth-stage name is added only to 3%, or the line if lower.
- Close call: a Hold whose scores sit between those new and standing lines says "close to a move", so a name a point either side of a line does not flip from day to day.
- Sale that costs more than its case: a Sell whose tax would be more than 5% of what the sale raises shows Hold with "selling costs more than it gains", unless Quality is under 25. Crumbs are still sold.
- Hold: none of the above. Funds show Core, money-market funds Cash, crypto and unscorable names Unrated. A company above the line is still trimmed even when its numbers cannot be read, but only halfway, since unread is not weak. On a very wide portfolio read for the first time, names whose figures take too long show Unrated for a moment ("still loading" under the filters) and the page asks again a few seconds later.
- Adds are paid for by the sales, never with money the plan does not raise: the best adds take what the sales free first. An add the sales cannot pay for shows Hold with "add with new money" and is listed under the plan in "If you add money", with the amount it would take; one the sales reach only in part is added that far and the rest is listed there too.
- Redeploy: money freed by sales and trims that the adds do not take goes next into Add or Hold names of Quality 60+ and Price 50+ with no warning, best first, up to the add line, or an even share of the companies' slice of the book where that is more, never past the concentration line (growth-stage names only to 3%). A Hold topped up this way shows as Add with "takes what the sales free". Top-ups under 0.5% of the book are skipped, so buys never exceed sales; what is left goes to the outside Buy candidates (below), and what none takes is cash with no home.
- Sector line: when one sector is 40% or more of the book across two companies or more, the page names it, no add (planned or from the sales) takes that sector past 40%, and an add blocked this way shows Hold with "its sector is already 40%+".
- Crypto: coins are never scored or cut; when they are 25% or more of the book the page says so.
The Move column is the money from the weight change at today's prices. "The plan", at the top of the page, leads with one figure: the new money the adds need, or the cash the sales free, with the tax on the sales beside it and two bars (To sell, To add) on one scale. The help text on each verdict quotes the lines this book was judged at. Under the plan every move is one row, split into "Sell or trim" and "Add to", biggest first. Hovering a name in the plan, the map or the table highlights it in the other two.
- Staying put: when nothing clears its line, the plan says to keep the book as it is, names how many holdings are close calls or held for tax, and records it in Decisions as one "stay put" entry. Doing nothing is a recommendation too.

## What the verdict does not read
A Sell or add verdict comes only from the two scores, the warning flags and the position's size, as above. When explaining one, name those numbers; nothing else moved it.
- Not your investor profile, risk appetite or horizon: an aggressive and a cautious account get the same verdict on the same book.
- Not a sector target: there is no "right" weight per sector to close a gap toward. Sectors only cap adds at 40% of the book.
- Not the price against its 52-week high or low, momentum, the news, the country or a political or regulatory risk (a Chinese ADR's structure, tariffs): a price the market cuts for such a risk reads as cheap.
- Not your gain or loss on the position. Buying more at a lower price lowers the average shown, but for Spanish tax each sale takes the oldest shares first (FIFO), so the old lots keep their cost; and selling shares at a loss within 2 months of buying the same security defers that loss.

## Tax on a sale and the repurchase-window date
Each Sell or Trim row on the Sell or add page shows the extra tax this year's bill would carry if you sold down to the target, replayed on your own lots with your tax jurisdiction and the gains and losses already booked this year. If the sale books a loss or is offset, it says no extra tax.
- "Buy after" date: where your jurisdiction has a repurchase rule and you sold something at a loss recently, an Add or Buy row shows the first day a purchase no longer undoes that loss. Windows are 2 months (Spain), 30 days (US and Canada) and 28 days (Ireland).
- Other jurisdictions have no window in the app, so no date appears.
- Losses that would cut the plan's tax: when the plan's sales add tax, the page checks the positions it keeps that sit at least the equivalent of 150 EUR under their cost, measured in your tax jurisdiction's currency (never one it says to add to). Each is replayed sold together with the plan, and those that lower the bill by at least the equivalent of 25 EUR are named with the combined saving, plus the date before which buying them back would undo the loss. It is arithmetic, not advice to sell.

## Notes about the whole book: country, currency, funds and cash
Above the plan, the Sell or add page names what shapes the book as a whole. A note is a warning about the book, never a verdict on a holding.
- One country: when one country is 70% or more of the book across three companies or more. It may be your own country; the page still says so.
- One currency: when 80% or more of the book (funds included) is quoted in a currency other than the page's. The result in your currency then also moves with the exchange rate. Pence count as pounds.
- Funds at the core: when funds (not money-market) are 60% or more, the single names are satellites around them; the funds themselves are held as Core, not scored.
- Idle cash: when money-market funds are 20% or more and the plan has names to add to or buy, or adds waiting for new money.
- A row quoted in a currency other than the page's carries a small currency tag beside its name; its details show country and currency.
- Tax residence: the plan's tax uses the country chosen in Profile. With none chosen, the plan says which country it assumed and links to Profile.

## Outside names: buy, watch or pass
The Outside the portfolio table judges watchlist names you do not hold, plus any tickers typed into "Weigh other tickers". Typed tickers are not saved to the watchlist; up to 10 can be added, and at most 30 outside names are judged.
- Buy: Quality 65+ and Price 55+ for a new buy (one the page already proposed holds while it clears 60 and 50), data not broken and no warning flag. A good business at a good price.
- Watch: Quality 60+ but still dear, or Quality 45+ with Price 50+. Wait for a better entry.
- Pass: neither bar is cleared.
- Sized buys: when the sales free money the portfolio cannot take, it goes to the Buy names, best first, each up to the add line and never pushing its sector past 40%. Each shows its target weight and amount, marked New in the plan. A buy still inside a repurchase window is sized and dated, not dropped. Amounts under 0.5% of the book are skipped.
- Bet and Unrated apply as for holdings; funds and coins are Unrated, indices are skipped.
The Include filter narrows what is compared (portfolio, favourites, watchlist or a group), and Sector and Weight filters narrow the tables.

## The quality map and its search
The "Quality against price" map plots every scored name: up is a better business, right is a cheaper one. Dashed lines sit at Quality 60 and Price 50, the bars the verdicts use, and the shaded corner ("Quality on sale") is where Add and Buy live. Your holdings are sized by weight; outside names are marked differently. Hover or tap a dot to see why.
- Bets, funds, cash and names with missing data have no dot; the map counts them below.
- "Find on the map" searches only names on the map, never the whole market. Typing fades non-matching dots and lists up to 8 matches with logo, symbol, name and verdict; picking one narrows the map to that dot. Names without a score are still listed as "Not on the map".
- A separate "Search this table" box filters the tables by symbol, name, sector or verdict.
- "Where it was" (Dónde estaba hace) picks 1M, 6M, 1Y or 2Y; "Now" (Ahora), the default, clears it. With a window picked, each dot trails a line from where the name sat that day, through where it sat every six months since (2Y passes 18 months, 1Y and 6M ago), into today's dot. Pointing at a name, or searching it, draws only its path, each step named (2Y, 18M, 1Y, 6M); its tooltip sits where it hides none of them. Each point is the score the review recorded that day when there is one; otherwise the business as its annual filings stood then (a filing counts from 90 days after its year closes), at that day's share price; with no filing that old, today's business at that day's price. The tooltip says which. A move to the left means the price made it dearer; down means the business got worse.
- With a window picked, two filters keep only the names whose price score moved one way ("Dearer" / "Cheaper") or whose quality score did ("Better quality" / "Worse quality"); the rest fade. The tables keep their own return window.
