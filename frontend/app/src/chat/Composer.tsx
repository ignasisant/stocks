/**
 * The input, and the control that changes what the next answer will be.
 *
 * The skill lens belongs at the composer rather than in a settings screen
 * opened once a quarter: it changes the *next* answer, so it sits beside the
 * thing it changes. It writes straight through to `PATCH /chat/settings`,
 * which returns the whole state — one round trip both applies the change and
 * re-reads what it implies. It is an icon inside the field rather than a chip
 * in a row of its own: on a phone that row was height taken from the
 * conversation for one control, and a lens off its default still shows, in
 * the icon's colour (`ag-box-set`).
 *
 * There is no Internet chip any more. The assistant reads the web wherever
 * search works (`engine.web_enabled`): the toggle was one almost nobody moved
 * off its default, and those who did got quietly worse answers with nothing
 * on screen saying why.
 *
 * A second send while one is in flight is refused here rather than queued: the
 * engine writes one thread, and a queued question would land inside the first
 * answer's history half-written. The field stays open the whole time, because
 * being unable to type the next question is not the same as being unable to
 * send it. While an answer is being written, Send *is* Stop: the one control a
 * reader looks for when an answer is going the wrong way is the one their
 * thumb is already on.
 *
 * The paperclip is the other control, and it is the one that does not change
 * the next answer but replaces it: a statement attached here is an import — a
 * parse, a preview and a confirmation — served by `/chat/attachments`, and the
 * card it opens is what writes to the ledger. One file per press, because a
 * second attachment would either queue a second preview behind the first or be
 * dropped with an apology, and in practice the second file was nearly always
 * the same export twice. Pasting into the field is the same door (`pasted.ts`):
 * a copied file, rows out of a spreadsheet or a base64 PDF go to the preview,
 * not into the question.
 *
 * A pasted picture is the other thing a paste can be, and it is part of the
 * question rather than in place of it: a screenshot of a broker's screen, a
 * chart, a table somebody posted. It is read into words on the way in
 * (`shots.ts`) — the chat is text from end to end — and waits above the field
 * as a thumbnail with a way to take it back, up to three. Send holds until
 * the reading is in, because a question sent ahead of its picture is a
 * question about nothing. The sent question shows the picture over it and
 * what was read under it (`Turn`), since a figure misread there is misread in
 * the answer. With the field left empty the picture is the question, and a
 * stock one is asked for it. Offered only where something can see
 * (`state.screenshots`). There the clip takes pictures too, and so does a
 * drop on the conversation (`take`): a phone has no Ctrl+V worth the name,
 * and its file picker is where the camera and the photo library are.
 *
 * A document is the third thing that can ride with a question (`docs.ts`): a
 * PDF's text, or words pasted in one piece too long to be a question. It
 * waits above the field as a chip with its name, and Send holds until it is
 * read, as for a picture. A PDF is also what a statement comes as, and
 * nothing in the file says which it is — so one that arrives is asked about
 * first: "Ask about it" or "Import its trades". Asking is taken mid-answer,
 * as a picture is; the import waits its turn. Only the start of a long one
 * goes with the question, and the line under the chip says so before it is
 * sent rather than after the answer misses page forty.
 *
 * The microphone is the fourth, inside the field beside the lens — the same
 * control, in the same corner, as the feedback dialog's (`ui/Mic`). It is
 * drawn only where it can work: this browser has to have `MediaRecorder` and
 * the deployment has to have a transcription key (`state.voice`). A spoken question is transcribed into the
 * field, not sent: Whisper mishears tickers and numbers often enough that the
 * reader has to see the words before they become a question, and correcting a
 * sent turn costs a whole answer. It joins whatever was already typed, because
 * a note recorded *with* something typed reads as one message rather than two,
 * and the turn is still badged as spoken when it goes. While it is being said,
 * the browser's recogniser writes it into the field as it is heard (`voice.ts`)
 * — greyed and read-only, with Send held, until Whisper's transcript replaces
 * it at the stop.
 *
 * "In depth" lives in the lens picker too, above the lenses: it changes how far
 * the next answer's research goes (`agent.DEEP`), which is a minute or two of
 * reading and, on the free chain, more of the day's allowance — said under it.
 * It is for the next question only, not a setting: a switch left on would
 * spend that allowance on every "thanks" after it. The lens icon is marked
 * while it is on, the way a lens off its default is, and the field's prompt
 * says it in words. Both it and the lens mode are one-of-a-few choices, so
 * they are the DS's segmented control; the lenses themselves are chips,
 * because several can be on at once.
 *
 * The model sits at the top of the same picker, for the provider that will
 * answer (`state.answering`): which model writes the next answer is as much a
 * choice about that answer as its depth. It is the settings screen's own
 * control (`Settings.Model`) — every model the key reaches, in one list — and
 * asks for the catalogue only once the picker opens; drawn only
 * where there is something to pick — the keyless chain has one model.
 *
 * The picker closes on a press anywhere outside it, and on Escape: it is a
 * popover over the conversation, and a reader who has picked turns back to the
 * answer — reaching for the icon again to put it away was one press too many.
 */

