/**
 * The one way the app tells somebody what just happened.
 *
 * Import, the assistant's actions, bank links and the settings all used to
 * draw their own line and time it their own way. Every transient notice now
 * goes through here, on sonner, mounted once by `ui/Toaster.tsx`. A caller
 * never imports sonner: the wrapper is where the defaults live (how long, how
 * it is dismissed, what motion it makes), so they change in one place.
 *
 * Four shapes, and no others:
 *  - `ok` / `warn` / `bad`: a sentence that fades by itself. A failure stays
 *    longer than a success, because it is the one a reader may have to act on.
 *  - `busy` (loading) and `promise`: the work in flight, turning into its
 *    outcome in the same slot rather than a second toast.
 *  - `stay`: no timer, a close button; for what has to be read to the end.
 *  - any of them with `action`: one button, Undo being the usual one.
 *
 * A toast never carries the only copy of something: the figure or state it
 * reports is on the page too, and a persistent page state (an empty card, a
 * stale banner, a failed load) is not a toast.
 */

import { toast as sonner, type ExternalToast } from "sonner";

type ToastAction = { label: string; onClick: () => void };

type ToastOptions = {
  /** Replaces the toast with this id instead of stacking a second one. */
  id?: string | number;
  /** The one button. Pressing it also closes the toast. */
  action?: ToastAction;
  /** Milliseconds; `Infinity` never fades. Defaults by kind. */
  duration?: number;
  /** A line under the sentence, for the detail a failure carries. */
  detail?: string;
};

/** How long each kind stays, in ms. */
export const DURATION = { ok: 4000, warn: 6000, bad: 8000, action: 8000 } as const;

/** Whether the reader asked the system for less motion. */
export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  );
}

function shape(kind: keyof typeof DURATION, options: ToastOptions = {}): ExternalToast {
  const { action, detail, duration, id } = options;
  return {
    id,
    description: detail,
    // A toast with a button is a decision: it waits long enough to be taken.
    duration: duration ?? (action ? DURATION.action : DURATION[kind]),
    closeButton: duration === Infinity,
    action: action
      ? {
          label: action.label,
          onClick: () => action.onClick(),
        }
      : undefined,
  };
}

const ok = (message: string, options?: ToastOptions) =>
  sonner.success(message, shape("ok", options));
const warn = (message: string, options?: ToastOptions) =>
  sonner.warning(message, shape("warn", options));
const bad = (message: string, options?: ToastOptions) =>
  sonner.error(message, shape("bad", options));
const stay = (message: string, options?: Omit<ToastOptions, "duration">) =>
  sonner(message, shape("ok", { ...options, duration: Infinity }));

/** Work in flight: stays until it is replaced (same `id`) or dismissed. */
const busy = (message: string, options?: Pick<ToastOptions, "id">) =>
  sonner.loading(message, { id: options?.id, duration: Infinity });

/** One slot that reads `loading`, then `success` or `error` by how it ended. */
function promise<T>(
  work: Promise<T>,
  words: {
    loading: string;
    success: string | ((value: T) => string);
    error: string | ((reason: unknown) => string);
  },
) {
  sonner.promise(work, {
    ...words,
    // Without these a failure would vanish at the success duration.
    success: (value: T) => ({
      message:
        typeof words.success === "function" ? words.success(value) : words.success,
      duration: DURATION.ok,
    }),
    error: (reason: unknown) => ({
      message: typeof words.error === "function" ? words.error(reason) : words.error,
      duration: DURATION.bad,
    }),
  });
  return work;
}

const dismiss = (id?: string | number) => sonner.dismiss(id);

export const toast = { ok, warn, bad, stay, busy, promise, dismiss };
