/**
 * A spoken question: recorded here, transcribed by the server, sent as text.
 *
 * `MediaRecorder` and nothing else. Encoding WAV by hand would mean pulling
 * every sample through an `AudioContext` and writing a header in the browser,
 * and the only thing it would buy is a format the backend does not need: the
 * recorder's own type travels with the bytes (`POST /chat/voice`), so Chrome's
 * WebM and Safari's MP4 are both simply what they are.
 *
 * The stream's tracks are stopped on every exit — the ordinary one, the failed
 * one and the abandoned one. A microphone left open is a recording light left
 * on, which is the one bug in this file a reader would notice from across the
 * room.
 *
 * While the reader talks, the browser's own recogniser (`SpeechRecognition`,
 * still prefixed in Chrome and Safari) writes what it hears as it hears it, so
 * a note is read while it is being said rather than after (`dictate`). Those
 * words are a preview, not the transcript: at the stop the clip goes to
 * Whisper as it always did, and Whisper's words replace them. They become the
 * transcript only where Whisper has none — refused on the hourly cap, or handed
 * a silent clip by a phone that gave the microphone to the recogniser — because
 * words the reader watched appear beat an apology for them. Chrome's recogniser
 * runs on Google's servers and Safari's on Apple's or the device; a browser
 * without one (Firefox) dictates exactly as before, the words arriving at the
 * stop.
 */

import { ApiError, send } from "../shell/api";

/** The types worth asking for, best first. The browser picks the first it has. */
const WANTED = ["audio/webm", "audio/mp4", "audio/ogg"];

/** Recording is a browser capability, not a deployment one — check both. */
export function canRecord(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.MediaRecorder !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia
  );
}

function mimeType(): string | undefined {
  return WANTED.find((type) => window.MediaRecorder.isTypeSupported?.(type));
}

type Recording = {
  /** Stop, and resolve with the clip. The tracks are released either way. */
  stop: () => Promise<Blob>;
  /** Drop the recording without transcribing it. */
  cancel: () => void;
};

/**
 * Start recording. Rejects when the reader denies the microphone, which is an
 * answer and not a failure — the caller draws nothing and the button resets.
 */
async function record(): Promise<Recording> {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const type = mimeType();
  const recorder = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
  const chunks: Blob[] = [];
  recorder.ondataavailable = (event) => {
    if (event.data.size) chunks.push(event.data);
  };
  recorder.start();

  const release = () => stream.getTracks().forEach((track) => track.stop());

  return {
    stop: () =>
      new Promise<Blob>((resolve) => {
        recorder.onstop = () => {
          release();
          resolve(
            new Blob(chunks, { type: recorder.mimeType || type || "audio/webm" }),
          );
        };
        // `inactive` already means the recorder stopped itself — a tab that
        // lost the device, most often — and calling stop() again throws.
        if (recorder.state === "inactive") {
          release();
          resolve(new Blob(chunks, { type: recorder.mimeType || "audio/webm" }));
        } else recorder.stop();
      }),
    cancel: () => {
      recorder.onstop = null;
      if (recorder.state !== "inactive") recorder.stop();
      release();
    },
  };
}

/**
 * The words in a clip, or a locale key to say why there are none.
 *
 * The server answers refusals with a catalog key (`chat.voice_silent`,
 * `chat.voice_too_long`, …), so the drawer says why in the reader's own
 * language.
 */
async function transcribe(clip: Blob, lang: string): Promise<string> {
  const buffer = await clip.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  // In chunks: `String.fromCharCode(...bytes)` on a minute of audio is a call
  // with a million arguments, which overflows the stack in every engine.
  let binary = "";
  for (let at = 0; at < bytes.length; at += 8192) {
    binary += String.fromCharCode(...bytes.subarray(at, at + 8192));
  }
  const body = {
    audio: btoa(binary),
    content_type: (clip.type || "audio/webm").split(";")[0],
    lang,
  };
  try {
    const { text } = await send<{ text: string }>("POST", "/chat/voice", body);
    return text;
  } catch (failure) {
    const detail = failure instanceof ApiError ? failure.detail : "";
    const wait = failure instanceof ApiError ? failure.retryAfter : undefined;
    throw new VoiceFailed(
      detail.startsWith("chat.") ? detail : "chat.voice_failed",
      wait === undefined ? {} : { seconds: wait },
    );
  }
}

