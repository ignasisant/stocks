/**
 * The browsers signed in to this account, each one endable from here.
 *
 * `GET /account/sessions` lists them (the caller's own marked); a row's button
 * ends that session on the server, so its cookie stops working on its next
 * request, and one more button ends every session but this one. The list is
 * the server's: after a press it is asked again rather than patched, so what
 * the reader sees is what the server now holds. "Last active" is coarse on
 * purpose (a few minutes); there is no address or place, because the host
 * gives us neither.
 */

import { useState } from "react";
import { ApiError, NotSignedIn, get, send } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { signOut } from "../../shell/keep";
import { useApi } from "../../shell/useApi";
import { Badge } from "../../ui/Badge";
import { Failure, Row } from "./ui";

/** `GET /account/sessions` — `routes.account.SessionRow`. */
export type SessionRow = {
  id: string;
  device: string;
  created: number;
  seen: number;
  current: boolean;
};

/** How long ago, in the reader's language; "now" inside the coarse window. */
export function ago(seen: number, lang: string, now = Date.now() / 1000): string {
  const secs = Math.max(0, now - seen);
  const fmt = new Intl.RelativeTimeFormat(lang, { numeric: "auto" });
  if (secs < 600) return fmt.format(0, "second");
  if (secs < 3600 * 2) return fmt.format(-Math.round(secs / 60), "minute");
  if (secs < 86400 * 2) return fmt.format(-Math.round(secs / 3600), "hour");
  return fmt.format(-Math.round(secs / 86400), "day");
}

/** What the block draws for one answer — no fetch, so a test can draw it. */
export function SessionList({
  rows,
  busy,
  failure,
  onEnd,
  onEndOthers,
}: {
  rows: SessionRow[];
  busy: string | null;
  failure: string | null;
  onEnd: (id: string) => void;
  onEndOthers: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const others = rows.filter((r) => !r.current);
  return (
    <Row label={t("profile.sessions_title")} help={t("profile.sessions_help")}>
      <ul className="pr-conns">
        {rows.map((row) => (
          <li className="pr-conn" key={row.id}>
            <div className="pr-conn-l">
              <span className="pr-conn-name">
                {row.device || t("profile.sessions_unknown")}
                {row.current && <Badge>{t("profile.sessions_this")}</Badge>}
              </span>
              <span className="pr-conn-meta">
                {t("profile.sessions_active", { when: ago(row.seen, lang) })}
              </span>
            </div>
            {!row.current && (
              <button
                type="button"
                className="pr-btn"
                disabled={busy !== null}
                onClick={() => onEnd(row.id)}
              >
                {t("profile.sessions_end")}
              </button>
            )}
          </li>
        ))}
      </ul>
      {others.length > 0 && (
        <button
          type="button"
          className="pr-btn"
          disabled={busy !== null}
          onClick={onEndOthers}
        >
          {t("profile.sessions_end_others")}
        </button>
      )}
      <Failure message={failure} />
    </Row>
  );
}

export function Sessions() {
  const t = useT();
  const query = useApi(() => get<{ sessions: SessionRow[] }>("/account/sessions"), []);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());

  if (query.state !== "loaded") return null;
  const rows = query.data.sessions.filter((r) => !gone.has(r.id));
  if (rows.length === 0) return null;

  const run = (
    key: string,
    call: Promise<unknown>,
    ended: (ids: Set<string>) => void,
  ) => {
    setBusy(key);
    setFailure(null);
    call.then(
      () => {
        setBusy(null);
        setGone((prev) => {
          const next = new Set(prev);
          ended(next);
          return next;
        });
      },
      (error: unknown) => {
        setBusy(null);
        if (error instanceof NotSignedIn) {
          void signOut();
          return;
        }
        // 404: already ended elsewhere — gone is what was asked for.
        if (error instanceof ApiError && error.status === 404) {
          setGone((prev) => new Set(prev).add(key));
          return;
        }
        setFailure(
          error instanceof ApiError
            ? t("profile.sessions_failed")
            : t("common.offline"),
        );
      },
    );
  };

  return (
    <SessionList
      rows={rows}
      busy={busy}
      failure={failure}
      onEnd={(id) =>
        run(
          id,
          send<unknown>(
            "DELETE",
            `/account/sessions/${encodeURIComponent(id)}`,
            undefined,
            {
              touches: ["/account"],
            },
          ),
          (s) => s.add(id),
        )
      }
      onEndOthers={() =>
        run(
          "others",
          send<unknown>("DELETE", "/account/sessions/others", undefined, {
            touches: ["/account"],
          }),
          (s) => rows.filter((r) => !r.current).forEach((r) => s.add(r.id)),
        )
      }
    />
  );
}
