/**
 * Opening a thread named from outside the list (`chat/opening`): a
 * notification's `?thread=` can point at one this account does not hold.
 */

import { describe, expect, it } from "vitest";
import { ApiError } from "../shell/api";
import { openOrBack, type Opening } from "./opening";

type Thread = { id: string };

/** A panel over the threads in `held`; what it did, in order. */
function panel(held: string[], activate?: (cid: string) => Promise<unknown>) {
  const did: string[] = [];
  const io: Opening<Thread> = {
    activate:
      activate ??
      (async (cid) => {
        if (!held.includes(cid)) throw new ApiError(404, "No such conversation");
      }),
    read: async (cid) => {
      if (!held.includes(cid)) throw new ApiError(404, "No such conversation");
      return { id: cid };
    },
    select: (cid) => did.push(`select ${cid}`),
    show: (thread) => did.push(`show ${thread.id}`),
  };
  return { io, did };
}

describe("openOrBack", () => {
  it("opens a thread this account holds", async () => {
    const { io, did } = panel(["c_mine", "c_card"]);
    expect(await openOrBack("c_card", "c_mine", io)).toBe("opened");
    expect(did).toEqual(["select c_card", "show c_card"]);
  });

  it("goes back to the thread on screen when the one asked for is not here", async () => {
    // The notification of another account on the same phone.
    const { io, did } = panel(["c_mine"]);
    expect(await openOrBack("c_theirs", "c_mine", io)).toBe("gone");
    expect(did).toEqual(["select c_theirs", "select c_mine", "show c_mine"]);
  });

  it("leaves no thread selected when there was none before", async () => {
    const { io, did } = panel([]);
    expect(await openOrBack("c_theirs", null, io)).toBe("gone");
    expect(did).toEqual(["select c_theirs", "select null"]);
  });

  it("tells a server that could not be asked from a thread that is not there", async () => {
    const down = async () => {
      throw new TypeError("Failed to fetch");
    };
    const { io, did } = panel(["c_mine", "c_card"], down);
    expect(await openOrBack("c_card", "c_mine", io)).toBe("failed");
    expect(did).toEqual(["select c_card", "select c_mine", "show c_mine"]);
    const broken = async () => {
      throw new ApiError(500, "boom");
    };
    expect(await openOrBack("c_card", "c_mine", panel(["c_mine"], broken).io)).toBe(
      "failed",
    );
  });

  it("still answers when the thread to go back to cannot be read either", async () => {
    const { io, did } = panel([]);
    expect(await openOrBack("c_theirs", "c_mine", io)).toBe("gone");
    expect(did).toEqual(["select c_theirs", "select c_mine"]);
  });
});
