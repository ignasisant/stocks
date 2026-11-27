/**
 * Bank — read-only PSD2 account information, through Enable Banking.
 *
 * Three things on it: the banks already connected with what they last reported,
 * the button that reads them again, and the picker that starts a new consent.
 * Nothing here initiates a payment, which the page says twice because it is the
 * question a reader has.
 *
 * This is also the OAuth-style landing spot, and that is what shapes the file.
 * The bank sends the reader back to the *registered redirect URL* with
 * `?code=&state=` — a cold page load in a browser that may not have been open
 * when the round trip started. So the `state` is not held here: the server
 * matched it against the account's own bank.json before it would exchange the
 * code, and this component's whole job on return is to hand both over once,
 * clear them off the URL, and say what came back.
 *
 * "Once" is load-bearing: the code is single use, and React's development
 * StrictMode mounts every component twice. The guard is a ref rather than
 * state because it has to hold across that second mount, which a state reset
 * would not.
 *
 * Availability is the server's answer, not a guess from the catalog: the
 * feature is an allowlist that fails closed (see `stocks.bank.access`), so
 * most accounts get a page that says so and nothing else.
 */

import { useEffect, useRef, useState } from "react";

import { ApiError, get, send } from "../../shell/api";
import { SignInWall } from "../../shell/guest";
import { useLang, useT } from "../../shell/i18n";
import { Loaded } from "../../shell/Layout";
import { Link, useRoute } from "../../shell/router";
import { useGuest } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import type { BankAuth, BankChoice, BankConnection, BankState } from "./types";
import { cashTotals, daysLeft, RENEW_WINDOW, renewable, usedPercent } from "./consent";
import "./bank.css";
import { Badge } from "../../ui/Badge";
import { toast } from "../../ui/toast";
import { formatter } from "../../shell/numbers";
import { calendarDay } from "../../shell/dates";

/** Countries Enable Banking covers that this app is likely to be used from;
    the bank list itself comes from the API per country. */
const COUNTRIES = [
  "ES",
  "PT",
  "FR",
  "IT",
  "DE",
  "NL",
  "BE",
  "IE",
  "FI",
  "SE",
  "NO",
  "DK",
  "AT",
  "PL",
];

/** "ES" as "🇪🇸 España": the flag is the two letters moved into the regional
    indicator block, so no table is needed. */
function countryName(code: string, lang: string): string {
  const flag = [...code]
    .map((c) => String.fromCodePoint(0x1f1a5 + c.charCodeAt(0)))
    .join("");
  let name = code;
  try {
    name = new Intl.DisplayNames([lang], { type: "region" }).of(code) ?? code;
  } catch {
    // An engine without DisplayNames keeps the bare code.
  }
  return `${flag} ${name}`;
}

/** Enable Banking sometimes lists a bank in all lower case ("ceca bank"). */
function bankName(name: string): string {
  if (name !== name.toLowerCase()) return name;
  return name.replace(
    /(^|[\s-])(\p{L})/gu,
    (_, gap: string, c: string) => gap + c.toUpperCase(),
  );
}

/** What just happened, as a toast: told apart by tone as well as by sentence. */
type Notice = { tone: "ok" | "warn" | "bad"; text: string };

/** `null` clears: the next press starts a fresh round trip, nothing to unsay. */
function notify(notice: Notice | null) {
  if (notice) toast[notice.tone](notice.text);
}

/**
 * The bank's own failures, as the sentence each one deserves.
 *
 * The route gives them separate status codes precisely so this can be a
 * lookup: 429 is a spent daily budget and nothing to fix, 409 is a consent
 * that ended early and needs reconnecting, anything else is a failure.
 */
function failure(
  error: unknown,
  t: (key: string, slots?: Record<string, string | number>) => string,
  fallback: string,
): Notice {
  const detail = error instanceof ApiError ? error.detail : t("common.offline");
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 429) return { tone: "warn", text: t("bank.rate_limited") };
  if (status === 409) return { tone: "warn", text: t("bank.consent_gone") };
  return { tone: "bad", text: t(fallback, { detail }) };
}

