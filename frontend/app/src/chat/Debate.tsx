/**
 * The bull and the bear case an answer weighed — two AG-UI subagents, argued
 * before the answer was written (`stocks/chat/debate.py`).
 *
 * Above the answer, because that is the order it happened in and the order it
 * reads best in: the case for, the case against, then the verdict that had to
 * weigh them. While a side is still being argued its column says so, like any
 * other wait in the drawer; a side that failed says that instead of vanishing,
 * so a one-sided debate never passes for a balanced one.
 */

import { useT } from "../shell/i18n";
import { Status } from "../ui/Status";
import { Markdown } from "./markdown";
import type { Arguing, DebateSide } from "./types";

const ORDER = ["bull", "bear"];

export function Debate({ sides }: { sides: (DebateSide | Arguing)[] }) {
  const t = useT();
  const drawn = [...sides].sort(
    (a, b) => ORDER.indexOf(a.side) - ORDER.indexOf(b.side),
  );
  if (!drawn.length) return null;
  return (
    <div className="ag-chat-debate">
      {drawn.map((side) => {
        const state = "state" in side ? side.state : "done";
        return (
          <section
            key={side.side}
            className={`ag-chat-case ag-chat-case-${side.side}`}
            aria-busy={state === "arguing"}
          >
            <h4 className="ag-chat-case-head">{t(`chat.debate_${side.side}`)}</h4>
            {state === "failed" ? (
              <p className="ag-chat-hint">{t("chat.debate_failed")}</p>
            ) : side.text ? (
              <Markdown text={side.text} />
            ) : (
              <Status label={t("chat.debate_arguing")} />
            )}
          </section>
        );
      })}
    </div>
  );
}
