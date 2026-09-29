/**
 * The three tiers, which are the safety property and not a presentation choice.
 *
 * `importable` is exactly what a commit writes. `rejected` failed validation
 * and is never committed — quarantined, and the reader has to fix it in the
 * export or add it by hand. `skipped` is what the parser leaves out by design:
 * cash movements, fees, tax corrections.
 *
 * All three are shown in full. A client that reported only counts would have
 * hidden the part a reader has to act on, which is the whole reason a bad
 * export cannot corrupt a cost basis here quietly.
 *
 * Warned rows appear twice on purpose, exactly as the Streamlit page shows
 * them: once among the rows that will be written, and again with their warning
 * spelled out, because a warning nobody reads is a warning that did not happen.
 *
 * The order is the reader's, not the pipeline's: the summary and a chip per
 * tier that jumps to it, the commit (`children`) pinned under them, then what
 * needs acting on — rejected and warned, each in its own tint — and only then
 * the full list. A button or a rejection at the foot of hundreds of rows is
 * one nobody scrolls to.
 */

import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useT } from "../../shell/i18n";
import type { Preview } from "./api";
import { Eyebrow, jump } from "./Card";
import { Glyph } from "./Glyph";
import type { GlyphName } from "./Glyph";
import { RowTable, SkippedTable } from "./Tables";
import { useVocabulary } from "./text";

/** How a rejected row gets in anyway. The CLI's own words, so not translated. */
const CLI = "uv run stocks tx add <date> <ticker> <action> --qty … --price …";

type Tone = "bad" | "warn" | "ok" | "skip";

const GLYPH: Record<Tone, GlyphName> = {
  bad: "bad",
  warn: "warn",
  ok: "ok",
  skip: "down",
};

