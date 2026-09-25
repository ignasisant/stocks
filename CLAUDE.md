# TopStocks — project rules

## Big features ship announced — nothing else does

The app tells its own users what changed. `src/stocks/web/onboarding.py`
carries the release registry, and the "what's new" modal pages a returning
account through the cards that shipped while it was away — one card each,
read once.

That modal interrupts someone who came to look at their portfolio, so the bar
is high: **a card has to be somewhere new to go.** A new section, page or tab;
a screen rebuilt under the user; a capability that lets them do something they
could not do at all before. Those get a `News` item in the current `Release`
(or a new `Release` when the last one has shipped) plus its `_title` / `_body`
copy in both `src/stocks/web/locales/en/tour.json` and `…/es/tour.json`.
Invoke the **update-tutorial** skill and follow it: it also decides when the
change needs a guided-tour `Step` of its own.

Everything else is announced nowhere, and everything else is most of the work.
Internal refactors, perf, infrastructure and fixes, obviously. But also the one
that is easy to get wrong: **one more of a kind that already ships.** Another
broker in the importer, another jurisdiction in the tax engine, another skill
in the chat, another field on a card — that is a sentence in the existing
step's `_body`, not a card of its own. The registry is not a git log, and a
release carrying more than a handful of cards means the bar slipped.

Verify with:

```bash
uv run pytest tests/test_onboarding.py tests/test_i18n_parity.py -q
```
