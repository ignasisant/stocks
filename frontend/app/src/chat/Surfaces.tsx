/**
 * The surfaces under an answer that are not a proposal's form: a what-if
 * sale's slider, today. Each is the server's A2UI (`a2ui.tsx` draws it), and a
 * press on one goes back to the server, whose answer is folded into it.
 *
 * The wait is short — a replay, no model — but it is still a wait, so it
 * names itself like every other one in the drawer, and the controls hold
 * still until it is over rather than queueing a second press behind the first.
 */

import { useState } from "react";
import { useT } from "../shell/i18n";
import { Status } from "../ui/Status";
import { toast } from "../ui/toast";
import { Surface, type A2uiAction } from "./a2ui";
import type { Activity } from "./types";

function One({
  shown,
  onPress,
}: {
  shown: Activity;
  onPress?: (activity: string, action: A2uiAction) => Promise<boolean>;
}) {
  const t = useT();
  const [waiting, setWaiting] = useState(false);
  return (
    <div className="ag-chat-surface">
      <Surface
        messages={shown.content.messages ?? []}
        disabled={waiting}
        onAction={
          onPress &&
          ((action) => {
            setWaiting(true);
            void onPress(shown.id, action).then((went) => {
              setWaiting(false);
              if (!went) toast.bad(t("chat.api_error"));
            });
          })
        }
      />
      {waiting && <Status label={t("chat.surface_working")} />}
    </div>
  );
}

export function Surfaces({
  activities,
  onPress,
}: {
  activities: Activity[];
  onPress?: (activity: string, action: A2uiAction) => Promise<boolean>;
}) {
  const drawn = activities.filter(
    (shown) => shown.type === "a2ui" && !shown.id.startsWith("form_"),
  );
  return (
    <>
      {drawn.map((shown) => (
        <One key={shown.id} shown={shown} onPress={onPress} />
      ))}
    </>
  );
}
