/**
 * What the book holds, and the one control that can empty it.
 *
 * `DELETE /v1/portfolio/transactions` removes every transaction — every import,
 * and every row typed in by hand years ago — takes no backup and cannot be
 * undone, which is why it is the only route on this page that demands the
 * signed-in address typed back. The control therefore opens something before it
 * can act, and the address is the thing that arms it: a tick nobody reads is
 * not a confirmation.
 *
 * `DELETE /import/last` is what almost every reader wants instead, and it lives
 * beside the last-import note where the batch it removes is named.
 *
 * Beside the count sit the three figures an import moves — value, money put in
 * and dividends booked — so a reader sees what a statement did to the book
 * without leaving the page. Each loads on its own and is asked again after
 * every write, as the count is.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useAccount, useCurrency } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import type { Query } from "../../shell/useApi";
import { Kpi, KpiGrid } from "../../ui/Kpi";
import { Status } from "../../ui/Status";
import { paid as paidOf, standing as standingOf, wipeLedger } from "./api";
import type { Book } from "./api";
import { Fold } from "./Card";
import { Danger } from "./Danger";
import { names } from "./repairs";
import { useVocabulary } from "./text";

export function Ledger({
  book,
  nonce,
  hasLast,
  onWiped,
}: {
  book: Query<Book>;
  /** Bumped by every write on the page, which moves all four figures. */
  nonce: number;
  /** A last import exists, so the delete can point at undoing only that. */
  hasLast: boolean;
  onWiped: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const me = useAccount();
  const base = useCurrency();
  const [cleared, setCleared] = useState(false);
  const [clearing, setClearing] = useState(false);
  const standing = useApi(() => standingOf(base), [base, nonce]);
  const paid = useApi(() => paidOf(base), [base, nonce]);

  /** A tile's figure: "…" while its call is out, n/a once it failed or is null. */
  const figure = <T extends { base: string }>(
    query: Query<T>,
    pick: (data: T) => number | null,
  ) => {
    if (query.state === "loading") return "…";
    if (query.state !== "loaded") return t("portfolio.na");
    const value = pick(query.data);
    return value === null ? t("portfolio.na") : vocab.money(value, query.data.base);
  };

  // The folded line: the count, and the value once there is one to state.
  const now = book.state === "loaded" ? book.data : null;
  const worth =
    now && now.total > 0 && standing.state === "loaded" && standing.data.value !== null
      ? vocab.money(standing.data.value, standing.data.base)
      : null;
  const summary = now
    ? [vocab.num(now.total, 0), worth].filter(Boolean).join(" · ")
    : undefined;

  return (
    <Fold id="im-book" summary={summary} title={t("import.book_now")}>
      {cleared && <p className="im-ok">{t("import.toast_cleared")}</p>}
      <Loaded query={book} skeleton={<Skeleton rows={2} />}>
        {(held) => (
          <>
            <KpiGrid>
              <Kpi
                help={t("import.metric_in_ledger")}
                label={t("import.kpi_rows")}
                value={vocab.num(held.total, 0)}
              />
              {/* An empty book has no value to report, and three n/a tiles
                  beside a zero would read as three failures. */}
              {held.total > 0 && (
                <>
                  <Kpi
                    help={t("import.metric_value_help")}
                    label={t("import.kpi_value")}
                    value={figure(standing, (data) => data.value)}
                  />
                  <Kpi
                    help={t("import.metric_injected_help")}
                    label={t("import.kpi_injected")}
                    value={figure(standing, (data) => data.injected)}
                  />
                  <Kpi
                    help={t("import.metric_dividends_help")}
                    label={t("import.kpi_dividends")}
                    value={figure(paid, (data) => data.booked_total)}
                  />
                </>
              )}
            </KpiGrid>
            {/* Not a warning: on this page the demo book is on its way out, and
                what the reader needs to know is that importing is what removes
                it. No address, no delete: a control that cannot be armed is
                worse than one that is not offered, and a token session has no
                email. */}
            {(held.demo > 0 || (held.total > 0 && me.email)) && (
              <div className="im-book-foot">
                <span className="im-fine">
                  {held.demo > 0
                    ? t("import.demo_rows_caption", { n: vocab.num(held.demo, 0) })
                    : null}
                </span>
                {held.total > 0 && me.email && !clearing ? (
                  <button
                    className="im-btn im-btn-text im-btn-danger"
                    onClick={() => setClearing(true)}
                    type="button"
                  >
                    {t("import.clear_all_short")}
                  </button>
                ) : null}
              </div>
            )}
            {clearing && me.email && held.total > 0 ? (
              <ClearAll
                email={me.email}
                hasLast={hasLast}
                onCancel={() => setClearing(false)}
                onWiped={() => {
                  setClearing(false);
                  setCleared(true);
                  onWiped();
                }}
                total={held.total}
              />
            ) : null}
          </>
        )}
      </Loaded>
    </Fold>
  );
}

function ClearAll({
  email,
  total,
  hasLast,
  onCancel,
  onWiped,
}: {
  email: string;
  total: number;
  hasLast: boolean;
  onCancel: () => void;
  onWiped: () => void;
}) {
  const t = useT();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const wipe = async () => {
    setBusy(true);
    setFailed(false);
    try {
      await wipeLedger(typed.trim());
      onWiped();
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Danger
        autoFocus
        disabled={busy}
        email={email}
        id="im-wipe"
        onChange={setTyped}
        prompt={t("import.wipe_type", { email })}
        safer={hasLast}
        total={total}
        value={typed}
      >
        <button
          className="im-btn im-btn-destructive"
          disabled={busy || !names(typed, email)}
          onClick={wipe}
          type="button"
        >
          {t("import.delete_everything")}
        </button>
        <button
          className="im-btn im-btn-text"
          disabled={busy}
          onClick={onCancel}
          type="button"
        >
          {t("common.cancel")}
        </button>
      </Danger>
      {failed && <p className="im-bad">{t("common.failed")}</p>}
      {busy && <Status label={t("import.work_wiping")} />}
    </>
  );
}
