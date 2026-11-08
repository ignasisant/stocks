import { describe, expect, it } from "vitest";

import { pastedStatement, tabular, type Clipboard } from "./pasted";

const KINDS = ["csv", "pdf", "xlsx"];

const clip = (text: string, files: File[] = []): Clipboard => ({
  files,
  getData: (format) => (format === "text/plain" ? text : ""),
});

describe("pastedStatement", () => {
  it("takes a copied file of a kind a parser reads", () => {
    const file = new File(["Date,Ticker"], "revolut.csv", { type: "text/csv" });
    expect(pastedStatement(clip("", [file]), KINDS)).toBe(file);
  });

  it("leaves a pasted screenshot alone", () => {
    const shot = new File([new Uint8Array([0x89, 0x50])], "image.png", {
      type: "image/png",
    });
    expect(pastedStatement(clip("", [shot]), KINDS)).toBeNull();
  });

  it("names a copied file that arrives without an extension by its type", () => {
    const file = new File(["%PDF"], "statement", { type: "application/pdf" });
    expect(pastedStatement(clip("", [file]), KINDS)).toBe(file);
  });

  it("turns rows copied out of a spreadsheet into a CSV", async () => {
    const rows = "Date\tTicker\tType\tQuantity\tPrice\n2026-01-02\tAAPL\tBUY\t3\t190.5";
    const file = pastedStatement(clip(rows), KINDS);
    expect(file?.name).toBe("pasted.csv");
    expect(await file?.text()).toBe(rows);
  });

  it("reads a PDF pasted as base64", () => {
    const pdf = btoa("%PDF-1.7\n" + "x".repeat(80));
    expect(pastedStatement(clip(pdf), KINDS)?.name).toBe("pasted.pdf");
  });

  it("keeps a question as text", () => {
    expect(pastedStatement(clip("¿Qué opinas de AAPL?"), KINDS)).toBeNull();
    expect(
      pastedStatement(
        clip("Hola, tengo AAPL, MSFT, NVDA\ny 3, 4, 5, 6 acciones"),
        KINDS,
      ),
    ).toBeNull();
  });
});

describe("tabular", () => {
  it("wants every line several columns wide", () => {
    const csv = [
      "Date,Ticker,Type,Qty,Price",
      "2026-01-02,AAPL,BUY,3,190",
      "2026-01-03,MSFT,BUY,1,410",
    ];
    expect(tabular(csv.join("\n"))).toBe(true);
    expect(tabular(csv.slice(0, 2).join("\n"))).toBe(false);
    expect(tabular("a,b\n1,2\n3,4")).toBe(false);
  });

  it("wants numbers under the header", () => {
    expect(tabular("a\tb\tc\td\ne\tf\tg\th")).toBe(false);
  });
});
