/**
 * The Notifications tab: what to receive, and the switch that turns it on for
 * this device.
 *
 * Every message — the evening digest, the Sunday review, price alerts, the
 * reminder, a finished answer — is a Web Push notification, so the channel is
 * per device (`PushCard`) while the three toggles are the account's. The
 * toggles are drawn whenever the deployment can push at all; with no device
 * subscribed yet they say where the messages will go once one is.
 */

import { useEffect, useState } from "react";
import { type PushState, readPush } from "../../shell/push";
import { useT } from "../../shell/i18n";
import type { Settings } from "./prefs";
import { PushCard } from "./pushCard";
import { Card, Failure, Prose, Row, Toggle } from "./ui";

export function Notifications({ prefs, saving, failure, save }: Settings) {
  const t = useT();
  const [push, setPush] = useState<PushState | null>(null);
  const fail = (field: string) => (failure?.field === field ? failure.message : null);

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
              label={t("profile.notify_digest")}
              help={t("profile.notify_digest_help")}
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
              help={t("profile.notify_weekly_help")}
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
