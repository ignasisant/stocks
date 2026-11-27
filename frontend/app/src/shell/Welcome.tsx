/**
 * The first-login wizard: one question per screen, every one skippable.
 *
 * It does two jobs a newcomer would otherwise meet as forms. First, what an AI
 * the reader already uses knows about them: which AI, the connector set up in
 * its own app, its summary pasted here, reviewed line by line and saved as
 * separate memories (`/chat/memories/import`). Then the investor profile the
 * assistant reads in every answer (`PUT /profile`): risk, horizon, interests,
 * rules, notes. The same profile the Profile page and the daily nudge edit.
 *
 * Shown once per account, on the first load the card surface decides
 * (`Tour.firstLoad`), and stamped the moment it opens — a welcome seen twice
 * is no longer one. It ends on the two ways on, and takes neither by itself:
 * the import, which is the point, and the section guide (`onTour`).
 */

import { useEffect, useRef, useState } from "react";

import { AiLogo } from "./aiLogos";
import { get, send } from "./api";
import { useT } from "./i18n";
import { canonical } from "./pages";
import { useRoute } from "./router";
import { landing } from "./Tour";
import { useDialog } from "./useDialog";
import { useExitGhost } from "./useSheet";

type Target = {
  id: string;
  path: string | null;
  params: Record<string, string>;
  session: Record<string, string>;
};

type Id =
  | "ai"
  | "which"
  | "connect"
  | "memo"
  | "review"
  | "risk"
  | "horizon"
  | "focus"
  | "constraints"
  | "notes"
  | "done";

/** The AIs asked about. Only the first two have a connector menu to walk through. */
const AIS = ["claude", "chatgpt", "gemini", "other"] as const;
const CONNECTABLE = new Set<string>(["claude", "chatgpt"]);

/** Interests, grouped as the Profile page offers them; an offered area this
 *  table does not know lands under "assets" rather than vanishing. */
const GROUPS: [string, string[]][] = [
  [
    "sectors",
    ["tech", "ai", "semis", "health", "energy", "fin", "consumer", "realestate"],
  ],
  ["style", ["growth", "dividends_value", "small"]],
  ["markets", ["us", "eu", "em"]],
  ["assets", ["etf", "crypto", "commod"]],
];

type Options = {
  risk: string[];
  horizon: string[];
  focus: string[];
  constraints: string[];
};
type Connections = { url: string | null; connections: unknown[] };
type Statement = { text: string; kind: string };
type Preview = { statements: Statement[]; over: number; room: number };

/** Milliseconds between asks while the other AI is still connecting. */
const POLL_MS = 4000;

/** The connector's address and who is connected, asked again while `active`. */
function useConnector(active: boolean): Connections | null {
  const [data, setData] = useState<Connections | null>(null);
  useEffect(() => {
    if (!active && data) return;
    let live = true;
    const ask = () =>
      get<Connections>("/connections").then(
        (answer) => {
          if (live) setData(answer);
        },
        () => undefined,
      );
    void ask();
    if (!active) return () => void (live = false);
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void ask();
    }, POLL_MS);
    return () => {
      live = false;
      clearInterval(timer);
    };
    // `data` only gates the first ask; re-running on it would poll in a loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);
  return data;
}

function CopyLine({
  text,
  label,
  wrap,
}: {
  text: string;
  label: string;
  wrap?: boolean;
}) {
  const t = useT();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const timer = setTimeout(() => setDone(false), 2000);
    return () => clearTimeout(timer);
  }, [done]);
  return (
    <div className="ag-welcome-copy">
      <code className={wrap ? "ag-welcome-code ag-wz-wrap" : "ag-welcome-code"}>
        {text}
      </code>
      <button
        type="button"
        className="ag-tour-quiet"
        aria-label={label}
        onClick={() =>
          void navigator.clipboard?.writeText(text).then(
            () => setDone(true),
            () => undefined,
          )
        }
      >
        {done ? t("tour.wz_copied") : t("tour.wz_copy")}
      </button>
    </div>
  );
}

/** A big card: one answer to pick, with an optional mark and a second line. */
function Card({
  on,
  onPick,
  title,
  line,
  mark,
}: {
  on: boolean;
  onPick: () => void;
  title: string;
  line?: string;
  mark?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      className={on ? "ag-wz-card ag-wz-on" : "ag-wz-card"}
      aria-pressed={on}
      onClick={onPick}
    >
      {mark ? <span className="ag-wz-mark">{mark}</span> : null}
      <span className="ag-wz-ct">
        <span className="ag-wz-ctitle">{title}</span>
        {line ? <span className="ag-wz-cline">{line}</span> : null}
      </span>
    </button>
  );
}

