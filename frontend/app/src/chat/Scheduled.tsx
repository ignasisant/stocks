/**
 * The scheduled runs, at the top of the thread list.
 *
 * One job — the AI briefing, the one summary a day — going out at the
 * reader's own time and days, or after the US close (`notify/schedule.py`),
 * and each run filed as a thread of its own. So the block is the job first
 * (when, and a switch), then the runs it filed: a push notification lands on
 * one of those threads, and the reader looking for it later finds it here
 * rather than buried among the conversations they started.
 *
 * Folded state is the browser's (a screen's layout, not the account's): read
 * once, and a storage that throws only means it opens folded.
 */

import { useEffect, useId, useRef, useState } from "react";
import { get, send } from "../shell/api";
import { useLang, useT } from "../shell/i18n";
import { type Prefs, type Schedule, useSession } from "../shell/session";
import { browserZone } from "../shell/zone";
import { Glyph } from "./icons";
import { closeTime, weekdayNames, whenLabel } from "./slots";
import type { Conversation } from "./types";

const JOBS = ["briefing"] as const;
const FOLD_KEY = "chatScheduledOpen";
/** Runs shown before "show more": a week of briefings. */
const FIRST_RUNS = 5;

function storedOpen(): boolean {
  try {
    return window.localStorage.getItem(FOLD_KEY) === "1";
  } catch {
    return false;
  }
}

function storeOpen(open: boolean) {
  try {
    window.localStorage.setItem(FOLD_KEY, open ? "1" : "0");
  } catch {
    // A private window: the fold just is not remembered.
  }
}

/**
 * When a run goes out: at a time of the reader's, or after the US close, and
 * on which days. The profile's Notifications tab draws the same form.
 */
export function ScheduleEditor({
  id,
  slot,
  names,
  zone,
  saving,
  onSave,
  onCancel,
}: {
  id: string;
  slot: Schedule;
  names: string[];
  zone: string | null;
  saving: boolean;
  onSave: (next: Schedule) => void;
  onCancel: () => void;
}) {
  const t = useT();
  const [time, setTime] = useState(slot.time);
  const [days, setDays] = useState(slot.days);
  const [close, setClose] = useState(!!slot.close);
  const flip = (d: number) =>
    setDays(
      days.includes(d)
        ? days.filter((x) => x !== d)
        : [...days, d].sort((a, b) => a - b),
    );
  return (
    <form
      id={id}
      className="ag-sched-edit"
      onSubmit={(event) => {
        event.preventDefault();
        onSave({ on: slot.on, time, days, close });
      }}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          onCancel();
        }
      }}
    >
      <div className="ag-sched-days" role="group" aria-label={t("chat.sched_mode")}>
        <button
          type="button"
          className="ag-chat-chip ag-sched-day ag-sched-mode"
          aria-pressed={!close}
          autoFocus={!close}
          onClick={() => setClose(false)}
        >
          {t("chat.sched_mode_time")}
        </button>
        <button
          type="button"
          className="ag-chat-chip ag-sched-day ag-sched-mode"
          aria-pressed={close}
          autoFocus={close}
          onClick={() => setClose(true)}
        >
          {t("chat.sched_mode_close", { time: closeTime(zone) })}
        </button>
      </div>
      {/* The time stays stored while it is unused: switching back finds it. */}
      {!close && (
        <label className="ag-sched-field">
          <span>{t("chat.sched_time")}</span>
          <input
            className="ag-chat-input"
            type="time"
            required
            value={time}
            onChange={(event) => setTime(event.target.value)}
          />
        </label>
      )}
      {close && <p className="ag-sched-hint">{t("chat.sched_close_hint")}</p>}
      <div className="ag-sched-days" role="group" aria-label={t("chat.sched_days")}>
        {names.map((name, d) => (
          <button
            key={d}
            type="button"
            className="ag-chat-chip ag-sched-day"
            aria-pressed={days.includes(d)}
            onClick={() => flip(d)}
          >
            {name}
          </button>
        ))}
      </div>
      {/* Said, not just a dead Save: the reader sees why it will not go. */}
      {!days.length && <p className="ag-sched-hint">{t("chat.sched_pick_day")}</p>}
      <div className="ag-chat-confirm-row">
        <button
          type="submit"
          className="ag-chat-btn ag-chat-btn-on"
          disabled={saving || !time || !days.length}
        >
          {t("chat.sched_save")}
        </button>
        <button type="button" className="ag-chat-btn" onClick={onCancel}>
          {t("chat.cancel")}
        </button>
      </div>
    </form>
  );
}

/** How long "Saved" stays on a row before it reads its schedule again. */
const SAVED_MS = 2000;

