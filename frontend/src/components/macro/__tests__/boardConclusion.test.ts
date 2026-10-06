import { describe, expect, it } from "vitest";
import { extractLeadConclusion } from "../boardConclusion";

describe("extractLeadConclusion", () => {
  it("returns an empty string for nullish or blank input", () => {
    expect(extractLeadConclusion(undefined)).toBe("");
    expect(extractLeadConclusion(null)).toBe("");
    expect(extractLeadConclusion("")).toBe("");
    expect(extractLeadConclusion("\n   \n")).toBe("");
  });

  it("skips headings and short labels and returns the first substantive line", () => {
    const markdown = [
      "# Macro Report",
      "## Key Points",
      "Global manufacturing PMI rebounded to 50.6 in October, suggesting the industrial cycle is bottoming out across major economies.",
    ].join("\n");

    expect(extractLeadConclusion(markdown)).toBe(
      "Global manufacturing PMI rebounded to 50.6 in October, suggesting the industrial cycle is bottoming out across major economies.",
    );
  });

  it("strips list markers and emphasis", () => {
    const markdown =
      "- **Inflation:** CPI stays elevated at 3.4 percent year over year while PPI narrows its decline, signalling easing disinflation pressure.";

    expect(extractLeadConclusion(markdown)).toBe(
      "Inflation: CPI stays elevated at 3.4 percent year over year while PPI narrows its decline, signalling easing disinflation pressure.",
    );
  });

  it("converts table rows to readable cells and ignores separator rows", () => {
    const markdown = [
      "| Indicator | Direction |",
      "|---|---|",
      "| PMI | Improving |",
    ].join("\n");

    expect(extractLeadConclusion(markdown)).toBe("Indicator · Direction");
  });

  it("truncates long conclusions with a trailing ellipsis", () => {
    const result = extractLeadConclusion("A".repeat(200), 160);

    expect(result).toHaveLength(160);
    expect(result.endsWith("…")).toBe(true);
    expect(result.slice(0, 159)).toBe("A".repeat(159));
  });

  it("falls back to the only candidate when every line is short", () => {
    expect(extractLeadConclusion("短标题")).toBe("短标题");
  });
});
