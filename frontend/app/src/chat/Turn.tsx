/**
 * One turn, drawn the way it will be drawn again on the next reload.
 *
 * Reading order is prose first, then provenance, then process — the same
 * collapse the Streamlit drawer made when an answer had grown five rows of
 * chrome all weighted like captions. Above the bubble: which lens produced it.
 * Below it: how many pages it stands on, and when it was written.
 *
 * The clock and the elapsed cost only appear on a turn this session watched
 * arrive. `/chat/conversations/{id}` stores neither, so a thread read back
 * carries its words, its lens and its sources and nothing about timing — and
 * a turn is drawn with what it has rather than with a zero standing in for
 * what was never recorded.
 */

import { useId, useState } from "react";
import { useLang, useT } from "../shell/i18n";
import { Glyph } from "./icons";
import { Markdown } from "./markdown";
import { capMessage, clock, host, providerLabel, skillName, took } from "./format";
import { GuideCard } from "./GuideCard";
import { unshortcode, type GuideState } from "./guide";
import type { SkillInfo, Step, Turn as Stored } from "./types";

/** The line that ticks while the answer is being built, naming what it is doing. */
function Working({ phase }: { phase?: string }) {
  const t = useT();
  // The server names the phase by its key; an unknown one (a newer server)
  // falls back to the generic line rather than printing a raw key.
  const key = `chat.work_${phase ?? "thinking"}`;
  const said = t(key);
  return (
    // A status rather than a plain line: it is the only thing that tells a
    // screen reader the question was taken, and it sits outside the bubble's
    // live region so that it is announced now rather than held back with the
    // answer that has not been written yet.
    <div className="ag-chat-work" role="status">
      <span className="ag-chat-work-glyph" aria-hidden="true">
        ✻
      </span>
      {said === key ? t("chat.work_thinking") : said}
    </div>
  );
}

/**
 * The tool trace behind a counter: "3 steps · 4.2s", opened on press.
 *
 * Worth reading once, when an answer looks wrong — not on every scroll past a
 * turn — which is why the lines are folded and only the count shows. A turn
 * that ran nothing says so, with its cost, but only while this session knows
 * the cost: a reloaded answer with no steps has nothing honest to claim.
 */
function Trace({ steps, spent }: { steps: Step[]; spent: string }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const uid = useId();
  const listId = `${uid}-steps`;
  if (!steps.length) {
    return spent ? (
      <span className="ag-chat-clock">{t("chat.no_tools", { took: spent })}</span>
    ) : null;
  }
  const label = t("chat.steps_n", { n: steps.length, took: spent }).replace(/ · $/, "");
  return (
    <>
      <button
        type="button"
        className="ag-chat-meta-btn"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((was) => !was)}
      >
        {label}
      </button>
      <ul className="ag-chat-steps" id={listId} hidden={!open}>
        {steps.map((step, i) => (
          <li key={i}>
            <code>{step.tool}</code>
            {step.arg && <span> {step.arg}</span>}
            {step.out && <span className="ag-chat-step-out"> → {step.out}</span>}
          </li>
        ))}
      </ul>
    </>
  );
}

function Sources({ web }: { web: { title: string; url: string }[] }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  // The list is drawn closed rather than left unmounted, so that the button's
  // `aria-controls` points at something that exists: an id that resolves to
  // nothing is the same as no id at all.
  const uid = useId();
  const listId = `${uid}-sources`;
  return (
    <>
      <button
        type="button"
        className="ag-chat-meta-btn"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((was) => !was)}
      >
        <Glyph name="link" size={12} />
        {t("chat.sources_n", { n: web.length })}
      </button>
      <ul className="ag-chat-sources" id={listId} hidden={!open}>
        {web.map((source, i) => (
          <li key={i}>
            <a
              className="ag-chat-a"
              href={source.url}
              target="_blank"
              rel="noopener noreferrer nofollow"
              title={source.title}
            >
              {host(source.url)}
            </a>
          </li>
        ))}
      </ul>
    </>
  );
}

