/**
 * What this account's devices were last sent: the newest few notifications,
 * the rest behind "Earlier". Read off `GET /push`'s `recent` (the same log the
 * connector's `push_history` tool reads), so what is listed is what went out,
 * not what the toggles say should.
 */

import { useState } from "react";
import { get } from "../../shell/api";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { ago } from "./Sessions";
import { Card } from "./ui";

/** `GET /push` → `recent[]`, as `api/routes/push.Sent` declares it. */
export type Sent = {
  at: number;
  topic: string;
  title: string;
  body: string;
  url: string;
  devices: number;
  took: number;
};

/** How many show before "Earlier". */
const SHOWN = 4;

export function PushHistory() {
  const t = useT();
  const lang = useLang();
  const query = useApi(() => get<{ recent?: Sent[] }>("/push"), []);
  const [all, setAll] = useState(false);
  if (query.state !== "loaded") return null;
  const rows = query.data.recent ?? [];
  if (!rows.length) return null;
  const shown = all ? rows : rows.slice(0, SHOWN);
  return (
    <Card title={t("profile.push_history_title")} sub={t("profile.push_history_sub")}>
      <ul className="pr-conns">
        {shown.map((row) => (
          <li className="pr-conn" key={`${row.at}${row.topic}${row.title}`}>
            <div className="pr-conn-l">
              <span className="pr-conn-name">{row.title || row.topic}</span>
              {row.body && <span className="pr-conn-meta">{row.body}</span>}
              <span className="pr-conn-meta">
                {ago(row.at, lang)}
                {row.devices > 0 &&
                  ` · ${t("profile.push_history_reached", {
                    took: row.took,
                    devices: row.devices,
                  })}`}
              </span>
            </div>
            {row.url.startsWith("/") && (
              <Link
                page={row.url.slice(1).split("?")[0] ?? ""}
                params={Object.fromEntries(
                  new URLSearchParams(row.url.split("?")[1] ?? ""),
                )}
                className="pr-btn"
              >
                {t("profile.push_history_open")}
              </Link>
            )}
          </li>
        ))}
      </ul>
      {rows.length > shown.length && (
        <div className="pr-cardbody">
          <button type="button" className="pr-btn" onClick={() => setAll(true)}>
            {t("profile.push_history_more", { n: rows.length - shown.length })}
          </button>
        </div>
      )}
    </Card>
  );
}
