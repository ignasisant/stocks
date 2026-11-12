/**
 * How a page opens "Send feedback" without importing the widget.
 *
 * The widget sits at the foot of the rail and, on a phone, again in the "More"
 * sheet; a page that has just watched three statements fail has neither in
 * front of the reader. It calls `reportProblem()`, and the widget that mounted
 * first opens: one dialog, however many are mounted.
 */

export type ReportKind = "bug" | "idea" | "other";

type Listener = (kind: ReportKind) => void;

const listeners: Listener[] = [];

/** Open the feedback dialog on `kind`. A no-op when no widget is mounted. */
export function reportProblem(kind: ReportKind = "bug"): void {
  listeners[0]?.(kind);
}

/** The widget's side: hear the request until the returned function is called. */
export function onReport(listener: Listener): () => void {
  listeners.push(listener);
  return () => {
    const at = listeners.indexOf(listener);
    if (at >= 0) listeners.splice(at, 1);
  };
}
