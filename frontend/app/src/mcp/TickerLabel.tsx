/**
 * A ticker in the view is a logo and a link, as everywhere in TopStocks.
 *
 * The logo is the server's mirrored copy on the TopStocks origin — the one
 * image source the view's CSP admits — and initials when there is none. The
 * link goes through the host (`ui/open-link`): a sandboxed frame cannot
 * navigate anywhere on its own, and the reader's TopStocks is a tab of its
 * own, not this frame.
 */

import type { Words } from "./types";

export function initials(ticker: string): string {
  return (
    ticker
      .replace(/[^A-Za-z0-9]/g, "")
      .slice(0, 2)
      .toUpperCase() || "?"
  );
}

export function TickerLabel({
  ticker,
  logo,
  words,
}: {
  ticker: string;
  logo?: string | null;
  words: Words;
}) {
  const path = `/ticker?ticker=${encodeURIComponent(ticker)}`;
  return (
    <a
      className="v-tick"
      href={path}
      title={words.t("connector.view_open_ticker", { ticker })}
      onClick={(event) => {
        event.preventDefault();
        words.open(path);
      }}
    >
      {logo ? (
        <img className="v-logo" src={logo} alt="" loading="lazy" />
      ) : (
        <span className="v-logo v-logo-i" aria-hidden="true">
          {initials(ticker)}
        </span>
      )}
      <span className="v-sym">{ticker}</span>
    </a>
  );
}
