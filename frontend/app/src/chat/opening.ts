/**
 * Opening a thread that may not be there.
 *
 * A thread is named from outside the list in three ways: a notification's
 * `?thread=`, a link under an answer, a memory's source. Any of them can
 * point at one this account's book does not hold: deleted on another device,
 * or — the case that showed it — a notification another account sent to this
 * same phone. Opening it used to leave the panel on an empty thread with
 * nothing said, and the reader's own conversation gone from the screen.
 *
 * So a thread that cannot be opened puts the reader back where they were, and
 * the caller is told which nothing it was: `gone` (the server has no such
 * thread) or `failed` (the server could not be asked).
 */

import { ApiError } from "../shell/api";

export type Opened = "opened" | "gone" | "failed";

export type Opening<T> = {
  /** Make `cid` the active thread on the server. */
  activate: (cid: string) => Promise<unknown>;
  read: (cid: string) => Promise<T>;
  /** Put the panel on thread `cid` (none: null), empty until `show`. */
  select: (cid: string | null) => void;
  show: (thread: T) => void;
};

/** Open `cid`; when it cannot be, go back to `before`. */
export async function openOrBack<T>(
  cid: string,
  before: string | null,
  io: Opening<T>,
): Promise<Opened> {
  io.select(cid);
  try {
    await io.activate(cid);
    io.show(await io.read(cid));
    return "opened";
  } catch (error) {
    io.select(before);
    if (before && before !== cid) {
      const back = await io.read(before).catch(() => null);
      if (back) io.show(back);
    }
    return error instanceof ApiError && error.status === 404 ? "gone" : "failed";
  }
}
