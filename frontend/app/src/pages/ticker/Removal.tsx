/**
 * Removing a holding imported by mistake, from the page that shows it.
 *
 * A wrong file, the demo account's statement, somebody else's export: the
 * rows land in the book and the only way out used to be wiping it whole or
 * asking the chat. Here the "More" menu offers it. The server plans the
 * deletion (`POST /portfolio/positions/{symbol}/removal`) over the same rows
 * the page shows the holding with — a broker move's ISIN rows included — and
 * the panel says what goes and what it does to realized gains before anything
 * is written. Confirming commits that plan under its token, so a book that
 * changed in between is refused rather than edited blind, and the notice that
 * follows carries the undo.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import type { EditPlan } from "../../api.gen";
import { DASH, money } from "../../shell/format";
import { useT } from "../../shell/i18n";
import { SidePanel } from "../../ui/SidePanel";
import { Status } from "../../ui/Status";
import { toast } from "../../ui/toast";
import { commitPlan, planRemoval, undoChange } from "./data";

/** One tax year whose realized gain the removal changes. */
export type Shift = { year: string; currency: string; before: number; after: number };

/**
 * The years the removal moves realized gain in, oldest first. Summed per
 * (currency, year): a holding the plan reports under two labels is still one
 * line a year.
 */
export function realizedShifts(plan: EditPlan): Shift[] {
  const sums = new Map<string, Shift>();
  for (const effect of plan.effects) {
    const years = new Set([
      ...Object.keys(effect.realized_before),
      ...Object.keys(effect.realized_after),
    ]);
    for (const year of years) {
      const key = `${effect.currency}-${year}`;
      const shift = sums.get(key) ?? {
        year,
        currency: effect.currency,
        before: 0,
        after: 0,
      };
      shift.before += effect.realized_before[year] ?? 0;
      shift.after += effect.realized_after[year] ?? 0;
      sums.set(key, shift);
    }
  }
  return [...sums.values()]
    .filter((shift) => Math.abs(shift.before - shift.after) >= 0.005)
    .sort(
      (a, b) => a.year.localeCompare(b.year) || a.currency.localeCompare(b.currency),
    );
}

/** First and last date among the rows it deletes. */
export function span(plan: EditPlan): { first: string; last: string } | null {
  const dates = plan.changes
    .map((change) => change.before?.date)
    .filter((date): date is string => !!date)
    .sort();
  const first = dates[0];
  const last = dates[dates.length - 1];
  return first && last ? { first, last } : null;
}

type Planned =
  { state: "loading" } | { state: "failed" } | { state: "loaded"; plan: EditPlan };

/**
 * The "Remove position" row and its panel. `inBook` is whether the book has
 * any row under this name: a page for a company never bought offers nothing.
 */
export function usePositionRemoval(
  ticker: string,
  inBook: boolean,
  onChanged: () => void,
) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [planned, setPlanned] = useState<Planned>({ state: "loading" });
  const [busy, setBusy] = useState(false);

  useEffect(() => setOpen(false), [ticker]);

  // Only the newest request may answer: a slow plan for the previous ask (or
  // the previous ticker) must not overwrite the one now on screen.
  const asked = useRef(0);
  const ask = useCallback(() => {
    const seq = ++asked.current;
    setPlanned({ state: "loading" });
    planRemoval(ticker).then(
      (plan) => seq === asked.current && setPlanned({ state: "loaded", plan }),
      () => seq === asked.current && setPlanned({ state: "failed" }),
    );
  }, [ticker]);

  const show = useCallback(() => {
    setOpen(true);
    ask();
  }, [ask]);

  const close = useCallback(() => setOpen(false), []);

  const undo = (changeId: number) =>
    undoChange(changeId).then(onChanged, () => toast.bad(t("common.failed")));

  const remove = (plan: EditPlan) => {
    setBusy(true);
    commitPlan(plan, t("ticker.remove_summary", { ticker }))
      .then(
        (done) => {
          setOpen(false);
          toast.ok(t("ticker.removed", { ticker }), {
            action: {
              label: t("ticker.split_undo"),
              onClick: () => void undo(done.id),
            },
          });
          onChanged();
        },
        () => {
          // Most often the book moved since the plan (409): show the new one.
          toast.bad(t("ticker.remove_failed"));
          ask();
        },
      )
      .finally(() => setBusy(false));
  };

  const title = t("ticker.remove_title");
  const panel = open ? (
    <SidePanel label={title} onClose={close} className="tk-remove">
      {planned.state === "loading" ? (
        <Status label={t("ticker.remove_checking")} />
      ) : planned.state === "failed" ? (
        <p className="tk-remove-bad">{t("common.failed")}</p>
      ) : (
        <RemovalPlan
          ticker={ticker}
          plan={planned.plan}
          busy={busy}
          onRemove={() => remove(planned.plan)}
          onCancel={close}
        />
      )}
    </SidePanel>
  ) : null;

  return { offered: inBook, label: title, open: show, panel };
}

export function RemovalPlan({
  ticker,
  plan,
  busy,
  onRemove,
  onCancel,
}: {
  ticker: string;
  plan: EditPlan;
  busy: boolean;
  onRemove: () => void;
  onCancel: () => void;
}) {
  const t = useT();
  const rows = plan.changes.length;
  const dates = span(plan);
  const shifts = realizedShifts(plan);
  return (
    <div className="tk-remove-body">
      <p>
        {t(rows === 1 ? "ticker.remove_rows_one" : "ticker.remove_rows_n", {
          ticker,
          n: rows,
          first: dates?.first ?? DASH,
          last: dates?.last ?? DASH,
        })}
      </p>
      {shifts.length > 0 ? (
        <ul className="tk-remove-shifts">
          {shifts.map((shift) => (
            <li key={`${shift.currency}-${shift.year}`}>
              {t("ticker.remove_realized", {
                year: shift.year,
                before: money(shift.before, { currency: shift.currency, digits: 2 }),
                after: money(shift.after, { currency: shift.currency, digits: 2 }),
              })}
            </li>
          ))}
        </ul>
      ) : null}
      {plan.ok ? (
        <p className="tk-muted">{t("ticker.remove_help")}</p>
      ) : (
        <div className="tk-remove-bad" role="alert">
          <p>{t("ticker.remove_blocked")}</p>
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
            className="ag-btn tk-btn-danger"
            disabled={busy}
            onClick={onRemove}
          >
            {t("ticker.remove_confirm")}
          </button>
        ) : null}
        <button type="button" className="ag-btn" disabled={busy} onClick={onCancel}>
          {t("common.cancel")}
        </button>
      </div>
      {busy ? <Status label={t("ticker.remove_working")} /> : null}
    </div>
  );
}
