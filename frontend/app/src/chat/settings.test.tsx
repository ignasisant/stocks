/**
 * The settings screen shows the provider the account *chose*.
 *
 * That is the one rule on this screen that is easy to get backwards, and the
 * bug it produces is the worst kind: pick the provider whose key you are about
 * to type, and the tile un-presses itself because `answering` is still the
 * free chain — which is exactly the state this screen exists to get out of. So
 * the tile, the model list and the key section all read `preferred`, and this
 * asserts it against a state where the two disagree.
 *
 * Rendered to static markup: the question is what the screen draws from a
 * given state, and none of it needs a DOM or a fetch.
 */

import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Settings } from "./Settings";
import type { ChatState, ProviderInfo } from "./types";

const provider = (over: Partial<ProviderInfo>): ProviderInfo => ({
  id: "free",
  label: "Aguait AI",
  models: ["auto"],
  model: "auto",
  needs_key: false,
  has_key: false,
  console_url: "",
  key_placeholder: "",
  key_days_left: null,
  domain: null,
  ...over,
});

const state = (over: Partial<ChatState>): ChatState => ({
  providers: [
    provider({}),
    provider({
      id: "anthropic",
      label: "Anthropic",
      models: ["claude-opus-5", "claude-sonnet-5"],
      model: "claude-sonnet-5",
      needs_key: true,
      console_url: "https://console.anthropic.com/",
      key_placeholder: "sk-ant-…",
    }),
  ],
  answering: "free",
  preferred: "free",
  free_left: 12,
  free_cap: 30,
  cap_reason: null,
  skills: [],
  skills_mode: "auto",
  skills_selected: [],
  max_manual: 3,
  web: false,
  web_available: false,
  upload_types: ["csv"],
  upload_max_mb: 10,
  voice: false,
  ...over,
});

const draw = (next: ChatState) =>
  renderToStaticMarkup(
    <Settings
      state={next}
      busy={false}
      thread={{ id: "c1", title: "Bolsa", messages: 4 }}
      onBack={() => {}}
      onSave={() => {}}
      onState={() => {}}
      onDeleteThread={() => {}}
    />,
  );

describe("the settings view", () => {
  it("asks for the key of the provider that was picked, not the one answering", () => {
    // Anthropic chosen, no key yet — so the free chain still answers.
    const out = draw(state({ preferred: "anthropic", answering: "free" }));
    expect(out).toContain('aria-pressed="true"');
    expect(out).toContain("sk-ant-…");
    expect(out).toContain("https://console.anthropic.com/");
    // Its models, and no quota bar: that pot belongs to the keyless chain.
    expect(out).toContain("claude-opus-5");
    expect(out).not.toContain("<progress");
  });

  it("shows the keyless chain its allowance and no key form", () => {
    const out = draw(state({}));
    expect(out).toContain("<progress");
    expect(out).toContain('value="12"');
    expect(out).toContain('max="30"');
    expect(out).not.toContain('type="password"');
  });

  it("offers to forget a key that is stored, rather than asking for it again", () => {
    const out = draw(
      state({
        preferred: "anthropic",
        providers: [
          provider({}),
          provider({
            id: "anthropic",
            label: "Anthropic",
            models: ["claude-opus-5"],
            model: "claude-opus-5",
            needs_key: true,
            has_key: true,
            key_days_left: 62,
          }),
        ],
      }),
    );
    expect(out).toContain("chat.key_stored");
    expect(out).toContain("chat.forget");
    expect(out).not.toContain('type="password"');
  });
});

/**
 * A key of your own, stored or held by this tab.
 *
 * The Streamlit panel's `_show_key` and "Remember" checkbox: a key in use is
 * shown masked (its tail only) with a reveal beside it, says whether it is
 * stored or this tab's, and a deployment that cannot store one offers the tab
 * and nothing else — before the reader types, not as a 503 after.
 */
describe("a key of your own", () => {
  const anthropic = (over: Partial<ProviderInfo>) =>
    provider({
      id: "anthropic",
      label: "Anthropic",
      models: ["claude-opus-5"],
      model: "claude-opus-5",
      needs_key: true,
      ...over,
    });

  it("is shown by its tail, with a reveal, and says it is stored", () => {
    const out = draw(
      state({
        preferred: "anthropic",
        providers: [
          provider({}),
          anthropic({ has_key: true, key_days_left: 30, key_tail: "9f3a" }),
        ],
      }),
    );
    expect(out).toContain("••••••••9f3a");
    expect(out).toContain("chat.key_show");
    expect(out).toContain("chat.key_stored");
  });

  it("says a key this tab holds is gone when the tab is", () => {
    const out = draw(
      state({
        preferred: "anthropic",
        providers: [
          provider({}),
          anthropic({ has_key: true, key_session: true, key_tail: "1234" }),
        ],
      }),
    );
    expect(out).toContain("chat.key_session_only");
    expect(out).not.toContain("chat.key_stored");
  });

  it("offers Remember where the server can keep a key", () => {
    const out = draw(
      state({
        preferred: "anthropic",
        key_storage: true,
        providers: [provider({}), anthropic({})],
      }),
    );
    expect(out).toContain("chat.remember");
    expect(out).toContain("chat.byok_help");
    expect(out).not.toContain("chat.byok_help_session");
  });

  it("offers only this tab where it cannot", () => {
    const out = draw(
      state({
        preferred: "anthropic",
        key_storage: false,
        providers: [provider({}), anthropic({})],
      }),
    );
    expect(out).not.toContain("chat.remember");
    expect(out).toContain("chat.byok_help_session");
    expect(out).toContain('type="password"');
  });
});
