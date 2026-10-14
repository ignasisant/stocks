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
import { useDialog } from "../../shell/useDialog";
import { useExitGhost } from "../../shell/useSheet";
import { useLang, useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { TickerCell } from "../../shell/tickers";
import { Chip, Help } from "../../ui/Kpi";
import { countryName } from "./countries";
import { useHelp } from "./lines";
import {
  OWN_LABEL,
  foreign,
  SHOWN,
  inYears,
  metric,
  money,
  percent,
  pnlChip,
  score,
  verdictTone,
} from "./format";
import type { ReviewRow } from "./types";

/** Catalog copy is markdown-lite; a tooltip is plain text. */
const plain = (text: string) => text.replaceAll("**", "").replaceAll("*", "");

/** A KPI's name: the catalog's, or this page's own for the ones it lacks. */
export function metricLabel(t: ReturnType<typeof useT>, key: string): string {
  return t(OWN_LABEL.has(key) ? `review.metric_${key}` : `kpi.${key}.label`);
}

/** The verdict pill, with the rule that produced it as its hover text. */
export function VerdictChip({ row }: { row: ReviewRow }) {
  const t = useT();
  const help = useHelp();
  return (
    <span className="ag-rev-verdict" title={help(`review.verdict_${row.verdict}_help`)}>
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

/**
 * What the dialog says: the verdict's rule, every reason's, the position as it
 * stands and where the verdict takes it, then every number. `taxCurrency` is
 * the plan's; without it the sale's tax is left out rather than mislabelled.
 */
function Details({ row, taxCurrency }: { row: ReviewRow; taxCurrency?: string }) {
  const t = useT();
  const lang = useLang();
  const base = useCurrency();
  const help = useHelp();
  const na = t("review.na");
  return (
    <div className="ag-rev-details">
      <p className="ag-rev-details-rule">
        <VerdictChip row={row} />
        <span>{help(`review.verdict_${row.verdict}_help`)}</span>
      </p>
      {row.reasons.length > 0 ? (
        <div className="ag-rev-details-group">
          <h3 className="ag-rev-h3">{t("review.details_reasons")}</h3>
          <ul className="ag-rev-why-list">
            {row.reasons.map((code) => (
              <li key={code}>
                <b>{t(`review.reason_${code}`)}</b>
                <span>{help(`review.reason_${code}_help`)}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {row.held || row.delta !== null ? (
        <div className="ag-rev-details-group">
          <h3 className="ag-rev-h3">{t("review.details_position")}</h3>
          <dl className="ag-rev-facts">
            {row.held ? (
              <>
                <Fact
                  label={t("review.col_value")}
                  value={money(row.value, base, lang) ?? na}
                />
                <Fact
                  label={t("review.col_weight")}
                  help={t("review.col_weight_help")}
                  value={percent(row.weight, lang) ?? na}
                />
                <Fact
                  label={t("review.col_pnl")}
                  help={t("review.col_pnl_help")}
                  value={<PnlChip row={row} />}
                />
              </>
            ) : null}
            <Fact
              label={t("review.col_target")}
              help={help("review.col_target_help")}
              value={percent(row.target_weight, lang) ?? "—"}
            />
            <Fact
              label={t("review.col_move")}
              help={t("review.col_move_help")}
              value={money(row.delta, base, lang, true) ?? "—"}
            />
            {taxCurrency && row.held ? (
              <Fact
                label={t("review.col_tax")}
                help={t("review.col_tax_help")}
                value={money(row.tax, taxCurrency, lang) ?? "—"}
              />
            ) : null}
          </dl>
        </div>
      ) : null}
      <div className="ag-rev-details-group">
        <h3 className="ag-rev-h3">{t("review.details_metrics")}</h3>
        <dl className="ag-rev-facts">
          {row.country ? (
            <Fact
              label={t("review.col_country")}
              value={countryName(row.country, lang)}
            />
          ) : null}
          {foreign(row, base) ? (
            <Fact
              label={t("review.col_currency")}
              help={t("review.ccy_tag_help", { currency: row.currency ?? "" })}
              value={row.currency}
            />
          ) : null}
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
          {SHOWN.map((key) => {
            const shown = metric(key, row.metrics[key], lang);
            return (
              <Fact
                key={key}
                label={metricLabel(t, key)}
                help={
                  OWN_LABEL.has(key)
                    ? t(`review.metric_${key}_help`)
                    : plain(t(`kpi.${key}.desc`))
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
  help?: string;
  value: ReactNode;
}) {
  return (
    <div className="ag-rev-fact">
      <dt>
        {label}
        {help ? <Help text={help} /> : null}
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
  taxCurrency,
}: {
  row: ReviewRow;
  variant?: "text" | "icon";
  taxCurrency?: string;
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
      {open ? (
        <DetailsDialog
          row={row}
          label={label}
          taxCurrency={taxCurrency}
          onClose={close}
        />
      ) : null}
    </>
  );
}

/**
 * The dialog itself, portalled to the body: `.ag-main` is a size container,
 * and a container is the containing block of a `position: fixed` inside it.
 * Esc, the backdrop and Close all close; focus goes to Close and back to the
 * button (or map dot) that opened it.
 */
export function DetailsDialog({
  row,
  label,
  taxCurrency,
  onClose,
}: {
  row: ReviewRow;
  label: string;
  taxCurrency?: string;
  onClose: () => void;
}) {
  const t = useT();
  const shut = useRef<HTMLButtonElement>(null);
  const scrim = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const card = useRef<HTMLDivElement>(null);
  useDialog(card, { initial: shut });

  return createPortal(
    <div
      ref={scrim}
      className="ag-rev-modal"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={card}
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
        <Details row={row} taxCurrency={taxCurrency} />
      </div>
    </div>,
    document.body,
  );
}
