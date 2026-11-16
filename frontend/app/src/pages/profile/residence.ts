/**
 * The two places a reader says where they pay tax — the investor profile's
 * constraints and Preferences' residence — can disagree. This names the clash
 * so both tabs can say it; neither is changed for the reader.
 */

const RESIDENCE_CONSTRAINT: Record<string, string> = {
  ES: "spain_tax",
  US: "us_tax",
};

/**
 * The residence the profile contradicts, or null. Only an explicit residence
 * counts: "auto" follows the browser and has said nothing yet.
 */
export function residenceClash(
  residence: string | null,
  constraints: readonly string[],
): { residence: string; constraint: string } | null {
  if (!residence) return null;
  const code = residence.toUpperCase();
  const own = RESIDENCE_CONSTRAINT[code];
  if (!own) return null;
  const other = Object.entries(RESIDENCE_CONSTRAINT).find(
    ([k, c]) => k !== code && constraints.includes(c) && !constraints.includes(own),
  );
  return other ? { residence: code, constraint: other[1] } : null;
}
