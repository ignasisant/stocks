/**
 * Which card may move the walkthrough.
 *
 * The rule the Streamlit guide is built on, and the one that is easy to lose
 * in a port: only the card for the step the account is *on* carries Next and
 * Skip. An older card keeps only its way there — pressing Next five turns up
 * would walk the guide backwards and the reader would never see why.
 *
 * Rendered to static markup with a window stubbed in: the router reads the
 * location on render, and that is all this needs from a browser.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { GuideCard } from "./GuideCard";
import { Turn } from "./Turn";
import { unshortcode, type GuideState, type GuideStep } from "./guide";

const step = (id: string, over: Partial<GuideStep> = {}): GuideStep => ({
  id,
  icon: "upload_file",
  path: "import_transactions",
  params: {},
  session: {},
  gated: false,
  done: null,
  title_key: `tour.${id}_title`,
  body_key: `tour.${id}_body`,
  cta_key: null,
  ...over,
});

const steps = [
  step("welcome", { path: "" }),
  step("import", { done: false }),
  step("last"),
];

const state = (on: string): GuideState => ({
  surface: "chat",
  active: true,
  finished: false,
  step: steps.find((s) => s.id === on) ?? null,
  steps,
  index: steps.findIndex((s) => s.id === on) + 1,
  of: steps.length,
  thread: "g1",
  auto_open: false,
  changed: false,
});

const draw = (card: GuideStep, guide: GuideState) =>
  renderToStaticMarkup(
    <GuideCard
      step={card}
      guide={guide}
      onNext={async () => guide}
      onSkip={() => {}}
      onLeave={() => {}}
    />,
  );

beforeEach(() => {
  vi.stubGlobal("window", {
    location: { pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: () => {},
    removeEventListener: () => {},
  });
});
afterEach(() => vi.unstubAllGlobals());

describe("the walkthrough's cards", () => {
  it("lets the card the account is on move the guide", () => {
    const out = draw(steps[1]!, state("import"));
    expect(out).toContain("guide.done_it"); // a step with something to switch on
    expect(out).toContain("guide.skip");
    expect(out).toContain("guide.progress");
    expect(out).toContain("tour.pending");
  });

  it("leaves an older card only its way there", () => {
    const out = draw(steps[0]!, state("import"));
    expect(out).toContain("guide.goto");
    expect(out).not.toContain("guide.next");
    expect(out).not.toContain("guide.skip");
  });

  it("finishes from the last step, and offers no skip past it", () => {
    const out = draw(steps[2]!, state("last"));
    expect(out).toContain("guide.finish");
    expect(out).not.toContain("guide.skip");
  });

  it("drops Streamlit's icon shortcodes from the stored copy", () => {
    expect(unshortcode(":material/check_circle: **Import** is set up.")).toBe(
      "**Import** is set up.",
    );
  });
});

/**
 * An answer on the walkthrough's thread that earned a jump.
 *
 * The server withholds the model's `[[goto:<step>]]` and files the validated
 * step as `guide_goto`; the turn draws it as the step's "take me there" and
 * never as text. A step the registry does not know draws nothing.
 */
describe("an answer's jump", () => {
  const answer = (goto: string | null) =>
    renderToStaticMarkup(
      <Turn
        turn={{
          role: "assistant",
          content: "Upload it on the import page.",
          skills: [],
          web: [],
          action: null,
          guide_goto: goto,
        }}
        skills={[]}
        providers={[]}
        cap={null}
        onRetry={() => {}}
        walk={{
          state: state("import"),
          onNext: async () => state("import"),
          onSkip: () => {},
          onLeave: () => {},
        }}
      />,
    );

  it("is a button to the step the answer named", () => {
    const out = answer("import");
    expect(out).toContain("guide.goto");
    expect(out).not.toContain("[[");
  });

  it("is nothing at all for a step that does not exist", () => {
    expect(answer("settings")).not.toContain("guide.goto");
    expect(answer(null)).not.toContain("guide.goto");
  });
});
