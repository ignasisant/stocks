/**
 * The drawer's small facts: when a turn was written, what it cost, where a
 * source came from, and which wall a refusal hit.
 *
 * Times are formatted by the browser in the account's language rather than
 * built out of catalog strings — "14:32" and "8.4s" are readings, not copy,
 * and the Streamlit drawer prints both the same way (`chat_core._clock`,
 * `_took`).
 */

type T = (key: string, slots?: Record<string, string | number>) => string;

/** A turn's stamp as HH:MM in the reader's own zone, or "" when unstamped. */
export function clock(ts: number | undefined, lang: string): string {
  if (!ts) return "";
  return new Date(ts).toLocaleTimeString(lang, {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** How long an answer took: 8.4s inside a minute, then 1m 12s. */
export function took(seconds: number | undefined): string {
  if (!seconds || seconds < 0) return "";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${Math.floor(seconds / 60)}m ${String(Math.floor(seconds % 60)).padStart(2, "0")}s`;
}

const days = (iso: string): number | null => {
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return null;
  const midnight = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
  return Math.round(
    (midnight(new Date()).getTime() - midnight(when).getTime()) / 86400000,
  );
};

/** A thread row's stamp: the time today, the weekday this week, else the date. */
export function stamp(iso: string, lang: string): string {
  const old = days(iso);
  if (old === null) return "";
  const when = new Date(iso);
  if (old <= 0)
    return when.toLocaleTimeString(lang, { hour: "2-digit", minute: "2-digit" });
  if (old < 7) return when.toLocaleDateString(lang, { weekday: "short" });
  return when.toLocaleDateString(lang, { day: "2-digit", month: "short" });
}

/** The heading a thread sits under: today, this week, or its month. */
export function group(iso: string, t: T, lang: string): string {
  const old = days(iso);
  if (old === null) return "";
  if (old <= 0) return t("chat.group_today");
  if (old < 7) return t("chat.group_week");
  return new Date(iso).toLocaleDateString(lang, { month: "long" }).toUpperCase();
}

/** A source's host, which is what a reader checking provenance reads. */
export function host(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return url;
  }
}

/** A skill's name in the reader's language, falling back to the API's own. */
export function skillName(t: T, id: string, fallback?: string): string {
  const key = `chat.skill.${id}`;
  const label = t(key);
  return label === key ? (fallback ?? id) : label;
}

/**
 * The i18n key a failed key write should be read out as.
 *
 * 503 is the one that is not a hiccup: this deployment has no `[chat] enc_key`
 * and refuses to write a provider key in the clear beside somebody's
 * portfolio. It is said plainly and never retried — a second PUT fails the
 * same way, and a client that retried would look like it was trying to get the
 * key stored anyway.
 *
 * 400/422 is the body being rejected, and the only thing in the body is the
 * key. Everything else — an unknown provider, a keyless one that takes no key
 * — is this client sending something it should not have sent, which the reader
 * cannot act on and is told about as the generic failure.
 */
export function keyError(status: number): string {
  if (status === 503) return "chat.no_enc";
  if (status === 400 || status === 422) return "chat.invalid_key";
  return "chat.api_error";
}

/**
 * The one line a provider row says about itself, as a key and its slot.
 *
 * Three facts, and they are not interchangeable: a keyless provider costs
 * nothing and is rationed, a provider with a key of its own says how long that
 * key has left, and one that needs a key it has not been given says so. The
 * days are the server's — the sliding 90-day window and the absolute cap,
 * whichever runs out first — and never computed here.
 *
 * Null when a stored key has no lifetime to report. "Expires in 0 days" over a
 * key that works is a worse thing to say than nothing.
 */
export function providerTag(provider: {
  needs_key: boolean;
  has_key: boolean;
  key_days_left: number | null;
}): { key: string; days?: number } | null {
  if (!provider.needs_key) return { key: "chat.free_tag" };
  if (!provider.has_key) return { key: "chat.key_needed" };
  if (provider.key_days_left === null) return null;
  return { key: "chat.key_stored", days: provider.key_days_left };
}

/** A provider's brand name from its id, falling back to the id itself. */
export function providerLabel(
  providers: { id: string; label: string }[],
  id: string | null | undefined,
): string {
  if (!id) return "";
  return providers.find((p) => p.id === id)?.label ?? id;
}

/**
 * The refusal for the wall a turn actually hit.
 *
 * Three walls guard the free chain and they fail differently — this account's
 * allowance resets tomorrow, the shared pot is everyone's, an ineligible
 * account never had one — so the key comes from the server and is never
 * guessed here.
 *
 * `chat.free_cap_trial` also names the allowance the account grows into, and
 * `/chat/state` carries only the cap in force today. Rather than print a raw
 * `{full}` at a reader, an unfillable slot falls back to the plain account
 * wall: the same news, minus the number this client cannot know.
 */
export function capMessage(t: T, key: string, cap: number | null): string {
  const slots: Record<string, string | number> = cap === null ? {} : { cap };
  const text = t(key, slots);
  if (!text.includes("{")) return text;
  const plain = t("chat.free_cap", slots);
  return plain.includes("{") ? t("chat.free_exhausted") : plain;
}
