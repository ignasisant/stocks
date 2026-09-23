/**
 * Market pulse — one screen, read in five seconds, thirty, or three minutes.
 *
 * The same information ranked by how much of it a reader actually needs:
 *
 * * **Five seconds.** The hero: the composite score, its band, how long it has
 *   held that band, and beside it one sentence joining the regime to the book,
 *   plus the three figures that carry most of it (equity beta, correlation
 *   with the long bond, dollar share).
 * * **Thirty seconds.** Why: the composite's eight inputs with their own
 *   direction and level, and what the score is missing.
 * * **Three minutes.** The detail: the seven long tables — indices, gauges,
 *   rates, inflation, rotation, factor pairs, cross-asset — behind one tab
 *   strip, so nothing is lost and the scroll is one card instead of seven.
 *
 * **Direction over level.** A 10-year yield at 4.79% is a fact; "+33bp over
 * three months while the curve went nowhere" is the reading, and a smooth
 * drift and a spike-and-round-trip land on the identical three-month delta,
 * which is what the sparkline is for.
 *
 * **Personalisation is the point, not a decoration.** A VIX percentile is the
 * same number for everyone; "your book is 71% dollar-priced and the dollar
 * fell 1.2% this month" is not. So the hero's right half is the reader's own,
 * the indices are reordered by the geography they hold and say which of their
 * money sits there, and the rotation rows carry their own sector weights.
 *
 * **Every block degrades on its own.** Three endpoints, three queries, three
 * independent states: Yahoo throttles datacenter IPs and FRED tarpits some
 * user agents, so a failed fetch keeps its heading and says which source died
 * instead of taking the page down.
 */

import { get } from "../../shell/api";
import { useApi } from "../../shell/useApi";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { useCurrency } from "../../shell/session";
import { Composite, Side } from "./Hero";
import { Why } from "./Why";
import { Book } from "./Book";
import { SignInWall } from "../../shell/guest";
import { useGuest } from "../../shell/session";
import { Snapshot } from "./Snapshot";
import { Detail } from "./Detail";
import type { Pulse, PulseBook, TrendTables } from "./types";
import "./sentiment.css";

/** `macro.as_of()`'s own spelling, so the caption reads the same on both apps. */
function stamp(): string {
  return `${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC`;
}

/**
 * On a phone the four sections are four full screens, so a strip that jumps
 * between them earns its place; on a desktop they are within one scroll and it
 * would be chrome for its own sake. The stylesheet hides it there.
 */
function Jump() {
  const t = useT();
  const links: [string, string][] = [
    ["ag-pulse", "sentiment.jump_summary"],
    ["ag-why", "sentiment.jump_why"],
    ["ag-book", "sentiment.jump_book"],
    ["ag-detail", "sentiment.jump_detail"],
  ];
  return (
    <div className="sn-jump">
      {links.map(([anchor, key]) => (
        <a href={`#${anchor}`} key={anchor}>
          {t(key)}
        </a>
      ))}
    </div>
  );
}

export default function Page() {
  const t = useT();
  const base = useCurrency();
  const pulse = useApi(() => get<Pulse>("/pulse"), []);
  const guest = useGuest();
  // Not fetched for a guest, and this is the one place in the app where that
  // is a claim about honesty rather than about cost. `/pulse/book` is the
  // regime projected onto a holder's own positions — a beta, a dollar share —
  // and over the shared demo ledger it would compute perfectly well and mean
  // nothing: invented trades reading as this reader's exposure. `sentiment.py`
  // draws `_side_invite` here for exactly the same reason, and calls the
  // skipped call "stage 1 speed" on top of it.
  const book = useApi(
    () =>
      guest
        ? Promise.resolve<PulseBook | null>(null)
        : get<PulseBook>("/pulse/book", { base }),
    [base, guest],
  );
  const tables = useApi(() => get<TrendTables>("/pulse/tables"), []);

  // The lede in the hero's right half names the band, and the band comes from
  // the other query. Until it lands there is no reading, which is a state the
  // catalogs already have a word for.
  const regime = pulse.state === "loaded" ? pulse.data.regime : "unknown";
  // The rotation table reads better with the reader's own capture under it,
  // and it is the only figure the detail card borrows from the book query —
  // absent until that one lands, which is a caption short, not a wrong number.
  const capture =
    book.state === "loaded" ? (book.data?.rotation_capture ?? null) : null;
  // The book card's sentence about which of the reader's own sectors is
  // leading needs the sectors' excess returns, which ride on the tables query
  // rather than on the book's. Null until it lands: a sentence short, not a
  // sentence guessed.
  const rotation =
    tables.state === "loaded"
      ? (tables.data.blocks.find((entry) => entry.block === "rotation") ?? null)
      : null;

  return (
    <div className="sn-page">
      <h1 className="sn-title">{t("sentiment.title")}</h1>
      <Jump />

      <section className="sn-card sn-hero" id="ag-pulse">
        <div className="sn-hero-l">
          <Loaded query={pulse} skeleton={<Skeleton rows={6} />}>
            {(data) => <Composite pulse={data} />}
          </Loaded>
        </div>
        <div className="sn-hero-r">
          {/* Where `sentiment.py` draws `_side_invite`: there is no honest
              version of this panel without the reader's own book, so it says
              what it would show and offers the one step that would fill it. */}
          {guest ? (
            <SignInWall
              text="sentiment.book_signed_out"
              note="sentiment.book_signed_out_note"
              cta="sentiment.book_signin_cta"
            />
          ) : (
            <Loaded query={book} skeleton={<Skeleton rows={4} />}>
              {(data) => (data ? <Side book={data} regime={regime} /> : null)}
            </Loaded>
          )}
        </div>
      </section>

      {/* Two queries in one card, each drawing when it lands: the eight inputs
          come from the composite and the snapshot below them is read off the
          detail tables, and neither is a reason to hold the other back.

          The snapshot needs both — its breadth counts and the stock/bond
          correlation ride on the composite's own call, the rates quadrant on
          the tables — so it is the one block that waits for the pair. It waits
          on the tables outside and reads the composite through its own
          `Loaded` rather than holding the eight inputs above it hostage. */}
      <section className="sn-card">
        <Loaded query={pulse} skeleton={<Skeleton rows={8} />}>
          {(data) => <Why pulse={data} />}
        </Loaded>
        <Loaded query={tables} skeleton={<Skeleton rows={3} />}>
          {(loadedTables) => (
            <Loaded query={pulse} skeleton={<Skeleton rows={3} />}>
              {(loadedPulse) => <Snapshot pulse={loadedPulse} tables={loadedTables} />}
            </Loaded>
          )}
        </Loaded>
      </section>

      {/* Nothing at all for a guest rather than a second sign-in prompt: the
          hero above already said it once, and this card is the same projection
          of the same regime onto the same absent book. */}
      {guest ? null : (
        <section className="sn-card">
          <Loaded query={book} skeleton={<Skeleton rows={5} />}>
            {(data) => (data ? <Book book={data} rotation={rotation} /> : null)}
          </Loaded>
        </section>
      )}

      <section className="sn-card">
        <Loaded query={tables} skeleton={<Skeleton rows={10} />}>
          {(data, reload) => (
            <Detail tables={data} capture={capture} onRetry={reload} />
          )}
        </Loaded>
      </section>

      <p className="sn-caption">{t("sentiment.sources", { stamp: stamp() })}</p>
    </div>
  );
}
