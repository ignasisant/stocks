/**
 * The rail's repairs card: what a statement cannot carry, fixed beside it.
 *
 * Both repairs propose and neither writes until the reader names what they
 * believe — every proposal arrives ticked, and a press is still required. The
 * badge counts what is waiting, so a book that is reporting a gain nobody made
 * says so before another statement is poured on top of it.
 */

import { useState } from "react";
import { useT } from "../../shell/i18n";
import type { Move } from "./api";
import { Eyebrow } from "./Card";
import { MoveList } from "./Moves";
import { Splits } from "./Splits";
import { useVocabulary } from "./text";

export function Repairs({
  moves,
  onApplied,
  onStale,
}: {
  moves: Move[];
  onApplied: () => void;
  onStale: () => void;
}) {
  const t = useT();
  const vocab = useVocabulary();
  const [gaps, setGaps] = useState(0);
  const waiting = moves.length + gaps;

  return (
    <section
      aria-labelledby="im-repairs-title"
      className="im-card im-repairs"
      id="im-repairs"
    >
      <div className="im-card-top">
        <Eyebrow id="im-repairs-title">{t("import.repairs")}</Eyebrow>
        {waiting > 0 && (
          <span className="im-badge">
            {t("import.repairs_pending", { n: vocab.num(waiting, 0) })}
          </span>
        )}
      </div>
      <MoveList moves={moves} onApplied={onApplied} onStale={onStale} />
      {moves.length > 0 && <hr className="im-rule" />}
      <Splits onApplied={onApplied} onFound={setGaps} />
    </section>
  );
}