import { useEffect, useId, useRef, useState, type Ref } from "react";
import { useLang, useT } from "../shell/i18n";
import { capMessage, skillName } from "./format";
import { Glyph } from "./icons";
import { acceptOf } from "../pages/import/api";
import { Box, Mic } from "../ui/Mic";
import { Segmented } from "../ui/Segmented";
import { Status } from "../ui/Status";
import { ToggleChip } from "../ui/Toggle";
import type { ChatState, Doc, SettingsPatch, SkillsMode } from "./types";
import { canRecord, dictate, join, VoiceFailed, type Dictation } from "./voice";
import { useAssistantFills } from "../shell/assistant";
import { takeDraft } from "./draft";
import { noteShot } from "./api";
import {
  isPdf,
  MAX_DOCS,
  PASTE_FROM,
  pastedDoc,
  refused as refusedDoc,
  textOf,
} from "./docs";
import { pastedShot, pastedStatement, sorted } from "./pasted";
import { encoded, keepPicture, MAX_SHOTS, refused, wordsOf, type Way } from "./shots";
import { Model } from "./Settings";

const MODES: SkillsMode[] = ["auto", "manual", "off"];

/**
 * Where an own-key reader's "in depth" is remembered. On the free chain the
 * switch is for one question — each deep turn spends several of the day's
 * uses — but an account whose own key answers spends none, so the depth it
 * picked stays picked, across questions and reloads.
 */
const DEEP_KEPT = "chatDeep";

function keptDeep(): boolean {
  try {
    return window.localStorage.getItem(DEEP_KEPT) === "1";
  } catch {
    return false;
  }
}

function keepDeep(deep: boolean): void {
  try {
    if (deep) window.localStorage.setItem(DEEP_KEPT, "1");
    else window.localStorage.removeItem(DEEP_KEPT);
  } catch {
    // Private mode: the switch still holds until the drawer closes.
  }
}