export function Tiers({
  preview,
  children,
}: {
  preview: Preview;
  children?: ReactNode;
}) {
  const t = useT();
  const vocab = useVocabulary();
  // The skipped rows sit folded, so the chip that jumps to them opens them too.
  const [skippedOpen, setSkippedOpen] = useState(false);
  const warned = preview.importable.filter((row) =>
    row.issues.some((issue) => issue.severity === "warning"),
  );
  const rejected = preview.rejected.length;
  const skipped = preview.skipped.length;

  const all: { id: string; tone: Tone; label: string; n: number }[] = [
    { id: "im-rejected", tone: "bad", label: t("import.tier_rejected"), n: rejected },
    { id: "im-warned", tone: "warn", label: t("import.tier_warned"), n: warned.length },
    {
      id: "im-importable",
      tone: "ok",
      label: t("import.tier_importable"),
      n: preview.importable.length,
    },
    { id: "im-skipped", tone: "skip", label: t("import.tier_skipped"), n: skipped },
  ];
  const tiers = all.filter((tier) => tier.n > 0);

  const go = (id: string) => {
    if (id === "im-skipped") setSkippedOpen(true);
    jump(id);
  };

  return (
    <section aria-labelledby="im-review-title" className="im-card im-review">
      <header className="im-review-head">
        <h2 className="im-review-title" id="im-review-title">
          <Eyebrow n={3}>{t("import.review")}</Eyebrow>
          <span className="im-review-sum">
            {vocab.tn("import.sum_importable", preview.importable.length)}
            {warned.length > 0 && (
              <>
                {" "}
                <span className="im-tone-warn">
                  {vocab.tn("import.sum_warned", warned.length)}
                </span>
              </>
            )}
            {", "}
            <span className={rejected > 0 ? "im-tone-bad" : undefined}>
              {vocab.tn("import.sum_rejected", rejected)}
            </span>
            {", "}
            {vocab.tn("import.sum_skipped", skipped)}
          </span>
        </h2>
        {tiers.length > 1 && (
          <nav aria-label={t("import.tiers_label")} className="im-jumps">
            {tiers.map((tier) => (
              <button
                className={`im-jump im-jump-${tier.tone}`}
                key={tier.id}
                onClick={() => go(tier.id)}
                type="button"
              >
                <span aria-hidden="true" className="im-dot" />
                {tier.label}
                <span className="im-mono">{vocab.num(tier.n, 0)}</span>
              </button>
            ))}
          </nav>
        )}
      </header>

      {children}

      <div className="im-tiers">
        {rejected > 0 && (
          <Tier
            id="im-rejected"
            note={t("import.tier_rejected_note")}
            title={`${t("import.tier_rejected")} · ${vocab.num(rejected, 0)}`}
            tone="bad"
          >
            {/* No links: a rejected symbol is malformed by definition. */}
            <RowTable
              brief
              issues="errors"
              link={false}
              rows={preview.rejected}
              tone="bad"
            />
            <div className="im-tier-foot">
              <span>{t("import.rejected_fix")}</span>
              <code className="im-cli">{CLI}</code>
              <Copy text={CLI} />
            </div>
          </Tier>
        )}

        {warned.length > 0 && (
          <Tier
            id="im-warned"
            note={t("import.tier_warned_note")}
            title={`${t("import.tier_warned")} · ${vocab.num(warned.length, 0)}`}
            tone="warn"
          >
            <RowTable brief issues="warnings" rows={warned} tone="warn" />
          </Tier>
        )}

        {preview.importable.length > 0 ? (
          <Tier
            id="im-importable"
            note={t("import.tier_importable_note")}
            title={`${t("import.tier_importable")} · ${vocab.num(preview.importable.length, 0)}`}
            tone="ok"
          >
            <RowTable rows={preview.importable} tall />
          </Tier>
        ) : (
          <p className="im-line-warn">{t("import.no_importable")}</p>
        )}

        {skipped > 0 && (
          <details
            className="im-skipped"
            id="im-skipped"
            onToggle={(event) => setSkippedOpen(event.currentTarget.open)}
            open={skippedOpen}
          >
            <summary>
              <Glyph name={GLYPH.skip} />
              <span className="im-h3">
                {t("import.tier_skipped")} · {vocab.num(skipped, 0)}
              </span>
              <span className="im-fine">{t("import.tier_skipped_note")}</span>
            </summary>
            <div className="im-skipped-body">
              <SkippedTable rows={preview.skipped} />
              <p className="im-fine">
                {t(
                  preview.platform === "revolut"
                    ? "import.skipped_caption_revolut"
                    : "import.skipped_caption_generic",
                )}
              </p>
            </div>
          </details>
        )}
      </div>
    </section>
  );
}

function Tier({
  id,
  tone,
  title,
  note,
  children,
}: {
  id: string;
  tone: Tone;
  title: string;
  note: string;
  children: ReactNode;
}) {
  return (
    <section
      aria-labelledby={`${id}-title`}
      className={`im-tier im-tier-${tone}`}
      id={id}
    >
      <header className="im-tier-head">
        <Glyph name={GLYPH[tone]} />
        <h3 className="im-h3" id={`${id}-title`}>
          {title}
        </h3>
        <span className="im-fine">{note}</span>
      </header>
      {children}
    </section>
  );
}

/** The command onto the clipboard, and two seconds of saying so. */
function Copy({ text }: { text: string }) {
  const t = useT();
  const [done, setDone] = useState(false);
  useEffect(() => {
    if (!done) return;
    const timer = setTimeout(() => setDone(false), 2000);
    return () => clearTimeout(timer);
  }, [done]);
  return (
    <button
      className="im-btn im-btn-text"
      // No clipboard outside a secure context; the command is on screen to
      // select by hand, so the press simply does nothing there.
      onClick={() =>
        void navigator.clipboard?.writeText(text).then(
          () => setDone(true),
          () => undefined,
        )
      }
      type="button"
    >
      {done ? t("import.copied") : t("import.copy")}
    </button>
  );
}
