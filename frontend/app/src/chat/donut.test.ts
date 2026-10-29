import { describe, expect, it } from "vitest";
import { sliceName } from "./donut";

const strings: Record<string, string> = {
  "portfolio.alloc_unknown": "Sin clasificar",
  "portfolio.alloc_crypto": "Cripto (sin país)",
  "sentiment.sector_technology": "Tecnología",
};
const t = (key: string) => strings[key] ?? key;

describe("the chat donut's labels", () => {
  // Local review 2026-10-29: an English ring under a Spanish answer.
  it("reads in the reader's language", () => {
    expect(sliceName(t, "es", "country", "United States")).toBe("Estados Unidos");
    expect(sliceName(t, "es", "country", "Unknown")).toBe("Sin clasificar");
    expect(sliceName(t, "es", "country", "Crypto")).toBe("Cripto (sin país)");
    expect(sliceName(t, "es", "sector", "Technology")).toBe("Tecnología");
  });

  it("keeps what has no translation as the data spells it", () => {
    expect(sliceName(t, "es", "sector", "Space Mining")).toBe("Space Mining");
    expect(sliceName(t, "es", "position", "Unknown")).toBe("Unknown");
    expect(sliceName(t, "es", "currency", "USD")).toBe("USD");
  });
});
