/**
 * The input, and the two controls that change what the next answer will be.
 *
 * Internet and the skill lens belong at the composer rather than in a settings
 * screen opened once a quarter: they change the *next* answer, so they sit
 * beside the thing they change. Both write straight through to
 * `PATCH /chat/settings`, which returns the whole state — one round trip both
 * applies the change and re-reads what it implies.
 *
 * A second send while one is in flight is refused here rather than queued: the
 * engine writes one thread, and a queued question would land inside the first
 * answer's history half-written. The field stays open the whole time, because
 * being unable to type the next question is not the same as being unable to
 * send it. While an answer is being written, Send *is* Stop — the Streamlit
 * composer's `submit_mode="stop"`: the one control a reader looks for when an
 * answer is going the wrong way is the one their thumb is already on.
 *
 * The paperclip is the third control, and it is the one that does not change
 * the next answer but replaces it: a statement attached here is an import — a
 * parse, a preview and a confirmation — served by `/chat/attachments`, and the
 * card it opens is what writes to the ledger. One file per press, because a
 * second attachment would either queue a second preview behind the first or be
 * dropped with an apology, and in practice the second file was nearly always
 * the same export twice.
 *
 * The microphone is the fourth, and it is drawn only where it can work: this
 * browser has to have `MediaRecorder` and the deployment has to have a
 * transcription key (`state.voice`). A spoken question is transcribed into the
 * field, not sent: Whisper mishears tickers and numbers often enough that the
 * reader has to see the words before they become a question, and correcting a
 * sent turn costs a whole answer. It joins whatever was already typed, because
 * a note recorded *with* something typed reads as one message rather than two,
 * and the turn is still badged as spoken when it goes.
 */

import { useEffect, useId, useRef, useState } from "react";
import { useLang, useT } from "../shell/i18n";
import { capMessage, skillName } from "./format";
import { Glyph } from "./icons";
import type { ChatState, SettingsPatch, SkillsMode } from "./types";
import { canRecord, record, transcribe, VoiceFailed, type Recording } from "./voice";

const MODES: SkillsMode[] = ["auto", "manual", "off"];

function Skills({
  id,
  hidden,
  state,
  onSave,
}: {
  id: string;
  /** Drawn closed rather than unmounted: see the chip's `aria-controls`. */
  hidden: boolean;
  state: ChatState;
  onSave: (patch: SettingsPatch) => void;
}) {
  const t = useT();
  const mode = (MODES as string[]).includes(state.skills_mode)
    ? (state.skills_mode as SkillsMode)
    : "auto";
  const picked = state.skills_selected;
  // At the cap the lenses that are off go disabled rather than silently
  // refusing the press: the limit is the router's, and it has to be visible.
  const full = picked.length >= state.max_manual;

  return (
    <div className="ag-chat-picker" id={id} hidden={hidden}>
      <div className="ag-chat-group">{t("chat.skills_mode")}</div>
      <div className="ag-chat-modes">
        {MODES.map((name) => (
          <button
            type="button"
            key={name}
            className={`ag-chat-btn${name === mode ? " ag-chat-btn-on" : ""}`}
            aria-pressed={name === mode}
            onClick={() => onSave({ skills_mode: name })}
          >
            {t(`chat.skills_${name}`)}
          </button>
        ))}
      </div>
      {mode === "auto" && <p className="ag-chat-hint">{t("chat.skills_auto_hint")}</p>}
      {mode === "manual" && (
        <>
          <div className="ag-chat-group">{t("chat.skills_label")}</div>
          <div className="ag-chat-chips">
            {state.skills.map((skill) => {
              const on = picked.includes(skill.id);
              const blocked = full && !on;
              return (
                <button
                  type="button"
                  key={skill.id}
                  className={`ag-chat-chip${on ? " ag-chat-chip-on" : ""}`}
                  disabled={blocked}
                  aria-pressed={on}
                  onClick={() =>
                    onSave({
                      skills: on
                        ? picked.filter((id) => id !== skill.id)
                        : [...picked, skill.id],
                    })
                  }
                >
                  {skillName(t, skill.id, skill.name)}
                </button>
              );
            })}
          </div>
          {/* The cap said once, under the lenses it disables. A `title` on a
              disabled button is the one tooltip no reader ever gets: it opens
              for a mouse only, and a disabled control takes no focus. */}
          {full && (
            <p className="ag-chat-hint">
              {t("chat.skills_full", { n: state.max_manual })}
            </p>
          )}
        </>
      )}
    </div>
  );
}

