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
  it("draws each provider's mark, and the app's own spark for the keyless chain", () => {
    const base = state({});
    const out = draw({
      ...base,
      providers: base.providers.map((p) =>
        p.id === "anthropic"
          ? { ...p, logo: "/app/static/logos/brand-ai-anthropic.png" }
          : p,
      ),
    });
    expect(out).toContain('src="/app/static/logos/brand-ai-anthropic.png"');
    // The initial under the logo, so a logo that fails leaves a letter.
    expect(out).toMatch(/ag-chat-mark"[^>]*>A<img/);
    expect(out).toMatch(/ag-chat-mark ag-chat-mark-own"[^>]*><svg/);
  });

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

  it("lets a provider of your own reach past its curated models", () => {
    const out = draw(state({ preferred: "anthropic" }));
    expect(out).toContain("chat.model_other");
    // A model saved from the catalogue is still the select's value.
    const custom = draw(
      state({
        preferred: "anthropic",
        providers: [
          provider({}),
          provider({
            id: "anthropic",
            label: "Anthropic",
            models: ["claude-opus-5", "claude-opus-4-1"],
            model: "claude-opus-4-1",
            needs_key: true,
          }),
        ],
      }),
    );
    expect(custom).toMatch(/<option value="claude-opus-4-1" selected="">/);
  });

  it("gives the keyless chain no model to pick", () => {
    const out = draw(state({}));
    expect(out).not.toContain("chat.model_other");
    expect(out).not.toContain("ag-chat-select");
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
 * A key in use is shown masked (its tail only) with a reveal beside it, says
 * whether it is stored or this tab's, and a deployment that cannot store one
 * offers the tab and nothing else — before the reader types, not as a 503
 * after.
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

/**
 * A provider that mints the key by sign-in (`connect.ts`): the sign-in is the
 * way in and the paste field the fallback, with one Remember box deciding
 * where the key goes either way.
 */
describe("a provider you sign in to", () => {
  const openrouter = (over: Partial<ProviderInfo>) =>
    provider({
      id: "openrouter",
      label: "OpenRouter",
      models: ["openrouter/auto"],
      model: "openrouter/auto",
      needs_key: true,
      key_placeholder: "sk-or-v1-...",
      connect_url: "https://openrouter.ai/auth",
      connect_token_url: "https://openrouter.ai/api/v1/auth/keys",
      ...over,
    });

  it("offers the sign-in first, and pasting after it", () => {
    const out = draw(
      state({ preferred: "openrouter", providers: [provider({}), openrouter({})] }),
    );
    expect(out).toContain("chat.connect_cta");
    expect(out).toContain("chat.connect_help");
    expect(out).toContain("chat.connect_or");
    expect(out).not.toContain("chat.byok_help");
    // Still a field to paste into, but not the primary press any more.
    expect(out).toContain('type="password"');
    expect(out.indexOf("chat.connect_cta")).toBeLessThan(
      out.indexOf('type="password"'),
    );
    expect(out.match(/ag-chat-btn-on/g)).toHaveLength(1);
    // One Remember box, ahead of the sign-in's "or".
    expect(out.match(/chat\.remember/g)).toHaveLength(1);
    expect(out.indexOf("chat.remember")).toBeLessThan(out.indexOf("chat.connect_or"));
  });

  it("is not offered for a provider that only takes a pasted key", () => {
    const out = draw(
      state({
        preferred: "anthropic",
        providers: [
          provider({}),
          provider({ id: "anthropic", label: "Anthropic", needs_key: true }),
        ],
      }),
    );
    expect(out).not.toContain("chat.connect_cta");
    expect(out).toContain("chat.byok_help");
  });

  it("is not offered once the account has a key there", () => {
    const out = draw(
      state({
        preferred: "openrouter",
        providers: [provider({}), openrouter({ has_key: true, key_tail: "beef" })],
      }),
    );
    expect(out).not.toContain("chat.connect_cta");
    expect(out).toContain("chat.forget");
  });
});

describe("memory", () => {
  const drawn = (next: ChatState) =>
    renderToStaticMarkup(
      <Settings
        state={next}
        busy={false}
        thread={null}
        onBack={() => {}}
        onSave={() => {}}
        onState={() => {}}
        onDeleteThread={() => {}}
        onMemory={() => {}}
      />,
    );

  it("offers both switches, on for an account that never touched them", () => {
    const out = drawn(state({}));
    expect(out).toContain("chat.sec_memory");
    expect(out).toContain("chat.mem_switch");
    expect(out).toContain("chat.recall_switch");
    expect(out).toContain("chat.mem_manage");
    expect(out.match(/checked=""/g)?.length).toBe(2);
  });

  it("shows a switch the account turned off as off", () => {
    const out = drawn(state({ memory: false, recall: true }));
    expect(out.match(/checked=""/g)?.length).toBe(1);
  });
});
