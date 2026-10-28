/**
 * "Analyse with AI", as one press and a short menu of angles.
 *
 * The press asks for the full analysis; the chevron beside it offers the
 * three questions a reader asks of a share most often after that — the bear
 * case, the latest results, how it fits the book. Each sends a one-line label
 * the thread keeps, and names the angle (`brief`) the server writes out in
 * full (`chat/brief.py`): the company's lenses, the reader's position, the
 * report dates, the answer's structure. Always in a new conversation — an
 * analysis of LEU is not a follow-up to the thread about CBRS on screen.
 *
 * Only a share has angles: a fund, a coin or a money-market fund gets the
 * one press, still briefed by the server.
 */

import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { askAssistant, type Brief } from "../../shell/assistant";
import { useT } from "../../shell/i18n";

const MORE: readonly Exclude<Brief, "full">[] = ["bear", "earnings", "fit"];

/** The page's side gutter the menu keeps clear of (DS phone gutter). */
const GUTTER = 16;

export function AiAsk({
  ticker,
  name,
  prompt,
  angles,
  compact,
}: {
  ticker: string;
  name: string;
  /** The full analysis's label, per kind (`layout.ts`'s `ai`). */
  prompt: string;
  /** Whether the chevron's menu is drawn (shares only). */
  angles: boolean;
  /** Phone width: the main press is the sparkle alone. */
  compact: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const toggle = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const items = useRef<(HTMLButtonElement | null)[]>([]);

  const ask = (brief: Brief) => {
    setOpen(false);
    const key = brief === "full" ? prompt : `ticker.ai_prompt_${brief}`;
    askAssistant(t(key, { ticker, name }), { fresh: true, brief });
  };

  useEffect(() => {
    if (!open) return;
    // Pointerdown, not click, so an item's own handler still runs first.
    const away = (event: PointerEvent) => {
      if (!box.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    items.current[0]?.focus();
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  // The header wraps, so the group can sit anywhere along a phone's row: the
  // menu hangs from the group's right edge, then slides back inside the
  // viewport. Measured from the group and the menu's width, not the menu's
  // own box, which `ag-pop-in` is still scaling on this frame.
  useLayoutEffect(() => {
    const el = menu.current;
    if (!open || !el || !box.current) return;
    const group = box.current.getBoundingClientRect();
    const room = document.documentElement.clientWidth;
    const width = el.offsetWidth;
    const left = Math.max(GUTTER, Math.min(group.right - width, room - GUTTER - width));
    el.style.left = `${left - group.left}px`;
    el.style.right = "auto";
  }, [open]);

  const walk = (event: KeyboardEvent) => {
    const list = items.current.filter(Boolean) as HTMLButtonElement[];
    const at = list.indexOf(document.activeElement as HTMLButtonElement);
    const next =
      event.key === "ArrowDown"
        ? (at + 1) % list.length
        : event.key === "ArrowUp"
          ? (at - 1 + list.length) % list.length
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? list.length - 1
              : null;
    if (event.key === "Escape" || event.key === "Tab") {
      setOpen(false);
      if (event.key === "Escape") {
        event.preventDefault();
        toggle.current?.focus();
      }
      return;
    }
    if (next === null) return;
    event.preventDefault();
    list[next]?.focus();
  };

  return (
    <div className="tk-ai-group" ref={box}>
      <button
        type="button"
        className="ag-ai tk-ai"
        title={t("ticker.ai_analyze_help", { ticker })}
        aria-label={compact ? t("ticker.ai_analyze") : undefined}
        onClick={() => ask("full")}
      >
        {compact ? "✨" : t("ticker.ai_analyze")}
      </button>
      {angles ? (
        <>
          <button
            ref={toggle}
            type="button"
            className={open ? "tk-ai-more tk-pop-open" : "tk-ai-more"}
            aria-haspopup="menu"
            aria-expanded={open}
            aria-label={t("ticker.ai_more")}
            title={t("ticker.ai_more")}
            onClick={() => setOpen((was) => !was)}
          >
            <span className="tk-ai-chevron" aria-hidden="true" />
          </button>
          {open ? (
            <div
              ref={menu}
              className="tk-pop-panel tk-ai-menu"
              role="menu"
              aria-label={t("ticker.ai_more")}
              onKeyDown={walk}
            >
              {MORE.map((brief, n) => (
                <button
                  key={brief}
                  ref={(el) => {
                    items.current[n] = el;
                  }}
                  type="button"
                  role="menuitem"
                  className="tk-ai-item"
                  onClick={() => ask(brief)}
                >
                  <span className="tk-ai-item-label">
                    {t(`ticker.ai_angle_${brief}`)}
                  </span>
                  <span className="tk-ai-item-hint">
                    {t(`ticker.ai_angle_${brief}_hint`)}
                  </span>
                </button>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
