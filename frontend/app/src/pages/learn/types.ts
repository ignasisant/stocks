/** The Learn page's wire shapes: `src/stocks/api/routes/learn.py`. */

export type LessonRef = { id: string; title: string; minutes: number };

export type LearnPath = { id: string; icon: string; lessons: LessonRef[] };

export type Curriculum = { paths: LearnPath[]; done: string[]; terms: number };

type TermRef = { id: string; label: string; desc: string };

export type Lesson = {
  id: string;
  path: string;
  title: string;
  minutes: number;
  as_of: string;
  body: string;
  /** A shell slug, optionally with a query: `portfolio?tab=risk`. */
  app: string;
  terms: TermRef[];
  before: LessonRef | null;
  after: LessonRef | null;
  done: boolean;
};

export type Term = {
  id: string;
  label: string;
  aliases: string[];
  desc: string;
  lesson: LessonRef | null;
};

export type Glossary = { terms: Term[] };
