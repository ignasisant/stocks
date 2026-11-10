/**
 * The Notifications tab: what to receive, and the switch that turns it on for
 * this device.
 *
 * Every message but one — the daily AI summary, price alerts, the reminder, a
 * finished answer — is a Web Push notification, so the channel is per device
 * (`PushCard`) while the toggles are the account's. The toggles are drawn
 * whenever the deployment can push at all; with no device subscribed yet they
 * say where the messages will go once one is.
 *
 * The one is the Friday email, sent to the sign-in address with no device
 * involved, so its card stands outside the push gate.
 *
 * The daily summary is the one scheduled push, so when it goes out is changed
 * right on its row — at a time, or after the US close — with the same form
 * the chat's "Scheduled" block opens (`?chat=scheduled`, where its past runs
 * are kept). Its notification carries a "Change time" button to here.
 */

import { useEffect, useId, useState } from "react";
import { type PushState, readPush } from "../../shell/push";
import { useLang, useT } from "../../shell/i18n";
import { get, send } from "../../shell/api";
import { type Prefs, type Schedule, useSession } from "../../shell/session";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { browserZone } from "../../shell/zone";
import { ScheduleEditor } from "../../chat/Scheduled";
import { weekdayNames, whenLabel } from "../../chat/slots";
import type { Settings } from "./prefs";
import { PushCard } from "./pushCard";
import { Card, Failure, Prose, Row, Toggle } from "./ui";

export function Notifications({ prefs, saving, failure, save }: Settings) {
  const t = useT();
  const lang = useLang();
  const session = useSession();
  const email = session.guest ? null : session.me.email;
  const { params, setParams } = useRoute();
  const [push, setPush] = useState<PushState | null>(null);
  const fail = (field: string) => (failure?.field === field ? failure.message : null);
  const names = weekdayNames(lang);
  const zone = session.prefs.timezone ?? browserZone();
  const editorId = useId();
  // Read fresh, since the session's copy predates whatever the chat saved;
  // then whatever this tab saved itself.
  const fresh = useApi(() => get<Prefs>("/prefs"), []);
  const [saved, setSaved] = useState<Schedule | null>(null);
  // The notification's "Change time" button lands here with the form open.
  const [editing, setEditing] = useState(() => params.get("edit") === "briefing");
  const [timing, setTiming] = useState(false);
  const [timeFailed, setTimeFailed] = useState(false);
  const briefing = prefs.notify_briefing ?? true;
  const slot =
    saved ??
    (fresh.state === "loaded" ? fresh.data.schedules?.briefing : null) ??
    prefs.schedules?.briefing;
  const help = slot
    ? `**${whenLabel({ ...slot, on: briefing }, names, t, zone)}.** ${t("profile.notify_briefing_help")}`
    : t("profile.notify_briefing_help");
  const retime = (next: Schedule) => {
    setTiming(true);
    setTimeFailed(false);
    send<Prefs>("PUT", "/schedules/briefing", { ...next, on: briefing }).then(
      (out) => {
        setTiming(false);
        if (out.schedules?.briefing) setSaved(out.schedules.briefing);
        setEditing(false);
      },
      () => {
        setTiming(false);
        setTimeFailed(true);
      },
    );
  };

  useEffect(() => {
    let alive = true;
    readPush().then(
      (fresh) => alive && setPush(fresh),
      () => alive && setPush(null),
    );
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="pr-body">
      <div className="pr-main">
        <PushCard state={push} onState={setPush} />

        {/* The toggles gate what is sent to the account's devices; on a
            deployment with no push key there is nothing to send. */}
        {push?.configured && (
          <Card
            title={t("profile.notify_what_title")}
            sub={t("profile.notify_what_sub")}
          >
            {push.devices === 0 && (
              <div className="pr-cardbody">
                <p className="pr-hint">{t("profile.notify_no_devices")}</p>
              </div>
            )}
            <Row label={t("profile.notify_briefing")} help={help} middle>
              <Toggle
                label={t("profile.notify_briefing")}
                checked={briefing}
                disabled={saving === "notify_briefing"}
                onToggle={(on) => save("notify_briefing", on)}
              />
              <Failure message={fail("notify_briefing")} />
            </Row>
            {/* Under the switch it times: change it in one tap, or see what
                it sent before. */}
            <div className="pr-cardbody pr-btnrow">
              <button
                type="button"
                className="pr-btn"
                aria-expanded={editing}
                aria-controls={editing ? editorId : undefined}
                disabled={!slot}
                onClick={() => setEditing(!editing)}
              >
                {t("profile.notify_briefing_time")}
              </button>
              <button
                type="button"
                className="pr-btn"
                onClick={() => setParams({ chat: "scheduled" })}
              >
                {t("profile.notify_schedule_open")}
              </button>
            </div>
            {editing && slot && (
              <div className="pr-cardbody">
                <ScheduleEditor
                  id={editorId}
                  slot={slot}
                  names={names}
                  zone={zone}
                  saving={timing}
                  onSave={retime}
                  onCancel={() => setEditing(false)}
                />
                <Failure message={timeFailed ? t("chat.sched_failed") : null} />
              </div>
            )}
            <Row
              label={t("profile.notify_alerts")}
              help={t("profile.notify_alerts_help")}
              middle
            >
              <Toggle
                label={t("profile.notify_alerts")}
                checked={prefs.notify_alerts}
                disabled={saving === "notify_alerts"}
                onToggle={(on) => save("notify_alerts", on)}
              />
              <Failure message={fail("notify_alerts")} />
            </Row>
          </Card>
        )}

        {email && (
          <Card
            title={t("profile.notify_email_title")}
            sub={t("profile.notify_email_sub", { email })}
          >
            <Row
              label={t("profile.notify_weekly_email")}
              help={t("profile.notify_weekly_email_help")}
              middle
            >
              <Toggle
                label={t("profile.notify_weekly_email")}
                checked={prefs.notify_weekly_email ?? true}
                disabled={saving === "notify_weekly_email"}
                onToggle={(on) => save("notify_weekly_email", on)}
              />
              <Failure message={fail("notify_weekly_email")} />
            </Row>
          </Card>
        )}
      </div>

      <aside className="pr-rail">
        <Card>
          <div className="pr-sum">
            <b className="pr-sum-t">{t("profile.notify_caption")}</b>
            <Prose text={t("profile.notify_how_body")} />
          </div>
        </Card>
      </aside>
    </div>
  );
}
