import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

const fill = vi.fn();
vi.mock("../shell/assistant", () => ({ fillAssistant: (t: string) => fill(t) }));
vi.mock("../shell/i18n", () => ({ useT: () => (k: string) => k }));

import { TypeInstead } from "./TypeInstead";

describe("TypeInstead", () => {
  it("is a button labelled with the action", () => {
    const out = renderToStaticMarkup(<TypeInstead className="x" />);
    expect(out).toContain("import.type_button");
    expect(out).toContain('type="button"');
    expect(out).toContain('class="x"');
  });

  it("opens the assistant with the starter prompt", () => {
    const el = TypeInstead({});
    (el.props as { onClick: () => void }).onClick();
    expect(fill).toHaveBeenCalledWith("import.type_prompt");
  });
});
