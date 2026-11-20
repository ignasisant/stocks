/**
 * Recording a buy or a sale by hand, from the page of the thing bought.
 *
 * A fund no importer reads, a broker without an export, a fill the statement
 * has not caught up with: until now the chat was the only way to type one in.
 * The "More" menu offers it on any page whose kind can be held. The form
 * builds one `add` row; the server plans it (`POST /portfolio/changes/plan`)
 * and the panel shows what it does to the holding before anything is written.
 * Confirming commits that plan under its token, as removing a holding does,
 * and the notice that follows carries the undo.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { EditPlan } from "../../api.gen";
import { decimal, money } from "../../shell/format";
import { useT } from "../../shell/i18n";
import { Segmented } from "../../ui/Segmented";
import { SidePanel } from "../../ui/SidePanel";
import { Status } from "../../ui/Status";
import { toast } from "../../ui/toast";
import { commitPlan, planTrade, undoChange, type TradeRow } from "./data";

export type Side = "buy" | "sell";

export type Draft = {
  side: Side;
  date: string;
  quantity: string;
  price: string;
  fee: string;
  currency: string;
};

/** What the form opens with: the holding's currency and today's price in it. */
export type TradeDefaults = { currency: string; price: number | null };

/**
 * Listings quoted in a minor unit, and the major one a ledger row is kept in.
 * A pence price stored as pounds is a hundredfold error, so the form never
 * offers one: it converts.
 */
const MINOR: Record<string, string> = {
  GBp: "GBP",
  GBX: "GBP",
  ZAc: "ZAR",
  ILA: "ILS",
};

/**
 * The quote's currency and price as a ledger row keeps them: in the major
 * unit. Case-sensitive on purpose — "GBp" is pence, "GBP" pounds.
 */
export function majorUnit(
  currency: string | null,
  price: number | null,
): { currency: string | null; price: number | null } {
  if (!currency) return { currency: null, price };
  const major = MINOR[currency];
  if (!major) return { currency: currency.toUpperCase(), price };
  return { currency: major, price: price === null ? null : price / 100 };
}

/** The reader's local day, `YYYY-MM-DD` — not UTC's, which is tomorrow by evening in Asia. */
export function localDay(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** A share or unit count with the decimals it has, six at most: 16,16135, not 16,16. */
export function count(n: number): string {
  const rounded = +n.toFixed(6);
  const places = String(rounded).split(".")[1]?.length ?? 0;
  return decimal(rounded, { digits: places });
}

/** Whether `text` may stand in a number field while typed: digits and one mark. */
const numeric = (text: string) => /^\d*(?:[.,]\d*)?$/.test(text);

/** A typed amount as a number, comma or point as the decimal mark; NaN if not one. */
export function amount(text: string): number {
  const clean = text.trim().replace(",", ".");
  return clean === "" || !numeric(clean) ? Number.NaN : Number(clean);
}

/**
 * The ledger row the draft stands for, or null while it cannot be one: a day
 * that is not a date or is in the future, a quantity that is not above zero,
 * a price or a fee that is not a number. An empty fee is zero.
 */
export function tradeRow(ticker: string, draft: Draft, today: string): TradeRow | null {
  const quantity = amount(draft.quantity);
  const price = amount(draft.price);
  const fee = draft.fee.trim() === "" ? 0 : amount(draft.fee);
  const currency = draft.currency.trim().toUpperCase();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(draft.date) || draft.date > today) return null;
  if (!(quantity > 0) || !(price >= 0) || !(fee >= 0)) return null;
  if (!/^[A-Z]{3}$/.test(currency)) return null;
  return {
    date: draft.date,
    ticker,
    action: draft.side,
    quantity,
    price,
    currency,
    fee,
    note: "",
  };
}

type Stage =
  | { state: "form" }
  | { state: "planning" }
  | { state: "failed" }
  | { state: "planned"; plan: EditPlan };

/**
 * The "Add a trade" row and its panel. `defaults` is null where nothing can be
 * held — an index — and the menu then offers nothing.
 */