function Job({
  job,
  slot,
  names,
  zone,
  onSave,
}: {
  job: string;
  slot: Schedule;
  names: string[];
  zone: string | null;
  onSave: (next: Schedule) => Promise<void>;
}) {
  const t = useT();
  const editorId = useId();
  const opener = useRef<HTMLButtonElement>(null);
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  // The answer to the last save, on the row it changed: "Saved" for a
  // moment, or why it did not take — never a banner somewhere else.
  const [outcome, setOutcome] = useState<"saved" | "failed" | null>(null);
  useEffect(() => {
    if (outcome !== "saved") return;
    const timer = window.setTimeout(() => setOutcome(null), SAVED_MS);
    return () => window.clearTimeout(timer);
  }, [outcome]);
  const close = () => {
    setEditing(false);
    opener.current?.focus();
  };
  const save = (next: Schedule) => {
    setSaving(true);
    setOutcome(null);
    onSave(next).then(
      () => {
        setSaving(false);
        setOutcome("saved");
        if (editing) close();
      },
      () => {
        setSaving(false);
        setOutcome("failed");
      },
    );
  };
  const name = t(`chat.sched_${job}`);
  const when = whenLabel(slot, names, t, zone);
  return (
    <div className="ag-sched-job" data-off={slot.on ? undefined : ""}>
      <div className="ag-chat-card">
        <button
          ref={opener}
          type="button"
          className="ag-chat-card-open ag-sched-open"
          aria-expanded={editing}
          aria-controls={editing ? editorId : undefined}
          title={t("chat.sched_edit")}
          onClick={() => (editing ? close() : setEditing(true))}
        >
          <span className="ag-chat-card-title">{name}</span>
          <span className="ag-chat-card-meta" aria-live="polite">
            {outcome === "saved" ? (
              <span className="ag-sched-saved">
                <Glyph name="check" size={12} />
                {t("chat.sched_saved")}
              </span>
            ) : (
              when
            )}
          </span>
        </button>
        <label className="ag-sched-switch">
          <input
            type="checkbox"
            role="switch"
            checked={slot.on}
            disabled={saving}
            aria-label={name}
            onChange={(event) => save({ ...slot, on: event.target.checked })}
          />
        </label>
      </div>
      {outcome === "failed" && (
        <p className="ag-sched-hint" role="alert">
          {t("chat.sched_failed")}
        </p>
      )}
      {editing && (
        <ScheduleEditor
          id={editorId}
          slot={slot}
          names={names}
          zone={zone}
          saving={saving}
          onSave={save}
          onCancel={close}
        />
      )}
    </div>
  );
}

export function Scheduled({
  runs,
  searching,
  forceOpen,
  renderRun,
}: {
  /** The threads scheduled runs filed, newest first, already searched. */
  runs: Conversation[];
  /** A search is on: the block opens on its matches and hides the jobs. */
  searching: boolean;
  /** Sent here (`?chat=scheduled`): open, whatever was remembered. */
  forceOpen?: boolean;
  renderRun: (conv: Conversation) => React.ReactNode;
}) {
  const t = useT();
  const lang = useLang();
  const session = useSession();
  const [open, setOpen] = useState(() => !!forceOpen || storedOpen());
  const [all, setAll] = useState(false);
  const [slots, setSlots] = useState(session.prefs.schedules ?? {});
  // The session's copy is from when the app loaded; the profile's toggles
  // may have moved a switch since, so the block reads its own.
  useEffect(() => {
    if (session.guest) return;
    let alive = true;
    get<Prefs>("/prefs").then(
      (fresh) => alive && fresh.schedules && setSlots(fresh.schedules),
      () => undefined,
    );
    return () => {
      alive = false;
    };
  }, [session.guest]);
  // Sent here while the list was already on screen.
  useEffect(() => {
    if (forceOpen) setOpen(true);
  }, [forceOpen]);
  const names = weekdayNames(lang);
  const zone = session.prefs.timezone ?? browserZone();
  // A guest reads the shared demo book: it has no runs and nothing to time.
  const jobs = session.guest
    ? []
    : JOBS.flatMap((job) => {
        const slot = slots[job];
        return slot ? [{ job, slot }] : [];
      });
  if (!jobs.length && !runs.length) return null;
  if (searching && !runs.length) return null;

  const shown = open || searching;
  const visible = all || searching ? runs : runs.slice(0, FIRST_RUNS);
  const save = (job: string) => (next: Schedule) =>
    send<Prefs>("PUT", `/schedules/${job}`, next).then((fresh) => {
      if (fresh.schedules) setSlots(fresh.schedules);
    });

  return (
    <section className="ag-sched" aria-label={t("chat.sched_title")}>
      <button
        type="button"
        className="ag-sched-head"
        aria-expanded={shown}
        onClick={() => {
          storeOpen(!open);
          setOpen(!open);
        }}
      >
        <Glyph name="schedule" size={15} />
        <span className="ag-sched-name">{t("chat.sched_title")}</span>
        {runs.length > 0 && <span className="ag-sched-count">{runs.length}</span>}
        <span className="ag-sched-chev" data-open={shown || undefined}>
          <Glyph name="back" size={15} />
        </span>
      </button>
      {shown && (
        <div className="ag-sched-body">
          {!searching &&
            jobs.map(({ job, slot }) => (
              <Job
                key={job}
                job={job}
                slot={slot}
                names={names}
                zone={zone}
                onSave={save(job)}
              />
            ))}
          {!searching && jobs.length > 0 && zone && (
            <p className="ag-chat-note">{t("chat.sched_zone", { zone })}</p>
          )}
          {!searching && !runs.length && (
            <p className="ag-chat-note">{t("chat.sched_none")}</p>
          )}
          {visible.map((conv) => (
            <div key={conv.id} className="ag-sched-run">
              {renderRun(conv)}
            </div>
          ))}
          {!all && !searching && runs.length > FIRST_RUNS && (
            <button
              type="button"
              className="ag-chat-btn ag-sched-more"
              onClick={() => setAll(true)}
            >
              {t("chat.sched_more", { n: runs.length - FIRST_RUNS })}
            </button>
          )}
        </div>
      )}
    </section>
  );
}
