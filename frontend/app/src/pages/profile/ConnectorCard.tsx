/**
 * TopStocks inside Claude: the address to paste, how to paste it, and every
 * app this account has let in — each one revocable from here.
 *
 * The address is the server's to give (`GET /connections` `url`), not built
 * here from `location`: the connector answers on the one public origin its
 * tokens name, and a page opened through another hostname would hand out an
 * address the tokens are not bound to. Without one the connector is off on
 * this deployment, and the card draws only what is still connected — a grant
 * from before stays revocable whatever happened to the door.
 *
 * Revoking ends the grant on the server at once; an app holding a token from
 * it gets a 401 on its next call. Signing out of TopStocks does not: those
 * apps never used the browser's session in the first place, and the card says
 * so, because the opposite is what anyone would assume.
 */

import { useEffect, useState } from "react";
import { ApiError, NotSignedIn, get, send } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { useApi } from "../../shell/useApi";
import { Badge } from "../../ui/Badge";
import { Card, Failure, Prose, Row } from "./ui";

/** `GET /connections` — `routes.connections.Connection`. */
export type Connection = {
  id: string;
  client_name: string;
  verified: boolean;
  redirect_host: string;
  created: string;
  used: string | null;
  expires: string;
};

export type Connections = { url: string | null; connections: Connection[] };

/** The one line Claude Code needs. */
export function command(url: string): string {
  return `claude mcp add --transport http topstocks ${url}`;
}

/** A timestamp as a day the reader can place, in their own language. */
export function day(iso: string | null, lang: string): string | null {
  if (!iso) return null;
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return null;
  return new Intl.DateTimeFormat(lang, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

/** Text onto the clipboard, and two seconds of saying so. */
function Copy({ text, label }: { text: string; label: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const timer = setTimeout(() => setDone(false), 2000);
    return () => clearTimeout(timer);
  }, [done]);
  return (
    <button
      type="button"
      className="pr-btn"
      aria-label={label}
      // No clipboard outside a secure context; the text is on screen to
      // select by hand, so the press simply does nothing there.
      onClick={() =>
        void navigator.clipboard?.writeText(text).then(
          () => setDone(true),
          () => undefined,
        )
      }
    >
      {done ? t("profile.connector_copied") : t("profile.connector_copy")}
    </button>
  );
}

function Line({ connection, onGone }: { connection: Connection; onGone: () => void }) {
  const t = useT();
  const lang = useLang();
  const [busy, setBusy] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);

  const revoke = () => {
    setBusy(true);
    setRefused(null);
    send<void>("DELETE", `/connections/${encodeURIComponent(connection.id)}`).then(
      onGone,
      (error: unknown) => {
        setBusy(false);
        if (error instanceof NotSignedIn) {
          window.location.assign("/auth/logout");
          return;
        }
        // 404 is a grant that already ended — revoked from another tab, or
        // spent by a replayed refresh token. Either way it is gone, which is
        // what the reader asked for.
        if (error instanceof ApiError && error.status === 404) {
          onGone();
          return;
        }
        setRefused(
          error instanceof ApiError
            ? t("profile.connector_revoke_failed")
            : t("common.offline"),
        );
      },
    );
  };

  const used = day(connection.used, lang);
  return (
    <li className="pr-conn">
      <div className="pr-conn-l">
        <span className="pr-conn-name">
          {connection.client_name}
          {!connection.verified && (
            <Badge title={t("profile.connector_unverified_help")}>
              {t("profile.connector_unverified")}
            </Badge>
          )}
        </span>
        <span className="pr-conn-meta">
          {t("profile.connector_returns_to", { host: connection.redirect_host })}
        </span>
        <span className="pr-conn-meta">
          {t("profile.connector_since", { date: day(connection.created, lang) ?? "" })}
          {" · "}
          {used
            ? t("profile.connector_used", { date: used })
            : t("profile.connector_never_used")}
        </span>
        <Failure message={refused} />
      </div>
      <button type="button" className="pr-btn" disabled={busy} onClick={revoke}>
        {t("profile.connector_revoke")}
      </button>
    </li>
  );
}

export function ConnectorCard() {
  const query = useApi(() => get<Connections>("/connections"), []);
  // Revoked here, gone from the list without a refetch; the next load agrees.
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());

  if (query.state !== "loaded") return null;
  return (
    <Connector
      url={query.data.url}
      connections={query.data.connections.filter((c) => !gone.has(c.id))}
      onGone={(id) => setGone((prev) => new Set(prev).add(id))}
    />
  );
}

/** What the card draws for one answer — no fetch, so a test can draw it. */
export function Connector({
  url,
  connections,
  onGone,
}: Connections & { onGone: (id: string) => void }) {
  const t = useT();
  if (!url && connections.length === 0) return null;

  return (
    <Card title={t("profile.connector_title")} sub={t("profile.connector_sub")}>
      {url && (
        <>
          <Row
            label={t("profile.connector_url")}
            help={t("profile.connector_url_help")}
          >
            <div className="pr-copyline">
              <code className="pr-code">{url}</code>
              <Copy text={url} label={t("profile.connector_copy_url")} />
            </div>
          </Row>
          <Row label={t("profile.connector_how")}>
            <Prose text={t("profile.connector_how_app")} />
            <span className="pr-hint">{t("profile.connector_how_code")}</span>
            <div className="pr-copyline">
              <code className="pr-code">{command(url)}</code>
              <Copy text={command(url)} label={t("profile.connector_copy_command")} />
            </div>
          </Row>
        </>
      )}
      <Row
        label={t("profile.connector_list")}
        help={t("profile.connector_logout_note")}
      >
        {connections.length === 0 ? (
          <span className="pr-muted">{t("profile.connector_none")}</span>
        ) : (
          <ul className="pr-conns">
            {connections.map((connection) => (
              <Line
                key={connection.id}
                connection={connection}
                onGone={() => onGone(connection.id)}
              />
            ))}
          </ul>
        )}
      </Row>
    </Card>
  );
}
