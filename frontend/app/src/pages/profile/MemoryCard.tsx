/**
 * What the assistant remembers, offered from the profile.
 *
 * The memories live in the chat drawer (Settings → Memory), because that is
 * where they are made and undone. A reader looking over their account looks
 * here, though, so the rail carries how many there are and a link that opens
 * the drawer on that screen — `?chat=memory`, which the drawer reads off the
 * URL the way the tour card's `?tour=1` is read by the shell.
 *
 * A failed read draws no count rather than a wrong one, and the link still
 * works: the drawer makes its own read.
 */

import { get } from "../../shell/api";
import { useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Card } from "./ui";

/** The fields of `GET /chat/memories` this card reads. */
type Saved = { memories: unknown[]; enabled: boolean; max: number };

export function MemoryCard() {
  const t = useT();
  const { setParams } = useRoute();
  const read = useApi(() => get<Saved>("/chat/memories"), []);
  const saved = read.state === "loaded" ? read.data : null;

  return (
    <Card>
      <div className="pr-sum">
        <span className="pr-sum-t">{t("profile.memory_title")}</span>
        <span className="pr-sum-note">{t("profile.memory_caption")}</span>
        {saved && (
          <span className="pr-sum-note">
            {saved.enabled
              ? t("profile.memory_count", { n: saved.memories.length, max: saved.max })
              : t("profile.memory_off")}
          </span>
        )}
        <button
          type="button"
          className="pr-btn pr-selfstart"
          onClick={() => setParams({ chat: "memory" })}
        >
          {t("profile.memory_open")}
        </button>
      </div>
    </Card>
  );
}
