/**
 * A picture for a feedback report: of this screen, or of an image the reader
 * already has.
 *
 * Two ways in, because one of them can fail on any given page:
 *
 * * **Capture** rasterises the viewport with html2canvas-pro — the same pinned
 *   build the Streamlit composer loads (`web/screenshot.LIB_URL`), and loaded
 *   the same way: imported from the CDN when the reader asks for a shot and not
 *   a byte before. It is ~210 KB that most readers never need, so it is not in
 *   the shell bundle. The `-pro` fork because this app's CSS is full of
 *   `color-mix()`, which the original throws on. The feedback dialog itself is
 *   left out of the picture: it is this widget's chrome, not the screen being
 *   reported.
 * * **Attach** takes a file, or an image pasted from the clipboard — a system
 *   screenshot is usually one keystroke away, and it works where the
 *   rasteriser cannot (cross-origin images, a CDN that is blocked).
 *
 * Both end as one JPEG under the API's ceiling (`routes/feedback.MAX_SHOT`),
 * re-encoded down a quality ladder rather than refused at the first try: a
 * dense page of tables is several times the bytes of a mostly-empty one.
 */

const LIB_URL = "https://cdn.jsdelivr.net/npm/html2canvas-pro@1.5.11/+esm";

/** Decoded bytes the API accepts; base64 is 4/3 of that. */
const MAX_BYTES = 2 * 1024 * 1024;
const MAX_B64 = Math.floor((MAX_BYTES * 4) / 3);
const MAX_WIDTH = 1600;

export type Shot = {
  /** Base64 JPEG, no `data:` prefix — what `POST /feedback` takes as `shot`. */
  base64: string;
  /** A data URL of the same picture, for the preview. */
  url: string;
  kb: number;
};

export class ShotFailed extends Error {
  constructor(readonly key: "feedback.shot_failed" | "feedback.shot_big") {
    super(key);
  }
}

/** The smallest acceptable JPEG of a canvas, or `feedback.shot_big`. */
function encode(canvas: HTMLCanvasElement): Shot {
  for (const quality of [0.72, 0.5, 0.35]) {
    const url = canvas.toDataURL("image/jpeg", quality);
    const base64 = url.slice(url.indexOf(",") + 1);
    if (base64.length <= MAX_B64) {
      return { base64, url, kb: Math.round((base64.length * 3) / 4 / 1024) };
    }
  }
  throw new ShotFailed("feedback.shot_big");
}

/** The scale that keeps a picture within `MAX_WIDTH`, never enlarging it. */
function scaleFor(width: number): number {
  return Math.min(1, MAX_WIDTH / Math.max(1, width));
}

/**
 * Rasterise the viewport, leaving out anything `skip` matches.
 *
 * The viewport, not the whole document: a page scrolled to a chart halfway down
 * should come back as that chart, and a tall page would rasterise into tens of
 * megabytes.
 */
export async function capture(skip: (element: Element) => boolean): Promise<Shot> {
  type H2C = (
    el: HTMLElement,
    opts: Record<string, unknown>,
  ) => Promise<HTMLCanvasElement>;
  let html2canvas: H2C;
  try {
    const mod = (await import(/* @vite-ignore */ LIB_URL)) as { default?: H2C };
    html2canvas = mod.default ?? (mod as unknown as H2C);
  } catch {
    throw new ShotFailed("feedback.shot_failed");
  }
  const scale = scaleFor(window.innerWidth);
  let canvas: HTMLCanvasElement;
  try {
    canvas = await Promise.race([
      html2canvas(document.body, {
        backgroundColor: getComputedStyle(document.body).backgroundColor || null,
        scale,
        useCORS: true,
        logging: false,
        imageTimeout: 5000,
        ignoreElements: skip,
        x: window.scrollX,
        y: window.scrollY,
        width: window.innerWidth,
        height: window.innerHeight,
      }),
      // html2canvas can walk a big DOM for a long time; past this the reader
      // is better served by attaching a system screenshot instead.
      new Promise<never>((_, reject) =>
        window.setTimeout(() => reject(new Error("timeout")), 20000),
      ),
    ]);
  } catch {
    throw new ShotFailed("feedback.shot_failed");
  }
  return encode(canvas);
}

/** Any image the browser can decode, as a JPEG under the ceiling. */
export async function fromFile(file: Blob): Promise<Shot> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new ShotFailed("feedback.shot_failed");
  }
  const scale = scaleFor(bitmap.width);
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d");
  if (!context) throw new ShotFailed("feedback.shot_failed");
  // JPEG has no alpha: a transparent PNG would otherwise come out black.
  context.fillStyle = "white";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  return encode(canvas);
}
