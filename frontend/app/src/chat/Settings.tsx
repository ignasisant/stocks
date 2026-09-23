/**
 * The drawer's account-level settings: who answers, on which model, with whose
 * key — and the one destructive action the thread list should not carry.
 *
 * A view rather than a strip above the conversation, for the reason the
 * Streamlit panel moved it there too: provider, model and key are set once and
 * then left alone for months, so they have no business taking room over every
 * message. Here they get room, and deleting a conversation ends up where a
 * destructive action belongs — at the bottom, behind a confirmation.
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
 * Unlike the panel there is no "this session only" key: an HTTP client has no
 * session for a key to live in, so the only honest choices are store it
 * encrypted or do not send it, and the copy here says the first.
 */

import { useId, useState } from "react";
import { useT } from "../shell/i18n";
import { ApiError } from "../shell/api";
import { forgetKey, storeKey } from "./api";
import { keyError, providerTag } from "./format";
import { Glyph } from "./icons";
import type { ChatState, ProviderInfo, SettingsPatch } from "./types";

function Group({ children }: { children: string }) {
  return <p className="ag-chat-group">{children}</p>;
}

/** The key form, or what is stored and the button that forgets it. */
function Key({
  provider,
  busy,
  onState,
}: {
  provider: ProviderInfo;
  busy: boolean;
  onState: (next: ChatState) => void;
}) {
  const t = useT();
  const uid = useId();
  const [typed, setTyped] = useState("");
  const [failed, setFailed] = useState<string | null>(null);
  const [working, setWorking] = useState(false);

  const save = async () => {
    const key = typed.trim();
    if (!key || working) return;
    setWorking(true);
    setFailed(null);
    try {
      onState(await storeKey(provider.id, key));
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

  if (provider.has_key) {
    return (
      <>
        <p className="ag-chat-hint">
          {/* "Expires in 0 days" over a key that works is worse than saying
              nothing about its lifetime, so a key with none to report says
              only that it is kept. */}
          {provider.key_days_left === null
            ? t("chat.key_kept")
            : t("chat.key_stored", { days: provider.key_days_left })}
        </p>
        <button
          type="button"
          className="ag-chat-btn"
          disabled={busy || working}
          onClick={async () => {
            setWorking(true);
            try {
              onState(await forgetKey(provider.id));
            } catch {
              setFailed("chat.api_error");
            } finally {
              setWorking(false);
            }
          }}
        >
          <Glyph name="key" size={14} />
          {t("chat.forget")}
        </button>
        {failed && <p className="ag-chat-note">{t(failed)}</p>}
      </>
    );
  }

  return (
    <form
      className="ag-chat-key"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <p className="ag-chat-hint">
        {t("chat.byok_help_stored", { provider: provider.label })}
      </p>
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
      <div className="ag-chat-import-acts">
        <button
          type="submit"
          className="ag-chat-btn ag-chat-btn-on"
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
}: {
  state: ChatState;
  busy: boolean;
  /** The open conversation, for the line the confirmation has to name. */
  thread: { id: string; title: string; messages: number } | null;
  onBack: () => void;
  onSave: (patch: SettingsPatch) => void;
  onState: (next: ChatState) => void;
  onDeleteThread: (cid: string) => void;
}) {
  const t = useT();
  const tag = useTag();
  const [confirming, setConfirming] = useState(false);

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
            <span className="ag-chat-tile-name">{provider.label}</span>
            <span className="ag-chat-tile-tag">{tag(provider)}</span>
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
              <Key provider={picked} busy={busy} onState={onState} />
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