function Balance({
  amount,
  currency,
  lang,
  stale = false,
}: {
  amount: number | null;
  currency: string;
  lang: string;
  /** A consent that ended: the figure is the last one read, dimmed. */
  stale?: boolean;
}) {
  const cls = stale ? "bk-balance bk-stale" : "bk-balance";
  if (amount === null) return <span className={cls}>—</span>;
  const text = (() => {
    try {
      return formatter(lang, {
        style: "currency",
        currency: currency || "EUR",
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      }).format(amount);
    } catch {
      // A bank can report a currency Intl does not know; the figure is still
      // worth printing and the code trails it.
      return `${amount.toFixed(2)} ${currency}`.trim();
    }
  })();
  return <span className={cls}>{text}</span>;
}

/** Cash at the connected banks, on top, and — when the server could convert
    every balance and price the book — its sum with the book. */
function CashTotal({
  connections,
  currency,
  cash,
  book,
}: {
  connections: BankConnection[];
  currency: string;
  cash: number | null;
  book: number | null;
}) {
  const t = useT();
  const lang = useLang();
  const totals = cashTotals(connections);
  if (totals.length === 0) return null;
  return (
    <div className="bk-total">
      <span className="bk-note">{t("bank.cash_total")}</span>
      {totals.map((total) => (
        <Balance
          key={total.currency}
          amount={total.amount}
          currency={total.currency}
          lang={lang}
        />
      ))}
      {cash !== null && book !== null ? (
        <span className="bk-note">
          {t("bank.with_book")}{" "}
          <Balance amount={book} currency={currency} lang={lang} />
          {" = "}
          <b>
            <Balance amount={cash + book} currency={currency} lang={lang} />
          </b>
        </span>
      ) : null}
    </div>
  );
}