export function Turn({
  turn,
  skills,
  providers,
  cap,
  onRetry,
  walk,
}: {
  turn: Stored;
  skills: SkillInfo[];
  /** The offered backends, to name the two in a failover by brand. */
  providers: { id: string; label: string }[];
  /** Today's free allowance, for the refusals that name it. */
  cap: number | null;
  onRetry: () => void;
  /** The walkthrough, for a turn it wrote. Absent: no guide on this server. */
  walk?: {
    state: GuideState;
    onNext: () => Promise<GuideState>;
    onSkip: () => void;
    onLeave: () => void;
  } | null;
}) {
  const t = useT();
  const lang = useLang();
  const mine = turn.role === "user";
  const lens = turn.skills.length
    ? t("chat.lens", {
        skills: turn.skills
          .map((id) => skillName(t, id, skills.find((s) => s.id === id)?.name))
          .join(" · "),
      })
    : "";
  const when = clock(turn.ts, lang);
  const spent = took(turn.took);
  // One provider answered for another. Session-only: a stored turn records
  // neither, so a reloaded thread names nobody rather than naming today's
  // head of the chain.
  const fallback =
    turn.by && turn.chose && turn.by !== turn.chose
      ? t("chat.fallback_note", {
          provider: providerLabel(providers, turn.by),
          chosen: providerLabel(providers, turn.chose),
        })
      : "";

  if (turn.error) {
    return (
      <div className="ag-chat-turn ag-chat-assistant">
        <div className="ag-chat-bubble ag-chat-bad">
          <p className="ag-chat-p">
            {turn.wait !== undefined
              ? t(turn.error, { seconds: turn.wait })
              : capMessage(t, turn.error, cap)}
          </p>
          <button type="button" className="ag-chat-retry" onClick={onRetry}>
            {t("chat.retry")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className={`ag-chat-turn ${mine ? "ag-chat-mine" : "ag-chat-assistant"}`}>
      {lens && <span className="ag-chat-lens">{lens}</span>}
      {/* A transcript is the reader's own words at one remove: Whisper
          mishears a ticker now and then, and a question that reads oddly
          should say why before its author blames the answer. */}
      {turn.spoken && <span className="ag-chat-badge">{t("chat.voice_badge")}</span>}
      {/* An answer that breaks off mid-sentence reads as the model losing the
          thread. Said plainly, it reads as what it was. */}
      {turn.stopped && <span className="ag-chat-badge">{t("chat.stopped_badge")}</span>}
      <div className="ag-chat-bubble">
        {mine ? (
          turn.content ? (
            <Markdown text={turn.content} />
          ) : null
        ) : (
          // An answer announced once, when it is finished. `aria-busy` holds
          // the region quiet while the tokens land — a polite region that
          // fired on every animation frame of a stream would read the answer
          // to itself, word by word, and never reach the end of it.
          <div aria-live="polite" aria-busy={!!turn.pending}>
            {turn.content ? (
              <Markdown text={turn.guide ? unshortcode(turn.content) : turn.content} />
            ) : turn.stopped ? (
              // Stopped before a single word arrived. The thread on disk holds
              // neither the question nor the silence, so this line is all
              // there is to show for it — and it is truer than an empty
              // bubble.
              <p className="ag-chat-p">{t("chat.stopped_note")}</p>
            ) : null}
          </div>
        )}
        {turn.pending && !turn.content && <Working phase={turn.phase} />}
      </div>
      {fallback && <p className="ag-chat-hint">{fallback}</p>}
      {walk &&
        turn.guide &&
        !turn.guide.state &&
        (() => {
          const step = walk.state.steps.find((s) => s.id === turn.guide?.step);
          return step ? (
            <GuideCard
              step={step}
              guide={walk.state}
              onNext={walk.onNext}
              onSkip={walk.onSkip}
              onLeave={walk.onLeave}
            />
          ) : null;
        })()}
      {(turn.web.length > 0 || when || spent || (turn.steps?.length ?? 0) > 0) && (
        <div className="ag-chat-foot">
          {turn.web.length > 0 && <Sources web={turn.web} />}
          {/* The cost rides on the trace counter for an answer, so the clock
              beside it only says when. */}
          {!mine && !turn.pending && <Trace steps={turn.steps ?? []} spent={spent} />}
          {when && <span className="ag-chat-clock">{when}</span>}
        </div>
      )}
    </div>
  );
}
