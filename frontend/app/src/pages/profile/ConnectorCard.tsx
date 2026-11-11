/**
 * TopStocks inside any MCP app: the address to paste, how each app takes it,
 * and every app this account has let in — each one revocable from here.
 *
 * The server is plain MCP over HTTP with OAuth (dynamic registration, https or
 * loopback redirects), so no app is special-cased on the server: Claude,
 * ChatGPT, Codex and the rest differ only in where the address goes, which is
 * all `APPS` holds.
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
 *
 * It is also the one place anyone learns how to connect, so it reports how it
 * is used (`stocks logs connector`): the first read names where the reader
 * came from (`?from=`), and each copy says which line was copied, for which
 * app. Coming back from the app refetches, so a connection made there turns
 * into "connected" here without a reload.
 */

import { useEffect, useRef, useState } from "react";
import { ApiError, NotSignedIn, get, send } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { signOut } from "../../shell/keep";
import { useApi } from "../../shell/useApi";
import { Badge } from "../../ui/Badge";
import { Card, Chips, Failure, Inline, Prose, Row } from "./ui";

/** `GET /connections` — `routes.connections.Connection`. */
export type Connection = {
  id: string;
  client_name: string;
  verified: boolean;
  redirect_host: string;
  can_write?: boolean;
  created: string;
  used: string | null;
  expires: string;
};

export type Connections = { url: string | null; connections: Connection[] };

/** Where a reader arrived from — `routes.connections.Source`. */
const SOURCES = ["profile", "chat", "news", "tour"] as const;
type Source = (typeof SOURCES)[number];

export function source(from: string | null | undefined): Source {
  return SOURCES.find((s) => s === from) ?? "profile";
}

/** The apps the card knows how to explain — `routes.connections.App`. */
export const APPS = [
  "claude",
  "claude_code",
  "chatgpt",
  "codex",
  "gemini",
  "cursor",
  "vscode",
  "windsurf",
  "lechat",
  "other",
] as const;
export type App = (typeof APPS)[number];

/**
 * Each app's name (a product's, never translated; "other" has none) and the
 * catalog key that says where the address goes. Literal keys, so
 * `test_frontend_i18n_keys` sees every one.
 */
const INFO: Record<App, { name?: string; key: string }> = {
  claude: { name: "Claude", key: "profile.connector_how_claude" },
  claude_code: { name: "Claude Code", key: "profile.connector_how_claude_code" },
  chatgpt: { name: "ChatGPT", key: "profile.connector_how_chatgpt" },
  codex: { name: "Codex", key: "profile.connector_how_codex" },
  gemini: { name: "Gemini CLI", key: "profile.connector_how_gemini" },
  cursor: { name: "Cursor", key: "profile.connector_how_cursor" },
  vscode: { name: "VS Code", key: "profile.connector_how_vscode" },
  windsurf: { name: "Windsurf", key: "profile.connector_how_windsurf" },
  lechat: { name: "Le Chat", key: "profile.connector_how_lechat" },
  other: { key: "profile.connector_how_other" },
};

/** One server entry in the JSON files the editors read. */
const entry = (root: string, key: string, url: string) =>
  JSON.stringify({ [root]: { topstocks: { [key]: url } } }, null, 2);

/**
 * What to paste for each app that takes a line rather than a form. Apps set
 * up only through their own settings screen (Claude, ChatGPT, Le Chat) have
 * none: the address above is the whole of it.
 */
export function setup(app: App, url: string): string | null {
  switch (app) {
    case "claude_code":
      return `claude mcp add --transport http topstocks ${url}`;
    case "codex":
      return `codex mcp add topstocks --url ${url}`;
    case "gemini":
      return `gemini mcp add --transport http topstocks ${url}`;
    case "cursor":
      return entry("mcpServers", "url", url);
    case "vscode":
      return `code --add-mcp '${JSON.stringify({ name: "topstocks", type: "http", url })}'`;
    case "windsurf":
      return entry("mcpServers", "serverUrl", url);
    case "other":
      // For an app that only runs local servers: a bridge that speaks OAuth
      // and HTTP on its behalf.
      return `npx -y mcp-remote ${url}`;
    default:
      return null;
  }
}

/** Which line was copied, for which app, told to the server and nothing else. */
function copied(what: "url" | "command", app: App): void {
  // A beacon: it changes nothing a screen holds, and a failure is not the
  // reader's problem.
  send<void>("POST", "/connections/copied", { what, app }, { touches: [] }).catch(
    () => undefined,
  );
}

const PICKED = "ag.mcp.app";

