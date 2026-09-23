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

export type Recording = {
  /** Stop, and resolve with the clip. The tracks are released either way. */
  stop: () => Promise<Blob>;
  /** Drop the recording without transcribing it. */
  cancel: () => void;
};

/**
 * Start recording. Rejects when the reader denies the microphone, which is an
 * answer and not a failure — the caller draws nothing and the button resets.
 */
export async function record(): Promise<Recording> {
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
 * The server answers refusals with the key the drawer already renders
 * (`chat.voice_silent`, `chat.voice_too_long`, …), so both front ends say the
 * same thing about the same recording in the reader's own language.
 */
export async function transcribe(clip: Blob, lang: string): Promise<string> {
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

/** A refusal with a locale key on it — never a sentence. */
export class VoiceFailed extends Error {
  constructor(
    readonly key: string,
    readonly slots: Record<string, number> = {},
  ) {
    super(key);
  }
}
