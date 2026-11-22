/**
 * One lesson: the text, where the idea shows up in the app, the terms it
 * leans on, and the way on to the next one.
 *
 * The body is the chat's own markdown renderer, so a lesson and an answer
 * read alike; its classes are styled by `chat/chat.css`, which the shell
 * already carries for the drawer. Only the reading width is set here.
 */

import { useState } from "react";
import { calendarDay } from "../../shell/dates";

import { ApiError, get } from "../../shell/api";
import { askAssistant } from "../../shell/assistant";
import { Icon } from "../../shell/Icon";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useT } from "../../shell/i18n";
import { canonical, pageFor } from "../../shell/pages";
import { Link } from "../../shell/router";
import { useApi } from "../../shell/useApi";
import { Markdown } from "../../chat/markdown";
import { SidePanel } from "../../ui/SidePanel";
import { appTarget, pathKey, type Place } from "./logic";
import type { Progress } from "./useProgress";
import type { Lesson, LessonRef, Quiz as QuizData, TermRef } from "./types";

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

/** One question with its answer explained. Pressing an option settles it: the
    right one is marked whatever was pressed, and the why appears below. */
export function Quiz({ quiz }: { quiz: QuizData }) {
  const t = useT();
  const [pick, setPick] = useState<number | null>(null);
  const right = pick === quiz.answer;
  return (
    <section className="lr-quiz" aria-labelledby="lr-quiz-h">
      <h2 className="lr-h2" id="lr-quiz-h">
        {t("learn.quiz_title")}
      </h2>
      <p className="lr-quiz-q">{quiz.question}</p>
      <div className="lr-opts">
        {quiz.options.map((option, at) => {
          const state =
            pick === null
              ? ""
              : at === quiz.answer
                ? " lr-opt-ok"
                : at === pick
                  ? " lr-opt-ko"
                  : "";
          return (
            <button
              key={option}
              type="button"
              className={`lr-opt${state}`}
              aria-pressed={pick === at}
              disabled={pick !== null}
              onClick={() => setPick(at)}
            >
              {option}
            </button>
          );
        })}
      </div>
      <div role="status" aria-live="polite">
        {pick !== null && (
          <p className={right ? "lr-fb lr-fb-ok" : "lr-fb lr-fb-ko"}>
            <b>
              {right
                ? t("learn.quiz_right")
                : t("learn.quiz_wrong", { answer: quiz.options[quiz.answer] ?? "" })}
            </b>{" "}
            {quiz.why}
          </p>
        )}
      </div>
    </section>
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
  const [term, setTerm] = useState<TermRef | null>(null);
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
        <button
          type="button"
          className="ag-btn lr-ask"
          onClick={() =>
            askAssistant(t("learn.ask_lesson", { title: lesson.title }), {
              topic: `lesson:${lesson.id}`,
            })
          }
        >
          <Icon name="auto_awesome" size={16} />
          {t("learn.ask")}
        </button>
      </div>
      {lesson.quiz && <Quiz key={lesson.id} quiz={lesson.quiz} />}
      {lesson.terms.length > 0 && (
        <section className="lr-terms" aria-labelledby="lr-terms-h">
          <h2 className="lr-h2" id="lr-terms-h">
            {t("learn.terms")}
          </h2>
          <ul className="lr-chips">
            {lesson.terms.map((entry) => (
              <li key={entry.id}>
                <button
                  type="button"
                  className="lr-chip"
                  aria-haspopup="dialog"
                  onClick={() => setTerm(entry)}
                >
                  {entry.label}
                </button>
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
        {t("learn.as_of", { date: calendarDay(lesson.as_of) })}
        {lesson.path === TAX_PATH && <> · {t("learn.disclaimer")}</>}
      </p>
      {term && (
        <SidePanel label={term.label} onClose={() => setTerm(null)}>
          <div className="lr-define">
            <p className="lr-define-desc">{term.desc}</p>
            <Link
              className="lr-term-lesson"
              page="learn"
              params={{ tab: "glossary", term: term.id }}
            >
              {t("learn.term_open")}
            </Link>
          </div>
        </SidePanel>
      )}
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
            <LessonBody
              key={lesson.id}
              lesson={lesson}
              progress={progress}
              place={place}
            />
          ) : (
            <Missing />
          )
        }
      </Loaded>
    </>
  );
}
