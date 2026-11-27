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

/** One thing to try in the app: a sentence (bold tickers become links) and the
    shell slug of the screen where it is done. */
export type Step = { text: string; app: string };

/** A real name whose figures the lesson shows as they are now. */
export type Live = { ticker: string; facts: string[]; why: string };

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
  steps?: Step[];
  live?: Live | null;
};

export type Term = {
  id: string;
  label: string;
  aliases: string[];
  desc: string;
  lesson: LessonRef | null;
};

export type Glossary = { terms: Term[] };

/** The few figures of the Ticker page's quote and metrics a live card reads. */
export type LiveQuote = { price: number | null; currency: string | null };
export type LiveMetrics = {
  kpis: { key: string; value: number | null; formatted: string }[];
};
