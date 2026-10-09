/**
 * Everything a verdict stands on, for whoever asks "why?" about one name.
 *
 * The page's rows are terse on purpose — a pill, two reasons, a figure — and
 * this is where each word is spelled out: the rule behind the verdict, the
 * rule behind every reason, and the numbers the scores were built from,
 * each with the KPI catalog's own definition behind a `Help` mark (a tap on
 * a phone, a hover with a mouse). Nothing here is computed: the thresholds in
 * the copy are `stocks.analysis.review`'s, and a number the feed lacked reads
 * as n/a rather than dropping out, so a short list never hides why a score
 * is missing.
 */

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { TickerCell } from "../../shell/tickers";
import { Chip, Help } from "../../ui/Kpi";
import {
  OWN_LABEL,
  SHOWN,
  inYears,
  metric,
  pnlChip,
  score,
  verdictTone,
} from "./format";
import type { ReviewRow } from "./types";

/** Catalog copy is markdown-lite; a tooltip is plain text. */
const plain = (text: string) => text.replaceAll("**", "").replaceAll("*", "");

/** The verdict pill, with the rule that produced it as its hover text. */
export function VerdictChip({ row }: { row: ReviewRow }) {
  const t = useT();
  return (
    <span className="ag-rev-verdict" title={t(`review.verdict_${row.verdict}_help`)}>
      <Chip
        chip={{
          text: t(`review.verdict_${row.verdict}`),
          tone: verdictTone(row.verdict),
        }}
      />
    </span>
  );
}

/** A column head with its definition behind the "?" mark. */
export function Head({
  label,
  help,
  left = false,
}: {
  label: string;
  help?: string;
  left?: boolean;
}) {
  return (
    <th className={left ? "ag-rev-left" : undefined}>
      <span className="ag-rev-th">
        {label}
        {help ? <Help text={help} /> : null}
      </span>
    </th>
  );
}

/** A held name's gain or loss as a chip, green up, red down. */
export function PnlChip({ row }: { row: ReviewRow }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const chip = pnlChip(row, base, lang);
  return chip ? <Chip chip={chip} /> : <>{t("review.na")}</>;
}

/** What the dialog says: the verdict's rule, every reason's, every number. */
function Details({ row }: { row: ReviewRow }) {
  const t = useT();
  const lang = useLang();
  const na = t("review.na");
  return (
    <div className="ag-rev-details">
      <p className="ag-rev-details-rule">
        <VerdictChip row={row} />
        <span>{t(`review.verdict_${row.verdict}_help`)}</span>
      </p>
      {row.reasons.length > 0 ? (
        <div className="ag-rev-details-group">
          <h3 className="ag-rev-h3">{t("review.details_reasons")}</h3>
          <ul className="ag-rev-why-list">
            {row.reasons.map((code) => (
              <li key={code}>
                <b>{t(`review.reason_${code}`)}</b>
                <span>{t(`review.reason_${code}_help`)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      <div className="ag-rev-details-group">
        <h3 className="ag-rev-h3">{t("review.details_metrics")}</h3>
        <dl className="ag-rev-facts">
          <Fact
            label={t("review.col_quality")}
            help={t("review.col_quality_help")}
            value={score(row.quality) ?? na}
          />
          <Fact
            label={t("review.col_cheapness")}
            help={t("review.col_cheapness_help")}
            value={score(row.cheapness) ?? na}
          />
          {row.held ? (
            <Fact
              label={t("review.col_pnl")}
              help={t("review.col_pnl_help")}
              value={<PnlChip row={row} />}
            />
          ) : null}
          {SHOWN.map((key) => {
            const shown = metric(key, row.metrics[key], lang);
            const own = OWN_LABEL.has(key);
            return (
              <Fact
                key={key}
                label={t(own ? `review.metric_${key}` : `kpi.${key}.label`)}
                help={
                  own ? t(`review.metric_${key}_help`) : plain(t(`kpi.${key}.desc`))
                }
                value={
                  shown === null
                    ? na
                    : inYears(key)
                      ? t("review.years", { value: shown })
                      : shown
                }
              />
            );
          })}
        </dl>
      </div>
    </div>
  );
}

function Fact({
  label,
  help,
  value,
}: {
  label: string;
  help: string;
  value: ReactNode;
}) {
  return (
    <div className="ag-rev-fact">
      <dt>
        {label}
        <Help text={help} />
      </dt>
      <dd>{value}</dd>
    </div>
  );
}

/**
 * The way into a name's details: a dialog over the page, never a fold.
 *
 * Folded open, the panel took the width of whatever it sat in — a ~17rem move
 * card on a desktop grid, a phone row past its logo — and pushed every row
 * under it down by a screen. In a dialog it reads at one width everywhere and
 * the list stays where the reader left it. `text` is the "Details" link under
 * a card or a dense row; `icon` is the chevron in a table's last column.
 */
export function DetailsButton({
  row,
  variant = "text",
}: {
  row: ReviewRow;
  variant?: "text" | "icon";
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const label = t("review.details_label", { ticker: row.symbol || row.ticker });
  return (
    <>
      <button
        type="button"
        className={variant === "icon" ? "ag-rev-fold" : "ag-rev-more"}
        aria-haspopup="dialog"
        aria-label={variant === "icon" ? label : undefined}
        title={variant === "icon" ? label : undefined}
        onClick={() => setOpen(true)}
      >
        {variant === "text" ? t("review.details") : null}
        <span className="ag-rev-chevron" aria-hidden="true" />
      </button>
      {open ? <DetailsDialog row={row} label={label} onClose={close} /> : null}
    </>
  );
}

/**
 * The dialog itself, portalled to the body: `.ag-main` is a size container,
 * and a container is the containing block of a `position: fixed` inside it.
 * Esc, the backdrop and Close all close; focus goes to Close and back to the
 * button that opened it.
 */
function DetailsDialog({
  row,
  label,
  onClose,
}: {
  row: ReviewRow;
  label: string;
  onClose: () => void;
}) {
  const t = useT();
  const shut = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    shut.current?.focus();
    return () => before?.focus?.();
  }, []);

  return createPortal(
    <div
      className="ag-rev-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        className="ag-rev-modal-card"
        role="dialog"
        aria-modal="true"
        aria-label={label}
      >
        <div className="ag-rev-modal-head">
          <TickerCell ticker={row.ticker} className="ag-rev-modal-who" />
          <button
            ref={shut}
            type="button"
            className="ag-rev-modal-close"
            onClick={onClose}
          >
            {t("review.close")}
          </button>
        </div>
        <Details row={row} />
      </div>
    </div>,
    document.body,
  );
}
