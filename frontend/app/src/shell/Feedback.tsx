/**
 * "Send feedback", on every page — because in the Streamlit app it is on every
 * page, and dropping it in the rebuild would be the quietest way to stop
 * hearing about the bugs this rebuild introduces.
 *
 * Two differences from the Streamlit composer, both deliberate:
 *
 * * **No screenshot.** Streamlit captures the screen behind the dialog through
 *   its own runtime. There is no equivalent here that does not mean shipping a
 *   canvas-rasterising library into the shell chunk every reader pays for, to
 *   serve a button most of them never press. The API accepts one; this client
 *   does not send one, and `feedback.shot*` stays unused rather than half-built.
 * * **Signed-in only.** The Streamlit button is offered to guests too — a
 *   visitor who bounced knowing why is worth more than a login — but `POST
 *   /feedback` stores against an account and there is no anonymous variant.
 *   This app only draws its chrome behind the sign-in wall, so the difference
 *   costs nothing *here*; it would cost something the day this app serves
 *   guests, and that is the day to give the route an anonymous path.
 *
 * The draft survives a failed send. Somebody who typed three paragraphs into a
 * box that then lost them does not type them again.
 */

import { useState } from "react";

import { send } from "./api";
import { useT } from "./i18n";
import { useRoute } from "./router";

const KINDS = ["bug", "idea", "other"] as const;
type Kind = (typeof KINDS)[number];

/** The ceiling the store applies (`web/feedback.MAX_CHARS`). */
const MAX = 4000;

export function Feedback() {
  const t = useT();
  const { page } = useRoute();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Kind>("bug");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  function submit() {
    const body = text.trim();
    if (!body || busy) return;
    setBusy(true);
    setFailed(null);
    send("POST", "/feedback", { text: body, kind, page })
      .then(() => {
        setSent(true);
        setText("");
        setOpen(false);
        // Long enough to read, short enough not to sit over the page.
        window.setTimeout(() => setSent(false), 4000);
      })
      .catch(() => setFailed(t("feedback.failed")))
      .finally(() => setBusy(false));
  }

  return (
    <>
      <button
        type="button"
        className="ag-fb-open"
        onClick={() => setOpen(true)}
        title={t("feedback.button")}
      >
        {t("feedback.button")}
      </button>
      {sent ? <p className="ag-fb-sent">{t("feedback.sent")}</p> : null}
      {open ? (
        <div className="ag-fb-scrim" role="presentation" onClick={() => setOpen(false)}>
          <div
            className="ag-fb"
            role="dialog"
            aria-modal="true"
            aria-label={t("feedback.button")}
            onClick={(event) => event.stopPropagation()}
          >
            <h2 className="ag-fb-h">{t("feedback.button")}</h2>
            <p className="ag-fb-caption">{t("feedback.caption")}</p>
            <div className="ag-fb-kinds" role="group" aria-label={t("feedback.kind")}>
              {KINDS.map((option) => (
                <button
                  key={option}
                  type="button"
                  className={option === kind ? "ag-fb-kind ag-fb-on" : "ag-fb-kind"}
                  aria-pressed={option === kind}
                  onClick={() => setKind(option)}
                >
                  {t(`feedback.kind_${option}`)}
                </button>
              ))}
            </div>
            <textarea
              className="ag-fb-text"
              rows={6}
              maxLength={MAX}
              value={text}
              placeholder={t("feedback.placeholder")}
              aria-label={t("feedback.button")}
              onChange={(event) => setText(event.target.value)}
            />
            {failed ? <p className="ag-fb-bad">{failed}</p> : null}
            <div className="ag-fb-foot">
              <button
                type="button"
                className="ag-fb-quiet"
                onClick={() => setOpen(false)}
              >
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="ag-fb-send"
                disabled={busy || !text.trim()}
                onClick={submit}
              >
                {t("feedback.button")}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </>
  );
}
