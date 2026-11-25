import { describe, expect, it } from "vitest";
import { onReport, reportProblem, type ReportContext } from "./report";

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

  it("hands the widget where it happened and the file it is about", () => {
    const heard: ReportContext[] = [];
    const off = onReport((_, context) => heard.push(context));
    const blob = new Blob(["Date,Ticker"]);
    reportProblem("bug", { page: "chat/import", file: { name: "a.csv", blob } });
    reportProblem();
    off();
    expect(heard[0]).toEqual({ page: "chat/import", file: { name: "a.csv", blob } });
    // A plain report carries nothing over from the last one.
    expect(heard[1]).toEqual({});
  });
});
