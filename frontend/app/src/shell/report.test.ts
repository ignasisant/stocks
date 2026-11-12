import { describe, expect, it } from "vitest";
import { onReport, reportProblem } from "./report";

describe("reportProblem", () => {
  it("opens one widget, the first mounted, however many listen", () => {
    const heard: string[] = [];
    const rail = onReport((kind) => heard.push(`rail:${kind}`));
    const sheet = onReport((kind) => heard.push(`sheet:${kind}`));
    reportProblem();
    reportProblem("idea");
    expect(heard).toEqual(["rail:bug", "rail:idea"]);

    // The rail's goes: the one still mounted answers.
    rail();
    reportProblem();
    expect(heard.at(-1)).toBe("sheet:bug");

    sheet();
    reportProblem();
    expect(heard).toHaveLength(3);
  });
});