function Skills({
  id,
  box,
  hidden,
  state,
  onSave,
  deep,
  onDeep,
  free,
}: {
  id: string;
  box: Ref<HTMLDivElement>;
  /** Drawn closed rather than unmounted: see the chip's `aria-controls`. */
  hidden: boolean;
  state: ChatState;
  onSave: (patch: SettingsPatch) => void;
  deep: boolean;
  onDeep: (deep: boolean) => void;
  /** The free chain answers, so a deep question costs more of its allowance. */
  free: boolean;
}) {
  const t = useT();
  const mode = (MODES as string[]).includes(state.skills_mode)
    ? (state.skills_mode as SkillsMode)
    : "auto";
  const picked = state.skills_selected;
  // At the cap the lenses that are off go disabled rather than silently
  // refusing the press: the limit is the router's, and it has to be visible.
  const full = picked.length >= state.max_manual;
  const answers = state.providers.find((p) => p.id === state.answering);
  const choosable = answers && (answers.needs_key || answers.models.length > 1);

  return (
    <div className="ag-chat-picker" id={id} ref={box} hidden={hidden}>
      {choosable && (
        <>
          <div className="ag-chat-group" aria-hidden="true">
            {t("chat.model")}
          </div>
          <Model
            key={answers.id}
            provider={answers}
            busy={false}
            onSave={onSave}
            active={!hidden}
          />
        </>
      )}
      <div className="ag-chat-group" aria-hidden="true">
        {t("chat.depth_mode")}
      </div>
      <Segmented
        items={[
          { id: "normal", label: t("chat.depth_normal") },
          { id: "deep", label: t("chat.depth_deep") },
        ]}
        value={deep ? "deep" : "normal"}
        onPick={(next) => onDeep(next === "deep")}
        label={t("chat.depth_mode")}
      />
      {deep && (
        <p className="ag-chat-hint">
          {t(free ? "chat.depth_hint" : "chat.depth_hint_kept")}
          {free && ` ${t("chat.depth_cost", { n: state.deep_units })}`}
        </p>
      )}
      <div className="ag-chat-group" aria-hidden="true">
        {t("chat.skills_mode")}
      </div>
      <Segmented
        items={MODES.map((name) => ({ id: name, label: t(`chat.skills_${name}`) }))}
        value={mode}
        onPick={(name) => onSave({ skills_mode: name })}
        label={t("chat.skills_mode")}
      />
      {mode === "auto" && <p className="ag-chat-hint">{t("chat.skills_auto_hint")}</p>}
      {mode === "manual" && (
        <>
          <div className="ag-chat-group">{t("chat.skills_label")}</div>
          <div className="ag-chat-chips">
            {state.skills.map((skill) => {
              const on = picked.includes(skill.id);
              const blocked = full && !on;
              return (
                <ToggleChip
                  key={skill.id}
                  on={on}
                  disabled={blocked}
                  onClick={() =>
                    onSave({
                      skills: on
                        ? picked.filter((id) => id !== skill.id)
                        : [...picked, skill.id],
                    })
                  }
                >
                  {skillName(t, skill.id, skill.name)}
                </ToggleChip>
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
  drops,
}: {
  state: ChatState;
  busy: boolean;
  /** A statement is being read, or written. The clip and Send both wait. */
  reading: boolean;
  onSend: (
    text: string,
    spoken?: boolean,
    deep?: boolean,
    shots?: string[],
    docs?: Doc[],
  ) => void;
  /** Cut the answer being written. Offered in Send's place while it streams. */
  onStop?: () => void;
  onSave: (patch: SettingsPatch) => void;
  onAttach: (file: File) => void;
  onSettings: () => void;
  /**
   * Where the panel finds `take`: files dropped on the conversation above
   * are this composer's to sort, since the pictures wait here.
   */
  drops?: { current: ((files: File[]) => void) | null };
}) {
  const t = useT();
  const lang = useLang();
  const [text, setText] = useState("");
  const [picking, setPicking] = useState(false);
  const byok = state.providers.some((p) => p.id === state.answering && p.needs_key);
  const [deep, setDeep] = useState(() => byok && keptDeep());
  const file = useRef<HTMLInputElement | null>(null);
  const field = useRef<HTMLTextAreaElement | null>(null);
  // The field holds a transcript, so the turn it becomes is badged as spoken.
  // Cleared with the field: a reader who deletes it all and types has typed.
  const spoken = useRef(false);
  const clip = useRef<Dictation | null>(null);
  // What the field held when the recording started: the words being said are
  // drawn after it, and the transcript replaces them there.
  const before = useRef("");
  // "" is not recording; "…" while the clip is being turned into words.
  const [taping, setTaping] = useState(false);
  const [saying, setSaying] = useState(false);
  const [voiceError, setVoiceError] = useState<{
    key: string;
    slots: Record<string, number>;
  } | null>(null);
  // Pasted pictures, oldest first. No `url` yet is one still being decoded;
  // no `text` yet is one still being read.
  const [shots, setShots] = useState<{ id: number; url?: string; text?: string }[]>([]);
  const [shotError, setShotError] = useState<{
    key: string;
    slots: Record<string, number>;
  } | null>(null);
  // The pictures still wanted: one taken back mid-reading must neither come
  // back when its reading lands nor apologise when it fails.
  const wanted = useRef(new Set<number>());
  const shotId = useRef(0);
  // The documents for the next question, oldest first. No `text` yet is a
  // PDF still being read.
  const [docs, setDocs] = useState<
    {
      id: number;
      name: string;
      text?: string;
      cut?: boolean;
      pages?: number;
      read?: number;
    }[]
  >([]);
  const [docError, setDocError] = useState<{
    key: string;
    slots: Record<string, number>;
  } | null>(null);
  const docsWanted = useRef(new Set<number>());
  const docId = useRef(0);
  // A PDF that has arrived and has not been told what it is for.
  const [pdf, setPdf] = useState<{ file: File; via: Way } | null>(null);
  // Focus lands at the end of the transcript once it is in the field, so the
  // reader can fix a word or press Enter without reaching for the mouse.
  const [caret, setCaret] = useState(false);
  const uid = useId();
  const pickerId = `${uid}-skills`;
  const picker = useRef<HTMLDivElement | null>(null);
  const lensButton = useRef<HTMLButtonElement | null>(null);

  // A press outside the picker puts it away. The icon is left out: its own
  // click toggles, and closing here first would have that click reopen it.
  useEffect(() => {
    if (!picking) return;
    const away = (event: PointerEvent) => {
      const target = event.target as Node;
      if (picker.current?.contains(target)) return;
      if (lensButton.current?.contains(target)) return;
      setPicking(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      // Only the picker: the drawer closes on Escape too (on `window`, which
      // this `document` listener runs before), and one press is one step back.
      event.stopPropagation();
      setPicking(false);
      lensButton.current?.focus();
    };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [picking]);

  const mode = state.skills_mode;
  const skills = t("chat.skills_chip", { mode: t(`chat.skills_${mode}`) });
  const lens = deep ? `${skills} · ${t("chat.depth_deep")}` : skills;
  // Said in the field too, not only by the icon's colour: the switch is for
  // this question, and the field is where the reader is looking when it goes.
  const hint = t(deep ? "chat.placeholder_deep" : "chat.placeholder");
  // The counter and the wall are about the free chain, so neither is drawn for
  // an account whose own key answers: it has no allowance to spend and no wall
  // to hit.
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
      before.current = text;
      try {
        clip.current = await dictate(lang, (words) =>
          setText(join(before.current, words)),
        );
        setTaping(true);
      } catch {
        // Denying the microphone is an answer, not a failure: nothing is
        // drawn, and the button goes back to where it was.
        clip.current = null;
        setText(before.current);
      }
      return;
    }
    const tape = clip.current;
    clip.current = null;
    setTaping(false);
    if (!tape) return;
    setSaying(true);
    try {
      setText(join(before.current, await tape.stop()));
      spoken.current = true;
      setCaret(true);
    } catch (failure) {
      setText(before.current);
      setVoiceError(
        failure instanceof VoiceFailed
          ? { key: failure.key, slots: failure.slots }
          : { key: "chat.voice_failed", slots: {} },
      );
    } finally {
      setSaying(false);
    }
  };

  // A recording must not outlive the drawer: the microphone light would stay
  // on, and the recogniser would keep writing into a field nobody sees.
  useEffect(() => () => clip.current?.cancel(), []);

  // The drawer hands its focus to the panel on open (`Drawer.tsx`); with a
  // mouse and keyboard the field is where it belongs. Not on a touch screen,
  // where focusing raises the soft keyboard over the answer the reader opened
  // the drawer to read.
  useEffect(() => {
    const el = field.current;
    const host = el?.closest(".ag-chat-panel");
    if (!el || !host || document.activeElement !== host) return;
    if (window.matchMedia?.("(hover: hover) and (pointer: fine)").matches) {
      el.focus({ preventScroll: true });
    }
  }, []);

  // A question asked as a guest, kept across the sign-in (`draft.ts`): put in
  // the field, caret at its end, and left for the reader to send — sending it
  // would spend the daily allowance on a press made before there was one.
  const takeKept = () => {
    const kept = takeDraft();
    if (!kept) return;
    setText(kept);
    setCaret(true);
  };
  useEffect(takeKept, []);
  // A page's "type it instead" (`shell/assistant.ts`) while the drawer is
  // already open: the same slot, told to be read now rather than on mount.
  useAssistantFills(takeKept);

  useEffect(() => {
    if (!caret) return;
    setCaret(false);
    const el = field.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(el.value.length, el.value.length);
  }, [caret]);

  // The words in the field are still being said, or about to be replaced.
  const live = taping || saying;

  const paste = async (picture: File, via: Way = "paste") => {
    // Counted off the ref, not the state: two pastes in one tick both see it.
    if (wanted.current.size >= MAX_SHOTS) {
      setShotError({ key: "chat.shot_too_many", slots: { n: MAX_SHOTS } });
      noteShot("refused", { why: "chat.shot_too_many", sent: false });
      return;
    }
    setShotError(null);
    const id = ++shotId.current;
    wanted.current.add(id);
    const fill = (more: { url?: string; text?: string }) =>
      setShots((list) =>
        list.map((shot) => (shot.id === id ? { ...shot, ...more } : shot)),
      );
    // Up before the picture is even decoded: the paste was seen.
    setShots((list) => [...list, { id }]);
    let sent = false;
    try {
      const shot = await encoded(picture);
      fill({ url: shot.url });
      sent = true;
      fill({ text: await wordsOf(shot, lang, via) });
    } catch (failure) {
      if (!wanted.current.delete(id)) return;
      setShots((list) => list.filter((shot) => shot.id !== id));
      const { key, slots } = refused(failure);
      setShotError({ key, slots });
      noteShot("refused", { why: key, sent });
    }
  };

  /** Room for one more document, or the line that says there is none. */
  const room = (): boolean => {
    // Counted off the ref, as the pictures are.
    if (docsWanted.current.size < MAX_DOCS) {
      setDocError(null);
      return true;
    }
    setDocError({ key: "chat.doc_too_many", slots: { n: MAX_DOCS } });
    return false;
  };

  /** Read a PDF into the text the next question takes with it. */
  const study = async (file: File, via: Way) => {
    if (!room()) return;
    const id = ++docId.current;
    docsWanted.current.add(id);
    // Up before it is read, under the name it has on this device.
    setDocs((list) => [...list, { id, name: file.name }]);
    try {
      const found = await textOf(file, via);
      if (!docsWanted.current.has(id)) return;
      setDocs((list) => list.map((doc) => (doc.id === id ? { id, ...found } : doc)));
    } catch (failure) {
      if (!docsWanted.current.delete(id)) return;
      setDocs((list) => list.filter((doc) => doc.id !== id));
      const { key, slots } = refusedDoc(failure);
      setDocError({ key, slots });
    }
  };

  /**
   * A PDF has arrived. Where a statement can come as one, the reader says
   * which this is; where none can, it is a document to ask about.
   */
  const offer = (file: File, via: Way) => {
    setDocError(null);
    if (state.upload_types.includes("pdf")) setPdf({ file, via });
    else void study(file, via);
  };

  /**
   * Files from the clip or a drop: the pictures join the question, as a
   * paste would have; the first of the rest is a statement to import, or a
   * PDF to ask about.
   */
  const take = (files: ArrayLike<File>, via: Way) => {
    const { shots: pictures, statement } = sorted(files, state.screenshots);
    for (const picture of pictures) void paste(picture, via);
    if (!statement) return;
    // A picture or a document is for the next question and is taken
    // mid-answer, as typing is. A statement is an import of its own, and
    // waits its turn.
    if (isPdf(statement)) offer(statement, via);
    else if (!busy && !reading) onAttach(statement);
  };
  // Every render: `take` reads the state of the one it was made in.
  useEffect(() => {
    if (!drops) return;
    drops.current = (files) => take(files, "drop");
    return () => {
      drops.current = null;
    };
  });

  const drop = (id: number) => {
    wanted.current.delete(id);
    noteShot("removed", {
      read: shots.some((shot) => shot.id === id && shot.text !== undefined),
    });
    setShots((list) => list.filter((shot) => shot.id !== id));
    setShotError(null);
  };

  const dropDoc = (id: number) => {
    docsWanted.current.delete(id);
    setDocs((list) => list.filter((doc) => doc.id !== id));
    setDocError(null);
  };

  const read = shots.flatMap((shot) => (shot.text === undefined ? [] : [shot.text]));
  const studied = docs.flatMap((doc) =>
    doc.text === undefined ? [] : [{ name: doc.name, text: doc.text, cut: !!doc.cut }],
  );
  const unstudied = docs.length > studied.length;
  const unread = shots.length > read.length;
  // What Send waits for: everything that rides with the question is in.
  const waiting = unread || unstudied;
  // Said once each: two long pastes are one sentence, not the same one twice.
  const cuts = [
    ...new Set(
      docs.flatMap((doc) =>
        !doc.cut
          ? []
          : doc.pages && doc.read && doc.read < doc.pages
            ? [t("chat.doc_cut_pages", { read: doc.read, pages: doc.pages })]
            : [t("chat.doc_cut")],
      ),
    ),
  ];

  const submit = () => {
    // A picture or a document with nothing typed is the question: asked in a
    // stock sentence, because a turn is filed, titled and notified by its
    // words.
    const question =
      text.trim() ||
      (read.length ? t("chat.shot_ask") : studied.length ? t("chat.doc_ask") : "");
    if (!question || busy || live || waiting) return;
    // The thread keeps the words; the picture over the sent question is this
    // device's copy.
    for (const shot of shots) {
      if (shot.text !== undefined && shot.url) keepPicture(shot.text, shot.url);
    }
    setText("");
    setShots([]);
    setShotError(null);
    wanted.current.clear();
    setDocs([]);
    setDocError(null);
    docsWanted.current.clear();
    onSend(
      question,
      spoken.current || undefined,
      deep || undefined,
      read.length ? read : undefined,
      studied.length ? studied : undefined,
    );
    spoken.current = false;
    if (!byok) setDeep(false);
  };

  const pickDepth = (next: boolean) => {
    setDeep(next);
    if (byok) keepDeep(next);
  };

  const attachLabel = t(state.screenshots ? "chat.attach_any" : "chat.attach", {
    mb: state.upload_max_mb,
  });

  return (
    // A file let go over the field instead of the conversation is the same
    // drop — and left to the browser it would open in place of the app.
    <div
      className="ag-chat-composer"
      onDragOver={(event) => {
        if (event.dataTransfer.types.includes("Files")) event.preventDefault();
      }}
      onDrop={(event) => {
        if (!event.dataTransfer.files?.length) return;
        event.preventDefault();
        take(event.dataTransfer.files, "drop");
      }}
    >
      {voiceError && (
        <p className="ag-chat-note">{t(voiceError.key, voiceError.slots)}</p>
      )}
      {/* Above the field the transcript is about to fill: a long note is a
          few seconds of Whisper, and the mic going grey says nothing. */}
      {saying && <Status label={t("chat.work_transcribing")} />}
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
      <Skills
        id={pickerId}
        box={picker}
        hidden={!picking}
        state={state}
        onSave={onSave}
        deep={deep}
        onDeep={pickDepth}
        free={!byok && state.free_cap !== null}
      />
      {shotError && (
        <p className="ag-chat-note" role="alert">
          {t(shotError.key, shotError.slots)}
        </p>
      )}
      {shots.length > 0 && (
        <ul className="ag-chat-shots">
          {shots.map((shot) => (
            <li
              key={shot.id}
              className={`ag-chat-shot${shot.text === undefined ? " ag-chat-shot-unread" : ""}`}
            >
              {shot.url && <img src={shot.url} alt={t("chat.shot_alt")} />}
              <button
                type="button"
                className="ag-chat-shot-x"
                aria-label={t("chat.shot_remove")}
                onClick={() => drop(shot.id)}
              >
                <Glyph name="close" size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {/* A reading is a few seconds of a model looking; a dimmed thumbnail
          alone does not say what Send is waiting for. */}
      {unread && <Status label={t("chat.work_reading_shot")} />}
      {docError && (
        <p className="ag-chat-note" role="alert">
          {t(docError.key, docError.slots)}
        </p>
      )}
      {pdf && (
        <div className="ag-chat-pdf" role="group" aria-label={pdf.file.name}>
          <span className="ag-chat-doc-name">{pdf.file.name}</span>
          <span className="ag-chat-pdf-acts">
            <button
              type="button"
              className="ag-chat-btn"
              onClick={() => {
                setPdf(null);
                void study(pdf.file, pdf.via);
              }}
            >
              {t("chat.pdf_ask")}
            </button>
            <button
              type="button"
              className="ag-chat-btn"
              disabled={busy || reading}
              onClick={() => {
                setPdf(null);
                onAttach(pdf.file);
              }}
            >
              {t("chat.pdf_import")}
            </button>
            <button
              type="button"
              className="ag-chat-doc-x"
              aria-label={t("chat.doc_remove")}
              onClick={() => setPdf(null)}
            >
              <Glyph name="close" size={12} />
            </button>
          </span>
        </div>
      )}
      {docs.length > 0 && (
        <ul className="ag-chat-docs">
          {docs.map((doc) => (
            <li
              key={doc.id}
              className={`ag-chat-doc${doc.text === undefined ? " ag-chat-doc-unread" : ""}`}
            >
              <Glyph name="attach" size={13} />
              <span className="ag-chat-doc-name">
                {doc.name || t("chat.doc_pasted")}
              </span>
              <button
                type="button"
                className="ag-chat-doc-x"
                aria-label={t("chat.doc_remove")}
                onClick={() => dropDoc(doc.id)}
              >
                <Glyph name="close" size={12} />
              </button>
            </li>
          ))}
        </ul>
      )}
      {cuts.map((cut) => (
        <p className="ag-chat-hint ag-chat-doc-cut" key={cut}>
          {cut}
        </p>
      ))}
      {unstudied && <Status label={t("chat.work_reading_doc")} />}
      <form
        className="ag-chat-form"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {/* The input is the button: a visible file field in a chat composer
            reads as a form, and `accept` is the server's own list of every
            extension a parser (or the column mapper) can read — with the MIME
            types each goes by, since Android's picker filters on those.
            Pictures join it where something can see: `image/*` is what makes
            a phone offer its camera and photo library beside its files, and
            several can be picked because a question takes several. */}
        <input
          ref={file}
          type="file"
          className="ag-sr"
          tabIndex={-1}
          accept={
            state.screenshots
              ? `${acceptOf(state.upload_types)},image/*`
              : acceptOf(state.upload_types)
          }
          multiple={state.screenshots}
          onChange={(event) => {
            // Copied first: the list is the input's own, and empties with it.
            const picked = Array.from(event.target.files ?? []);
            // Cleared on the way out, so attaching the same file twice in a
            // row still fires a change event the second time.
            event.target.value = "";
            take(picked, "pick");
          }}
        />
        <button
          type="button"
          className="ag-chat-clip"
          disabled={busy || reading}
          title={attachLabel}
          aria-label={attachLabel}
          onClick={() => file.current?.click()}
        >
          <Glyph name="attach" size={18} />
        </button>
        <Box
          tools={
            <>
              <button
                ref={lensButton}
                type="button"
                className={`ag-box-tool${picking ? " ag-box-open" : ""}${
                  mode !== "auto" || deep ? " ag-box-set" : ""
                }`}
                aria-expanded={picking}
                aria-controls={pickerId}
                title={lens}
                aria-label={lens}
                onClick={() => setPicking((was) => !was)}
              >
                <Glyph name="spark" size={16} />
              </button>
              {state.voice && canRecord() && (
                <Mic
                  on={taping}
                  disabled={busy || reading || saying}
                  label={t(taping ? "chat.voice_stop" : "chat.voice_start")}
                  onPress={() => void talk()}
                />
              )}
            </>
          }
        >
          <textarea
            ref={field}
            className={`ag-chat-field${live ? " ag-chat-heard" : ""}`}
            value={text}
            readOnly={live}
            rows={1}
            enterKeyHint="send"
            placeholder={hint}
            aria-label={hint}
            onChange={(event) => {
              setText(event.target.value);
              if (!event.target.value.trim()) spoken.current = false;
            }}
            onPaste={(event) => {
              if (live) return;
              const pasted = pastedStatement(event.clipboardData, state.upload_types);
              if (pasted && isPdf(pasted)) {
                event.preventDefault();
                offer(pasted, "paste");
                return;
              }
              if (pasted) {
                // Mid-answer a statement is left to land as whatever the
                // browser makes of it: an import waits its turn.
                if (busy || reading) return;
                event.preventDefault();
                onAttach(pasted);
                return;
              }
              // Taken while an answer is still being written, as typing is:
              // the picture is for the next question.
              const picture = pastedShot(event.clipboardData);
              if (picture) {
                if (!state.screenshots) {
                  // Left alone, as before, but no longer unseen: a reader who
                  // pastes where nothing can read is one the feature missed.
                  noteShot("ignored");
                  return;
                }
                event.preventDefault();
                void paste(picture);
                return;
              }
              // An article or a filing copied whole is not a question: it
              // rides beside one, and the field stays free to ask it in.
              const words = event.clipboardData.getData("text/plain");
              if (words.trim().length < PASTE_FROM) return;
              event.preventDefault();
              if (!room()) return;
              const id = ++docId.current;
              docsWanted.current.add(id);
              setDocs((list) => [...list, { id, ...pastedDoc(words) }]);
            }}
            onKeyDown={(event) => {
              // Enter sends, shift-enter writes a second line — the shape every
              // chat field in this app has had.
              // Not while an IME is composing: that Enter confirms a candidate.
              if (
                event.key === "Enter" &&
                !event.shiftKey &&
                !event.nativeEvent.isComposing
              ) {
                event.preventDefault();
                submit();
              }
            }}
          />
        </Box>
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
            disabled={
              busy ||
              live ||
              waiting ||
              (!text.trim() && !read.length && !studied.length)
            }
            aria-label={t("chat.send")}
          >
            <Glyph name="send" size={18} />
          </button>
        )}
      </form>
    </div>
  );
}
