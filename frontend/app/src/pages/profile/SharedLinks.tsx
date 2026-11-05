/**
 * The answers and lists this account shared by link, each one takeable down
 * from here.
 *
 * `GET /chat/shares` lists them from the account's own index, so a link
 * whose thread was pruned is still here to stop. Stopping one takes down
 * every link its answer went out under (the masked cut and the open one), so
 * the rows of that answer go together; a list has only its own. A question
 * (a list's name) opens the link itself, which is what a reader of it sees.
 * Draws nothing until there is a link.
 */

import { useState } from "react";
import { listShares, unshare } from "../../chat/api";
import type { ListedShare } from "../../chat/types";
import { ApiError, NotSignedIn } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { signOut } from "../../shell/keep";
import { useApi } from "../../shell/useApi";
import { Badge } from "../../ui/Badge";
import { Failure, Row } from "./ui";

/** The day a link went up, in the reader's language; "" for a bad stamp. */
export function sharedOn(created: string, lang: string): string {
  const when = new Date(created);
  return Number.isNaN(when.getTime())
    ? ""
    : new Intl.DateTimeFormat(lang, { dateStyle: "medium" }).format(when);
}

/** What the block draws for one answer — no fetch, so a test can draw it. */
export function SharedLinkList({
  rows,
  busy,
  failure,
  onStop,
}: {
  rows: ListedShare[];
  busy: string | null;
  failure: string | null;
  onStop: (row: ListedShare) => void;
}) {
  const t = useT();
  const lang = useLang();
  return (
    <Row label={t("profile.shares_title")} help={t("profile.shares_help")}>
      <ul className="pr-conns">
        {rows.map((row) => {
          const date = sharedOn(row.created, lang);
          return (
            <li className="pr-conn" key={row.id}>
              <div className="pr-conn-l">
                <a
                  className="pr-share-q"
                  href={`/?share=${encodeURIComponent(row.id)}`}
                >
                  {row.question}
                </a>
                <span className="pr-conn-meta pr-share-meta">
                  {date && t("profile.shares_on", { date })}
                  {row.masked && <Badge>{t("profile.shares_masked")}</Badge>}
                  {row.kind === "watchlist" && (
                    <Badge>{t("profile.shares_list")}</Badge>
                  )}
                </span>
              </div>
              <button
                type="button"
                className="pr-btn"
                disabled={busy !== null}
                onClick={() => onStop(row)}
              >
                {t("profile.shares_stop")}
              </button>
            </li>
          );
        })}
      </ul>
      <Failure message={failure} />
    </Row>
  );
}

/** What a taken-down row takes with it: every link of its answer, or a list
 *  alone (a list has no answer, and all of them share the empty one). */
const goesWith = (row: ListedShare) =>
  row.kind === "watchlist" ? `list:${row.id}` : row.answer_id;

export function SharedLinks() {
  const t = useT();
  const query = useApi(listShares, []);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());

  if (query.state !== "loaded") return null;
  const rows = query.data.filter((r) => !gone.has(goesWith(r)));
  if (rows.length === 0) return null;

  const stopped = (row: ListedShare) => {
    setBusy(null);
    setGone((prev) => new Set(prev).add(goesWith(row)));
  };

  const stop = (row: ListedShare) => {
    setBusy(row.id);
    setFailure(null);
    unshare(row.id).then(
      () => stopped(row),
      (error: unknown) => {
        if (error instanceof NotSignedIn) {
          setBusy(null);
          void signOut();
          return;
        }
        // 404: already down — gone is what was asked for.
        if (error instanceof ApiError && error.status === 404) {
          stopped(row);
          return;
        }
        setBusy(null);
        setFailure(
          error instanceof ApiError ? t("profile.shares_failed") : t("common.offline"),
        );
      },
    );
  };

  return <SharedLinkList rows={rows} busy={busy} failure={failure} onStop={stop} />;
}
