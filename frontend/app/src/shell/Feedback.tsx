/**
 * "Send feedback", on every page — because in the Streamlit app it is on every
 * page, and dropping it in the rebuild would be the quietest way to stop
 * hearing about the bugs this rebuild introduces.
 *
 * Offered to guests too: a visitor who bounced knowing why is worth more than a
 * login, which is why `POST /feedback` is the API's one unauthenticated write.
 *
 * What the Streamlit composer offers, this offers:
 *
 * * **A screenshot**, optional (`web/feedback._attachment`). Captured from this
 *   screen on request — the rasteriser is fetched only then, never in the
 *   shell bundle — or attached as an image file, or pasted into the box. Every
 *   route ends as one JPEG under the API's ceiling (`screenshot.ts`).
 * * **Dictation** (`web/feedback._transcribe`), through `POST /chat/voice`.
 *   That route spends the operator's transcription key and is a `Writer`, so a
 *   guest never sees the microphone (`GUEST_CHROME.dictation`) — and neither
 *   does a deployment with no transcription key, which `/chat/state` says.
 *   The words land in the box to be read before sending, rather than being
 *   sent as heard: Whisper mishears tickers, and a report is not a chat turn.
 *
 * The draft survives a failed send. Somebody who typed three paragraphs into a
 * box that then lost them does not type them again.
 */

import { useEffect, useRef, useState } from "react";

import {
  canRecord,
  record,
  transcribe,
  VoiceFailed,
  type Recording,
} from "../chat/voice";
import { ApiError, get, send } from "./api";
import { GUEST_CHROME } from "./guest";
import { useLang, useT } from "./i18n";
import { useRoute } from "./router";
import { capture, fromFile, ShotFailed, type Shot } from "./screenshot";
import { useGuest } from "./session";

const KINDS = ["bug", "idea", "other"] as const;
type Kind = (typeof KINDS)[number];

/** The ceiling the store applies (`web/feedback.MAX_CHARS`). */
const MAX = 4000;

/** Whether an element is this dialog's own chrome — left out of a capture. */
const chrome = (element: Element) =>
  element.classList?.contains("ag-fb-scrim") ||
  element.classList?.contains("ag-fb-sent");

