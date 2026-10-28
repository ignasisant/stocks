/**
 * One lesson: the text, where the idea shows up in the app, the terms it
 * leans on, and the way on to the next one.
 *
 * The body is the chat's own markdown renderer, so a lesson and an answer
 * read alike; its classes are styled by `chat/chat.css`, which the shell
 * already carries for the drawer. Only the reading width is set here.
 */

import { ApiError, get } from "../../shell/api";
import { Icon } from "../../shell/Icon";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { canonical, pageFor } from "../../shell/pages";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Markdown } from "../../chat/markdown";
import { appTarget, pathKey, type Place } from "./logic";
import type { Progress } from "./useProgress";
import type { Lesson, LessonRef } from "./types";

/** The path whose lessons are about Spanish tax law, which changes yearly. */
const TAX_PATH = "tax-es";

function Step({ to, dir }: { to: LessonRef | null; dir: "prev" | "next" }) {
  const t = useT();
  if (!to) return <span />;
  return (
    <Link className={`lr-step lr-step-${dir}`} page="learn" params={{ lesson: to.id }}>
      <span className="lr-step-dir">
        {dir === "prev" && <Icon name="arrow_back" size={16} />}
        {t(dir === "prev" ? "learn.prev" : "learn.next")}
        {dir === "next" && <Icon name="arrow_forward" size={16} />}
      </span>
      <span className="lr-step-title">{to.title}</span>
    </Link>
  );
}

export function LessonBody({
  lesson,
  progress,
  place = null,
}: {
  lesson: Lesson;
  progress: Progress;
  place?: Place | null;
}) {
  const t = useT();
  const read = progress.done ? progress.done.has(lesson.id) : lesson.done;
  const target = appTarget(lesson.app);
  const where = target ? pageFor(canonical(target.page)) : null;
  return (
    <article className="lr-lesson" aria-labelledby="lr-lesson-title">
      <p className="lr-eyebrow">
        {t(`learn.path_${pathKey(lesson.path)}_title`)} ·{" "}
        {place && <>{t("learn.lesson_of", place)} · </>}
        {t("learn.minutes", { n: lesson.minutes })}
      </p>
      <h1 className="lr-title" id="lr-lesson-title">
        {lesson.title}
      </h1>
      <div className="lr-body">
        <Markdown text={lesson.body} />
      </div>
      <div className="lr-acts">
        <button
          type="button"
          className={read ? "ag-btn lr-mark lr-mark-on" : "ag-btn ag-btn-cta lr-mark"}
          aria-pressed={read}
          onClick={() => progress.mark(lesson.id, !read)}
        >
          {read && <Icon name="check" size={16} />}
          {t(read ? "learn.read_mark" : "learn.mark_read")}
        </button>
        {target && where && (
          <Link className="ag-btn lr-app" page={where.slug} params={target.params}>
            {t("learn.in_app")} · {t(where.label)}
          </Link>
        )}
      </div>
      {lesson.terms.length > 0 && (
        <section className="lr-terms" aria-labelledby="lr-terms-h">
          <h2 className="lr-h2" id="lr-terms-h">
            {t("learn.terms")}
          </h2>
          <ul className="lr-chips">
            {lesson.terms.map((term) => (
              <li key={term.id}>
                <Link
                  className="lr-chip"
                  page="learn"
                  params={{ tab: "glossary", term: term.id }}
                  title={term.desc}
                >
                  {term.label}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      <nav className="lr-steps" aria-label={t("learn.title")}>
        <Step to={lesson.before} dir="prev" />
        <Step to={lesson.after} dir="next" />
      </nav>
      <p className="lr-foot">
        {t("learn.as_of", { date: lesson.as_of })}
        {lesson.path === TAX_PATH && <> · {t("learn.disclaimer")}</>}
      </p>
    </article>
  );
}

function Missing() {
  const t = useT();
  return (
    <div className="lr-empty">
      <p>{t("learn.not_found")}</p>
      <Link className="ag-btn" page="learn">
        {t("learn.back")}
      </Link>
    </div>
  );
}

export default function LessonPage({
  id,
  lang,
  progress,
  place = null,
}: {
  id: string;
  lang: string;
  progress: Progress;
  place?: Place | null;
}) {
  const t = useT();
  // A retired lesson's bookmark is a 404, answered as an empty page with the
  // way back — not as the error card a failed load gets.
  const query = useApi(
    () =>
      get<Lesson>(`/learn/lessons/${encodeURIComponent(id)}`, { lang }).catch(
        (error: unknown) => {
          if (error instanceof ApiError && error.status === 404) return null;
          throw error;
        },
      ),
    [id, lang],
  );
  return (
    <>
      <Link className="lr-back" page="learn">
        <Icon name="arrow_back" size={16} />
        {t("learn.back")}
      </Link>
      <Loaded query={query} skeleton={<Skeleton rows={10} />}>
        {(lesson) =>
          lesson ? (
            <LessonBody lesson={lesson} progress={progress} place={place} />
          ) : (
            <Missing />
          )
        }
      </Loaded>
    </>
  );
}
