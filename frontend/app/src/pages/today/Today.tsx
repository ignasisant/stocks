/**
 * Today — the day's front page: what happened, and whether anything needs
 * doing, in five seconds; the detail behind each line in three minutes.
 *
 * Two layers with two lifetimes (`api/routes/today.py`):
 *
 * - **The market**, the same for everyone and written once a morning: rates,
 *   the Fed and the ECB, inflation, the risk regime, which sectors lead and
 *   which trail, crypto sentiment. It is on screen the moment the page opens.
 * - **Yours**, written when you open it: the alerts that fired, your book
 *   against the index, what you asked the card to tell you, news, filings and
 *   insider trades on your names, and each position against its sector and
 *   the S&P 500 with the Review page's verdict. Until it lands a status line
 *   says it is being written; the market half never waits for it.
 *
 * Read like a newspaper: a mono dateline, one headline as the focal point,
 * figures in tiles, then the sections in a fixed order — what to act on,
 * then what is yours (your names against their benchmarks, news and insider
 * trades on them), then the market — the market in a narrower column of its
 * own where the page is wide. A tab strip narrows it to one section; `?tab=`
 * makes that a link. A section with nothing in it is not drawn and not
 * offered as a tab. Under All a long list shows its first few rows and how
 * many more its own tab holds.
 *
 * Each card line with a trigger behind it opens its analysis in place, as on
 * Home. Rows the server computed (news, insiders, comparisons) are set as
 * they were read, with their source and day, and link out to the article or
 * filing.
 */

import { useState } from "react";
import { openAssistant, openThread } from "../../shell/assistant";
import { SignInWall } from "../../shell/guest";
import { useLang, useT } from "../../shell/i18n";
import { Skeleton } from "../../shell/Layout";
import { useRoute } from "../../shell/router";
import { useGuest } from "../../shell/session";
import { Tabs } from "../../ui/Tabs";
import { Glyph } from "../../chat/icons";
import { Badge } from "../../ui/Badge";
import { Status } from "../../ui/Status";
import { BriefEditor } from "../home/BriefEditor";
import { monthDay, parseDay } from "../home/format";
import { stampKey, useAnalyses } from "./Analysis";
import { BookChart, BookKpis, IndexKpis, SectionChart } from "./Book";
import {
  TAB_LABELS,
  activeTab,
  badgeKey,
  linesOf,
  noteKey,
  sectionOf,
  sectionsOf,
  shows,
  stampOf,
  tabsOf,
  type TabId,
} from "./card";
import { Compare } from "./Compare";
import { Macro, Trends } from "./Market";
import { Block, Lines, Rows } from "./Section";
import type { PersonalCard, TodayCard, TodaySection } from "./types";
import { useToday } from "./useToday";
import "../home/home.css";
import "./today.css";

/** "Tuesday, 13 October" in the reader's language. */
function longDay(iso: string, lang: string): string {
  const day = parseDay(iso);
  if (!day) return iso;
  return new Intl.DateTimeFormat(lang, {
    weekday: "long",
    day: "numeric",
    month: "long",
  }).format(day);
}

/** One of the header's controls: an icon, its name as label and tooltip. */
function IconButton({
  icon,
  label,
  onClick,
  disabled,
  pressed,
}: {
  icon: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  pressed?: boolean;
}) {
  return (
    <button
      type="button"
      className="td-icon-btn"
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
    >
      <Glyph name={icon} size={17} />
    </button>
  );
}

/** How many rows a computed section shows under All; its own tab has them all. */
const FRONT_ROWS = 4;

/** A computed section of the card (news, insiders), or nothing to draw. */
function Computed({
  section,
  title,
  help,
  onMore,
}: {
  section: TodaySection | null;
  title: string;
  help: string;
  /** Open the section's own tab; set only under All, where the list is cut. */
  onMore?: () => void;
}) {
  if (!section || (!section.rows.length && !section.missing.length)) return null;
  return (
    <Block
      id={section.id}
      title={title}
      count={section.rows.length}
      help={help}
      note={section.note}
      missing={section.missing}
    >
      {section.rows.length ? (
        <Rows
          rows={section.rows}
          limit={onMore ? FRONT_ROWS : undefined}
          onMore={onMore}
        />
      ) : null}
    </Block>
  );
}

