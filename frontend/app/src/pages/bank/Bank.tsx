/**
 * Bank — read-only PSD2 account information, through Enable Banking.
 *
 * Same page as `web/app_pages/bank.py`, and the same three things on it: the
 * banks already connected with what they last reported, the button that reads
 * them again, and the picker that starts a new consent. Nothing here initiates
 * a payment, which the page says twice because it is the question a reader has.
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
import { useLang, useT } from "../../shell/i18n";
import { Loaded } from "../../shell/Layout";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import type { BankAuth, BankChoice, BankConnection, BankState } from "./types";
import "./bank.css";

/** Countries Enable Banking covers that this app is likely to be used from;
    the bank list itself comes from the API per country. Same table as the
    Streamlit page — a country offered on one front end and not the other
    would be a bank somebody can only connect from one of them. */
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

/** A message the page shows above everything: what just happened. */
type Notice = { tone: "ok" | "warn" | "bad"; text: string };

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
  const detail = error instanceof ApiError ? error.detail : String(error);
  const status = error instanceof ApiError ? error.status : 0;
  if (status === 429) return { tone: "warn", text: t("bank.rate_limited") };
  if (status === 409) return { tone: "warn", text: t("bank.consent_gone") };
  return { tone: "bad", text: t(fallback, { detail }) };
}

function Balance({
  amount,
  currency,
  lang,
}: {
  amount: number | null;
  currency: string;
  lang: string;
}) {
  if (amount === null) return <span className="bk-balance">—</span>;
  const text = (() => {
    try {
      return new Intl.NumberFormat(lang, {
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
  return <span className="bk-balance">{text}</span>;
}

function Connection({
  connection,
  onChanged,
  onNotice,
}: {
  connection: BankConnection;
  onChanged: () => void;
  onNotice: (notice: Notice | null) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);

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
          <span className="bk-badge">{t("bank.consent_expired")}</span>
        ) : (
          <span className="bk-note">
            {t("bank.valid_until", { date: connection.valid_until.slice(0, 10) })}
          </span>
        )}
      </div>

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
            />
          </div>
          {account.fetched_at && (
            <span className="bk-note">
              {t("bank.fetched_at", { when: account.fetched_at.replace("T", " ") })}
            </span>
          )}
        </div>
      ))}

      <div className="bk-actions">
        <button
          type="button"
          className="ag-btn"
          disabled={busy || connection.expired}
          onClick={() => act("refresh")}
        >
          {t("bank.refresh")}
        </button>
        {confirming ? (
          <span className="bk-confirm">
            {/* The Streamlit popover's copy, inline: the emphasis markers in
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
  onConnected,
  onNotice,
}: {
  redirect: string;
  onConnected: () => void;
  onNotice: (notice: Notice | null) => void;
}) {
  const t = useT();
  const [country, setCountry] = useState(COUNTRIES[0]!);
  const [chosen, setChosen] = useState("");
  const [auth, setAuth] = useState<BankAuth | null>(null);
  const [busy, setBusy] = useState(false);
  const banks = useApi(() => get<BankChoice[]>("/bank/aspsps", { country }), [country]);

  // The list is per country, so the bank picked in one is not a bank in the
  // next: cleared here rather than left pointing at something that is gone.
  useEffect(() => setChosen(""), [country]);

  const start = () => {
    setBusy(true);
    onNotice(null);
    void send<BankAuth>("POST", "/bank/auth", { country, name: chosen })
      .then(setAuth)
      .catch((error: unknown) => onNotice(failure(error, t, "bank.connect_failed")))
      .finally(() => setBusy(false));
  };

  return (
    <section className="bk-card">
      <h2 className="bk-h2">{t("bank.add_title")}</h2>

      <label className="bk-field">
        <span className="bk-note">{t("bank.country")}</span>
        <select
          className="bk-select"
          value={country}
          onChange={(event) => setCountry(event.target.value)}
        >
          {COUNTRIES.map((code) => (
            <option key={code} value={code}>
              {code}
            </option>
          ))}
        </select>
      </label>

      {/* Not the shell's generic failure: a bank list that will not load is
          the one thing standing between the reader and a consent, and the
          catalog has the sentence that says so — the Streamlit page prints
          the same one, with the same reason from the API. */}
      {banks.state === "failed" ? (
        <p className="bk-warn">
          {t("bank.aspsps_failed", {
            detail: banks.error instanceof ApiError ? banks.error.detail : "—",
          })}
        </p>
      ) : (
        <label className="bk-field">
          <span className="bk-note">{t("bank.bank")}</span>
          <select
            className="bk-select"
            value={chosen}
            disabled={banks.state !== "loaded"}
            onChange={(event) => setChosen(event.target.value)}
          >
            <option value="">—</option>
            {(banks.state === "loaded" ? [...banks.data] : [])
              .sort((a, b) => a.name.localeCompare(b.name))
              .map((bank) => (
                <option key={bank.name} value={bank.name}>
                  {bank.name}
                </option>
              ))}
          </select>
        </label>
      )}

      {!redirect && <p className="bk-warn">{t("bank.no_redirect")}</p>}

      <button
        type="button"
        className="ag-btn bk-primary"
        disabled={busy || !chosen || !redirect}
        onClick={start}
      >
        {t("bank.connect")}
      </button>

      {auth && (
        <div className="bk-handoff">
          {/* A real link, not a redirect this app performs: the reader is
              leaving for their bank and should be able to see where to. */}
          <a className="ag-btn bk-primary" href={auth.url} onClick={onConnected}>
            {t("bank.continue_to_bank", { bank: auth.bank })}
          </a>
          <span className="bk-note">{t("bank.continue_caption")}</span>
        </div>
      )}
    </section>
  );
}

export default function Page() {
  const t = useT();
  const { params, setParams } = useRoute();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [nonce, setNonce] = useState(0);
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
      setNotice({ tone: "warn", text: t("bank.auth_declined") });
      setParams({ error: undefined, code: undefined, state: undefined });
      return;
    }
    if (!code || !returned) return;
    landed.current = true;
    void send<BankState>("POST", "/bank/session", { code, state: returned })
      .then((answer) => {
        const bank = answer.connections.at(-1)?.name ?? "";
        setNotice({ tone: "ok", text: t("bank.connected_toast", { bank }) });
        setNonce((n) => n + 1);
      })
      .catch((error: unknown) => {
        // A `state` the server cannot match is its own sentence: it is the
        // one failure that is not the bank's fault and not ours either — an
        // authorisation that expired, or one that belongs elsewhere.
        setNotice(
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
      <h1 className="bk-title">{t("bank.title")}</h1>

      {notice && <p className={`bk-notice bk-${notice.tone}`}>{notice.text}</p>}

      <Loaded query={state}>
        {(data, reload) =>
          !data.available ? (
            <p className="bk-note">{t("bank.unavailable")}</p>
          ) : (
            <>
              <p className="bk-note">{t("bank.intro_caption")}</p>

              {data.connections.length === 0 ? (
                <p className="bk-note">{t("bank.none_connected")}</p>
              ) : (
                data.connections.map((connection) => (
                  <Connection
                    key={connection.session_id}
                    connection={connection}
                    onChanged={reload}
                    onNotice={setNotice}
                  />
                ))
              )}

              <AddBank
                redirect={data.redirect_url}
                onConnected={reload}
                onNotice={setNotice}
              />

              <p className="bk-note">{t("bank.privacy_caption")}</p>
            </>
          )
        }
      </Loaded>
    </div>
  );
}
