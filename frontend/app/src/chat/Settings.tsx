/**
 * The drawer's account-level settings: who answers, on which model, with whose
 * key — and the one destructive action the thread list should not carry.
 *
 * A view rather than a strip above the conversation: provider, model and key
 * are set once and then left alone for months, so they have no business
 * taking room over every message. Here they get room, and deleting a
 * conversation ends up where a destructive action belongs — at the bottom,
 * behind a confirmation.
 *
 * Every control writes through `PATCH /chat/settings` (or the key routes),
 * each of which answers with the whole state: picking a provider that needs a
 * key changes the allowance, the wall and which key this screen should be
 * asking for, and one round trip settles all of it.
 *
 * The provider tiles show what the account *chose*, not what would answer.
 * Those differ exactly when a BYOK provider has been picked and not yet given
 * a key — the case this screen exists to resolve — and a tile that un-pressed
 * itself would tell the reader their choice did not take.
 *
 * A key is either stored encrypted on the account or held by this tab alone,
 * in its sessionStorage (`sessionKey.ts`) — the "Remember" checkbox decides.
 * A deployment with no encryption secret offers only the second, and says so
 * before the reader types anything rather than refusing the key on submit.
 *
 * Memory has two switches, because they stop two different things: what the
 * reader asked the assistant to remember (read into every prompt) and the
 * earlier conversations an answer may search. Off is not forgotten — the list
 * stays, and forgetting is the memory screen's own button.
 */

import { useEffect, useId, useRef, useState } from "react";
import { useT } from "../shell/i18n";
import { ApiError } from "../shell/api";
import { Status } from "../ui/Status";
import { forgetKey, readState, revealKey, storeKey } from "./api";
import { ConnectFailed, connectUrl, finishConnect, type ConnectAsk } from "./connect";
import { keyError, providerLabel, providerTag } from "./format";
import { Glyph, ProviderMark } from "./icons";
import { dropSessionKey, holdSessionKey, readSessionKey } from "./sessionKey";
import type { ChatState, ProviderInfo, SettingsPatch } from "./types";

/** What a minted key is called on the reader's own provider dashboard. */
const CONNECT_LABEL = "TopStocks";

function Group({ children }: { children: string }) {
  return <p className="ag-chat-group">{children}</p>;
}

/**
 * The key in use, masked, with an opt-in reveal.
 *
 * Masked by default because a settings screen is the one a reader opens with
 * somebody looking over their shoulder; the tail alone is enough to tell two
 * keys apart. Revealing a stored key is a round trip to the one route that
 * hands a secret out (session only, never cached); revealing this tab's key
 * needs none, because the tab already holds it. Either way the full key lives
 * in this component's state for as long as it is on screen and is dropped the
 * moment it is hidden again.
 */
function Shown({ provider }: { provider: ProviderInfo }) {
  const t = useT();
  const [full, setFull] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const masked = `••••••••${provider.key_tail ?? ""}`;

  const toggle = async () => {
    if (full !== null) {
      setFull(null);
      return;
    }
    setFailed(false);
    if (provider.key_session) {
      const held = readSessionKey();
      if (held?.provider === provider.id) setFull(held.key);
      return;
    }
    try {
      setFull(await revealKey(provider.id));
    } catch {
      setFailed(true);
    }
  };

  return (
    <div className="ag-chat-keyshow">
      <code className="ag-chat-keycode">{full ?? masked}</code>
      <button
        type="button"
        className="ag-chat-meta-btn"
        aria-pressed={full !== null}
        onClick={() => void toggle()}
      >
        {t("chat.key_show")}
      </button>
      {failed && <p className="ag-chat-note">{t("chat.api_error")}</p>}
    </div>
  );
}

