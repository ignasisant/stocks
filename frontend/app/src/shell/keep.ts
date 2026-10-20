/**
 * The last answer each screen opened with, kept on this device between visits.
 *
 * Arriving at the app used to mean a blank card for as long as the server took
 * to price the book — tens of seconds on a cold instance, a minute when Yahoo
 * throttled it. The reader has seen these figures before; showing them again
 * at once, and swapping in the live ones when they land, is what this is for.
 * `shell/api` writes every answer a screen opens with here, and `useApi` reads
 * them back for the first paint of the next visit (`fromKept`).
 *
 * IndexedDB rather than `localStorage`: a book's risk and history are hundreds
 * of KB each, and a page reads only the handful it asks for, not the lot.
 *
 * Three rules keep an old answer from being worse than none:
 *
 * * **Nothing answers until `/me` has.** A kept answer belongs to whoever was
 *   signed in when it landed, and the first `/me` of a visit says who is asking
 *   now (`claim`). A different account — someone signed out, somebody else
 *   signed in, a guest — empties the shelf before a single page reads it, and
 *   `/me` itself is never answered from here, so that check cannot be fooled
 *   by its own copy.
 * * **A new release starts empty.** The shelf is stamped with the build it was
 *   written by; a deploy that changed the frontend changed what it expects of
 *   an answer, and an old shape would break a screen rather than slow it.
 * * **A week at most.** Older than that it is not a figure worth flashing.
 *
 * Every step is best-effort: a private window, a refused quota or a missing
 * IndexedDB (the MCP views, the tests) only means the screen waits as it
 * always did.
 */

const NAME = "topstocks-kept";
const ANSWERS = "answers";
const META = "meta";
/** The one URL a kept copy may never answer, because it decides who reads. */
const WHO = "/api/v1/me";
const MAX_ENTRIES = 150;
const MAX_AGE_MS = 7 * 86_400_000;
/**
 * The URL of the entry chunk, whose content hash changes with every release
 * that touches the frontend (a page chunk renamed renames its importer too).
 */
const BUILD = import.meta.url;

export type Kept = { url: string; at: number; body: unknown };
type Meta = { owner: string; build: string };

/** Where answers are kept. IndexedDB in the browser; a Map in the tests. */
export type Shelf = {
  read(url: string): Promise<Kept | undefined>;
  write(kept: Kept): Promise<void>;
  meta(): Promise<Meta | undefined>;
  /** Drop every answer and stamp the shelf for its new owner and build. */
  reset(meta: Meta): Promise<void>;
  /** Drop the oldest answers past `max`. */
  trim(max: number): Promise<void>;
};

let shelf: Shelf | null = open();
/** Settles to whether the shelf may answer; null until `/me` has spoken. */
let ready: Promise<boolean> | null = null;

function open(): Shelf | null {
  try {
    return typeof indexedDB === "undefined" ? null : idbShelf(indexedDB);
  } catch {
    return null;
  }
}

/** Swap the shelf, and forget who owned the last one. For the tests. */
export function setShelf(next: Shelf | null): void {
  shelf = next;
  ready = null;
}

/**
 * Whether a screen opening may be shown the kept copy of `url`.
 *
 * Exported for `shell/api`, which asks before reading the shelf so `/me`
 * always goes to the network.
 */
export function keepable(url: string): boolean {
  return url !== WHO;
}

/**
 * An answer a screen opened with has landed: keep it for next time. `/me` is
 * not kept — it settles whose shelf this is.
 */
export function landed(url: string, body: unknown): void {
  if (url === WHO) {
    claim(identity(body));
    return;
  }
  const s = shelf;
  const gate = ready;
  if (!s || !gate) return;
  gate
    .then((ok) => (ok ? s.write({ url, at: Date.now(), body }) : undefined))
    .catch(() => undefined);
}

/** The kept answer for `url`, if it may stand in; never throws. */
export async function recall(url: string): Promise<Kept | undefined> {
  const s = shelf;
  const gate = ready;
  if (!s || !gate || !keepable(url)) return undefined;
  try {
    if (!(await gate)) return undefined;
    const kept = await s.read(url);
    return kept && Date.now() - kept.at < MAX_AGE_MS ? kept : undefined;
  } catch {
    return undefined;
  }
}