function Connection({
  connection,
  onChanged,
  onNotice,
  onRenew,
}: {
  connection: BankConnection;
  onChanged: () => void;
  onNotice: (notice: Notice | null) => void;
  onRenew: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const left = daysLeft(connection.valid_until);

  const act = (verb: "refresh" | "disconnect") => {
    setBusy(true);
    onNotice(null);
    const call =
      verb === "refresh"
        ? send<BankState>("POST", `/bank/connections/${connection.session_id}/refresh`)
        : send<BankState>("DELETE", `/bank/connections/${connection.session_id}`);
    void call
      .then(() => onChanged())
      .catch((error: unknown) => {
        onNotice(
          failure(
            error,
            t,
            verb === "refresh" ? "bank.refresh_failed" : "bank.connect_failed",
          ),
        );
        // A consent the server just found dead is now stored as expired, so
        // the card has to be redrawn to stop offering a refresh.
        if (error instanceof ApiError && error.status === 409) onChanged();
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="bk-card">
      <div className="bk-card-head">
        <span className="bk-bank">
          <strong>{connection.name}</strong>
          {connection.country ? ` · ${connection.country}` : ""}
        </span>
        {connection.expired ? (
          <Badge>{t("bank.consent_expired")}</Badge>
        ) : (
          <span className="bk-note">
            {t("bank.valid_until", { date: calendarDay(connection.valid_until) })}
          </span>
        )}
      </div>

      {connection.expired ? (
        <p className="bk-note">{t("bank.expired_note")}</p>
      ) : (
        left !== null && (
          <div className="bk-consent">
            <span className={left <= RENEW_WINDOW ? "bk-warn" : "bk-note"}>
              {t(left === 1 ? "bank.days_left_one" : "bank.days_left", { days: left })}
            </span>
            <div
              className="bk-meter"
              role="meter"
              aria-valuemin={0}
              aria-valuemax={90}
              aria-valuenow={90 - Math.min(90, left)}
              aria-label={t("bank.consent_used")}
            >
              <i style={{ width: `${usedPercent(left)}%` }} />
            </div>
          </div>
        )
      )}

      {connection.accounts.map((account) => (
        <div className="bk-account" key={account.uid}>
          <div className="bk-account-row">
            <span className="bk-account-label">
              {[account.name, account.masked_id].filter(Boolean).join(" · ") ||
                account.uid}
            </span>
            <Balance
              amount={account.balance}
              currency={account.balance_currency || account.currency}
              lang={lang}
              stale={connection.expired}
            />
          </div>
          {account.fetched_at && (
            <span className="bk-note">
              {connection.expired ? `${t("bank.last_known")} · ` : ""}
              {t("bank.fetched_at", { when: account.fetched_at.replace("T", " ") })}
            </span>
          )}
        </div>
      ))}

      <div className="bk-actions">
        {connection.expired ? (
          <button type="button" className="ag-btn bk-primary" onClick={onRenew}>
            {t("bank.renew")}
          </button>
        ) : (
          <button
            type="button"
            className="ag-btn"
            disabled={busy}
            onClick={() => act("refresh")}
          >
            {t("bank.refresh")}
          </button>
        )}
        {!connection.expired && renewable(connection) && (
          <button type="button" className="ag-btn" onClick={onRenew}>
            {t("bank.renew_now")}
          </button>
        )}
        {confirming ? (
          <span className="bk-confirm">
            {/* The confirmation copy, inline: the emphasis markers in
                the catalog string are the bank's name and read fine as text. */}
            <span className="bk-note">
              {t("bank.disconnect_confirm", { bank: connection.name }).replaceAll(
                "**",
                "",
              )}
            </span>
            <button
              type="button"
              className="ag-btn bk-danger"
              disabled={busy}
              onClick={() => act("disconnect")}
            >
              {t("bank.disconnect_confirm_button")}
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="ag-btn"
            disabled={busy}
            onClick={() => setConfirming(true)}
          >
            {t("bank.disconnect")}
          </button>
        )}
      </div>
    </div>
  );
}

function AddBank({
  redirect,
  renew,
  onConnected,
  onNotice,
  onCancel,
}: {
  redirect: string;
  /** Renewing is connecting again with the bank already chosen. */
  renew: { country: string; name: string } | null;
  onConnected: () => void;
  onNotice: (notice: Notice | null) => void;
  onCancel: (() => void) | null;
}) {
  const t = useT();
  const lang = useLang();
  const [country, setCountry] = useState(renew?.country || COUNTRIES[0]!);
  const [chosen, setChosen] = useState(renew?.name ?? "");
  const [needle, setNeedle] = useState("");
  const [auth, setAuth] = useState<BankAuth | null>(null);
  const [busy, setBusy] = useState(false);
  const banks = useApi(() => get<BankChoice[]>("/bank/aspsps", { country }), [country]);

  // The list is per country, so the bank picked in one is not a bank in the
  // next: cleared here rather than left pointing at something that is gone.
  const pickCountry = (code: string) => {
    setCountry(code);
    setChosen("");
    setNeedle("");
  };

  const start = () => {
    setBusy(true);
    onNotice(null);
    void send<BankAuth>("POST", "/bank/auth", { country, name: chosen })
      .then(setAuth)
      .catch((error: unknown) => onNotice(failure(error, t, "bank.connect_failed")))
      .finally(() => setBusy(false));
  };

  const matches =
    banks.state === "loaded"
      ? [...banks.data]
          .filter((bank) =>
            bankName(bank.name).toLowerCase().includes(needle.trim().toLowerCase()),
          )
          .sort((a, b) => a.name.localeCompare(b.name))
      : [];

  return (
    <section className="bk-card" aria-labelledby="bk-add-h">
      <div className="bk-card-head">
        <h2 className="bk-h2" id="bk-add-h">
          {renew
            ? t("bank.renew_title", { bank: bankName(renew.name) })
            : t("bank.add_title")}
        </h2>
        {onCancel && (
          <button type="button" className="ag-btn" onClick={onCancel}>
            {t("bank.cancel")}
          </button>
        )}
      </div>

      <ul className="bk-promise">
        {["bank.promise_read", "bank.promise_pay", "bank.promise_90"].map((key) => (
          <li key={key}>{t(key)}</li>
        ))}
      </ul>

      <ol className="bk-steps">
        <li className="bk-step">
          <span className="bk-n">1</span>
          <label className="bk-step-b">
            <span className="bk-step-l">{t("bank.country")}</span>
            <select
              className="bk-select"
              value={country}
              disabled={renew !== null}
              onChange={(event) => pickCountry(event.target.value)}
            >
              {COUNTRIES.map((code) => (
                <option key={code} value={code}>
                  {countryName(code, lang)}
                </option>
              ))}
            </select>
          </label>
        </li>

        <li className="bk-step">
          <span className="bk-n">2</span>
          <div className="bk-step-b">
            <span className="bk-step-l">{t("bank.bank")}</span>
            {chosen ? (
              <div className="bk-chosen">
                <strong>{bankName(chosen)}</strong>
                {!renew && (
                  <button
                    type="button"
                    className="ag-btn"
                    onClick={() => setChosen("")}
                  >
                    {t("bank.change")}
                  </button>
                )}
              </div>
            ) : banks.state === "failed" ? (
              // Not the shell's generic failure: a bank list that will not
              // load is the one thing between the reader and a consent.
              <p className="bk-warn">
                {t("bank.aspsps_failed", {
                  detail: banks.error instanceof ApiError ? banks.error.detail : "—",
                })}
              </p>
            ) : (
              <>
                <input
                  type="search"
                  className="bk-select"
                  aria-label={t("bank.filter")}
                  placeholder={t("bank.filter")}
                  value={needle}
                  autoComplete="off"
                  disabled={banks.state !== "loaded"}
                  onChange={(event) => setNeedle(event.target.value)}
                />
                <ul className="bk-list" aria-label={t("bank.bank")}>
                  {matches.length === 0 && banks.state === "loaded" ? (
                    <li className="bk-note bk-nores">
                      {t("bank.no_match", { q: needle.trim() })}
                    </li>
                  ) : (
                    matches.map((bank) => (
                      <li key={bank.name}>
                        <button type="button" onClick={() => setChosen(bank.name)}>
                          {bankName(bank.name)}
                        </button>
                      </li>
                    ))
                  )}
                </ul>
              </>
            )}
          </div>
        </li>

        <li className="bk-step">
          <span className="bk-n">3</span>
          <div className="bk-step-b">
            <span className="bk-step-l">{t("bank.authorise")}</span>
            {!redirect && <p className="bk-warn">{t("bank.no_redirect")}</p>}
            {auth ? (
              <div className="bk-handoff">
                {/* A real link, not a redirect this app performs: the reader
                    is leaving for their bank and should see where to. */}
                <a className="ag-btn bk-primary" href={auth.url} onClick={onConnected}>
                  {t("bank.continue_to_bank", { bank: auth.bank })}
                </a>
                <span className="bk-note">{t("bank.continue_caption")}</span>
              </div>
            ) : (
              <button
                type="button"
                className="ag-btn bk-primary"
                disabled={busy || !chosen || !redirect}
                onClick={start}
              >
                {renew ? t("bank.renew_go") : t("bank.connect")}
              </button>
            )}
          </div>
        </li>
      </ol>
    </section>
  );
}

/** This screen is not in the menu: it is reached from Asignación, and goes back there. */
function BackLink() {
  const t = useT();
  return (
    <Link page="portfolio" className="bk-back">
      {`← ${t("bank.back")}`}
    </Link>
  );
}

export default function Page() {
  // `/v1/bank/*` is shut to a guest — a bank link is somebody's — so the wall
  // comes before the first request rather than after its 401.
  const t = useT();
  if (useGuest()) {
    return (
      <div className="bk-page">
        <BackLink />
        <h1 className="bk-title">{t("bank.title")}</h1>
        <SignInWall text="common.sign_in" />
      </div>
    );
  }
  return <Bank />;
}

function Bank() {
  const t = useT();
  const { params, setParams } = useRoute();
  const [nonce, setNonce] = useState(0);
  // `null`: not connecting; `"new"`: adding another bank; a connection: renewing it.
  const [flow, setFlow] = useState<null | "new" | BankConnection>(null);
  const state = useApi(() => get<BankState>("/bank"), [nonce]);
  // The redirect's code is single use, and StrictMode mounts twice. A ref
  // survives that; state would not.
  const landed = useRef(false);

  const code = params.get("code") ?? "";
  const returned = params.get("state") ?? "";
  const declined = params.get("error") ?? "";

  useEffect(() => {
    if (landed.current) return;
    if (declined) {
      landed.current = true;
      notify({ tone: "warn", text: t("bank.auth_declined") });
      setParams({ error: undefined, code: undefined, state: undefined });
      return;
    }
    if (!code || !returned) return;
    landed.current = true;
    void send<BankState>("POST", "/bank/session", { code, state: returned })
      .then((answer) => {
        const bank = answer.connections.at(-1)?.name ?? "";
        notify({ tone: "ok", text: t("bank.connected_toast", { bank }) });
        setNonce((n) => n + 1);
      })
      .catch((error: unknown) => {
        // A `state` the server cannot match is its own sentence: it is the
        // one failure that is not the bank's fault and not ours either — an
        // authorisation that expired, or one that belongs elsewhere.
        notify(
          error instanceof ApiError && error.status === 404
            ? { tone: "bad", text: t("bank.state_mismatch") }
            : failure(error, t, "bank.connect_failed"),
        );
      })
      // Off the URL either way: the code is spent, and a reload that replayed
      // it would only produce a second, more confusing failure.
      .finally(() => setParams({ code: undefined, state: undefined }));
  }, [code, returned, declined, setParams, t]);

  return (
    <div className="bk-page">
      <BackLink />
      <h1 className="bk-title">{t("bank.title")}</h1>

      <Loaded query={state}>
        {(data, reload) =>
          !data.available ? (
            <p className="bk-note">{t("bank.unavailable")}</p>
          ) : (
            <>
              <p className="bk-note">{t("bank.intro_caption")}</p>

              <CashTotal
                connections={data.connections}
                currency={data.currency}
                cash={data.cash_value}
                book={data.book_value}
              />

              <div className="bk-layout">
                <div className="bk-col">
                  {data.connections.length === 0 ? (
                    <p className="bk-note">{t("bank.none_connected")}</p>
                  ) : (
                    data.connections.map((connection) => (
                      <Connection
                        key={connection.session_id}
                        connection={connection}
                        onChanged={reload}
                        onNotice={notify}
                        onRenew={() => setFlow(connection)}
                      />
                    ))
                  )}
                </div>
                <div className="bk-col">
                  {data.connections.length > 0 && flow === null ? (
                    <section className="bk-card">
                      <h2 className="bk-h2">{t("bank.connect_another")}</h2>
                      <p className="bk-note">{t("bank.connect_another_caption")}</p>
                      <button
                        type="button"
                        className="ag-btn"
                        onClick={() => setFlow("new")}
                      >
                        {t("bank.add_title")}
                      </button>
                    </section>
                  ) : (
                    <AddBank
                      // A fresh form per flow: renewing one bank then another
                      // must not carry the first one's pick.
                      key={flow === null || flow === "new" ? "new" : flow.session_id}
                      redirect={data.redirect_url}
                      renew={
                        flow !== null && flow !== "new"
                          ? { country: flow.country, name: flow.name }
                          : null
                      }
                      onConnected={reload}
                      onNotice={notify}
                      onCancel={flow === null ? null : () => setFlow(null)}
                    />
                  )}
                </div>
              </div>

              <p className="bk-note">{t("bank.privacy_caption")}</p>
            </>
          )
        }
      </Loaded>
    </div>
  );
}