/** The key form, or what is in use and the button that forgets it. */
function Key({
  provider,
  storage,
  busy,
  onState,
}: {
  provider: ProviderInfo;
  /** Whether the deployment can keep a key at all (`state.key_storage`). */
  storage: boolean;
  busy: boolean;
  onState: (next: ChatState) => void;
}) {
  const t = useT();
  const uid = useId();
  const [typed, setTyped] = useState("");
  // Remember is the default where the server can keep a key: that is what
  // this drawer always did, and a reader who wants less ticks it off. Where
  // it cannot, there is no box — a choice with one answer is not a choice.
  const [remember, setRemember] = useState(true);
  const [failed, setFailed] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const save = async () => {
    const key = typed.trim();
    if (!key || working) return;
    setWorking(true);
    setFailed(null);
    try {
      if (storage && remember) {
        onState(await storeKey(provider.id, key));
        // A stored key supersedes one this tab was holding for the same
        // provider; leaving both would make the tab's win on every request.
        if (readSessionKey()?.provider === provider.id) dropSessionKey();
      } else {
        if (!holdSessionKey({ provider: provider.id, key })) {
          setFailed("chat.key_session_blocked");
          return;
        }
        onState(await readState());
      }
      setTyped("");
    } catch (failure) {
      // The three refusals are not interchangeable: 503 is this deployment
      // saying it has no encryption secret and will not write a key in the
      // clear, and a rejected body can only be the key itself.
      setFailed(
        failure instanceof ApiError ? keyError(failure.status) : "chat.api_error",
      );
    } finally {
      setWorking(false);
    }
  };

  // A provider that mints keys by sign-in (`connect.ts`): one press, and the
  // reader comes back with a key on their own account instead of hunting for
  // the console, copying a secret and pasting it here. The Remember box means
  // the same thing for both ways in, so it is read before leaving.
  const connectable = Boolean(provider.connect_url && provider.connect_token_url);
  const signIn = async () => {
    if (working) return;
    setWorking(true);
    setFailed(null);
    let url: string | null = null;
    try {
      url = await connectUrl(provider, storage && remember, CONNECT_LABEL);
    } catch {
      // No `crypto.subtle` — a page served over plain http off localhost.
    }
    if (!url) {
      setFailed("chat.connect_blocked");
      setWorking(false);
      return;
    }
    // Still working on purpose: the page is leaving, and a second press
    // would only overwrite the verifier the first one is coming back for.
    window.location.assign(url);
  };

  const forget = async () => {
    setWorking(true);
    setFailed(null);
    try {
      if (provider.key_session) {
        dropSessionKey();
        onState(await readState());
      } else {
        onState(await forgetKey(provider.id));
      }
    } catch {
      setFailed("chat.api_error");
    } finally {
      setWorking(false);
    }
  };

  if (provider.has_key) {
    return (
      <>
        {provider.key_tail && <Shown provider={provider} />}
        <p className="ag-chat-hint">
          {/* "Expires in 0 days" over a key that works is worse than saying
              nothing about its lifetime, so a key with none to report says
              only that it is kept. A key this tab holds says where it lives,
              because "gone when you close the tab" is the thing to know. */}
          {provider.key_session
            ? t("chat.key_session_only")
            : provider.key_days_left === null
              ? t("chat.key_kept")
              : t("chat.key_stored", { days: provider.key_days_left })}
        </p>
        <button
          type="button"
          className="ag-chat-btn"
          disabled={busy || working}
          onClick={() => void forget()}
        >
          <Glyph name="key" size={14} />
          {t("chat.forget")}
        </button>
        {failed && <p className="ag-chat-note">{t(failed)}</p>}
      </>
    );
  }

  const rememberBox = storage && (
    <label className="ag-chat-check">
      <input
        type="checkbox"
        checked={remember}
        onChange={(event) => setRemember(event.target.checked)}
      />
      {t("chat.remember")}
    </label>
  );

  return (
    <form
      className="ag-chat-key"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      {connectable ? (
        <>
          <p className="ag-chat-hint">
            {t("chat.connect_help", { provider: provider.label })}
          </p>
          <button
            type="button"
            className="ag-chat-btn ag-chat-btn-on"
            disabled={busy || working}
            onClick={() => void signIn()}
          >
            <Glyph name="link" size={14} />
            {t("chat.connect_cta", { provider: provider.label })}
          </button>
          {/* Above the paste field rather than beside its Save: it decides
              where the signed-in key goes as much as a typed one. */}
          {rememberBox}
          <p className="ag-chat-or">{t("chat.connect_or")}</p>
        </>
      ) : (
        <p className="ag-chat-hint">
          {t(storage ? "chat.byok_help" : "chat.byok_help_session", {
            provider: provider.label,
          })}
        </p>
      )}
      <label htmlFor={`${uid}-key`} className="ag-sr">
        {t("chat.key_label", { provider: provider.label })}
      </label>
      <input
        id={`${uid}-key`}
        type="password"
        value={typed}
        autoComplete="off"
        placeholder={provider.key_placeholder}
        aria-label={t("chat.key_label", { provider: provider.label })}
        onChange={(event) => setTyped(event.target.value)}
      />
      {!connectable && rememberBox}
      <div className="ag-chat-import-acts">
        <button
          type="submit"
          // One primary per form: where sign-in is offered, it is the way in
          // and pasting is the fallback.
          className={`ag-chat-btn${connectable ? "" : " ag-chat-btn-on"}`}
          disabled={busy || working || !typed.trim()}
        >
          {t("chat.byok_save")}
        </button>
        {provider.console_url && (
          <a
            className="ag-chat-btn"
            href={provider.console_url}
            target="_blank"
            rel="noreferrer noopener"
          >
            {t("chat.get_key")}
          </a>
        )}
      </div>
      {failed && <p className="ag-chat-note">{t(failed)}</p>}
      <p className="ag-chat-hint">{t("chat.byok_reassure")}</p>
    </form>
  );
}

