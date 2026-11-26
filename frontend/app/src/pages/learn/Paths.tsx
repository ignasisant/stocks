/**
 * The paths, side by side: what each covers, how far in the reader is, and
 * the one lesson to open next.
 *
 * Above them, the one lesson to open next with the total progress: the
 * screen's single filled button. A path read to the end offers its first
 * lesson again, to review.
 */

import { get } from "../../shell/api";
import { calendarDay } from "../../shell/dates";
import { Icon } from "../../shell/Icon";
import { useLang, useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { nextUp, pathKey, standing, termOfDay } from "./logic";
import type { NextUp } from "./logic";
import type { Curriculum, Glossary } from "./types";

/** The path about Spanish tax law: its review date is shown beside it. */
const TAX_PATH = "tax-es";

function Bar({ read, total, label }: { read: number; total: number; label: string }) {
  return (
    <div
      className="lr-prog"
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={read}
    >
      <div className="lr-prog-track">
        <div
          className="lr-prog-fill"
          style={{ transform: `scaleX(${total ? read / total : 0})` }}
        />
      </div>
      <span className="lr-prog-n">{label}</span>
    </div>
  );
}

/** Where to pick up, and how far the whole curriculum has come. */
function Hero({ up }: { up: NextUp }) {
  const t = useT();
  const fresh = up.read === 0;
  return (
    <section className="lr-hero" aria-labelledby="lr-hero-h">
      <div className="lr-hero-main">
        <p className="lr-eyebrow">
          {t(fresh ? "learn.hero_start" : "learn.hero_resume")}
        </p>
        <h2 className="lr-hero-title" id="lr-hero-h">
          {up.lesson.title}
        </h2>
        <p className="lr-path-meta">
          {t(`learn.path_${pathKey(up.path.id)}_title`)} ·{" "}
          {t("learn.lesson_of", { at: up.at, total: up.total })} ·{" "}
          {t("learn.minutes", { n: up.lesson.minutes })}
        </p>
        <Link
          className="ag-btn ag-btn-cta lr-go"
          page="learn"
          params={{ lesson: up.lesson.id }}
        >
          {t(fresh ? "learn.start" : "learn.continue")}
          <Icon name="arrow_forward" size={16} />
        </Link>
      </div>
      <div className="lr-hero-side">
        <Bar
          read={up.read}
          total={up.all}
          label={t("learn.progress", { done: up.read, total: up.all })}
        />
        <p className="lr-path-meta">
          {t(fresh ? "learn.hero_total" : "learn.hero_left", {
            n: fresh ? up.minutesAll : up.minutesLeft,
          })}
        </p>
      </div>
    </section>
  );
}

/** One concept a day, with the lesson that teaches it. Quiet when the glossary
    cannot be had: the paths below do not wait for it. */
function TermOfDay() {
  const t = useT();
  const lang = useLang();
  const glossary = useApi(() => get<Glossary>("/learn/glossary", { lang }), [lang]);
  if (glossary.state !== "loaded") return null;
  const term = termOfDay(glossary.data.terms, new Date());
  if (!term?.lesson) return null;
  return (
    <section className="lr-day" aria-labelledby="lr-day-h">
      <p className="lr-eyebrow" id="lr-day-h">
        {t("learn.day_title")}
      </p>
      <h2 className="lr-day-term">{term.label}</h2>
      <p className="lr-day-desc">{term.desc}</p>
      <div className="lr-acts">
        <Link className="ag-btn" page="learn" params={{ lesson: term.lesson.id }}>
          {t("learn.day_lesson")}
        </Link>
        <Link
          className="ag-btn"
          page="learn"
          params={{ tab: "glossary", term: term.id }}
        >
          {t("learn.day_glossary")}
        </Link>
      </div>
    </section>
  );
}

export default function Paths({
  curriculum,
  done,
}: {
  curriculum: Curriculum;
  done: ReadonlySet<string>;
}) {
  const t = useT();
  const standings = curriculum.paths.map((path) => standing(path, done));
  const up = nextUp(curriculum, done);
  return (
    <>
      {up && <Hero up={up} />}
      <TermOfDay />
      <div className="lr-paths">
        {curriculum.paths.map((path, at) => {
          const s = standings[at]!;
          const key = pathKey(path.id);
          const open = s.next ?? path.lessons[0]?.id;
          const cta =
            s.next === null
              ? "learn.review"
              : s.read
                ? "learn.continue"
                : "learn.start";
          const minutes = path.lessons.reduce((sum, lesson) => sum + lesson.minutes, 0);
          return (
            <section
              className="lr-path"
              key={path.id}
              aria-labelledby={`lr-path-${path.id}`}
            >
              <div className="lr-path-head">
                <span className="lr-path-icon">
                  <Icon name={path.icon} size={22} />
                </span>
                <div>
                  <h2 className="lr-path-title" id={`lr-path-${path.id}`}>
                    {t(`learn.path_${key}_title`)}
                  </h2>
                  <p className="lr-path-meta">
                    {t("learn.lessons_count", { n: s.total })} ·{" "}
                    {t("learn.minutes", { n: minutes })}
                  </p>
                </div>
                {s.total > 0 && s.next === null && (
                  <span className="lr-path-done">{t("learn.path_done")}</span>
                )}
              </div>
              <p className="lr-path-body">{t(`learn.path_${key}_body`)}</p>
              {path.id === TAX_PATH && path.as_of && (
                <p className="lr-asof">
                  {t("learn.path_as_of", { date: calendarDay(path.as_of) })}
                </p>
              )}
              <Bar
                read={s.read}
                total={s.total}
                label={t("learn.progress", { done: s.read, total: s.total })}
              />
              <ol className="lr-list">
                {path.lessons.map((lesson) => {
                  const read = done.has(lesson.id);
                  return (
                    <li key={lesson.id}>
                      <Link
                        className={read ? "lr-item lr-item-read" : "lr-item"}
                        page="learn"
                        params={{ lesson: lesson.id }}
                      >
                        <span className={read ? "lr-dot lr-dot-done" : "lr-dot"}>
                          {read && <Icon name="check" size={14} />}
                        </span>
                        <span className="lr-item-title">{lesson.title}</span>
                        {read && <span className="ag-sr">{t("learn.read_mark")}</span>}
                        <span className="lr-item-min">
                          {t("learn.minutes", { n: lesson.minutes })}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ol>
              {open && (
                <Link className="ag-btn lr-go" page="learn" params={{ lesson: open }}>
                  {t(cta)}
                </Link>
              )}
            </section>
          );
        })}
      </div>
    </>
  );
}