export default function Today() {
  const t = useT();
  const lang = useLang();
  const guest = useGuest();
  const { params, setParams } = useRoute();
  const { state, regenerate, restart } = useToday(lang, guest);
  const [editing, setEditing] = useState(false);

  // The card on screen: none while today's is being written for the first
  // time (an older one is not what the reader came for), none for a guest.
  const shown: PersonalCard | null =
    state.kind === "ready" && !state.writing ? state.view.personal : null;
  const { panels, toggle } = useAnalyses(stampKey(shown));

  if (state.kind === "loading") {
    return (
      <div className="td-page" aria-busy="true">
        <h1 className="td-dateline">{t("nav.today")}</h1>
        <Skeleton rows={6} />
      </div>
    );
  }
  if (state.kind === "failed") {
    return (
      <div className="td-page">
        <h1 className="td-dateline">{t("nav.today")}</h1>
        <div className="td-empty">
          <p className="hm-note">{t("today.failed")}</p>
          <button type="button" className="ag-btn" onClick={restart}>
            {t("today.retry")}
          </button>
        </div>
      </div>
    );
  }

  const { view, writing } = state;
  const market = view.market;
  // Nothing to brief on (no positions and no watchlist): the card is not
  // drawn, and the market is the page.
  const card = shown && (shown.headline || shown.pending) ? shown : null;
  const regenerating = Boolean(card && !card.headline);
  const busy = writing || regenerating || Boolean(card?.pending);
  const visible: Pick<TodayCard, "market" | "personal"> = {
    market,
    personal: regenerating ? null : card,
  };
  const tabs = tabsOf(visible);
  const active = activeTab(tabs, params.get("tab"));
  const pick = (tab: TabId) => setParams({ tab: tab === "all" ? undefined : tab });

  const lines = card ? linesOf(card) : [];
  const { alerts, watch } = sectionsOf(lines);
  const brief = card?.sections ?? [];
  const book = card?.book?.rows.length ? card.book : null;
  // Not while a briefing is still being written: the stand-in on screen is
  // about to be replaced, and its lines with it.
  const canOpen = Boolean(card) && !regenerating && !card?.pending;
  const note = card && !regenerating ? noteKey(card) : null;
  const headline = card?.headline || market?.headline || null;
  const lineProps = { canOpen, panels, toggle };

  const badge = card
    ? { key: badgeKey(card), brand: badgeKey(card) === "home.daily_badge" }
    : market
      ? {
          key:
            market.source === "llm"
              ? "today.market_badge"
              : "today.market_badge_computed",
          brand: market.source === "llm",
        }
      : null;

  const session = market ? monthDay(market.session, t) : null;
  const tools = card ? (
    <div className="td-tools">
      <IconButton
        icon="edit"
        label={t("home.daily_edit")}
        pressed={editing}
        disabled={regenerating}
        onClick={() => setEditing((was) => !was)}
      />
      <IconButton
        icon="refresh"
        label={t("home.daily_refresh")}
        // Disabled while its own rewrite is out: a second press would spend a
        // second unit of the allowance on a card already being written.
        disabled={busy || editing}
        onClick={regenerate}
      />
      <IconButton
        icon="forum"
        label={t("home.daily_ask")}
        onClick={() => (card.thread ? openThread(card.thread) : openAssistant())}
      />
    </div>
  ) : null;

  const compare = card ? sectionOf(card, "compare") : null;
  const front = active === "all";
  const yours = (
    <>
      {shows(active, "alerts") && alerts.length ? (
        <Block id="alerts" title={t("home.daily_sec_alerts")} count={alerts.length}>
          <Lines items={alerts} {...lineProps} />
        </Block>
      ) : null}
      {shows(active, "routines")
        ? brief.map((section, n) => (
            <Block key={n} id={`brief-${n}`} title={section.title}>
              {section.lines.length ? (
                <Lines items={section.lines} {...lineProps} />
              ) : null}
              <SectionChart section={section} />
            </Block>
          ))
        : null}
      {shows(active, "book") && book ? (
        <Block id="book" title={t("home.daily_sec_book")} help={t("today.book_help")}>
          <BookChart book={book} />
        </Block>
      ) : null}
      {shows(active, "book") && !brief.length && watch.length ? (
        <Block id="watch" title={t("home.daily_sec_watch")}>
          <Lines items={watch} {...lineProps} />
        </Block>
      ) : null}
      {shows(active, "compare") && compare?.rows.length ? (
        <Block
          id="compare"
          title={t("today.section_compare")}
          help={t("today.compare_help")}
          note={compare.note}
          missing={compare.missing}
        >
          <Compare rows={compare.rows} />
        </Block>
      ) : null}
      {shows(active, "news") ? (
        <Computed
          section={sectionOf(card, "news")}
          title={t("today.section_news")}
          help={t("today.news_help")}
          onMore={front ? () => pick("news") : undefined}
        />
      ) : null}
      {shows(active, "insiders") ? (
        <Computed
          section={sectionOf(card, "insiders")}
          title={t("today.section_insiders")}
          help={t("today.insiders_help")}
          onMore={front ? () => pick("insiders") : undefined}
        />
      ) : null}
    </>
  );

  const context = (
    <>
      {shows(active, "macro") && market ? (
        <Block id="macro" title={t("today.sec_macro")} help={t("today.macro_help")}>
          <Macro market={market} />
        </Block>
      ) : null}
      {shows(active, "trends") && market ? (
        <Block id="trends" title={t("today.sec_trends")} help={t("today.trends_help")}>
          <Trends market={market} />
        </Block>
      ) : null}
    </>
  );

  return (
    <div className="td-page" aria-busy={busy}>
      <header className="td-head">
        <div className="td-top">
          <h1 className="td-dateline">
            {t("nav.today")} · {longDay(card?.day ?? view.action_day, lang)}
            {session ? (
              <span className="td-session">
                {" "}
                · {t("today.dateline", { date: session })}
              </span>
            ) : null}
          </h1>
          {tools}
        </div>
        {badge ? (
          <div className="td-byline">
            <Badge tone={badge.brand ? "brand" : "neutral"}>{t(badge.key)}</Badge>
            {card && !regenerating ? (
              <span className="td-stamp">{stampOf(card, t)}</span>
            ) : null}
          </div>
        ) : null}
        {/* Said before the headline: a fallback read as the AI's answer
            first, or yesterday's card read as today's, is already misread by
            the time a note at the foot of the page comes. */}
        {note ? (
          <p className="hm-note" role="status">
            {t(note)}
          </p>
        ) : null}
        {card && !card.fresh && !card.pending ? (
          <p className="hm-note">
            {t("home.daily_stale", {
              date: monthDay(card.day ?? card.action_day, t) ?? "",
            })}
          </p>
        ) : null}
        {market && view.market_stale && session ? (
          <p className="hm-note">{t("today.market_stale", { date: session })}</p>
        ) : null}
        {headline && !regenerating ? <p className="td-headline">{headline}</p> : null}
        {writing || regenerating ? (
          <Status label={t("today.writing")} />
        ) : card?.pending ? (
          <Status label={t("home.daily_pending")} />
        ) : null}
        {!market && view.market_stale ? (
          <Status label={t("today.market_wait")} />
        ) : null}
      </header>

      {editing ? (
        <div className="hm-card">
          <BriefEditor
            onClose={(changed) => {
              setEditing(false);
              if (changed) restart();
            }}
          />
        </div>
      ) : (
        <>
          {book ? (
            <BookKpis book={book} />
          ) : market?.index ? (
            <IndexKpis index={market.index} />
          ) : null}

          {tabs.length > 1 ? (
            <Tabs
              items={tabs.map((tab) => ({
                id: tab.id,
                label: t(TAB_LABELS[tab.id]),
                count: tab.count,
              }))}
              active={active}
              onPick={pick}
            />
          ) : null}

          {writing || regenerating ? <Skeleton rows={3} /> : null}

          <div
            className={active === "all" ? "td-body td-body-two" : "td-body"}
            role="tabpanel"
          >
            <div className="td-col">{yours}</div>
            <div className="td-col td-side">{context}</div>
          </div>

          {guest ? <SignInWall text="today.guest_wall" /> : null}
          {!guest && !card && !writing && !busy ? (
            <p className="hm-note td-empty">{t("today.empty")}</p>
          ) : null}
          {!market && !view.market_stale ? (
            <p className="hm-note">{t("today.market_none")}</p>
          ) : null}
          {(card && !note && !card.pending) || market?.source === "llm" ? (
            <p className="hm-note">{t("home.daily_disclaimer")}</p>
          ) : null}
        </>
      )}
    </div>
  );
}
