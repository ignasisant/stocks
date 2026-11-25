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
 * **The statement**, when the report comes from the assistant's import
 *   (`report.ts`): offered ticked, with what happens to it said under the box —
 *   kept encrypted for fifteen days, like a failed import. A file the store
 *   would refuse is not offered, and a send whose file was not kept says so.
 *   A file a failed read already kept (asked by its sha256) is not offered
 *   either: the report names that copy, and the dialog says it goes with it.
 *
 * The draft survives a failed send. Somebody who typed three paragraphs into a
 * box that then lost them does not type them again.
 */

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { asBase64 } from "../chat/api";
import { canRecord, dictate, join, VoiceFailed, type Dictation } from "../chat/voice";
import { ApiError, get, scoped, send } from "./api";
import { GUEST_CHROME } from "./guest";
import { useLang, useT } from "./i18n";
import { onReport, type ReportContext } from "./report";
import { useRoute } from "./router";
import { useDialog } from "./useDialog";
import { capture, fromFile, ShotFailed, type Shot } from "./screenshot";
import { useGuest } from "./session";
import { Box, Mic } from "../ui/Mic";
import { toast } from "../ui/toast";
import { ToggleChip, ToggleRow } from "../ui/Toggle";

const KINDS = ["bug", "idea", "other"] as const;
type Kind = (typeof KINDS)[number];

/** The ceiling the store applies (`web/feedback.MAX_CHARS`). */
const MAX = 4000;

/** The store's ceiling on `page` (`api/routes/feedback.Feedback.page`). */
const PAGE_MAX = 120;

/** The ceiling the statement store keeps (`portfolio/failed_files.MAX_BYTES`). */
const STATEMENT_MAX = 8 * 1024 * 1024;

/**
 * Whether an element is chrome the reader opened to get here — this dialog,
 * and on a phone the "More" sheet it lives in — rather than the screen being
 * reported. Left out of a capture: a picture of the menu says nothing.
 */
const CHROME = ["ag-fb-scrim", "ag-toast", "ag-nav-sheet", "ag-nav-scrim"];
const chrome = (element: Element) =>
  CHROME.some((name) => element.classList?.contains(name));

/** The name `failed_files` keeps a file under: sha256, first 16 hex. */
export async function digestOf(blob: Blob): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(hash).slice(0, 8), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function Feedback() {
  const t = useT();
  const lang = useLang();
  const guest = useGuest();
  const { page, params } = useRoute();
  // Which ticker, which tab: "ticker" alone does not say which screen it was.
  const query = params.toString();
  const [context, setContext] = useState<ReportContext>({});
  const where = (context.page ?? (query ? `${page}?${query}` : page)).slice(
    0,
    PAGE_MAX,
  );
  // Offered only where it could be kept: a guest's never is, nor a file past
  // the store's ceiling.
  const statement =
    !guest && context.file && context.file.blob.size <= STATEMENT_MAX
      ? context.file
      : null;
  const [sendFile, setSendFile] = useState(true);
  // The statement's digest when the server already keeps it; null when it
  // does not, undefined while asking (nothing about the file is drawn yet).
  const [held, setHeld] = useState<string | null | undefined>(undefined);
  const [open, setOpen] = useState(false);
  // Not sent while that is unknown: the box it would be sent by is not drawn.
  const asking = !!statement && held === undefined;
  const [text, setText] = useState("");
  const [kind, setKind] = useState<Kind>("bug");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  // A page that is failing somebody opens this on their behalf (`report.ts`).
  useEffect(
    () =>
      onReport((asked, about) => {
        setKind(asked);
        setContext(about);
        setSendFile(true);
        setOpen(true);
      }),
    [],
  );

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
    const scope = new AbortController();
    scoped(scope.signal, () => get<{ voice: boolean }>("/chat/state"))
      .then((state) => alive && setVoice(state.voice))
      .catch(() => undefined);
    return () => {
      alive = false;
      scope.abort();
    };
  }, [open, guest]);

  // A recording must not outlive the component: the microphone light would
  // stay on. Through a ref and on unmount only — a cleanup keyed on `taping`
  // would also fire when a recording is handed over to be transcribed, and
  // cancel it mid-stop.
  // Kept already? A read that failed keeps its file; the report then links
  // that copy rather than asking for it and sending it a second time.
  const blob = statement?.blob;
  useEffect(() => {
    if (!open || !blob) return;
    let alive = true;
    setHeld(undefined);
    digestOf(blob)
      .then((digest) =>
        get<{ held: boolean }>(`/feedback/statement/${digest}`).then((answer) =>
          answer.held ? digest : null,
        ),
      )
      .catch(() => null)
      .then((found) => alive && setHeld(found));
    return () => {
      alive = false;
    };
  }, [open, blob]);

  const tape = useRef<Dictation | null>(null);
  tape.current = taping;
  useEffect(() => () => tape.current?.cancel(), []);

  // Escape closes like the scrim does; focus goes in on open and back to the
  // button after.
  const card = useRef<HTMLDivElement>(null);
  useDialog(card, { open });
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") closeRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  function close() {
    // Dropped, and so are its words: they were never transcribed.
    if (taping) setText(before.current);
    taping?.cancel();
    setTaping(null);
    setOpen(false);
  }
  const closeRef = useRef(close);
  closeRef.current = close;

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

  async function attached(): Promise<{ filename: string; content: string } | null> {
    if (!statement || !sendFile || held) return null;
    // Read only now, on send: a dialog opened and cancelled reads nothing.
    return { filename: statement.name, content: await asBase64(statement.blob) };
  }

  function submit() {
    const body = text.trim();
    if (!body || busy || shooting || live || asking) return;
    setBusy(true);
    setFailed(null);
    attached()
      .catch(() => null)
      .then((file) =>
        send<{ statement?: boolean }>("POST", "/feedback", {
          text: body,
          kind,
          page: where,
          lang,
          ...(shot ? { shot: shot.base64 } : {}),
          ...(file ? { statement: file } : {}),
          ...(statement && held ? { statement_digest: held } : {}),
        }).then((sent) => ({
          asked: !!statement && (!!held || sendFile),
          kept: !!sent?.statement,
        })),
      )
      .then(({ asked, kept }) => {
        // A file that did not go is said, not implied.
        toast.ok(t(asked && !kept ? "feedback.sent_no_file" : "feedback.sent"));
        setText("");
        setShot(null);
        setContext({});
        setOpen(false);
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
        onClick={() => {
          setContext({});
          setOpen(true);
        }}
        title={t("feedback.button")}
      >
        {t("feedback.button")}
      </button>
      {open
        ? createPortal(
            <div className="ag-fb-scrim" role="presentation" onClick={close}>
              <div
                ref={card}
                tabIndex={-1}
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
                {statement && held ? (
                  <p className="ag-fb-hint ag-fb-file">
                    {t("feedback.statement_held", { name: statement.name })}
                  </p>
                ) : statement && held === null ? (
                  <div className="ag-fb-file">
                    <label className="ag-fb-check">
                      <input
                        type="checkbox"
                        checked={sendFile}
                        onChange={(event) => setSendFile(event.target.checked)}
                      />
                      <span>{t("feedback.statement", { name: statement.name })}</span>
                    </label>
                    <p className="ag-fb-hint">{t("feedback.statement_help")}</p>
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
                    disabled={busy || shooting || live || asking || !text.trim()}
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
