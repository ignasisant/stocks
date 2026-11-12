/**
 * A screenshot pasted into the composer, on its way to being words.
 *
 * The chat is text from end to end, so a picture is read once, before the
 * question goes (`POST /chat/screenshots`), the way a voice note is
 * transcribed before it is sent. What comes back is what the picture shows,
 * and that is what travels with the question (`runInput`'s `screenshots`).
 *
 * The picture itself never leaves the reader's hands. The server reads it and
 * drops it, and the thread stores words. So the copy drawn over the sent
 * question (`Turn`) is this device's own (`keepPicture`): held in memory for
 * the visit and on the kept shelf (`shell/keep`) for a week, found again by
 * what was read in it. Another device, a signed-out browser or an older
 * question shows the reading alone, which is all the answer ever had.
 *
 * It is re-encoded first (`shell/screenshot.fromFile`): one JPEG under the
 * API's ceiling whatever was pasted, so a 5 MB PNG of a retina screen is read
 * rather than refused.
 */

import { ApiError } from "../shell/api";
import { stow, stowed } from "../shell/keep";
import { fromFile, ShotFailed, type Shot } from "../shell/screenshot";
import { readScreenshot } from "./api";

/** Per question — the server's `screenshot.MAX_SHOTS`. */
export const MAX_SHOTS = 3;

/** A refusal with a locale key on it — never a sentence. */
export class ShotRefused extends Error {
  constructor(
    readonly key: string,
    readonly slots: Record<string, number> = {},
  ) {
    super(key);
  }
}

/** What went wrong, as the key that says so and how to get past it. */
export function refused(failure: unknown): ShotRefused {
  if (failure instanceof ShotRefused) return failure;
  if (failure instanceof ShotFailed) {
    return new ShotRefused(
      failure.key === "feedback.shot_big"
        ? "chat.shot_too_big"
        : "chat.shot_unreadable",
    );
  }
  if (failure instanceof ApiError && failure.detail.startsWith("chat.")) {
    return new ShotRefused(
      failure.detail,
      failure.retryAfter === undefined ? {} : { seconds: failure.retryAfter },
    );
  }
  return new ShotRefused("chat.shot_failed");
}

/** The pasted picture as the JPEG that is sent, and shown while it is read. */
export async function encoded(file: Blob): Promise<Shot> {
  try {
    return await fromFile(file);
  } catch (failure) {
    throw refused(failure);
  }
}

/** How a picture reached the composer: pasted, picked with the clip, dropped. */
export type Way = "paste" | "pick" | "drop";

/** What the picture shows, in words. */
export async function wordsOf(
  shot: Shot,
  lang: string,
  via: Way = "paste",
): Promise<string> {
  try {
    const { text } = await readScreenshot(shot.base64, lang, via);
    if (!text.trim()) throw new ShotRefused("chat.shot_failed");
    return text;
  } catch (failure) {
    throw refused(failure);
  }
}

/** Pictures sent this visit, by what was read in them. */
const sent = new Map<string, string>();
/** Each is up to 2 MB of data URL: the last few questions' worth. */
const MAX_SENT = 12;

/**
 * A reading's name on the shelf: cyrb53 over its words, spacing aside. Not a
 * secret and not unique by proof. Two pictures that read the same to the last
 * word are, to the thread, the same picture.
 */
function tag(reading: string): string {
  const words = reading.replace(/\s+/g, " ").trim();
  let a = 0xdeadbeef ^ words.length;
  let b = 0x41c6ce57 ^ words.length;
  for (let i = 0; i < words.length; i++) {
    const code = words.charCodeAt(i);
    a = Math.imul(a ^ code, 2654435761);
    b = Math.imul(b ^ code, 1597334677);
  }
  a = Math.imul(a ^ (a >>> 16), 2246822507) ^ Math.imul(b ^ (b >>> 13), 3266489909);
  b = Math.imul(b ^ (b >>> 16), 2246822507) ^ Math.imul(a ^ (a >>> 13), 3266489909);
  return `shot:${(b >>> 0).toString(36)}${(a >>> 0).toString(36)}`;
}

const picture = (kept: unknown): string | undefined =>
  typeof kept === "string" && kept.startsWith("data:image/") ? kept : undefined;

/** The question is going: hold its picture here, under what was read in it. */
export function keepPicture(reading: string, url: string): void {
  if (!picture(url)) return;
  const key = tag(reading);
  sent.delete(key);
  sent.set(key, url);
  for (const oldest of sent.keys()) {
    if (sent.size <= MAX_SENT) break;
    sent.delete(oldest);
  }
  stow(key, url);
}

/** The picture a reading came from, if it was sent in this visit. */
export function pictureNow(reading: string): string | undefined {
  return sent.get(tag(reading));
}

/** The picture a reading came from, if this device still holds it. */
export async function pictureOf(reading: string): Promise<string | undefined> {
  return pictureNow(reading) ?? picture(await stowed(tag(reading)));
}

/** Forget the pictures of this visit. For the tests. */
export function forgetPictures(): void {
  sent.clear();
}
