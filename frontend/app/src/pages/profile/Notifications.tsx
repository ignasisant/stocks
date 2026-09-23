/**
 * The Notifications tab: where the digest and the alerts are delivered, which
 * of them are on, and the handshake that connects the chat in the first place.
 *
 * The connection's state is read from `GET /notify/telegram`, not from the
 * session's `telegram_linked`. Both answer the same question, but only one of
 * them is re-read: the chat id arrives while this screen is open, written by
 * the job that reads the bot's updates, and a copy taken when the app booted
 * cannot know that. The session's answer seeds the first paint so the card
 * does not flicker, and the route's answer replaces it the moment it lands.
 */

import { useT } from "../../shell/i18n";
import type { Settings } from "./prefs";
import { useTelegram } from "./telegram";
import { Card, Failure, Inline, Prose, Row, Toggle } from "./ui";

export function Notifications({ prefs, saving, failure, save }: Settings) {
  const t = useT();
  const tg = useTelegram(t("common.offline"));
  const fail = (field: string) => (failure?.field === field ? failure.message : null);

  // Seeded from the session, replaced by the route (see the note above).
  const linked = tg.state ? tg.state.linked : prefs.telegram_linked;
  // Null is "not known yet": this deployment may have no bot at all, and
  // offering to connect one that does not exist is a dead end. A linked
  // account answers it without waiting — nothing could have been linked
  // without a bot to link it to.
  const configured = tg.state?.configured ?? (prefs.telegram_linked ? true : null);

  return (
    <div className="pf-body">
      <div className="pf-main">
        <Card
          title={t("profile.notify_channel_title")}
          sub={t("profile.notify_channel_sub")}
        >
          <div className="pf-cardbody">
            {configured === null && !tg.note && (
              <p className="pf-busy">{t("common.loading")}</p>
            )}

            {/* Not an error, a sentence: nothing here can be connected. */}
            {configured === false && (
              <p className="pf-hint">{t("profile.tg_not_configured")}</p>
            )}

            {configured === true && linked && (
              <span className="pf-chips">
                <span className="pf-badge">{t("profile.notify_connected")}</span>
                {/* The handle stays on the server with the chat id, so this
                    reads as the Streamlit page reads it when it has none. */}
                <span className="pf-hint">
                  {t("profile.tg_linked_as", { handle: "" }).trim()}
                </span>
              </span>
            )}

            {/* Step one: ask for a code. Step two: open the link it came
                with. The button is replaced by the link rather than sitting
                beside it — there is one next thing to do at any point in the
                dance, and a second control here would be a way to invalidate
                the code the reader is holding. */}
            {configured === true && !linked && !tg.pending && (
              <span className="pf-chips">
                <button
                  type="button"
                  className="pf-btn pf-btn-p"
                  disabled={tg.busy === "connect"}
                  onClick={tg.connect}
                >
                  {t("profile.tg_connect")}
                </button>
                {tg.expired && (
                  <span className="pf-warn">{t("profile.tg_expired")}</span>
                )}
              </span>
            )}

            {configured === true && !linked && tg.pending && (
              <>
                {/* A real link to Telegram, in its own tab: on a phone this
                    hands off to the app, which is exactly what should happen,
                    and this tab stays open behind it to catch the answer. */}
                <a
                  className="pf-linkbtn"
                  href={tg.pending.deepLink}
                  target="_blank"
                  rel="noreferrer noopener"
                >
                  {t("profile.tg_open")}
                </a>
                {/* Some clients show no Start button. Typing the command is
                    the same handshake, so the code is on screen either way. */}
                <p className="pf-hint">
                  <Inline
                    text={t("profile.tg_manual", {
                      bot: tg.pending.bot,
                      code: tg.pending.code,
                    })}
                  />
                </p>
                <p className="pf-busy">
                  {tg.stalled ? t("profile.tg_poll_error") : t("profile.tg_waiting")}
                </p>
              </>
            )}

            {tg.note?.kind === "failed" && <Failure message={tg.note.error} />}
            {tg.note?.kind === "unlinked" && (
              <p className="pf-hint">{t("profile.tg_unlinked")}</p>
            )}
          </div>

          {/* Check and disconnect are actions on the link, not settings, so
              they stay on the channel card — each in its own row, because a
              bare pair of buttons gives no clue what the second one costs. */}
          {configured === true && linked && (
            <>
              <Row
                label={t("profile.notify_test_row")}
                help={t("profile.notify_test_help")}
                middle
              >
                <button
                  type="button"
                  className="pf-btn"
                  disabled={tg.busy === "test"}
                  onClick={tg.test}
                >
                  {t("profile.tg_test")}
                </button>
                {tg.note?.kind === "test_sent" && (
                  <p className="pf-hint">{t("profile.tg_test_sent")}</p>
                )}
                {tg.note?.kind === "test_failed" && (
                  <Failure
                    message={t("profile.tg_test_failed", { error: tg.note.error })}
                  />
                )}
              </Row>
              <Row
                label={t("profile.notify_unlink_row")}
                help={t("profile.notify_unlink_help")}
                middle
              >
                <button
                  type="button"
                  className="pf-btn"
                  disabled={tg.busy === "unlink"}
                  onClick={tg.unlink}
                >
                  {t("profile.tg_unlink")}
                </button>
              </Row>
            </>
          )}
        </Card>

        {/* Both toggles gate delivery, and delivery needs a chat: an account
            with none is shown the channel card and nothing to switch. */}
        {configured === true && linked && (
          <Card
            title={t("profile.notify_what_title")}
            sub={t("profile.notify_what_sub")}
          >
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

      <aside className="pf-rail">
        <Card>
          <div className="pf-sum">
            <b className="pf-sum-t">{t("profile.notify_caption")}</b>
            <Prose text={t("profile.tg_how_body")} />
          </div>
        </Card>
      </aside>
    </div>
  );
}