export function useTradeEntry(
  ticker: string,
  defaults: TradeDefaults | null,
  onChanged: () => void,
) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [stage, setStage] = useState<Stage>({ state: "form" });
  const [busy, setBusy] = useState(false);

  useEffect(() => setOpen(false), [ticker]);

  const asked = useRef(0);
  const today = localDay();
  const row = draft ? tradeRow(ticker, draft, today) : null;

  const show = useCallback(() => {
    if (!defaults) return;
    asked.current++;
    setDraft({
      side: "buy",
      date: localDay(),
      quantity: "",
      price: defaults.price === null ? "" : String(+defaults.price.toFixed(4)),
      fee: "",
      currency: defaults.currency,
    });
    setStage({ state: "form" });
    setOpen(true);
  }, [defaults]);

  const close = useCallback(() => {
    asked.current++;
    setOpen(false);
  }, []);

  const review = (next: TradeRow) => {
    const seq = ++asked.current;
    setStage({ state: "planning" });
    planTrade(next).then(
      (plan) => seq === asked.current && setStage({ state: "planned", plan }),
      () => seq === asked.current && setStage({ state: "failed" }),
    );
  };

  const undo = (changeId: number) =>
    undoChange(changeId).then(onChanged, () => toast.bad(t("common.failed")));

  const confirm = (plan: EditPlan, done: TradeRow) => {
    setBusy(true);
    const summary = t(
      done.action === "buy" ? "ticker.trade_summary_buy" : "ticker.trade_summary_sell",
      {
        quantity: count(done.quantity),
        ticker,
        price: money(done.price, { currency: done.currency, digits: 2 }),
        date: done.date,
      },
    );
    commitPlan(plan, summary)
      .then(
        (change) => {
          setOpen(false);
          toast.ok(summary, {
            action: {
              label: t("ticker.split_undo"),
              onClick: () => void undo(change.id),
            },
          });
          onChanged();
        },
        () => {
          // Most often the book moved since the plan (409): plan it again.
          toast.bad(t("ticker.trade_failed"));
          review(done);
        },
      )
      .finally(() => setBusy(false));
  };

  const title = t("ticker.trade_title");
  const panel =
    open && draft ? (
      <SidePanel label={title} onClose={close} className="tk-trade">
        {stage.state === "form" ? (
          <TradeForm
            draft={draft}
            today={today}
            ready={row !== null}
            onDraft={setDraft}
            onReview={() => row && review(row)}
            onCancel={close}
          />
        ) : stage.state === "planning" ? (
          <Status label={t("ticker.remove_checking")} />
        ) : stage.state === "failed" ? (
          <div className="tk-remove-body">
            <p className="tk-remove-bad">{t("common.failed")}</p>
            <div className="tk-remove-actions">
              <button
                type="button"
                className="ag-btn"
                onClick={() => setStage({ state: "form" })}
              >
                {t("ticker.trade_back")}
              </button>
            </div>
          </div>
        ) : (
          <TradePlan
            plan={stage.plan}
            busy={busy}
            onConfirm={() => row && confirm(stage.plan, row)}
            onBack={() => {
              asked.current++;
              setStage({ state: "form" });
            }}
          />
        )}
      </SidePanel>
    ) : null;

  return { offered: defaults !== null, label: title, open: show, panel };
}

