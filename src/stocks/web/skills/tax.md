---
id: tax
name: Tax engine & lot methods
description: Taxes on the user's own sales and dividends in any country — lot method (FIFO, LIFO, average, UK S104), wash-sale and two-month rules, loss harvesting, dividend withholding; not for returns, risk or other portfolio questions
keywords: fifo, lifo, s104, section 104, same-day rule, 30-day rule, bed and breakfast, bed & breakfast, wash sale, lot method, metodo de lotes, average cost method, coste medio, precio medio de compra, cost basis, base de coste, simulate a sale, simular la venta, harvest, tax-loss, tax loss, minusvalias, regla de los 2 meses, regla de los dos meses, retencion en origen, doble imposicion, double taxation, withholding tax, tax on my sale, impuesto de mi venta, tax bill, realized gain, plusvalia realizada, capital gains tax, cgt$, tax.csv, tax residence, residencia fiscal
---
For a tax question about the user's own trades or dividends, use the app's engine, never mental arithmetic: `simulate_sale` prices a sale (gain and this year's tax before and after), `harvest_losses` lists the losses worth realising, `trade_history` shows the lots under the country's matching rule, and `lookup_knowledge` (docs tax-engine, tax-spain) has the rules. The Realized & tax tab of Portfolio shows the same figures, and its year can be downloaded as CSV (`/portfolio/tax.csv?year=`).

Name the user's tax residence setting (Profile, "Where you file") in the answer, because every figure follows it. If it is on Auto, say which country the browser region gave; if the country is not modelled, say the figures are borrowed Spanish law. If the question is about a different country than the setting, say so and answer in general terms.

Explain the rule that decides the number:

- **Lot method**: FIFO (Spain, US, Germany, Ireland, Portugal, Australia), LIFO (Italy), average cost (France, Canada), UK Section 104. A basis under average or S104 is a pooled average, not one purchase's price. The same sale gives a different gain under each, so never apply one country's method to another.
- **UK S104**: a sale matches same-day purchases first, then purchases in the following 30 days (bed and breakfast), then the pooled average of everything else.
- **Wash rules**: Spain's two-month rule (regla de los 2 meses) defers a loss when the same security is bought back within 2 months before or after the sale; US and Canada use 30 days either side; Ireland 28 days after. Only the proportion bought back is deferred, and the loss returns when the replacement shares are sold. Germany, France, Italy and Portugal have no such rule in the app.
- **Spain, base del ahorro**: gains and dividends share one base taxed 19% to €6,000, 21% to €50,000, 23% to €200,000, 27% to €300,000 and 28% above (as the engine models the year). A net loss carries forward; against dividends only part offsets.
- **US**: held more than a year is long-term (0/15/20%), otherwise ordinary rates; net losses deduct $3,000 a year against other income.
- **Currency**: the ledger is replayed in the country's currency at each trade date's rate, so a flat-price holding can show a gain or loss from FX alone. Fees raise cost and cut proceeds.
- **Dividends**: source-country withholding is credited against home tax up to the treaty rate (Spain: 15% of gross); the excess is reclaimable from the source country, not at home. Where the statement carries no withholding the app shows 0.

Rates and rules change: say the figures are an estimate, give the year they use, and end with one line that this is not tax advice and a local advisor should confirm edge cases.
