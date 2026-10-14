/**
 * A line's analysis, opened under it: the comparison the line invites, made.
 *
 * Each line with a trigger behind it (`opens`) asks `POST /daily/analysis?key=`
 * on its first click — the company against its peers, its sector and the
 * index, the tax arithmetic of a sale, which positions explain a month behind
 * the index — and gets a verdict, a few points and the computed tables they
 * can be checked against. The server stores it with the card, and this page
 * keeps it per card and line, so collapsing and reopening never asks twice.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { send } from "../../shell/api";
import { Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { TickerCell } from "../home/ui";
import type { DailyAnalysis, DailyCard, DailyTable } from "../home/types";
import { tone } from "./card";

/** One line's analysis: absent while closed. */
export type Panel =
  { kind: "loading" } | { kind: "failed" } | { kind: "open"; body: DailyAnalysis };

function without(panels: Record<string, Panel>, key: string): Record<string, Panel> {
  const rest = { ...panels };
  delete rest[key];
  return rest;
}

/** Which card an analysis belongs to — a new card never shows the old one's. */
export function stampKey(
  card: Pick<DailyCard, "day" | "generated" | "lang"> | null,
): string {
  return card ? `${card.day}|${card.generated}|${card.lang}` : "";
}

/**
 * The open panels of one card, and the toggle that opens or shuts a line.
 * Lines open independently — each one is its own fetch and its own call.
 */
export function useAnalyses(stamp: string): {
  panels: Record<string, Panel>;
  toggle: (key: string) => void;
} {
  const [panels, setPanels] = useState<Record<string, Panel>>({});
  const analyses = useRef(new Map<string, DailyAnalysis>());
  useEffect(() => {
    setPanels({});
  }, [stamp]);
  const toggle = useCallback(
    (key: string) => {
      const now = panels[key];
      if (now && now.kind !== "failed") {
        setPanels((current) => without(current, key));
        return;
      }
      const cached = analyses.current.get(`${stamp}|${key}`);
      if (cached) {
        setPanels((current) => ({ ...current, [key]: { kind: "open", body: cached } }));
        return;
      }
      setPanels((current) => ({ ...current, [key]: { kind: "loading" } }));
      const asked = stamp;
      send<DailyAnalysis>(
        "POST",
        `/daily/analysis?${new URLSearchParams({ key }).toString()}`,
      ).then(
        (body) => {
          analyses.current.set(`${asked}|${key}`, body);
          // Only onto the wait it answers: a line collapsed meanwhile stays
          // shut, and a new card has already cleared the panels.
          setPanels((current) =>
            current[key]?.kind === "loading"
              ? { ...current, [key]: { kind: "open", body } }
              : current,
          );
        },
        () =>
          setPanels((current) =>
            current[key]?.kind === "loading"
              ? { ...current, [key]: { kind: "failed" } }
              : current,
          ),
      );
    },
    [panels, stamp],
  );
  return { panels, toggle };
}

/** One line's analysis, under it: the wait, the failure, or the verdict, the
 * points and the tables. */
export function AnalysisPanel({ id, panel }: { id: string; panel: Panel | undefined }) {
  const t = useT();
  if (!panel) return null;
  if (panel.kind === "loading") {
    return (
      <div className="td-an" id={id}>
        <p className="td-wait" role="status">
          {t("home.daily_an_loading")}
        </p>
        <Skeleton rows={3} />
      </div>
    );
  }
  if (panel.kind === "failed") {
    return (
      <p className="hm-note td-an-failed" id={id} role="status">
        {t("home.daily_an_failed")}
      </p>
    );
  }
  const { body } = panel;
  return (
    <div className="td-an" id={id}>
      {body.verdict ? (
        <p className="td-an-verdict">
          <b>{t("home.daily_an_verdict")}</b> {body.verdict}
        </p>
      ) : null}
      {body.points.length > 0 ? (
        <div className="td-an-points">
          {body.points.map((point, n) => (
            <section key={n} className="td-an-point">
              <h4 className="td-an-title">{point.title}</h4>
              <p>{point.text}</p>
            </section>
          ))}
        </div>
      ) : null}
      {body.tables.length > 0 ? (
        <div className="td-an-tables">
          {body.tables.map((table, n) => (
            <AnalysisTable key={n} table={table} />
          ))}
        </div>
      ) : null}
      {body.source === "computed" ? (
        <p className="hm-note">{t("home.daily_an_computed")}</p>
      ) : null}
    </div>
  );
}

/** A computed table under an analysis. Every symbol is a ticker cell — logo
 * and link — with the company's name beside it. */
function AnalysisTable({ table }: { table: DailyTable }) {
  return (
    <figure className="td-an-table">
      <figcaption className="td-an-caption">{table.title}</figcaption>
      <div className="td-an-scroll">
        <table className="hm-table">
          <thead>
            <tr>
              {table.columns.map((column, n) => (
                <th key={n} scope="col" className={n ? "hm-num" : undefined}>
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, n) => (
              <tr key={n} className={row.highlight ? "td-an-hl" : undefined}>
                <td className="td-an-name">
                  {row.ticker ? (
                    <span className="td-an-who">
                      <TickerCell ticker={row.ticker} name={false} />
                      {row.label ? (
                        <span className="td-an-label">{row.label}</span>
                      ) : null}
                    </span>
                  ) : (
                    row.label
                  )}
                </td>
                {row.cells.map((cell, m) => {
                  const sign = tone(cell);
                  return (
                    <td key={m} className={sign ? `hm-num td-${sign}` : "hm-num"}>
                      {cell}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note ? <p className="hm-note">{table.note}</p> : null}
    </figure>
  );
}
