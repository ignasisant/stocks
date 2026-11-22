/**
 * Every term, searchable as the reader types: by name, by another name it
 * goes by ("PER" finds P/E), then by its definition. Accents and case do not
 * matter, so "indice" finds "Índice".
 *
 * `?term=<id>` is where a lesson's chip lands: the list scrolls to that term
 * and marks it, and the search is left empty so the rest stays in reach.
 */

import { useEffect, useMemo, useRef, useState } from "react";

import { get } from "../../shell/api";
import { askAssistant } from "../../shell/assistant";
import { Icon } from "../../shell/Icon";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Segmented } from "../../ui/Segmented";
import { highlight, inPath, matching, pathKey, shownAliases } from "./logic";
import type { Glossary as GlossaryData, Term } from "./types";

/** `text` with what the search found drawn marked. */
function Marked({ text, query }: { text: string; query: string }) {
  return (
    <>
      {highlight(text, query).map((piece, at) =>
        piece.hit ? <mark key={at}>{piece.text}</mark> : piece.text,
      )}
    </>
  );
}

const anchor = (id: string) => `lr-term-${id}`;

export function TermList({
  terms,
  focus,
  pathIds = [],
  paths = {},
}: {
  terms: readonly Term[];
  focus: string | null;
  /** The curriculum's paths, in order: what the filter offers. */
  pathIds?: readonly string[];
  /** Lesson id → path id, to tell which path teaches a term. */
  paths?: Readonly<Record<string, string>>;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const [path, setPath] = useState<string | null>(null);
  const shown = useMemo(
    () => matching(inPath(terms, path, paths), query),
    [terms, query, path, paths],
  );
  const suggestions = t("learn.try_terms").split("|").filter(Boolean);
  const q = query.trim();
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (focus)
      document.getElementById(anchor(focus))?.scrollIntoView({ block: "center" });
  }, [focus]);

  return (
    <div className="lr-gloss">
      <input
        ref={search}
        className="lr-search"
        type="search"
        value={query}
        placeholder={t("learn.search_placeholder")}
        aria-label={t("learn.search_label")}
        autoComplete="off"
        autoCorrect="off"
        enterKeyHint="search"
        spellCheck={false}
        onChange={(event) => setQuery(event.target.value)}
      />
      {pathIds.length > 0 && (
        <Segmented<string>
          className="lr-filter"
          label={t("learn.filter_label")}
          value={path ?? "all"}
          onPick={(next) => setPath(next === "all" ? null : next)}
          items={[
            { id: "all", label: t("learn.filter_all") },
            ...pathIds.map((id) => ({
              id,
              label: t(`learn.path_${pathKey(id)}_title`),
            })),
          ]}
        />
      )}
      <p className="lr-count" aria-live="polite">
        {shown.length
          ? t("learn.term_count", { n: shown.length })
          : t("learn.no_match", { q })}
      </p>
      {shown.length === 0 && (
        <div className="lr-none">
          <p className="lr-none-h">{t("learn.try")}</p>
          <div className="lr-chips">
            {suggestions.map((word) => (
              <button
                key={word}
                type="button"
                className="lr-chip"
                onClick={() => {
                  setQuery(word);
                  search.current?.focus();
                }}
              >
                {word}
              </button>
            ))}
          </div>
          <div className="lr-none-acts">
            {path && (
              <button type="button" className="ag-btn" onClick={() => setPath(null)}>
                {t("learn.search_all")}
              </button>
            )}
            {q && (
              <button
                type="button"
                className="ag-btn"
                onClick={() =>
                  askAssistant(t("learn.ask_term", { q }), {
                    topic: `term:${q.trim().toLowerCase()}`,
                  })
                }
              >
                <Icon name="auto_awesome" size={16} />
                {t("learn.ask")}
              </button>
            )}
            {query && (
              <button
                type="button"
                className="ag-btn"
                onClick={() => {
                  setQuery("");
                  search.current?.focus();
                }}
              >
                {t("learn.clear")}
              </button>
            )}
          </div>
        </div>
      )}
      <dl className="lr-terms-list">
        {shown.map((term) => {
          const aka = shownAliases(term);
          return (
            <div
              className={term.id === focus ? "lr-term lr-term-on" : "lr-term"}
              id={anchor(term.id)}
              key={term.id}
            >
              <dt className="lr-term-label">
                <Marked text={term.label} query={query} />
                {aka.length > 0 && (
                  <span className="lr-term-aka">
                    {" · "}
                    {aka.map((a, at) => (
                      <span key={a}>
                        {at > 0 && " · "}
                        <Marked text={a} query={query} />
                      </span>
                    ))}
                  </span>
                )}
              </dt>
              <dd className="lr-term-desc">
                <Marked text={term.desc} query={query} />
                {term.lesson && (
                  <Link
                    className="lr-term-lesson"
                    page="learn"
                    params={{ lesson: term.lesson.id }}
                  >
                    {t("learn.term_lesson", { title: term.lesson.title })}
                  </Link>
                )}
              </dd>
            </div>
          );
        })}
      </dl>
    </div>
  );
}

export default function Glossary({
  lang,
  focus,
  pathIds,
  paths,
}: {
  lang: string;
  focus: string | null;
  pathIds?: readonly string[];
  paths?: Readonly<Record<string, string>>;
}) {
  const query = useApi(() => get<GlossaryData>("/learn/glossary", { lang }), [lang]);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={10} />}>
      {(data) => (
        <TermList terms={data.terms} focus={focus} pathIds={pathIds} paths={paths} />
      )}
    </Loaded>
  );
}