export function Feedback() {
  const t = useT();
  const lang = useLang();
  const guest = useGuest();
  const { page } = useRoute();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Kind>("bug");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  const [shot, setShot] = useState<Shot | null>(null);
  const [shooting, setShooting] = useState(false);
  const [shotNote, setShotNote] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);

  const [voice, setVoice] = useState(false);
  const [taping, setTaping] = useState<Recording | null>(null);
  const [hearing, setHearing] = useState(false);

  // Whether this deployment can transcribe at all — asked when the dialog
  // opens, and only by somebody who could use the answer. A microphone that
  // apologises on press is worse than no microphone.
  useEffect(() => {
    if (!open || (guest && !GUEST_CHROME.dictation) || !canRecord()) return;
    let alive = true;
    get<{ voice: boolean }>("/chat/state")
      .then((state) => alive && setVoice(state.voice))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [open, guest]);

  // A recording must not outlive the component: the microphone light would
  // stay on. Through a ref and on unmount only — a cleanup keyed on `taping`
  // would also fire when a recording is handed over to be transcribed, and
  // cancel it mid-stop.
  const live = useRef<Recording | null>(null);
  live.current = taping;
  useEffect(() => () => live.current?.cancel(), []);

  function close() {
    taping?.cancel();
    setTaping(null);
    setOpen(false);
  }

  function attach(blob: Blob) {
    setShotNote(null);
    setShooting(true);
    fromFile(blob)
      .then(setShot)
      .catch((error: unknown) =>
        setShotNote(
          t(error instanceof ShotFailed ? error.key : "feedback.shot_failed"),
        ),
      )
      .finally(() => setShooting(false));
  }

  function shoot() {
    setShotNote(null);
    setShooting(true);
    capture(chrome)
      .then(setShot)
      .catch((error: unknown) =>
        setShotNote(
          t(error instanceof ShotFailed ? error.key : "feedback.shot_failed"),
        ),
      )
      .finally(() => setShooting(false));
  }

  async function dictate() {
    if (taping) {
      const recording = taping;
      setTaping(null);
      setHearing(true);
      try {
        const said = await transcribe(await recording.stop(), lang);
        // A note recorded *with* something typed is one report, not two.
        setText((before) => (before.trim() ? `${before.trim()} ${said}` : said));
      } catch (error) {
        setFailed(
          error instanceof VoiceFailed
            ? t(error.key, error.slots)
            : t("chat.voice_failed"),
        );
      } finally {
        setHearing(false);
      }
      return;
    }
    try {
      setFailed(null);
      setTaping(await record());
    } catch {
      // The reader denied the microphone: an answer, not a failure.
    }
  }

  function submit() {
    const body = text.trim();
    if (!body || busy || shooting) return;
    setBusy(true);
    setFailed(null);
    send("POST", "/feedback", {
      text: body,
      kind,
      page,
      lang,
      ...(shot ? { shot: shot.base64 } : {}),
    })
      .then(() => {
        setSent(true);
        setText("");
        setShot(null);
        setOpen(false);
        // Long enough to read, short enough not to sit over the page.
        window.setTimeout(() => setSent(false), 4000);
      })
      .catch((error: unknown) =>
        setFailed(
          t(
            error instanceof ApiError && error.status === 429
              ? "feedback.rate_limited"
              : "feedback.failed",
          ),
        ),
      )
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
        <div className="ag-fb-scrim" role="presentation" onClick={close}>
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
              onPaste={(event) => {
                // A system screenshot on the clipboard is the fastest way to a
                // picture of the screen — take it rather than pasting nothing.
                const image = [...event.clipboardData.items].find((item) =>
                  item.type.startsWith("image/"),
                );
                const blob = image?.getAsFile();
                if (blob) {
                  event.preventDefault();
                  attach(blob);
                }
              }}
            />
            <div className="ag-fb-tools">
              <button
                type="button"
                className="ag-fb-quiet"
                disabled={shooting}
                title={t("feedback.shot_help")}
                onClick={shoot}
              >
                {t("feedback.shot_capture")}
              </button>
              <button
                type="button"
                className="ag-fb-quiet"
                disabled={shooting}
                onClick={() => file.current?.click()}
              >
                {t("feedback.shot_attach")}
              </button>
              <input
                ref={file}
                type="file"
                accept="image/*"
                hidden
                onChange={(event) => {
                  const picked = event.target.files?.[0];
                  if (picked) attach(picked);
                  event.target.value = "";
                }}
              />
              {voice ? (
                <button
                  type="button"
                  className={taping ? "ag-fb-quiet ag-fb-on" : "ag-fb-quiet"}
                  disabled={hearing}
                  aria-pressed={!!taping}
                  onClick={() => void dictate()}
                >
                  {t(
                    hearing
                      ? "feedback.dictating"
                      : taping
                        ? "feedback.dictate_stop"
                        : "feedback.dictate",
                  )}
                </button>
              ) : null}
            </div>
            <p className="ag-fb-hint">{t("feedback.shot_paste")}</p>
            {shooting ? (
              <p className="ag-fb-hint">{t("feedback.shot_working")}</p>
            ) : null}
            {shotNote ? <p className="ag-fb-bad">{shotNote}</p> : null}
            {shot ? (
              <div className="ag-fb-shot">
                <img src={shot.url} alt="" />
                <span className="ag-fb-hint">
                  {t("feedback.shot_ready", { kb: shot.kb })}
                </span>
                <button
                  type="button"
                  className="ag-fb-quiet"
                  onClick={() => setShot(null)}
                >
                  {t("feedback.shot_remove")}
                </button>
              </div>
            ) : null}
            {failed ? <p className="ag-fb-bad">{failed}</p> : null}
            <div className="ag-fb-foot">
              <button type="button" className="ag-fb-quiet" onClick={close}>
                {t("common.cancel")}
              </button>
              <button
                type="button"
                className="ag-fb-send"
                disabled={busy || shooting || !text.trim()}
                title={shooting ? t("feedback.shot_wait") : undefined}
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
