# TopStocks — project rules

## Every big feature or visible refactor ships announced

The app tells its own users what changed. `src/stocks/web/onboarding.py`
carries the release registry, and the "what's new" modal pages a returning
account through the features that shipped while it was away — one card per
feature, however many there are, and each account reads them once.

**A change is not done until it is in that registry.** Before committing
anything a signed-in user can see — a new page, tab, setting, importer,
jurisdiction, or a screen rebuilt under them — add a `News` item to the
current `Release` (or a new `Release` when the last one has shipped) and write
its `_title` / `_body` copy in both `src/stocks/web/locales/en/tour.json` and
`…/es/tour.json`. Invoke the **update-tutorial** skill and follow it: it also
decides when the change needs a guided-tour `Step` of its own.

Work with no user-visible surface — an internal refactor, a perf fix,
infrastructure — is announced nowhere. The registry is not a git log.

Verify with:

```bash
uv run pytest tests/test_onboarding.py tests/test_i18n_parity.py -q
```
