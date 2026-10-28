/**
 * The paths, side by side: what each covers, how far in the reader is, and
 * the one lesson to open next.
 *
 * Only the first path with something left unread gets the filled button — a
 * screen offers one main action — and a path read to the end offers its first
 * lesson again, to review.
 */

import { Icon } from "../../shell/Icon";
import { useT } from "../../shell/i18n";
import { Link } from "../../shell/router";
import { pathKey, standing } from "./logic";
import type { Curriculum } from "./types";

export default function Paths({
  curriculum,
  done,
}: {
  curriculum: Curriculum;
  done: ReadonlySet<string>;
}) {
  const t = useT();
  const standings = curriculum.paths.map((path) => standing(path, done));
  const lead = standings.findIndex((s) => s.next !== null && s.read > 0);
  const main = lead >= 0 ? lead : standings.findIndex((s) => s.next !== null);
  return (
    <div className="lr-paths">
      {curriculum.paths.map((path, at) => {
        const s = standings[at]!;
        const key = pathKey(path.id);
        const open = s.next ?? path.lessons[0]?.id;
        const cta =
          s.next === null ? "learn.review" : s.read ? "learn.continue" : "learn.start";
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
            </div>
            <p className="lr-path-body">{t(`learn.path_${key}_body`)}</p>
            <div
              className="lr-prog"
              role="progressbar"
              aria-label={t("learn.progress", { done: s.read, total: s.total })}
              aria-valuemin={0}
              aria-valuemax={s.total}
              aria-valuenow={s.read}
            >
              <div className="lr-prog-track">
                <div
                  className="lr-prog-fill"
                  style={{ transform: `scaleX(${s.total ? s.read / s.total : 0})` }}
                />
              </div>
              <span className="lr-prog-n">
                {t("learn.progress", { done: s.read, total: s.total })}
              </span>
            </div>
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
              <Link
                className={at === main ? "ag-btn ag-btn-cta lr-go" : "ag-btn lr-go"}
                page="learn"
                params={{ lesson: open }}
              >
                {t(cta)}
              </Link>
            )}
          </section>
        );
      })}
    </div>
  );
}