const toggle = (list: string[], option: string) =>
  list.includes(option) ? list.filter((o) => o !== option) : [...list, option];

export function Welcome({
  steps,
  onClose,
  onTour,
}: {
  steps: Target[];
  onClose: () => void;
  /** "Look round": the section guide, from its first stop. */
  onTour: () => void;
}) {
  const t = useT();
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);
  useExitGhost(scrim);
  useDialog(card);
  const { go } = useRoute();

  const [at, setAt] = useState<Id>("ai");
  const [uses, setUses] = useState<boolean | null>(null);
  const [which, setWhich] = useState("");
  const [memo, setMemo] = useState("");
  const [found, setFound] = useState<Preview | null>(null);
  const [off, setOff] = useState<number[]>([]);
  const [risk, setRisk] = useState("");
  const [horizon, setHorizon] = useState("");
  const [focus, setFocus] = useState<string[]>([]);
  const [constraints, setConstraints] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [options, setOptions] = useState<Options | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const [saved, setSaved] = useState(0);

  const connector = useConnector(at === "connect");
  const connected = (connector?.connections.length ?? 0) > 0;
  const hasConnect = CONNECTABLE.has(which) && Boolean(connector?.url);
  const ai = which ? t(`tour.wz_ai_${which}`) : "";
  const shown = found ? found.statements : [];
  const kept = shown.filter((_, k) => !off.includes(k));

  useEffect(() => {
    get<Options>("/profile-options").then(setOptions, () => undefined);
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  /** The screens this reader will see, in order; "done" is not counted. */
  const seq = (): Id[] => {
    const ai: Id[] = !uses
      ? []
      : [
          "which",
          ...(hasConnect ? (["connect"] as Id[]) : []),
          "memo",
          ...(shown.length ? (["review"] as Id[]) : []),
        ];
    return ["ai", ...ai, "risk", "horizon", "focus", "constraints", "notes"];
  };
  const order = seq();
  const index = Math.max(0, order.indexOf(at));

  const move = (to: Id) => {
    setFailed(false);
    setAt(to);
  };
  const next = () => move(order[index + 1] ?? "done");
  const back = () => move(order[index - 1] ?? "ai");
  /** The AI part ends here, whatever was done in it. */
  const toProfile = () => move("risk");

  const target = steps.find((s) => s.id === "import");
  const importNow =
    target && target.path !== null
      ? () => {
          onClose();
          go(canonical(target.path ?? ""), landing(target));
        }
      : null;

  function review() {
    setBusy(true);
    setFailed(false);
    send<Preview>("POST", "/chat/memories/import/preview", { text: memo.trim() })
      .then((answer) => {
        setFound(answer);
        setOff([]);
        // Nothing worth keeping in what was pasted: straight on, not an empty list.
        setAt(answer.statements.length ? "review" : "risk");
      })
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  }

  function keep() {
    setBusy(true);
    setFailed(false);
    send<{ added: number; updated: number }>("POST", "/chat/memories/import", {
      statements: kept.map((s) => s.text),
    })
      .then((done) => {
        setSaved(done.added + done.updated);
        setAt("risk");
      })
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  }

  function finish() {
    const any = risk || horizon || focus.length || constraints.length || notes.trim();
    if (!any) return move("done");
    setBusy(true);
    setFailed(false);
    send("PUT", "/profile", { risk, horizon, focus, constraints, notes: notes.trim() })
      .then(() => setAt("done"))
      .catch(() => setFailed(true))
      .finally(() => setBusy(false));
  }

  const heading: Record<Id, string> = {
    ai: t("tour.wz_ai_q"),
    which: t("tour.wz_which_q"),
    connect: t("tour.wz_connect_h", { ai }),
    memo: t("tour.wz_memo_h", { ai }),
    review: t("tour.wz_review_h"),
    risk: t("tour.wz_risk_q"),
    horizon: t("tour.wz_horizon_q"),
    focus: t("tour.wz_focus_q"),
    constraints: t("tour.wz_constraints_q"),
    notes: t("tour.wz_notes_q"),
    done: t("tour.wz_done_h"),
  };
  const sub: Partial<Record<Id, string>> = {
    ai: t("tour.wz_ai_sub"),
    which: t("tour.wz_which_sub"),
    connect: t("tour.wz_connect_sub"),
    memo: t("tour.wz_memo_sub"),
    review: t("tour.wz_review_sub"),
    risk: t("tour.wz_risk_sub"),
    horizon: t("tour.wz_horizon_sub"),
    focus: t("tour.wz_focus_sub"),
    constraints: t("tour.wz_constraints_sub"),
    notes: t("tour.wz_notes_sub"),
    done: saved ? t("tour.wz_done_saved", { n: saved }) : t("tour.wz_done_sub"),
  };

  const area = (name: string) => t(`profile.iv_focus_${name}`);
  const offered = options?.focus ?? [];
  const known = new Set(GROUPS.flatMap(([, list]) => list));
  const stray = offered.filter((o) => !known.has(o));
  const groups = GROUPS.map(
    ([g, list]) =>
      [
        g,
        [...list, ...(g === "assets" ? stray : [])].filter((o) => offered.includes(o)),
      ] as const,
  );

  let body: React.ReactNode = null;
  let foot: React.ReactNode = null;
  const skipAi = (
    <button type="button" className="ag-tour-quiet" onClick={toProfile}>
      {t("tour.wz_skip")}
    </button>
  );
  const skip = (
    <button type="button" className="ag-tour-quiet" onClick={next}>
      {t("tour.wz_skip")}
    </button>
  );
  const cta = (label: string, onClick: () => void, disabled = false) => (
    <button
      type="button"
      className="ag-tour-cta"
      disabled={disabled || busy}
      onClick={onClick}
    >
      {label}
    </button>
  );
  const err = failed ? (
    <p className="ag-wz-err" role="alert">
      {t("tour.wz_failed")}
    </p>
  ) : null;

  if (at === "ai") {
    body = (
      <div className="ag-wz-grid">
        <Card
          on={uses === true}
          onPick={() => {
            setUses(true);
            move("which");
          }}
          title={t("tour.wz_yes")}
          line={t("tour.wz_ai_yes_line")}
        />
        <Card
          on={uses === false}
          onPick={() => {
            setUses(false);
            toProfile();
          }}
          title={t("tour.wz_no")}
          line={t("tour.wz_ai_no_line")}
        />
      </div>
    );
  } else if (at === "which") {
    body = (
      <div className="ag-wz-grid">
        {AIS.map((id) => (
          <Card
            key={id}
            on={which === id}
            onPick={() => {
              setWhich(id);
              // The connector's menu exists for two of them; the rest go
              // straight to pasting what they know.
              setAt(CONNECTABLE.has(id) && connector?.url ? "connect" : "memo");
            }}
            title={t(`tour.wz_ai_${id}`)}
            mark={<AiLogo id={id} />}
          />
        ))}
      </div>
    );
    foot = skipAi;
  } else if (at === "connect") {
    body = (
      <section className="ag-welcome-ai">
        <p className="ag-welcome-line">{t("tour.wz_connect_copy")}</p>
        <CopyLine text={connector?.url ?? ""} label={t("tour.wz_copy_url")} />
        <ol className="ag-wz-steps">
          {[1, 2, 3].map((n) => (
            <li key={n}>{t(`tour.wz_connect_${which}_${n}`)}</li>
          ))}
        </ol>
        <p className={connected ? "ag-welcome-ok" : "ag-welcome-cap"} role="status">
          {connected ? t("tour.wz_connect_ok") : t("tour.wz_connect_wait")}
        </p>
      </section>
    );
    foot = (
      <>
        <button type="button" className="ag-tour-quiet" onClick={next}>
          {connected ? t("tour.wz_next") : t("tour.wz_connect_skip")}
        </button>
        {connected ? cta(t("tour.wz_next"), next) : null}
      </>
    );
  } else if (at === "memo") {
    body = (
      <section className="ag-welcome-ai">
        <p className="ag-welcome-line">{t("tour.wz_memo_ask", { ai })}</p>
        <CopyLine
          text={t("tour.wz_memo_prompt")}
          label={t("tour.wz_copy_prompt")}
          wrap
        />
        <textarea
          className="ag-wz-text"
          rows={6}
          maxLength={20000}
          value={memo}
          placeholder={t("tour.wz_memo_ph")}
          aria-label={t("tour.wz_memo_h", { ai })}
          onChange={(event) => setMemo(event.target.value)}
        />
        <small className="ag-welcome-cap">{t("tour.wz_memo_note")}</small>
        {err}
      </section>
    );
    foot = (
      <>
        {skipAi}
        {cta(t("tour.wz_review"), review, !memo.trim())}
      </>
    );
  } else if (at === "review") {
    body = (
      <>
        <ul className="ag-wz-mem">
          {shown.map((s, k) => {
            const on = !off.includes(k);
            return (
              <li key={s.text}>
                <button
                  type="button"
                  className={on ? "ag-wz-mrow ag-wz-on" : "ag-wz-mrow"}
                  aria-pressed={on}
                  onClick={() => setOff(on ? [...off, k] : off.filter((x) => x !== k))}
                >
                  <span className="ag-wz-mck" aria-hidden="true">
                    {on ? "✓" : ""}
                  </span>
                  <span>{s.text}</span>
                </button>
              </li>
            );
          })}
        </ul>
        <small className="ag-welcome-cap">
          {t("tour.wz_review_n", { kept: kept.length, total: shown.length })}
          {found && found.over > 0
            ? ` · ${t("tour.wz_review_over", { n: found.over })}`
            : ""}
        </small>
        {err}
      </>
    );
    foot = (
      <>
        {skipAi}
        {cta(t("tour.wz_review_save", { n: kept.length }), keep, !kept.length)}
      </>
    );
  } else if (at === "risk" || at === "horizon") {
    const list = (at === "risk" ? options?.risk : options?.horizon) ?? [];
    const value = at === "risk" ? risk : horizon;
    const pick = at === "risk" ? setRisk : setHorizon;
    body = (
      <div className="ag-wz-grid">
        {list.map((o) => (
          <Card
            key={o}
            on={value === o}
            onPick={() => {
              pick(o);
              next();
            }}
            title={t(`profile.iv_${at}_${o}`)}
            line={at === "risk" ? t(`profile.iv_risk_${o}_line`) : undefined}
          />
        ))}
      </div>
    );
    foot = skip;
  } else if (at === "focus") {
    body = (
      <div className="ag-wz-groups">
        {groups.map(([g, list]) =>
          list.length ? (
            <section key={g} className="ag-wz-group">
              <h3 className="ag-wz-gh">{t(`profile.iv_focus_group_${g}`)}</h3>
              <div className="ag-wz-chips">
                {list.map((o) => (
                  <button
                    key={o}
                    type="button"
                    className={focus.includes(o) ? "ag-wz-chip ag-wz-on" : "ag-wz-chip"}
                    aria-pressed={focus.includes(o)}
                    onClick={() => setFocus(toggle(focus, o))}
                  >
                    {area(o)}
                  </button>
                ))}
              </div>
            </section>
          ) : null,
        )}
      </div>
    );
    foot = (
      <>
        {skip}
        {cta(t("tour.wz_next"), next)}
      </>
    );
  } else if (at === "constraints") {
    body = (
      <div className="ag-wz-chips">
        {(options?.constraints ?? []).map((o) => (
          <button
            key={o}
            type="button"
            className={constraints.includes(o) ? "ag-wz-chip ag-wz-on" : "ag-wz-chip"}
            aria-pressed={constraints.includes(o)}
            onClick={() => setConstraints(toggle(constraints, o))}
          >
            {t(`profile.iv_constraints_${o}`)}
          </button>
        ))}
      </div>
    );
    foot = (
      <>
        {skip}
        {cta(t("tour.wz_next"), next)}
      </>
    );
  } else if (at === "notes") {
    body = (
      <>
        <textarea
          className="ag-wz-text"
          rows={5}
          maxLength={2000}
          value={notes}
          placeholder={t("profile.iv_notes_ph")}
          aria-label={t("tour.wz_notes_q")}
          onChange={(event) => setNotes(event.target.value)}
        />
        {err}
      </>
    );
    foot = (
      <>
        <button
          type="button"
          className="ag-tour-quiet"
          disabled={busy}
          onClick={() => move("done")}
        >
          {t("tour.wz_skip")}
        </button>
        {cta(t("tour.wz_finish"), finish)}
      </>
    );
  } else {
    body = null;
    foot = (
      <>
        <button type="button" className="ag-tour-quiet" onClick={onTour}>
          {t("tour.wz_done_tour")}
        </button>
        {importNow
          ? cta(t("tour.wz_done_import"), importNow)
          : cta(t("tour.wz_done_close"), onClose)}
      </>
    );
  }

  const last = at === "done";
  return (
    <div ref={scrim} className="ag-tour-scrim" role="presentation" onClick={onClose}>
      <div
        ref={card}
        tabIndex={-1}
        className="ag-tour ag-welcome ag-wz"
        role="dialog"
        aria-modal="true"
        aria-label={t("tour.wz_title")}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="ag-tour-head">
          <span className="ag-tour-title">{t("tour.wz_title")}</span>
          {last ? null : (
            <span className="ag-tour-progress">
              {t("tour.wz_progress", { n: index + 1, total: order.length })}
            </span>
          )}
        </header>
        <h2 className="ag-tour-h">{heading[at]}</h2>
        {sub[at] ? <p className="ag-tour-intro">{sub[at]}</p> : null}
        {body}
        <footer className="ag-tour-foot">
          {index > 0 && !last ? (
            <button
              type="button"
              className="ag-tour-quiet ag-wz-back"
              disabled={busy}
              onClick={back}
            >
              {t("tour.wz_back")}
            </button>
          ) : null}
          {foot}
        </footer>
      </div>
    </div>
  );
}
