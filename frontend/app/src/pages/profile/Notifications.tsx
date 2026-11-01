/**
 * The Notifications tab: what to receive, and the switch that turns it on for
 * this device.
 *
 * Every message — the AI briefing, the day's numbers, the weekly review, price
 * alerts, the reminder, a finished answer — is a Web Push notification, so the
 * channel is per device (`PushCard`) while the toggles are the account's. The
 * toggles are drawn whenever the deployment can push at all; with no device
 * subscribed yet they say where the messages will go once one is.
 *
 * The three scheduled runs say when they go out; that is changed where their
 * runs are read, the chat's "Scheduled" block (`?chat=scheduled`).
 */

import { useEffect, useState } from "react";
import { type PushState, readPush } from "../../shell/push";
import { useLang, useT } from "../../shell/i18n";
import { get } from "../../shell/api";
import type { Prefs } from "../../shell/session";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { weekdayNames, whenLabel } from "../../chat/slots";
import type { Settings } from "./prefs";
import { PushCard } from "./pushCard";
import { Card, Failure, Prose, Row, Toggle } from "./ui";

export function Notifications({ prefs, saving, failure, save }: Settings) {
  const t = useT();
  const lang = useLang();
  const { setParams } = useRoute();
  const [push, setPush] = useState<PushState | null>(null);
  const fail = (field: string) => (failure?.field === field ? failure.message : null);
  const names = weekdayNames(lang);
  // The switch is the toggle below, saved here; the time and days are the
  // chat's to change, so this only reads them — fresh, since the session's
  // copy predates whatever the chat saved.
  const fresh = useApi(() => get<Prefs>("/prefs"), []);
  const schedules =
    (fresh.state === "loaded" ? fresh.data.schedules : null) ?? prefs.schedules;
  const help = (job: "briefing" | "digest" | "weekly", on: boolean) => {
    const slot = schedules?.[job];
    const text = t(`profile.notify_${job}_help`);
    return slot ? `**${whenLabel({ ...slot, on }, names, t)}.** ${text}` : text;
  };
  const briefing = prefs.notify_briefing ?? true;

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
            <Row
              label={t("profile.notify_briefing")}
              help={help("briefing", briefing)}
              middle
            >
              <Toggle
                label={t("profile.notify_briefing")}
                checked={briefing}
                disabled={saving === "notify_briefing"}
                onToggle={(on) => save("notify_briefing", on)}
              />
              <Failure message={fail("notify_briefing")} />
            </Row>
            <Row
              label={t("profile.notify_digest")}
              help={help("digest", prefs.notify_digest)}
              middle
            >
              <Toggle
                label={t("profile.notify_digest")}
                checked={prefs.notify_digest}
                disabled={saving === "notify_digest"}
                onToggle={(on) => save("notify_digest", on)}
              />
              <Failure message={fail("notify_digest")} />
            </Row>
            <Row
              label={t("profile.notify_weekly")}
              help={help("weekly", prefs.notify_weekly)}
              middle
            >
              <Toggle
                label={t("profile.notify_weekly")}
                checked={prefs.notify_weekly}
                disabled={saving === "notify_weekly"}
                onToggle={(on) => save("notify_weekly", on)}
              />
              <Failure message={fail("notify_weekly")} />
            </Row>
            {/* Beside the three runs it times, not after the alerts it does not. */}
            <div className="pr-cardbody">
              <button
                type="button"
                className="pr-btn pr-selfstart"
                onClick={() => setParams({ chat: "scheduled" })}
              >
                {t("profile.notify_schedule_open")}
              </button>
            </div>
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
