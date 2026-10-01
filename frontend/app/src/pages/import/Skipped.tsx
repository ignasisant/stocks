/**
 * The rows the parser left out, one group per reason (`skips.ts`).
 *
 * A group is its reason in the reader's words — what kind of row, why it
 * stayed out — and the broker's own word for the rows (`CASH TOP-UP`), so the
 * statement can be checked against it. One that leaves a step to take by hand
 * says so, comes first, and lists its rows; any other folds a long list behind
 * one line, because twenty-six top-ups are one fact and not twenty-six.
 *
 * A row is one line: the day, what it was about, the amount. Fields a parser
 * keeps beyond those still print, labelled, rather than vanish.
 */

import { useT } from "../../shell/i18n";
import { TickerCell } from "../../shell/tickers";
import type { SkippedRow } from "./api";
import { OTHER, extras, figure, groupSkips, located, splitReason } from "./skips";
import type { SkipGroup } from "./skips";
import { useVocabulary } from "./text";

/** Rows a group lists before folding them behind one line. */
const INLINE = 3;

export function SkippedGroups({ rows }: { rows: SkippedRow[] }) {
  return (
    <div className="im-skip-groups">
      {groupSkips(rows).map((group, index) => (
        <Group group={group} id={`im-skip-${index}`} key={group.stem ?? group.reason} />
      ))}
    </div>
  );
}

function Group({ group, id }: { group: SkipGroup; id: string }) {
  const t = useT();
  const vocab = useVocabulary();
  const [title, note] = group.stem
    ? [t(group.stem), t(`${group.stem}_note`)]
    : splitReason(group.reason);
  // The strays' group is the one whose rows each carry their own reason, and
  // a row about the file itself is nothing but that reason.
  const strays = group.stem === OTHER;
  const listed = strays ? group.rows : group.rows.filter(located);
  const mixed = group.types.length > 1;
  const fold = !group.manual && listed.length > INLINE;
  const span =
    group.span &&
    (group.span[0] === group.span[1] ? group.span[0] : group.span.join(" – "));
  const meta = [
    ...group.types.map(([type, n]) => (mixed ? `${vocab.num(n, 0)} × ${type}` : type)),
    fold ? span : null,
  ].filter((item): item is string => Boolean(item));
  const list = <SkipRows rows={listed} reasons={strays} types={mixed} />;

  return (
    <section
      aria-labelledby={`${id}-title`}
      className={group.manual ? "im-skip-group im-skip-manual" : "im-skip-group"}
    >
      <header className="im-skip-head">
        <h4 className="im-skip-title" id={`${id}-title`}>
          {title}
          <span className="im-skip-n">{vocab.num(group.rows.length, 0)}</span>
        </h4>
        {group.manual && (
          <span className="im-tag im-tag-warn">{t("import.skip_tag_manual")}</span>
        )}
      </header>
      {note && <p className="im-fine">{note}</p>}
      {meta.length > 0 && (
        <p className="im-skip-meta">
          {/* Each item whole: a line may break between them, never inside. */}
          {meta.map((item, at) => (
            <span key={item}>
              {at ? " · " : null}
              <span className="im-nowrap">{item}</span>
            </span>
          ))}
        </p>
      )}
      {listed.length > 0 &&
        (fold ? (
          <details className="im-skip-more">
            <summary>{vocab.tn("import.skip_rows", listed.length)}</summary>
            {list}
          </details>
        ) : (
          list
        ))}
    </section>
  );
}

function SkipRows({
  rows,
  reasons,
  types,
}: {
  rows: SkippedRow[];
  /** Print each row's own reason: its group's heading does not say it. */
  reasons: boolean;
  /** Print each row's type: its group holds more than one. */
  types: boolean;
}) {
  const vocab = useVocabulary();
  return (
    <ul className="im-skip-rows">
      {rows.map((row, index) => {
        const amount = figure(row.amount);
        const quantity = figure(row.quantity);
        const what = [
          types && row.type ? String(row.type) : null,
          row.ticker ? (
            // The house rule: a symbol on screen is its logo and its page.
            <TickerCell className="im-tick" name={false} ticker={String(row.ticker)} />
          ) : null,
          quantity
            ? `${vocab.column("quantity")} ${vocab.num(quantity, Number.isInteger(quantity) ? 0 : 4)}`
            : null,
          ...extras(row).map(
            ([field, value]) => `${vocab.column(field)} ${String(value)}`,
          ),
          reasons && row.reason ? String(row.reason) : null,
        ].filter((item) => item !== null);
        return (
          <li className="im-skip-row" key={`${String(row.row)}-${index}`}>
            <span className="im-skip-date">
              {row.date ? String(row.date).slice(0, 10) : ""}
            </span>
            <span className="im-skip-what">
              {what.map((item, at) => (
                <span key={at}>
                  {at ? " · " : null}
                  {item}
                </span>
              ))}
            </span>
            <span className="im-skip-amount">
              {amount
                ? `${vocab.num(amount, 2)} ${String(row.currency ?? "")}`.trim()
                : ""}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
