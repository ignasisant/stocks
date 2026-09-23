/**
 * The alert editor's arithmetic, kept out of the component so it can be read
 * on its own.
 *
 * What an alert *is* — which types exist, which number each asks for, what to
 * prefill — is the server's answer (`/alert-types`, from `config.ALERT_FORMS`),
 * the same table the Streamlit watchlist widget reads. What is decided here is
 * only how a rule reads back and when a draft is worth sending.
 */

import type { Translate } from "./format";
import type { AlertForm, AlertRule } from "./types";

/** Python's `%g`: 5 prints as "5" and 120.50 as "120.5", as the app prints them. */
export function num(value: number): string {
  return String(Number(value.toPrecision(6)));
}

/** One rule as a line: "Price above 120.5", "Drawdown ≥ 5% (252d)". */
export function summary(rule: AlertRule, t: Translate): string {
  const parts = [t(`widgets.alert_t_${rule.type}`)];
  if (rule.price !== null && rule.price !== undefined) parts.push(num(rule.price));
  if (rule.pct !== null && rule.pct !== undefined) parts.push(`${num(rule.pct)}%`);
  if (rule.level !== null && rule.level !== undefined) parts.push(num(rule.level));
  if (rule.window) parts.push(`(${rule.window}d)`);
  return parts.join(" ");
}

/** A blank rule of this type, prefilled the way the app prefills it. */
export function draft(form: AlertForm): AlertRule {
  const rule: AlertRule = { type: form.type };
  if (form.field) rule[form.field] = form.default ?? 0;
  if (form.window !== null) rule.window = form.window;
  return rule;
}

/**
 * Whether a draft is worth sending.
 *
 * A threshold of zero is nothing anybody meant: no price is ever below 0, and a
 * 0% move fires on every tick. The levels are exempt — RSI 0 is a real number,
 * and its types arrive prefilled anyway.
 */
export function complete(form: AlertForm, rule: AlertRule): boolean {
  if (form.field === "price" || form.field === "pct") {
    const value = rule[form.field];
    return typeof value === "number" && value > 0;
  }
  return true;
}

/** The rule as the API takes it: the fields this type does not use stay out. */
export function payload(form: AlertForm, rule: AlertRule): AlertRule {
  const out: AlertRule = { type: form.type };
  if (form.field) out[form.field] = rule[form.field];
  if (rule.window !== null && rule.window !== undefined) out.window = rule.window;
  return out;
}