/**
 * Sign this device out: empty the shelf, end the session, land on the home
 * page as a guest.
 *
 * The shelf first. The next `/me` would empty it anyway, but only on the next
 * visit: until then a shared computer keeps the last account's book on disk.
 * Bounded, so a slow or broken IndexedDB never holds a sign-out hostage.
 *
 * Then a POST to `to` (`/auth/logout` unless the server named another path).
 * A GET there only asks — a sign-out that a GET performed could be aimed from
 * any page on the web — so the app sends the POST itself and then navigates.
 * When the POST cannot be sent at all, the GET page is where the reader can
 * still confirm by hand.
 */
export async function signOut(to = "/auth/logout"): Promise<void> {
  const s = shelf;
  ready = null;
  if (s) {
    await Promise.race([
      s.reset({ owner: "", build: "" }).catch(() => undefined),
      new Promise((resolve) => setTimeout(resolve, 600)),
    ]);
  }
  try {
    await fetch(to, {
      method: "POST",
      credentials: "same-origin",
      redirect: "manual",
    });
    window.location.assign("/");
  } catch {
    window.location.assign(to);
  }
}

function identity(body: unknown): string {
  const me = (body ?? {}) as { kind?: unknown; email?: unknown };
  return `${String(me.kind)}:${String(me.email ?? "")}`;
}

/**
 * Who is asking, from a live `/me`. Every read and write after this waits on
 * it, so a shelf written by somebody else is emptied before anything reads it.
 */
function claim(owner: string): void {
  const s = shelf;
  if (!s) return;
  ready = (async () => {
    const meta = await s.meta();
    if (!meta || meta.owner !== owner || meta.build !== BUILD) {
      await s.reset({ owner, build: BUILD });
    } else {
      await s.trim(MAX_ENTRIES);
    }
    return true;
  })().catch(() => false);
}

// ------------------------------------------------------------------ IndexedDB

function request<T>(req: IDBRequest<T>): Promise<T> {
  return new Promise((resolve, reject) => {
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function idbShelf(factory: IDBFactory): Shelf {
  const db = new Promise<IDBDatabase>((resolve, reject) => {
    const opening = factory.open(NAME, 1);
    opening.onupgradeneeded = () => {
      const created = opening.result;
      created.createObjectStore(ANSWERS, { keyPath: "url" }).createIndex("at", "at");
      created.createObjectStore(META);
    };
    opening.onsuccess = () => resolve(opening.result);
    opening.onerror = () => reject(opening.error);
  });
  const store = async (name: string, mode: IDBTransactionMode) =>
    (await db).transaction(name, mode).objectStore(name);
  return {
    read: async (url) =>
      request<Kept | undefined>((await store(ANSWERS, "readonly")).get(url)),
    write: async (kept) => {
      await request((await store(ANSWERS, "readwrite")).put(kept));
    },
    meta: async () =>
      request<Meta | undefined>((await store(META, "readonly")).get("meta")),
    reset: async (meta) => {
      const tx = (await db).transaction([ANSWERS, META], "readwrite");
      tx.objectStore(ANSWERS).clear();
      tx.objectStore(META).put(meta, "meta");
      await new Promise<void>((resolve, reject) => {
        tx.oncomplete = () => resolve();
        tx.onerror = tx.onabort = () => reject(tx.error);
      });
    },
    trim: async (max) => {
      const answers = await store(ANSWERS, "readwrite");
      let extra = (await request(answers.count())) - max;
      if (extra <= 0) return;
      await new Promise<void>((resolve, reject) => {
        const cursor = answers.index("at").openCursor();
        cursor.onsuccess = () => {
          const at = cursor.result;
          if (!at || extra-- <= 0) return resolve();
          at.delete();
          at.continue();
        };
        cursor.onerror = () => reject(cursor.error);
      });
    },
  };
}
