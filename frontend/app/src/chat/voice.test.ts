/**
 * Dictation shows the words while they are said and keeps Whisper's at the end.
 *
 * Two promises, each easy to break without noticing. The recogniser ends its
 * own sessions — on silence, after a phrase — and a note that forgot what came
 * before each restart would show only its last sentence. And the preview is a
 * fallback as well as a preview: when Whisper refuses the clip (the hourly cap,
 * a silent recording on a phone that handed the microphone to the recogniser),
 * the words the reader watched appear are what the field keeps.
 *
 * The browser is faked: a recogniser driven by hand, a recorder that yields one
 * chunk, and `send` standing in for `POST /chat/voice`.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const send = vi.hoisted(() => vi.fn());
vi.mock("../shell/api", async (original) => ({
  ...(await original<typeof import("../shell/api")>()),
  send,
}));

import { ApiError } from "../shell/api";
import { dictate, join, listen, VoiceFailed } from "./voice";

class Ear {
  static made: Ear[] = [];
  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  aborted = false;
  constructor() {
    Ear.made.push(this);
  }
  start() {}
  abort() {
    this.aborted = true;
  }
  /** Every result of this session so far, the way the browser reports them. */
  say(...phrases: string[]) {
    this.onresult?.({ results: phrases.map((transcript) => [{ transcript }]) });
  }
  end(error?: string) {
    if (error) this.onerror?.({ error });
    this.onend?.();
  }
}

const last = () => Ear.made[Ear.made.length - 1]!;

class Tape {
  static isTypeSupported = () => true;
  state = "inactive";
  mimeType = "audio/webm";
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["clip"]) });
    this.onstop?.();
  }
}

const released = vi.fn();

beforeEach(() => {
  Ear.made = [];
  send.mockReset();
  released.mockReset();
  vi.stubGlobal("window", { webkitSpeechRecognition: Ear, MediaRecorder: Tape });
  vi.stubGlobal("MediaRecorder", Tape);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: async () => ({ getTracks: () => [{ stop: released }] }),
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("join", () => {
  it("keeps what was typed, line breaks and all", () => {
    expect(join("first line\nsecond ", " said")).toBe("first line\nsecond said");
    expect(join("", "said")).toBe("said");
    expect(join("typed", "")).toBe("typed");
  });
});

describe("listen", () => {
  it("is nothing where the browser has no recogniser", () => {
    vi.stubGlobal("window", {});
    expect(listen("es", () => undefined)).toBeNull();
  });

  it("asks for the reader's language, word by word", () => {
    const words: string[] = [];
    listen("es", (said) => words.push(said));
    expect(last().lang).toBe("es-ES");
    expect(last().continuous).toBe(true);
    expect(last().interimResults).toBe(true);
    last().say("compra");
    last().say("compra", " NVDA");
    expect(words).toEqual(["compra", "compra NVDA"]);
  });

  it("carries the note across the sessions the browser ends", () => {
    const words: string[] = [];
    const ear = listen("en", (said) => words.push(said))!;
    last().say("buy");
    last().end();
    expect(Ear.made).toHaveLength(2);
    last().end("no-speech");
    expect(Ear.made).toHaveLength(3);
    last().say("NVDA");
    expect(words.at(-1)).toBe("buy NVDA");
    expect(ear.heard()).toBe("buy NVDA");
  });

  it("stops asking once the browser refuses", () => {
    listen("en", () => undefined);
    last().end("not-allowed");
    expect(Ear.made).toHaveLength(1);
  });

  it("does not loop on a session that ends having heard nothing", () => {
    listen("en", () => undefined);
    last().end();
    expect(Ear.made).toHaveLength(1);
  });

  it("says nothing after it is stopped", () => {
    const words: string[] = [];
    const ear = listen("en", (said) => words.push(said))!;
    const session = last();
    session.say("sell");
    ear.stop();
    session.say("sell everything");
    expect(session.aborted).toBe(true);
    expect(words).toEqual(["sell"]);
    expect(ear.heard()).toBe("sell");
  });
});

describe("dictate", () => {
  it("ends on Whisper's words, not the preview's", async () => {
    send.mockResolvedValue({ text: "buy NVDA" });
    const words: string[] = [];
    const note = await dictate("en", (said) => words.push(said));
    last().say("by and video");
    await expect(note.stop()).resolves.toBe("buy NVDA");
    expect(words).toEqual(["by and video"]);
    expect(released).toHaveBeenCalled();
  });

  it("keeps the preview when Whisper refuses the clip", async () => {
    send.mockRejectedValue(new ApiError(429, "chat.voice_rate", "rate", 60));
    const note = await dictate("en", () => undefined);
    last().say("buy NVDA");
    await expect(note.stop()).resolves.toBe("buy NVDA");
  });

  it("says why when neither heard anything", async () => {
    send.mockRejectedValue(new ApiError(422, "chat.voice_silent"));
    const note = await dictate("en", () => undefined);
    await expect(note.stop()).rejects.toEqual(new VoiceFailed("chat.voice_silent"));
  });

  it("stops listening when the reader denies the microphone", async () => {
    vi.stubGlobal("navigator", {
      mediaDevices: { getUserMedia: () => Promise.reject(new Error("denied")) },
    });
    await expect(dictate("en", () => undefined)).rejects.toThrow("denied");
    expect(last().aborted).toBe(true);
  });
});
