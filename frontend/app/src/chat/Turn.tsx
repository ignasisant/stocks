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
 *
 * Memory is said on the turn that used it, both ways. A turn that saved or
 * forgot something ("remember that…") carries a "Memory updated" line with
 * its undo, so a memory is never kept behind the reader's back; one that was
 * handed earlier conversations names them above the answer, so "as we
 * discussed" points at something the reader can open.
 */

import { useId, useState } from "react";
import { ApiError } from "../shell/api";
import { useLang, useT } from "../shell/i18n";
import { Glyph } from "./icons";
import { Markdown } from "./markdown";
import { Status } from "../ui/Status";
import { addMemory, dropMemory, editMemory } from "./api";
import {
  capMessage,
  clock,
  host,
  providerLabel,
  skillName,
  stamp,
  took,
} from "./format";
import { ActionCard } from "./ActionCard";
import { GuideCard, useVisit } from "./GuideCard";
import { unshortcode, type GuideState, type GuideStep } from "./guide";
import { PageLink } from "./links";
import { Surfaces } from "./Surfaces";
import { Debate } from "./Debate";
import type { A2uiAction } from "./a2ui";
import type {
  Edits,
  Learned,
  LiveStep,
  Recalled as Earlier,
  SkillInfo,
  Step,
  Turn as Stored,
} from "./types";
import { Badge } from "../ui/Badge";

