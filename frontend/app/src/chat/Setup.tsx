/**
 * The first screen for an account whose chosen provider cannot answer yet.
 *
 * The Streamlit panel's setup screen, and for the reason it was rebuilt: a
 * reader arriving with no key was once shown a provider list and an API-key
 * field, which reads as "you cannot use this yet". The free assistant is the
 * primary button, and the key sits below it for the reader who already knows
 * which provider they want — in the settings view, which is where the form
 * already lives, rather than in a second copy of it here.
 *
 * Only on an empty thread. Once there is a conversation the status row names
 * who is answering, and a setup card above somebody's history would be asking
 * them to start something they already started.
 */

import { useT } from "../shell/i18n";
import { Glyph } from "./icons";
import type { ChatState, SettingsPatch } from "./types";

/** True when the account picked a provider that needs a key it has not given. */
export function needsSetup(state: ChatState): boolean {
  const picked = state.providers.find((p) => p.id === state.preferred);
  return !!picked && picked.needs_key && !picked.has_key;
}

export function Setup({
  state,
  onSave,
  onSettings,
}: {
  state: ChatState;
  onSave: (patch: SettingsPatch) => void;
  onSettings: () => void;
}) {
  const t = useT();
  const free = state.providers.find((p) => !p.needs_key);
  return (
    <section className="ag-chat-setup">
      <h3>{t("chat.setup_title")}</h3>
      <p className="ag-chat-hint">{t("chat.setup_body")}</p>
      {free && (
        <>
          <button
            type="button"
            className="ag-chat-btn ag-chat-btn-on"
            onClick={() => onSave({ provider: free.id })}
          >
            <Glyph name="spark" size={14} />
            {t("chat.free_cta")}
          </button>
          {/* The pot, not a promise: an account the chain does not serve has
              no cap to name, and "null questions a day" says nothing. */}
          {state.free_cap !== null && (
            <p className="ag-chat-hint">
              {t("chat.free_cta_note", { cap: state.free_cap })}
            </p>
          )}
          <p className="ag-chat-or">{t("chat.setup_or")}</p>
        </>
      )}
      <button type="button" className="ag-chat-btn" onClick={onSettings}>
        <Glyph name="key" size={14} />
        {t("chat.free_add_key")}
      </button>
    </section>
  );
}
