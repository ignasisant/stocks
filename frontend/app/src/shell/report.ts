/**
 * How a page opens "Send feedback" without importing the widget.
 *
 * The widget sits at the foot of the rail and, on a phone, again in the "More"
 * sheet; a page that has just watched three statements fail has neither in
 * front of the reader. It calls `reportProblem()`, and the widget that mounted
 * first opens: one dialog, however many are mounted.
 *
 * A caller that knows more than the route can say so: the assistant's import
 * names itself as the place, and hands over the statement it read, which the
 * dialog offers to send with the report — ticked, and said so beside the box.
 */

export type ReportKind = "bug" | "idea" | "other";

export interface ReportContext {
  /** Where it happened, when the route alone does not say (`chat/import`). */
  page?: string;
  /** The file the report is about, offered to send with it. */
  file?: { name: string; blob: Blob };
}

type Listener = (kind: ReportKind, context: ReportContext) => void;

const listeners: Listener[] = [];

/** Open the feedback dialog on `kind`. A no-op when no widget is mounted. */
export function reportProblem(
  kind: ReportKind = "bug",
  context: ReportContext = {},
): void {
  listeners[0]?.(kind, context);
}

/** The widget's side: hear the request until the returned function is called. */
export function onReport(listener: Listener): () => void {
  listeners.push(listener);
  return () => {
    const at = listeners.indexOf(listener);
    if (at >= 0) listeners.splice(at, 1);
  };
}
