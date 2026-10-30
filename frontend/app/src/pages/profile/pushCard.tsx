/**
 * The Notifications tab's "This device" card: Web Push for a finished answer.
 *
 * Per device, unlike Telegram: the subscription is this browser's, so the
 * switch reads `pushManager` and the server together (`shell/push.ts`). It is
 * drawn only when the deployment has a key; a device that cannot push says
 * why — an iPhone tab is told to add the app to the Home Screen first.
 */

import { useEffect, useState } from "react";
import { useLang, useT } from "../../shell/i18n";
import {
  type PushState,
  disablePush,
  enablePush,
  needsInstall,
  permission,
  readPush,
  supported,
  testPush,
} from "../../shell/push";
import { describe } from "./errors";
import { Card, Failure, Row, Toggle } from "./ui";

type Busy = "toggle" | "test" | null;

export function PushCard() {
  const t = useT();
  const lang = useLang();
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [sent, setSent] = useState(false);

  useEffect(() => {
    let alive = true;
    readPush().then(
      (fresh) => alive && setState(fresh),
      () => alive && setState(null),
    );
    return () => {
      alive = false;
    };
  }, []);

  if (!state?.configured || !state.key) return null;
  const key = state.key;
  const blocked = permission() === "denied";
  const usable = supported() && !blocked;

  const toggle = async (on: boolean) => {
    setBusy("toggle");
    setError(null);
    setSent(false);
    try {
      if (on) {
        const granted = await enablePush(key, lang.startsWith("es") ? "es" : "en");
        setState({ ...state, subscribed: granted });
      } else {
        await disablePush();
        setState({ ...state, subscribed: false });
      }
    } catch (failure) {
      setError(describe(failure, t("common.offline")));
    } finally {
      setBusy(null);
    }
  };

  const test = async () => {
    setBusy("test");
    setError(null);
    try {
      await testPush();
      setSent(true);
    } catch (failure) {
      setError(describe(failure, t("common.offline")));
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card title={t("profile.push_title")} sub={t("profile.push_sub")}>
      {usable ? (
        <Row
          label={t("profile.push_answers")}
          help={t("profile.push_answers_help")}
          middle
        >
          <Toggle
            label={t("profile.push_answers")}
            checked={state.subscribed}
            disabled={busy !== null}
            onToggle={(on) => void toggle(on)}
          />
        </Row>
      ) : (
        <div className="pr-cardbody">
          <p className="pr-hint">
            {needsInstall()
              ? t("profile.push_install")
              : blocked
                ? t("profile.push_blocked")
                : t("profile.push_unsupported")}
          </p>
        </div>
      )}
      {usable && state.subscribed && (
        <Row
          label={t("profile.notify_test_row")}
          help={t("profile.push_test_help")}
          middle
        >
          <button
            type="button"
            className="pr-btn"
            disabled={busy !== null}
            onClick={() => void test()}
          >
            {t("profile.tg_test")}
          </button>
          {sent && <p className="pr-hint">{t("profile.push_test_sent")}</p>}
        </Row>
      )}
      <Failure message={error} />
    </Card>
  );
}