/** The app picked last time on this device, else Claude. */
function lastApp(): App {
  try {
    const kept = localStorage.getItem(PICKED);
    return APPS.find((app) => app === kept) ?? "claude";
  } catch {
    return "claude";
  }
}

function keepApp(app: App): void {
  try {
    localStorage.setItem(PICKED, app);
  } catch {
    // A private window: the pick lasts as long as the page.
  }
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
function Copy({
  text,
  label,
  onCopied,
}: {
  text: string;
  label: string;
  onCopied?: () => void;
}) {
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
          () => {
            setDone(true);
            onCopied?.();
          },
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
    send<void>(
      "DELETE",
      `/connections/${encodeURIComponent(connection.id)}`,
      undefined,
      {
        touches: ["/connections"],
      },
    ).then(onGone, (error: unknown) => {
      setBusy(false);
      if (error instanceof NotSignedIn) {
        void signOut();
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
    });
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
          {connection.can_write && (
            <Badge title={t("profile.connector_can_edit_help")}>
              {t("profile.connector_can_edit")}
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

/** An app id off the URL, or nothing when it names no app the card knows. */
export function knownApp(app: string | null | undefined): App | undefined {
  return APPS.find((known) => known === app);
}

export function ConnectorCard({
  from,
  app,
}: {
  from?: string | null;
  /** The app to open on (`?app=`), as the chat's nudge names it. */
  app?: string | null;
}) {
  // Only the first read says where the reader came from; a refetch is the
  // same visit and must not count as another one.
  const first = useRef(true);
  const query = useApi(() => {
    const params = first.current ? { from: source(from) } : undefined;
    first.current = false;
    return get<Connections>("/connections", params);
  }, []);
  const reload = query.state === "loaded" ? query.reload : null;
  // Connecting happens in the app, in another tab or window: back here, ask again.
  useEffect(() => {
    if (!reload) return;
    const back = () => {
      if (document.visibilityState === "visible") reload();
    };
    document.addEventListener("visibilitychange", back);
    return () => document.removeEventListener("visibilitychange", back);
  }, [reload]);
  // Revoked here, gone from the list without a refetch; the next load agrees.
  const [gone, setGone] = useState<ReadonlySet<string>>(new Set());

  if (query.state !== "loaded") return null;
  return (
    <Connector
      url={query.data.url}
      connections={query.data.connections.filter((c) => !gone.has(c.id))}
      onGone={(id) => setGone((prev) => new Set(prev).add(id))}
      app={knownApp(app)}
    />
  );
}

/** What the card draws for one answer — no fetch, so a test can draw it. */
export function Connector({
  url,
  connections,
  onGone,
  app: first,
}: Connections & { onGone: (id: string) => void; app?: App }) {
  const t = useT();
  const [app, setApp] = useState<App>(() => first ?? lastApp());
  if (!url && connections.length === 0) return null;
  const line = url ? setup(app, url) : null;

  return (
    <Card title={t("profile.connector_title")} sub={t("profile.connector_sub")}>
      {connections.length > 0 && (
        <p className="pr-conn-ok" role="status">
          {t("profile.connector_ok")}
        </p>
      )}
      {url && (
        <>
          <Row
            label={t("profile.connector_url")}
            help={t("profile.connector_url_help")}
          >
            <div className="pr-copyline">
              <code className="pr-code">{url}</code>
              <Copy
                text={url}
                label={t("profile.connector_copy_url")}
                onCopied={() => copied("url", app)}
              />
            </div>
          </Row>
          <Row label={t("profile.connector_app")}>
            <Chips
              value={app}
              options={APPS}
              labelOf={(option) =>
                INFO[option].name ?? t("profile.connector_app_other")
              }
              onPick={(option) => {
                setApp(option);
                keepApp(option);
              }}
            />
          </Row>
          <Row label={t("profile.connector_how")}>
            <Prose text={t(INFO[app].key)} />
            {app === "claude" && (
              <span className="pr-hint">{t("profile.connector_plans")}</span>
            )}
            {line && (
              <div className="pr-copyline">
                <code className="pr-code pr-code-block">{line}</code>
                <Copy
                  text={line}
                  label={t("profile.connector_copy_command")}
                  onCopied={() => copied("command", app)}
                />
              </div>
            )}
            {app === "codex" && (
              <span className="pr-hint">
                <Inline text={t("profile.connector_after_codex")} />
              </span>
            )}
            {app === "gemini" && (
              <span className="pr-hint">
                <Inline text={t("profile.connector_after_gemini")} />
              </span>
            )}
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
