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
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { matching, shownAliases } from "./logic";
import type { Glossary as GlossaryData, Term } from "./types";

const anchor = (id: string) => `lr-term-${id}`;

export function TermList({
  terms,
  focus,
}: {
  terms: readonly Term[];
  focus: string | null;
}) {
  const t = useT();
  const [query, setQuery] = useState("");
  const shown = useMemo(() => matching(terms, query), [terms, query]);
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
      <div className="lr-none">
        <p className="lr-count" aria-live="polite">
          {shown.length
            ? t("learn.term_count", { n: shown.length })
            : t("learn.no_match", { q: query.trim() })}
        </p>
        {shown.length === 0 && (
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
                {term.label}
                {aka.length > 0 && (
                  <span className="lr-term-aka"> · {aka.join(" · ")}</span>
                )}
              </dt>
              <dd className="lr-term-desc">
                {term.desc}
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
}: {
  lang: string;
  focus: string | null;
}) {
  const query = useApi(() => get<GlossaryData>("/learn/glossary", { lang }), [lang]);
  return (
    <Loaded query={query} skeleton={<Skeleton rows={10} />}>
      {(data) => <TermList terms={data.terms} focus={focus} />}
    </Loaded>
  );
}