/** Words from any source joined as one note, one space apart. */
export function join(...parts: string[]): string {
  return parts
    .map((part) => part.trim())
    .filter(Boolean)
    .join(" ");
}

/**
 * The browser's recogniser, as far as this file uses it. `lib.dom` types its
 * events but not the class, which is why this does.
 */
type Recogniser = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: SpeechRecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  abort: () => void;
};

type Recognisers = {
  SpeechRecognition?: new () => Recogniser;
  webkitSpeechRecognition?: new () => Recogniser;
};

/** The recogniser wants a region; the app knows a language. */
const LOCALES: Record<string, string> = { es: "es-ES", en: "en-US" };

export type Listening = {
  /** Everything heard so far, the phrase still being said included. */
  heard: () => string;
  /** Stop listening. No words arrive after this. */
  stop: () => void;
};

/**
 * Listen with the browser's recogniser, handing `onWords` the whole note so
 * far each time it changes. `null` where the browser has no recogniser.
 *
 * A continuous session still ends on its own — Chrome's after a stretch of
 * silence, Safari's after a phrase — so an ended session is followed by a new
 * one that carries the words before it. Only when the one that ended heard
 * something or ended on silence: a session that ends with neither is the
 * browser declining, and starting it again would only loop.
 */
export function listen(
  lang: string,
  onWords: (words: string) => void,
): Listening | null {
  const kinds = (typeof window === "undefined" ? {} : window) as Recognisers;
  const Kind = kinds.SpeechRecognition ?? kinds.webkitSpeechRecognition;
  if (!Kind) return null;
  // What the sessions before this one settled on, and this one's words.
  let kept = "";
  let now = "";
  let over = false;
  let session: Recogniser | null = null;

  const open = (Make: new () => Recogniser) => {
    const current = new Make();
    let quiet = false;
    session = current;
    current.lang = LOCALES[lang] ?? lang;
    current.continuous = true;
    current.interimResults = true;
    current.onresult = (event) => {
      now = join(...Array.from(event.results, (result) => result[0]?.transcript ?? ""));
      onWords(join(kept, now));
    };
    current.onerror = (event) => {
      // Silence ends a session and the next one picks up. Anything else —
      // denied, no service, no network — would only be refused again.
      if (event.error === "no-speech") quiet = true;
      else over = true;
    };
    current.onend = () => {
      const heard = !!now;
      kept = join(kept, now);
      now = "";
      if (over || !(heard || quiet)) {
        over = true;
        return;
      }
      try {
        open(Make);
      } catch {
        over = true;
      }
    };
    current.start();
  };

  try {
    open(Kind);
  } catch {
    return null;
  }
  return {
    heard: () => join(kept, now),
    stop: () => {
      over = true;
      const current = session as Recogniser | null;
      if (!current) return;
      current.onresult = null;
      current.onerror = null;
      current.onend = null;
      current.abort();
    },
  };
}

export type Dictation = {
  /**
   * Stop, and resolve with the words: Whisper's, or the recogniser's where
   * Whisper has none. Rejects with `VoiceFailed` only when neither heard any.
   */
  stop: () => Promise<string>;
  /** Drop it: no transcription, and no words after this. */
  cancel: () => void;
};

/**
 * Record a note, handing `onWords` what is being said while it is said.
 *
 * The recogniser starts first, still inside the press that asked for it —
 * browsers are readier to open a microphone for a gesture than after one —
 * and is dropped if the reader then denies the recording, which rejects the
 * way `record` does.
 */
export async function dictate(
  lang: string,
  onWords: (words: string) => void,
): Promise<Dictation> {
  const ear = listen(lang, onWords);
  let tape: Recording;
  try {
    tape = await record();
  } catch (denied) {
    ear?.stop();
    throw denied;
  }
  return {
    stop: async () => {
      ear?.stop();
      const heard = ear?.heard() ?? "";
      try {
        return (await transcribe(await tape.stop(), lang)) || heard;
      } catch (failure) {
        if (heard) return heard;
        throw failure;
      }
    },
    cancel: () => {
      ear?.stop();
      tape.cancel();
    },
  };
}

/** A refusal with a locale key on it — never a sentence. */
export class VoiceFailed extends Error {
  constructor(
    readonly key: string,
    readonly slots: Record<string, number> = {},
  ) {
    super(key);
  }
}
