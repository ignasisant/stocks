/**
 * A daily line's way to act on it: "Open Sell or add", "Open your plan".
 *
 * The server names the page that resolves each trigger (`DailyItem.go`, a
 * shell path with its query, from `daily.go_of`); this turns it into the
 * shell's own link, named after where it lands — a label that says what
 * happens, never a bare "Go". A path the table below does not know draws
 * nothing rather than a link with no name.
 */

import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";

/** Page (and tab) -> the name the link says it opens. */
const NAMES: Record<string, string> = {
  "profile?tab=plan": "home.daily_go_plan",
  "profile?tab=journal": "home.daily_go_journal",
  review: "home.daily_go_review",
  "portfolio?tab=tax": "home.daily_go_tax",
  earnings: "home.daily_go_earnings",
  sector: "home.daily_go_sector",
};

export type Target = { page: string; params?: Record<string, string>; name: string };

/** `/profile?tab=plan` -> the page, its query and the link's name; null for
 * an empty path or one with no name here. */
export function target(go: string | undefined): Target | null {
  const path = (go ?? "").replace(/^\/+/, "");
  const name = NAMES[path];
  if (!path || !name) return null;
  const at = path.indexOf("?");
  const page = at < 0 ? path : path.slice(0, at);
  const params =
    at < 0 ? undefined : Object.fromEntries(new URLSearchParams(path.slice(at + 1)));
  return { page, params, name };
}

export function Go({ go, className }: { go?: string; className: string }) {
  const t = useT();
  const to = target(go);
  if (!to) return null;
  return (
    <Link page={to.page} params={to.params} className={className}>
      {t("home.daily_go", { page: t(to.name) })}
    </Link>
  );
}