export function TradeForm({
  draft,
  today,
  ready,
  onDraft,
  onReview,
  onCancel,
}: {
  draft: Draft;
  today: string;
  ready: boolean;
  onDraft: (next: Draft) => void;
  onReview: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const set = (field: keyof Draft, value: string) =>
    onDraft({ ...draft, [field]: value });
  const typed = (field: "quantity" | "price" | "fee") => (value: string) => {
    if (numeric(value)) set(field, value);
  };
  const quantity = amount(draft.quantity);
  const price = amount(draft.price);
  const total = quantity > 0 && price >= 0 ? quantity * price : null;
  const currency = draft.currency.trim().toUpperCase();

  return (
    <form
      className="tk-trade-form"
      onSubmit={(event) => {
        event.preventDefault();
        if (ready) onReview();
      }}
    >
      <Segmented<Side>
        items={[
          { id: "buy", label: t("ticker.trade_buy") },
          { id: "sell", label: t("ticker.trade_sell") },
        ]}
        value={draft.side}
        onPick={(side) => onDraft({ ...draft, side })}
        label={t("ticker.trade_side")}
      />
      <label className="tk-trade-field">
        <span>{t("ticker.trade_date")}</span>
        <input
          className="tk-field"
          type="date"
          max={today}
          value={draft.date}
          onChange={(event) => set("date", event.target.value)}
        />
      </label>
      <label className="tk-trade-field">
        <span>{t("ticker.trade_quantity")}</span>
        <input
          className="tk-field"
          inputMode="decimal"
          enterKeyHint="next"
          autoComplete="off"
          value={draft.quantity}
          onChange={(event) => typed("quantity")(event.target.value)}
        />
      </label>
      <div className="tk-trade-pair">
        <label className="tk-trade-field">
          <span>{t("ticker.trade_price")}</span>
          <input
            className="tk-field"
            inputMode="decimal"
            enterKeyHint="next"
            autoComplete="off"
            aria-describedby="tk-trade-price-help"
            value={draft.price}
            onChange={(event) => typed("price")(event.target.value)}
          />
        </label>
        <label className="tk-trade-field tk-trade-ccy">
          <span>{t("ticker.trade_currency")}</span>
          <input
            className="tk-field"
            autoComplete="off"
            autoCapitalize="characters"
            maxLength={3}
            value={draft.currency}
            onChange={(event) =>
              set("currency", event.target.value.replace(/[^a-z]/gi, "").toUpperCase())
            }
          />
        </label>
      </div>
      <p id="tk-trade-price-help" className="tk-muted tk-trade-help">
        {t("ticker.trade_price_help")}
      </p>
      <label className="tk-trade-field">
        <span>{t("ticker.trade_fee")}</span>
        <input
          className="tk-field"
          inputMode="decimal"
          enterKeyHint="done"
          autoComplete="off"
          placeholder="0"
          value={draft.fee}
          onChange={(event) => typed("fee")(event.target.value)}
        />
      </label>
      {total !== null && /^[A-Z]{3}$/.test(currency) ? (
        <p className="tk-trade-total">
          {t("ticker.trade_total", { total: money(total, { currency, digits: 2 }) })}
        </p>
      ) : null}
      <div className="tk-remove-actions">
        <button type="submit" className="ag-btn ag-btn-cta" disabled={!ready}>
          {t("ticker.trade_review")}
        </button>
        <button type="button" className="ag-btn" onClick={onCancel}>
          {t("common.cancel")}
        </button>
      </div>
    </form>
  );
}

export function TradePlan({
  plan,
  busy,
  onConfirm,
  onBack,
}: {
  plan: EditPlan;
  busy: boolean;
  onConfirm: () => void;
  onBack: () => void;
}) {
  const t = useT();
  return (
    <div className="tk-remove-body">
      {plan.effects.length ? (
        <ul className="tk-remove-shifts">
          {plan.effects.map((effect) => (
            <li key={`${effect.ticker}-${effect.currency}`}>
              {t("ticker.trade_held", {
                before: count(effect.held_before),
                after: count(effect.held_after),
              })}
              <br />
              {t("ticker.trade_cost", {
                before: money(effect.cost_before, {
                  currency: effect.currency,
                  digits: 2,
                }),
                after: money(effect.cost_after, {
                  currency: effect.currency,
                  digits: 2,
                }),
              })}
            </li>
          ))}
        </ul>
      ) : null}
      {plan.ok ? (
        <p className="tk-muted">{t("ticker.trade_help")}</p>
      ) : (
        <div className="tk-remove-bad" role="alert">
          <p>{t("ticker.trade_blocked")}</p>
          <ul>
            {plan.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="tk-remove-actions">
        {plan.ok ? (
          <button
            type="button"
            className="ag-btn ag-btn-cta"
            disabled={busy}
            onClick={onConfirm}
          >
            {t("ticker.trade_confirm")}
          </button>
        ) : null}
        <button type="button" className="ag-btn" disabled={busy} onClick={onBack}>
          {t("ticker.trade_back")}
        </button>
      </div>
      {busy ? <Status label={t("ticker.trade_working")} /> : null}
    </div>
  );
}