/** What a tile says about itself under its name, or "" when it has nothing. */
function useTag() {
  const t = useT();
  return (provider: ProviderInfo) => {
    const said = providerTag(provider);
    return said ? t(said.key, said.days === undefined ? {} : { days: said.days }) : "";
  };
}

export function Settings({
  state,
  busy,
  thread,
  onBack,
  onSave,
  onState,
  onDeleteThread,
  connect = null,
  onConnectTaken,
  onMemory,
}: {
  state: ChatState;
  busy: boolean;
  /** The open conversation, for the line the confirmation has to name. */
  thread: { id: string; title: string; messages: number } | null;
  onBack: () => void;
  onSave: (patch: SettingsPatch) => void;
  onState: (next: ChatState) => void;
  onDeleteThread: (cid: string) => void;
  /** Back from a provider's sign-in, with the code still to be traded. */
  connect?: ConnectAsk | null;
  onConnectTaken?: () => void;
  /** Open the saved-memories screen. */
  onMemory?: () => void;
}) {
  const t = useT();
  const tag = useTag();
  const [confirming, setConfirming] = useState(false);

  // Finished here rather than where the return lands (`Drawer.tsx`): this
  // view mounts only once the drawer's opening read is in, so the state the
  // trade answers with cannot be overwritten by that read arriving late. The
  // code is single use and StrictMode runs effects twice, hence the ref.
  const [joining, setJoining] = useState<{
    provider: string;
    phase: "working" | "done" | "failed";
    error?: string;
  } | null>(null);
  const spent = useRef<string | null>(null);
  useEffect(() => {
    if (!connect || spent.current === connect.code) return;
    spent.current = connect.code;
    onConnectTaken?.();
    const { provider } = connect.pending;
    setJoining({ provider, phase: "working" });
    finishConnect(connect.code, connect.pending)
      .then((next) => {
        onState(next);
        setJoining({ provider, phase: "done" });
      })
      .catch((failure: unknown) => {
        setJoining({
          provider,
          phase: "failed",
          error: failure instanceof ConnectFailed ? failure.key : "chat.api_error",
        });
      });
  }, [connect]);
  const joinedAs = joining ? providerLabel(state.providers, joining.provider) : "";

  const picked =
    state.providers.find((p) => p.id === state.preferred) ?? state.providers[0];
  const cap = state.free_cap;
  const left = state.free_left;

  return (
    <div className="ag-chat-body ag-chat-settings">
      <button type="button" className="ag-chat-back" onClick={onBack}>
        <Glyph name="back" size={16} />
        {t("chat.back_thread")}
      </button>

      <Group>{t("chat.sec_provider")}</Group>
      {/* Tiles rather than a segmented control: four brand names do not fit a
          380px row, and each one has to say whether it needs a key. */}
      <div className="ag-chat-tiles">
        {state.providers.map((provider) => (
          <button
            key={provider.id}
            type="button"
            className={`ag-chat-tile${provider.id === picked?.id ? " ag-chat-tile-on" : ""}`}
            aria-pressed={provider.id === picked?.id}
            disabled={busy}
            onClick={() => onSave({ provider: provider.id })}
          >
            <ProviderMark provider={provider} />
            <span className="ag-chat-tile-text">
              <span className="ag-chat-tile-name">{provider.label}</span>
              <span className="ag-chat-tile-tag">{tag(provider)}</span>
            </span>
          </button>
        ))}
      </div>

      {picked && (
        <>
          <Group>{t("chat.sec_model")}</Group>
          {picked.models.length > 1 ? (
            <select
              className="ag-chat-select"
              value={picked.model}
              aria-label={t("chat.model")}
              disabled={busy}
              onChange={(event) =>
                onSave({ provider: picked.id, model: event.target.value })
              }
            >
              {picked.models.map((model) => (
                <option key={model} value={model}>
                  {model}
                </option>
              ))}
            </select>
          ) : (
            <p className="ag-chat-hint">{picked.model}</p>
          )}

          {picked.needs_key ? (
            <>
              <Group>{t("chat.sec_key")}</Group>
              {joining?.phase === "working" && (
                <Status label={t("chat.connect_working", { provider: joinedAs })} />
              )}
              {joining?.phase === "done" && (
                <p className="ag-chat-hint">
                  {t("chat.connect_done", { provider: joinedAs })}
                </p>
              )}
              {joining?.phase === "failed" && (
                <p className="ag-chat-note">
                  {t(joining.error ?? "chat.connect_failed", { provider: joinedAs })}
                </p>
              )}
              <Key
                provider={picked}
                storage={state.key_storage ?? true}
                busy={busy}
                onState={onState}
              />
            </>
          ) : (
            // The keyless chain's pot, as a figure and as a bar: the caption
            // alone never told anyone how close they were to the wall. Null is
            // not zero — an account the chain never served is shown no bar.
            left !== null &&
            cap !== null && (
              <>
                <p className="ag-chat-quota-row">
                  <span>{t("chat.free_left_label")}</span>
                  <span className="ag-chat-quota">
                    {left} / {cap}
                  </span>
                </p>
                <progress className="ag-chat-bar" value={left} max={cap || 1} />
                <p className="ag-chat-hint">{t("chat.free_note")}</p>
              </>
            )
          )}
        </>
      )}

      <Group>{t("chat.sec_memory")}</Group>
      <label className="ag-chat-check">
        <input
          type="checkbox"
          checked={state.memory ?? true}
          disabled={busy}
          onChange={(event) => onSave({ memory: event.target.checked })}
        />
        {t("chat.mem_switch")}
      </label>
      <label className="ag-chat-check">
        <input
          type="checkbox"
          checked={state.recall ?? true}
          disabled={busy}
          onChange={(event) => onSave({ recall: event.target.checked })}
        />
        {t("chat.recall_switch")}
      </label>
      <p className="ag-chat-hint">{t("chat.mem_switch_note")}</p>
      {onMemory && (
        <button type="button" className="ag-chat-btn" onClick={onMemory}>
          <Glyph name="memory" size={14} />
          {t("chat.mem_manage")}
        </button>
      )}

      <Group>{t("chat.sec_thread")}</Group>
      {confirming && thread ? (
        <div className="ag-chat-confirm">
          <p>
            {t("chat.delete_confirm", {
              title: thread.title || t("chat.untitled"),
              n: thread.messages,
            })}
          </p>
          <div className="ag-chat-import-acts">
            <button
              type="button"
              className="ag-chat-btn ag-chat-btn-on"
              onClick={() => {
                setConfirming(false);
                onDeleteThread(thread.id);
                onBack();
              }}
            >
              {t("chat.delete_yes")}
            </button>
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => setConfirming(false)}
            >
              {t("chat.cancel")}
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="ag-chat-btn"
          disabled={!thread}
          onClick={() => setConfirming(true)}
        >
          <Glyph name="trash" size={14} />
          {t("chat.clear_thread")}
        </button>
      )}
    </div>
  );
}