export function Composer({
  state,
  busy,
  reading,
  onSend,
  onStop,
  onSave,
  onAttach,
  onSettings,
}: {
  state: ChatState;
  busy: boolean;
  /** A statement is being read, or written. The clip and Send both wait. */
  reading: boolean;
  onSend: (text: string, spoken?: boolean) => void;
  /** Cut the answer being written. Offered in Send's place while it streams. */
  onStop?: () => void;
  onSave: (patch: SettingsPatch) => void;
  onAttach: (file: File) => void;
  onSettings: () => void;
}) {
  const t = useT();
  const lang = useLang();
  const [text, setText] = useState("");
  const [picking, setPicking] = useState(false);
  const file = useRef<HTMLInputElement | null>(null);
  const field = useRef<HTMLTextAreaElement | null>(null);
  // The field holds a transcript, so the turn it becomes is badged as spoken.
  // Cleared with the field: a reader who deletes it all and types has typed.
  const spoken = useRef(false);
  const clip = useRef<Recording | null>(null);
  // "" is not recording; "…" while the clip is being turned into words.
  const [taping, setTaping] = useState(false);
  const [saying, setSaying] = useState(false);
  const [voiceError, setVoiceError] = useState<{
    key: string;
    slots: Record<string, number>;
  } | null>(null);
  // Focus lands at the end of the transcript once it is in the field, so the
  // reader can fix a word or press Enter without reaching for the mouse.
  const [caret, setCaret] = useState(false);
  const uid = useId();
  const pickerId = `${uid}-skills`;
  const webHelpId = `${uid}-web`;

  const mode = state.skills_mode;
  // The counter and the wall are about the free chain, so neither is drawn for
  // an account whose own key answers: it has no allowance to spend and no wall
  // to hit.
  const byok = state.providers.some((p) => p.id === state.answering && p.needs_key);
  const wall = !byok && state.cap_reason ? state.cap_reason : null;

  /**
   * Press to record, press again to transcribe into the field.
   *
   * Hold-to-talk was the other option and it loses the recording on every
   * scroll, drag and accidental release — on a phone especially, which is
   * where a voice note is worth anything at all.
   */
  const talk = async () => {
    if (saying || busy || reading) return;
    setVoiceError(null);
    if (!taping) {
      try {
        clip.current = await record();
        setTaping(true);
      } catch {
        // Denying the microphone is an answer, not a failure: nothing is
        // drawn, and the button goes back to where it was.
        clip.current = null;
      }
      return;
    }
    const tape = clip.current;
    clip.current = null;
    setTaping(false);
    if (!tape) return;
    setSaying(true);
    try {
      const said = await transcribe(await tape.stop(), lang);
      setText((was) => (was.trim() ? `${was.trim()} ${said}` : said));
      spoken.current = true;
      setCaret(true);
    } catch (failure) {
      setVoiceError(
        failure instanceof VoiceFailed
          ? { key: failure.key, slots: failure.slots }
          : { key: "chat.voice_failed", slots: {} },
      );
    } finally {
      setSaying(false);
    }
  };

  useEffect(() => {
    if (!caret) return;
    setCaret(false);
    const el = field.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [caret]);

  const submit = () => {
    const question = text.trim();
    if (!question || busy) return;
    setText("");
    onSend(question, spoken.current || undefined);
    spoken.current = false;
  };

  return (
    <div className="ag-chat-composer">
      {voiceError && (
        <p className="ag-chat-note">{t(voiceError.key, voiceError.slots)}</p>
      )}
      {wall && (
        <div className="ag-chat-wall">
          <p>{capMessage(t, wall, state.free_cap)}</p>
          {/* The way out of a shared cap is a key of your own, so the wall
              offers it instead of describing it. */}
          <button type="button" className="ag-chat-btn" onClick={onSettings}>
            <Glyph name="key" size={13} />
            {t("chat.free_add_key")}
          </button>
        </div>
      )}
      <div className="ag-chat-rail">
        {state.web_available && (
          <>
            <button
              type="button"
              className={`ag-chat-chip${state.web ? " ag-chat-chip-on" : ""}`}
              aria-pressed={state.web}
              aria-describedby={webHelpId}
              title={t("chat.web_help")}
              onClick={() => onSave({ web: !state.web })}
            >
              <Glyph name="globe" size={13} />
              {t("chat.web_chip")}
            </button>
            {/* What the `title` says, for everyone the `title` never reaches:
                it opens on hover and nowhere else, so a keyboard or a touch
                reader learns nothing about what Internet turns on. */}
            <span id={webHelpId} className="ag-sr">
              {t("chat.web_help")}
            </span>
          </>
        )}
        <button
          type="button"
          className={`ag-chat-chip${picking ? " ag-chat-chip-on" : ""}`}
          aria-expanded={picking}
          aria-controls={pickerId}
          onClick={() => setPicking((was) => !was)}
        >
          <Glyph name="spark" size={13} />
          {t("chat.skills_chip", { mode: t(`chat.skills_${mode}`) })}
        </button>
      </div>
      <Skills id={pickerId} hidden={!picking} state={state} onSave={onSave} />
      <form
        className="ag-chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {/* The input is the button: a visible file field in a chat composer
            reads as a form, and `accept` is the server's own list of every
            extension a parser (or the column mapper) can read. */}
        <input
          ref={file}
          type="file"
          className="ag-sr"
          tabIndex={-1}
          accept={state.upload_types.map((ext) => `.${ext}`).join(",")}
          onChange={(event) => {
            const picked = event.target.files?.[0];
            // Cleared on the way out, so attaching the same file twice in a
            // row still fires a change event the second time.
            event.target.value = "";
            if (picked) onAttach(picked);
          }}
        />
        <button
          type="button"
          className="ag-chat-clip"
          disabled={busy || reading}
          title={t("chat.attach", { mb: state.upload_max_mb })}
          aria-label={t("chat.attach", { mb: state.upload_max_mb })}
          onClick={() => file.current?.click()}
        >
          <Glyph name="attach" size={18} />
        </button>
        {state.voice && canRecord() && (
          <button
            type="button"
            className={`ag-chat-clip${taping ? " ag-chat-taping" : ""}`}
            disabled={busy || reading || saying}
            aria-pressed={taping}
            title={t(taping ? "chat.voice_stop" : "chat.voice_start")}
            aria-label={t(taping ? "chat.voice_stop" : "chat.voice_start")}
            onClick={() => void talk()}
          >
            <Glyph name={taping ? "stop" : "mic"} size={18} />
          </button>
        )}
        <textarea
          ref={field}
          className="ag-chat-field"
          value={text}
          rows={1}
          placeholder={t("chat.placeholder")}
          aria-label={t("chat.placeholder")}
          onChange={(event) => {
            setText(event.target.value);
            if (!event.target.value.trim()) spoken.current = false;
          }}
          onKeyDown={(event) => {
            // Enter sends, shift-enter writes a second line — the shape every
            // chat field in this app has had.
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              submit();
            }
          }}
        />
        {busy && onStop ? (
          // A plain button, not the form's submit: Enter in the field while an
          // answer streams must not stop it — a reader typing the next
          // question presses Enter out of habit, and losing the answer they
          // are waiting for to a keystroke is worse than the send being held.
          <button
            type="button"
            className="ag-chat-send ag-chat-stop"
            title={t("chat.stop")}
            aria-label={t("chat.stop")}
            onClick={onStop}
          >
            <Glyph name="stop" size={18} />
          </button>
        ) : (
          <button
            type="submit"
            className="ag-chat-send"
            disabled={busy || !text.trim()}
            aria-label={t("chat.send")}
          >
            <Glyph name="send" size={18} />
          </button>
        )}
      </form>
    </div>
  );
}
