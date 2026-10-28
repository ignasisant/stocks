/**
 * Learn: investing taught from the start, in short lessons grouped into
 * paths, and a glossary of every term they use.
 *
 * The same for every reader — shipped files, not anyone's book (see
 * `src/stocks/learn.py`) — so it is open to a guest; only the ticks of what
 * has been read are the reader's own (`useProgress`). Two tabs, `?tab=paths`
 * and `?tab=glossary`; `?lesson=<id>` opens one lesson in their place, as a
 * real navigation, so the back button returns to the paths.
 */

import "./learn.css";
import { get } from "../../shell/api";
import { Loaded, Skeleton } from "../../shell/Layout";
import { useLang, useT } from "../../shell/i18n";
import { useRoute } from "../../shell/router";
import { useGuest } from "../../shell/session";
import { useApi } from "../../shell/useApi";
import { Tabs } from "../../ui/Tabs";
import Glossary from "./Glossary";
import LessonPage from "./Lesson";
import Paths from "./Paths";
import type { Curriculum } from "./types";
import { place } from "./logic";
import { useProgress } from "./useProgress";

type Tab = "paths" | "glossary";

export default function Page() {
  const t = useT();
  const lang = useLang();
  const guest = useGuest();
  const { params, setParams } = useRoute();
  const curriculum = useApi(() => get<Curriculum>("/learn", { lang }), [lang]);
  const progress = useProgress(
    curriculum.state === "loaded" ? curriculum.data.done : null,
    guest,
  );

  const lesson = (params.get("lesson") ?? "").trim();
  if (lesson) {
    const at = curriculum.state === "loaded" ? place(curriculum.data, lesson) : null;
    return <LessonPage id={lesson} lang={lang} progress={progress} place={at} />;
  }

  const tab: Tab = params.get("tab") === "glossary" ? "glossary" : "paths";
  return (
    <>
      <h1 className="lr-page-title">{t("learn.title")}</h1>
      <p className="lr-lead">{t("learn.lead")}</p>
      <Tabs<Tab>
        items={[
          { id: "paths", label: t("learn.tab_paths") },
          { id: "glossary", label: t("learn.tab_glossary") },
        ]}
        active={tab}
        onPick={(next) =>
          setParams({ tab: next === "paths" ? undefined : next, term: undefined })
        }
        label={t("learn.tabs_label")}
      />
      <div className="lr-panel" role="tabpanel">
        {tab === "glossary" ? (
          <Glossary lang={lang} focus={params.get("term")} />
        ) : (
          <Loaded query={curriculum} skeleton={<Skeleton rows={8} />}>
            {(data) => <Paths curriculum={data} done={progress.done ?? new Set()} />}
          </Loaded>
        )}
      </div>
    </>
  );
}
