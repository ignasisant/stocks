/** The Learn page's wire shapes: `src/stocks/api/routes/learn.py`. */

export type LessonRef = { id: string; title: string; minutes: number };

export type LearnPath = {
  id: string;
  icon: string;
  /** The oldest review date among the path's lessons; "" from an older server. */
  as_of?: string;
  lessons: LessonRef[];
};

export type Curriculum = { paths: LearnPath[]; done: string[]; terms: number };

export type TermRef = { id: string; label: string; desc: string };

/** One question to check a lesson landed; `answer` indexes `options`. */
export type Quiz = {
  question: string;
  options: string[];
  answer: number;
  why: string;
};

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
  quiz?: Quiz | null;
};

export type Term = {
  id: string;
  label: string;
  aliases: string[];
  desc: string;
  lesson: LessonRef | null;
};

export type Glossary = { terms: Term[] };
