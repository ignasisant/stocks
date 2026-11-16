/**
 * What is left to set up, read off `GET /onboarding`'s `setup` map: the page that settles the next gap.
 */

/** The capabilities this page can point at, in the order they are offered. */
const STEPS: Record<string, { page: string; params?: Record<string, string> }> = {
  import: { page: "import" },
  plan: { page: "profile", params: { tab: "plan" } },
  notify: { page: "profile", params: { tab: "notify" } },
  ai: { page: "profile", params: { tab: "prefs" } },
};

/** The first capability still off that has a place to switch it on. */
export function nextSetup(
  setup: Record<string, boolean>,
): { key: string; page: string; params?: Record<string, string> } | null {
  for (const key of Object.keys(STEPS)) {
    if (setup[key] === false) return { key, ...STEPS[key]! };
  }
  return null;
}
