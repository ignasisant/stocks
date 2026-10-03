/**
 * "Send feedback", on every page — because a page without it is the quietest
 * way to stop hearing about the bugs on that page.
 *
 * Offered to guests too: a visitor who bounced knowing why is worth more than a
 * login, which is why `POST /feedback` is the API's one unauthenticated write.
 *
 * Beside the text:
 *
 * * **A screenshot**, optional. Captured from this screen on request — the
 *   rasteriser is fetched only then, never in the shell bundle — or attached
 *   as an image file, or pasted into the box. Every route ends as one JPEG
 *   under the API's ceiling (`screenshot.ts`).
 * * **Dictation**, through `POST /chat/voice`.
 *   That route spends the operator's transcription key and is a `Writer`, so a
 *   guest never sees the microphone (`GUEST_CHROME.dictation`) — and neither
 *   does a deployment with no transcription key, which `/chat/state` says.
 *   The words land in the box to be read before sending, rather than being
 *   sent as heard: Whisper mishears tickers, and a report is not a chat turn.
 *   They land as they are said, where the browser has a recogniser, and
 *   Whisper's transcript replaces them at the stop (`chat/voice.dictate`).
 *   The microphone is an icon inside the box, bottom right — the chat
 *   composer's, in the same corner (`ui/Mic`) — not a text button under it.
 *
 * The draft survives a failed send. Somebody who typed three paragraphs into a
 * box that then lost them does not type them again.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { canRecord, dictate, join, VoiceFailed, type Dictation } from "../chat/voice";
import { ApiError, get, send } from "./api";
import { GUEST_CHROME } from "./guest";
import { useLang, useT } from "./i18n";
import { useRoute } from "./router";
import { capture, fromFile, ShotFailed, type Shot } from "./screenshot";
import { useGuest } from "./session";
import { Box, Mic } from "../ui/Mic";
import { ToggleChip, ToggleRow } from "../ui/Toggle";

const KINDS = ["bug", "idea", "other"] as const;
type Kind = (typeof KINDS)[number];

/** The ceiling the store applies (`web/feedback.MAX_CHARS`). */
const MAX = 4000;

/** The store's ceiling on `page` (`api/routes/feedback.Feedback.page`). */
const PAGE_MAX = 120;

/**
 * Whether an element is chrome the reader opened to get here — this dialog,
 * and on a phone the "More" sheet it lives in — rather than the screen being
 * reported. Left out of a capture: a picture of the menu says nothing.
 */
const CHROME = ["ag-fb-scrim", "ag-fb-sent", "ag-nav-sheet", "ag-nav-scrim"];
const chrome = (element: Element) =>
  CHROME.some((name) => element.classList?.contains(name));

export function Feedback() {
  const t = useT();
  const lang = useLang();
  const guest = useGuest();
  const { page, params } = useRoute();
  // Which ticker, which tab: "ticker" alone does not say which screen it was.
  const query = params.toString();
  const where = (query ? `${page}?${query}` : page).slice(0, PAGE_MAX);
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
  const [taping, setTaping] = useState<Dictation | null>(null);
  const [hearing, setHearing] = useState(false);
  // What the box held when the recording started: the words being said are
  // drawn after it, and the transcript replaces them there.
  const before = useRef("");
  const live = !!taping || hearing;

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
  const tape = useRef<Dictation | null>(null);
  tape.current = taping;
  useEffect(() => () => tape.current?.cancel(), []);

  function close() {
    // Dropped, and so are its words: they were never transcribed.
    if (taping) setText(before.current);
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

  async function talk() {
    if (taping) {
      const recording = taping;
      setTaping(null);
      setHearing(true);
      try {
        // A note recorded *with* something typed is one report, not two.
        setText(join(before.current, await recording.stop()));
      } catch (error) {
        setText(before.current);
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
      before.current = text;
      setTaping(await dictate(lang, (words) => setText(join(before.current, words))));
    } catch {
      // The reader denied the microphone: an answer, not a failure.
      setText(before.current);
    }
  }

  function submit() {
    const body = text.trim();
    if (!body || busy || shooting || live) return;
    setBusy(true);
    setFailed(null);
    send("POST", "/feedback", {
      text: body,
      kind,
      page: where,
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
      {sent
        ? createPortal(
            <p className="ag-fb-sent">{t("feedback.sent")}</p>,
            document.body,
          )
        : null}
      {open
        ? createPortal(
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
                <ToggleRow className="ag-fb-kinds" label={t("feedback.kind")}>
                  {KINDS.map((option) => (
                    <ToggleChip
                      key={option}
                      on={option === kind}
                      onClick={() => setKind(option)}
                    >
                      {t(`feedback.kind_${option}`)}
                    </ToggleChip>
                  ))}
                </ToggleRow>
                <Box
                  tools={
                    voice ? (
                      <Mic
                        on={!!taping}
                        disabled={hearing}
                        label={t(
                          hearing
                            ? "feedback.dictating"
                            : taping
                              ? "feedback.dictate_stop"
                              : "feedback.dictate",
                        )}
                        onPress={() => void talk()}
                      />
                    ) : null
                  }
                >
                  <textarea
                    className={live ? "ag-fb-text ag-fb-live" : "ag-fb-text"}
                    readOnly={live}
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
                </Box>
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
                    disabled={busy || shooting || live || !text.trim()}
                    title={shooting ? t("feedback.shot_wait") : undefined}
                    onClick={submit}
                  >
                    {t("feedback.button")}
                  </button>
                </div>
              </div>
            </div>,
            // Out to the body: on a phone the button lives in the tab bar's "More"
            // sheet, and a fixed bar is a stacking context — whatever z-index the
            // dialog asks for, it would stay level with the bar, under the corner
            // banner and the assistant's button.
            document.body,
          )
        : null}
    </>
  );
}