/** The line that ticks while the answer is being built, naming what it is doing. */
function Working({ phase }: { phase?: string }) {
  const t = useT();
  // The server names the phase by its key; an unknown one (a newer server)
  // falls back to the generic line rather than printing a raw key. Outside
  // the bubble's live region, so it is heard before the answer is written.
  const key = `chat.work_${phase ?? "thinking"}`;
  const said = t(key);
  return <Status label={said === key ? t("chat.work_thinking") : said} />;
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

/**
 * The research under an answer still being written, line by line as it runs.
 *
 * Open, unlike the trace it turns into: while the reader waits, what is being
 * looked up *is* the thing worth reading, and a line that says "search_web ·
 * nvidia guidance …" and then "→ 5 results" is the difference between a
 * spinner and watching someone work. Beside the status line, never instead
 * of it: every wait still names itself.
 */
function Live({ steps }: { steps: LiveStep[] }) {
  return (
    <ul className="ag-chat-steps ag-chat-live">
      {steps.map((step) => (
        <li key={step.id} aria-busy={step.out === undefined}>
          <code>{step.tool}</code>
          {step.arg && <span> {step.arg}</span>}
          {step.out === undefined ? (
            <span className="ag-chat-step-out"> …</span>
          ) : (
            <span className="ag-chat-step-out"> → {step.out}</span>
          )}
        </li>
      ))}
    </ul>
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

/**
 * "Based on 2 earlier conversations", opened on press into the conversations
 * themselves: title, when, and the line that was quoted. Each one opens its
 * thread, because a reader told "as we discussed" wants to check what was.
 *
 * Above the answer rather than in its foot, and drawn while the answer is
 * still being written: what the model was handed is read before what it made
 * of it.
 */
function Recalled({
  recalled,
  onOpen,
}: {
  recalled: Earlier[];
  onOpen?: (cid: string) => void;
}) {
  const t = useT();
  const lang = useLang();
  const [open, setOpen] = useState(false);
  const uid = useId();
  const listId = `${uid}-recalled`;
  return (
    <div className="ag-chat-recall">
      <button
        type="button"
        className="ag-chat-meta-btn"
        aria-expanded={open}
        aria-controls={listId}
        onClick={() => setOpen((was) => !was)}
      >
        <Glyph name="history" size={13} />
        {recalled.length === 1
          ? t("chat.recalled_one")
          : t("chat.recalled_n", { n: recalled.length })}
      </button>
      <ul className="ag-chat-recall-list" id={listId} hidden={!open}>
        {recalled.map((earlier) => (
          <li key={earlier.thread}>
            <button
              type="button"
              className="ag-chat-recall-item"
              disabled={!onOpen}
              title={t("chat.recalled_open")}
              onClick={() => onOpen?.(earlier.thread)}
            >
              <span className="ag-chat-recall-head">
                <span className="ag-chat-recall-title">
                  {earlier.title.trim() || t("chat.untitled")}
                </span>
                <span className="ag-chat-recall-when">{stamp(earlier.when, lang)}</span>
              </span>
              <span className="ag-chat-recall-snip">{earlier.snippet}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

type Undo = "idle" | "working" | "undone" | "gone" | "full" | "failed";

/** The memory screen's write that takes `change` back. */
export function undoMemory(change: Learned): Promise<unknown> {
  if (change.op === "added") return dropMemory(change.id);
  if (change.op === "updated")
    return editMemory(change.id, { text: change.before ?? change.text });
  return addMemory({ text: change.text, kind: change.kind });
}

/**
 * One change to the saved memories, said under the turn that made it, with
 * its undo: a memory added is deleted again, one forgotten is saved again,
 * one corrected gets its old words back. One learned unasked says so — the
 * reader never typed "remember", so the line is the only place they learn
 * that something was kept.
 *
 * The undo is a call to the memory screen's own routes, not a turn: taking
 * back a memory is not something to ask a model to do. Session-only, like
 * the clock — a reloaded turn offers the undo again, and pressing it on a
 * change that was already taken back says so (a 404) instead of failing.
 */
function Change({
  change,
  quoted,
  onMemory,
}: {
  change: Learned;
  /** Name the memory: the bubble above has not already done so. */
  quoted: boolean;
  onMemory?: () => void;
}) {
  const t = useT();
  const [undo, setUndo] = useState<Undo>("idle");

  const take = async () => {
    setUndo("working");
    try {
      await undoMemory(change);
      setUndo("undone");
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 404) setUndo("gone");
      else if (failure instanceof ApiError && failure.status === 409) setUndo("full");
      else setUndo("failed");
    }
  };

  const said = (() => {
    if (undo === "undone") {
      if (change.op === "added" && change.kind === "routine")
        return t("chat.mem_undone_routine");
      if (change.op === "added") return t("chat.mem_undone_added");
      if (change.op === "updated") return t("chat.mem_undone_updated");
      return t("chat.mem_undone_deleted");
    }
    if (change.op === "updated") return t("chat.mem_corrected");
    if (change.op === "deleted")
      return change.auto ? t("chat.mem_dropped") : t("chat.mem_forgotten");
    if (change.kind === "routine")
      return change.repeated
        ? t("chat.mem_routine_repeated", { n: change.repeated })
        : t("chat.mem_routine_added");
    return change.auto ? t("chat.mem_learned") : t("chat.mem_updated");
  })();
  return (
    <div className="ag-chat-memo">
      <span className="ag-chat-memo-said">
        <span className="ag-chat-memo-head">
          <Glyph name="memory" size={13} />
          {said}
        </span>
        {(quoted || change.auto) && (
          <span className="ag-chat-memo-text">«{change.text}»</span>
        )}
        {change.op === "updated" && change.before && undo !== "undone" && (
          <span className="ag-chat-memo-was">
            {t("chat.mem_was", { text: change.before })}
          </span>
        )}
      </span>
      {undo === "working" ? (
        <Status label={t("chat.mem_undoing")} />
      ) : (
        <span className="ag-chat-memo-acts">
          {(undo === "idle" || undo === "failed") && (
            <button
              type="button"
              className="ag-chat-meta-btn"
              onClick={() => void take()}
            >
              {t("chat.mem_undo")}
            </button>
          )}
          {onMemory && (
            <button type="button" className="ag-chat-meta-btn" onClick={onMemory}>
              {t("chat.mem_manage")}
            </button>
          )}
        </span>
      )}
      {undo === "gone" && <p className="ag-chat-hint">{t("chat.mem_undo_gone")}</p>}
      {undo === "full" && <p className="ag-chat-hint">{t("chat.mem_full_note")}</p>}
      {undo === "failed" && <p className="ag-chat-hint">{t("chat.api_error")}</p>}
    </div>
  );
}

/** Every memory change a turn made, under it. */
function Changes({ turn, onMemory }: { turn: Stored; onMemory?: () => void }) {
  const learned = turn.learned ?? [];
  if (!learned.length) return null;
  return (
    <>
      {learned.map((change) => (
        // A turn that was only the command already quotes the memory in its
        // own words; one that went on to answer a question does not.
        <Change
          key={`${change.op}-${change.id}`}
          change={change}
          quoted={turn.action !== "memory"}
          onMemory={onMemory}
        />
      ))}
    </>
  );
}

/**
 * The button an answer on the walkthrough's thread earned by ending in a valid
 * `[[goto:<step>]]` — `guide.render_jump`, and a `navigate` call with `{step}`
 * on the wire.
 *
 * A button and not a navigation: the model proposes, the reader decides. The
 * marker itself never reaches the screen (the server withholds it while the
 * answer streams), and an id the model invented never becomes one of these —
 * it was checked against the registry before it was stored.
 */
function Jump({ step, onLeave }: { step: GuideStep; onLeave: () => void }) {
  const t = useT();
  const visit = useVisit(onLeave);
  return (
    <div className="ag-guide-acts">
      <button type="button" className="ag-chat-btn" onClick={() => visit(step)}>
        {t(step.cta_key ?? "guide.goto")}
      </button>
    </div>
  );
}

export function Turn({
  turn,
  skills,
  providers,
  cap,
  onRetry,
  onDrop,
  onDecide,
  onLeave,
  onPress,
  onOpenThread,
  onMemory,
  walk,
}: {
  turn: Stored;
  skills: SkillInfo[];
  /** The offered backends, to name the two in a failover by brand. */
  providers: { id: string; label: string }[];
  /** Today's free allowance, for the refusals that name it. */
  cap: number | null;
  onRetry: () => void;
  /**
   * Take a refused turn off the thread — the Streamlit composer's "Discard
   * question" beside Retry. Absent: nothing to offer.
   */
  onDrop?: () => void;
  /** Answer a proposal card. Absent: its buttons are not drawn. */
  onDecide?: (id: string, approved: boolean, edits?: Edits) => Promise<string | null>;
  /** The drawer stepping aside for the page a link opened, on a phone. */
  onLeave?: () => void;
  /** A press on one of the answer's surfaces. Absent: they draw, inert. */
  onPress?: (activity: string, action: A2uiAction) => Promise<boolean>;
  /** Open an earlier conversation the answer was handed. */
  onOpenThread?: (cid: string) => void;
  /** Open the memory screen. Absent: the memory line offers only its undo. */
  onMemory?: () => void;
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
          {/* A memory command before the question was carried out whether
              or not the question was answered, so the refusal still says
              what was saved. */}
          <Changes turn={turn} onMemory={onMemory} />
          <div className="ag-chat-fail-acts">
            {/* A failed attachment has no question to ask again — Retry would
                re-send the exchange above it, which was answered. Its way
                forward is attaching the file again, so it only offers the
                way out. */}
            {turn.action !== "import" && (
              <button type="button" className="ag-chat-retry" onClick={onRetry}>
                {t("chat.retry")}
              </button>
            )}
            {onDrop && (
              <button type="button" className="ag-chat-retry" onClick={onDrop}>
                {t("chat.error_drop")}
              </button>
            )}
          </div>
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
      {turn.spoken && <Badge>{t("chat.voice_badge")}</Badge>}
      {/* An answer that breaks off mid-sentence reads as the model losing the
          thread. Said plainly, it reads as what it was. */}
      {turn.stopped && <Badge>{t("chat.stopped_badge")}</Badge>}
      {!mine && (turn.recalled?.length ?? 0) > 0 && (
        <Recalled recalled={turn.recalled ?? []} onOpen={onOpenThread} />
      )}
      {!mine && (turn.arguing?.length || turn.debate?.length) ? (
        <Debate sides={turn.pending ? (turn.arguing ?? []) : (turn.debate ?? [])} />
      ) : null}
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
        {turn.pending && (turn.live?.length ?? 0) > 0 && (
          <Live steps={turn.live ?? []} />
        )}
      </div>
      {fallback && <p className="ag-chat-hint">{fallback}</p>}
      {!turn.pending && <Changes turn={turn} onMemory={onMemory} />}
      {!turn.pending && (turn.activities?.length ?? 0) > 0 && (
        <Surfaces activities={turn.activities ?? []} onPress={onPress} />
      )}
      {!turn.pending &&
        (turn.tool_calls ?? []).map((call) => {
          if (call.name === "confirm_action") {
            const form = turn.activities?.find(
              (shown) => shown.id === `form_${call.id}` && shown.type === "a2ui",
            );
            return (
              <ActionCard
                key={call.id}
                call={call}
                form={form?.content.messages}
                onDecide={onDecide}
              />
            );
          }
          if (call.name !== "navigate") return null;
          if (typeof call.args.step === "string") {
            const step = walk?.state.steps.find((s) => s.id === call.args.step);
            return step && walk ? (
              <Jump key={call.id} step={step} onLeave={walk.onLeave} />
            ) : null;
          }
          return typeof call.args.page === "string" ? (
            <PageLink key={call.id} args={call.args} onLeave={onLeave ?? (() => {})} />
          ) : null;
        })}
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
